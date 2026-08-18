"""What "fixed sourcing vs time" must get right about time.

The experiment is simple. Its failure modes are not, and they are all
the same shape: a trace that looks entirely reasonable and is wrong
about *when*.

Four of them have a test here because each is a real fault this project
has already found once, in a different place:

* a **reconstructed** time axis (`i * interval`), which is fault 9 -
  the saved file describes the schedule that was requested rather than
  the one that happened;
* a **drifting** schedule (sleep the interval between readings rather
  than aim at absolute deadlines), which is fault 5 - each reading's
  cost accumulates and a nominal 1 Hz run silently becomes 0.8 Hz;
* a **short** run committed as a complete one, which is what
  `RunContext.expect()` guards everywhere else and cannot guard here;
* a reading **dropped** rather than blanked in place, which is fault 3 -
  omitting a value shifts every later column left.

Every test drives `_do_run` on the main thread, so nothing here is about
threading; `test_fixed_source_lifecycle.py` goes the other way.

Tk roots are built, so the file carries the `gui` marker and
`run_tests.py` gives it its own process.
"""
import pytest

pytestmark = [pytest.mark.gui]

import time
import tkinter as tk

import core.base_app as base_app
import experiments.base_experiment as base_experiment
import experiments.fixed_source.experiment as fixed_source
from core.base_app import LabApp
from core.identity import SampleRegistry
from core.ownership import InstrumentOwnership
from core.run_control import Outcome
from core.transports.null_transport import NullTransport
from drivers.dummy_smu import DummySMU
from experiments.fixed_source.experiment import FixedSourceExperiment


class DialogRecorder:
    """Swallow dialogs so a headless run doesn't block.

    Three modules import `messagebox`, not two - `LabApp.on_close()` has
    its own.
    """

    def __init__(self):
        self.calls = []

    def _record(self, kind):
        def call(title, message=None, **kw):
            self.calls.append((kind, title, message))
            return True
        return call

    def __getattr__(self, name):
        return self._record(name)


dialogs = DialogRecorder()
fixed_source.messagebox = dialogs
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs


# ------------------------------------------------------------------
# fake instruments
# ------------------------------------------------------------------
class SlowSMU(DummySMU):
    """A `DummySMU` whose readings cost a known amount of wall clock.

    Not a stub: the physics is the dummy's, so a run against it produces
    the same numbers a demo run does. The only change is that a reading
    takes time, which is the whole property under test - an instrument
    that answers instantly cannot tell a drifting schedule from an
    absolute one.

    The cost is spent inside `measure()`, where a real instrument spends
    it, rather than being simulated by moving a clock the experiment
    does not read.
    """

    def __init__(self, transport, cost_s=0.05, **kwargs):
        super().__init__(transport, **kwargs)
        self.cost_s = cost_s
        self.measure_calls = 0

    def measure(self, timeout_s=3.0):
        self.measure_calls += 1
        time.sleep(self.cost_s)
        return super().measure(timeout_s=timeout_s)


class OneSlowReadSMU(DummySMU):
    """Normal, except that one chosen reading takes much longer.

    Built to reproduce a platform difference without depending on the
    platform. The Windows failure came from timer granularity - a 10 ms
    wait taking 15.6 ms - pushing elapsed past the duration just before
    the sample due at the duration. Asserting that by sleeping and
    hoping would be a coin toss on any runner; making one reading
    deliberately slow puts the clock in exactly the same place on every
    machine.
    """

    def __init__(self, transport, slow_on=4, extra_s=0.06, **kwargs):
        super().__init__(transport, **kwargs)
        self.slow_on = slow_on
        self.extra_s = extra_s
        self.measure_calls = 0

    def measure(self, timeout_s=3.0):
        self.measure_calls += 1
        if self.measure_calls == self.slow_on:
            time.sleep(self.extra_s)
        return super().measure(timeout_s=timeout_s)


class FailingSMU(DummySMU):
    """Reads normally, then raises - the timed-out-read case.

    Modelled on the 2401's documented behaviour: a read that times out
    leaves its reply in the buffer and puts every reading after it one
    step out of phase. The experiment cannot resynchronise from where it
    sits, so it must stop rather than carry on producing a trace that is
    plausible and wrong about when.
    """

    def __init__(self, transport, fail_after=3, **kwargs):
        super().__init__(transport, **kwargs)
        self.fail_after = fail_after
        self.measure_calls = 0

    def measure(self, timeout_s=3.0):
        self.measure_calls += 1
        if self.measure_calls > self.fail_after:
            raise TimeoutError("VISA timeout on :READ?")
        return super().measure(timeout_s=timeout_s)


class BlankingSMU(DummySMU):
    """Returns no reading on chosen samples, as a sentinel would.

    The drivers turn `+9.91e37` into `None` before it reaches an
    experiment, so `None` here is exactly what a real over-range looks
    like from up here.
    """

    def __init__(self, transport, blank_on=(2,), **kwargs):
        super().__init__(transport, **kwargs)
        self.blank_on = set(blank_on)
        self.measure_calls = 0

    def measure(self, timeout_s=3.0):
        self.measure_calls += 1
        volts, amps = super().measure(timeout_s=timeout_s)
        if self.measure_calls in self.blank_on:
            return (volts, None)
        return (volts, amps)


class TrippingSMU(DummySMU):
    """Reports compliance tripped, unlike the dummy's honest `None`."""

    def __init__(self, transport, tripped=True, **kwargs):
        super().__init__(transport, **kwargs)
        self.tripped = tripped
        self.trip_queries = 0

    def compliance_tripped(self):
        self.trip_queries += 1
        return self.tripped


class Recorder:
    """Wraps a driver and records the order of every call."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def recorded(*a, **kw):
            self.calls.append(name)
            return attr(*a, **kw)
        return recorded

    def while_energised(self):
        """Every call made between an output_on and the next off."""
        out, live = [], False
        for name in self.calls:
            if name == "output_on":
                live = True
            elif name in ("output_off", "safe_output_off"):
                live = False
            elif live:
                out.append(name)
        return out


# ------------------------------------------------------------------
# harness
# ------------------------------------------------------------------
class Bench:
    def __init__(self, smu_cls=DummySMU, duration="1.0", interval="0.2",
                 level="0.1", compliance="0.01", mode="voltage",
                 watch=True, **smu_kwargs):
        self.root = tk.Tk()
        self.app = LabApp(self.root, FixedSourceExperiment,
                          ownership=InstrumentOwnership(),
                          samples=SampleRegistry())
        self.exp = self.app.experiment

        transport = NullTransport()
        transport.connect("demo")
        self.smu = smu_cls(transport, **smu_kwargs)
        self.app.instruments["source"] = self.smu
        self.app.transports["source"] = transport
        self.app.instrument_keys["source"] = "demo::fixed-source"
        self.root.update()

        self.exp.sample_name_var.set("film_A")
        self.exp.mode_var.set(mode)
        self.exp.on_mode_changed()
        self.exp.level_var.set(level)
        self.exp.compliance_var.set(compliance)
        self.exp.duration_var.set(duration)
        self.exp.interval_var.set(interval)
        self.exp.dataset_var.set("trace")
        self.exp.watch_compliance_var.set(watch)
        self.root.update()

    def run(self):
        """Run to completion on this thread, then drain the UI queue.

        Wrapped in `app.guard_run` rather than calling `_do_run` bare,
        because a refused commit raises `IncompleteRun` and that is
        exactly what several of these tests are provoking. In the
        application that exception is caught by the same wrapper, so
        going around it here would test a path the bench never takes.
        """
        self.exp._watch_compliance = bool(
            self.exp.watch_compliance_var.get())
        params = self.exp._params()
        self.app.guard_run(lambda: self.exp._do_run(params))()
        self.app.drain_ui_now()
        self.root.update()
        return self

    @property
    def status(self):
        return self.exp.run_controller.last_status

    def rows(self):
        return self.exp.tree.get_children()

    def only_run(self):
        rows = self.rows()
        assert len(rows) == 1, f"expected one row, got {len(rows)}"
        return self.exp.run_store.get(rows[0])

    def close(self):
        for _ in range(10):
            self.root.update()
        try:
            self.app.on_close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


# ------------------------------------------------------------------
# the arithmetic, before any instrument is involved
# ------------------------------------------------------------------
def test_the_nominal_count_survives_binary_floating_point(check):
    """A 0.3 s run at 0.1 s wants four samples, not three.

    `0.3 / 0.1` is `2.9999999999999996`, so the obvious `int()` gives
    three - and the sampling loop, doing the same division, drops the
    sample due at t = 0.3. The run is short by one, entirely plausibly,
    and the number that would have told you is computed from the same
    wrong division. A 60 s run at 0.1 s loses its last sample the same
    way.

    Checked here rather than only through a run, because this is
    arithmetic and deserves to fail in a place that names the
    arithmetic.
    """
    from core.identity import SampleRegistry as _Registry
    from core.parameters import FixedSourceParameters

    sample = _Registry().ref("film_A")
    cases = [(0.3, 0.1, 4), (1.0, 0.2, 6), (60.0, 0.1, 601),
             (2.0, 0.3, 7), (0.7, 0.1, 8)]
    for duration, interval, expected in cases:
        params = FixedSourceParameters(
            sample=sample, duration_s=duration, interval_s=interval)
        check(f"{duration} s at {interval} s is {expected} samples",
              params.nominal_readings == expected,
              str(params.nominal_readings))


# ------------------------------------------------------------------
# the control
# ------------------------------------------------------------------
def test_a_plain_run_commits_a_time_series(check):
    """The control. A matrix of failure cases proves nothing if the
    happy path could not have worked anyway."""
    bench = Bench(duration="1.0", interval="0.2")
    try:
        bench.run()
        check("the run completed",
              bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome))
        record = bench.only_run()
        check("six samples: t = 0, 0.2 ... 1.0",
              len(record.readings) == 6, str(len(record.readings)))
        check("the first sample is at t = 0",
              record.readings[0]["time_s"] < 0.05,
              str(record.readings[0]["time_s"]))
        check("the last sample is near the requested duration",
              0.95 <= record.readings[-1]["time_s"] <= 1.15,
              str(record.readings[-1]["time_s"]))
        check("it records that the timebase is the host's",
              record.metadata["timebase"] == "host")
        check("it records how it ended",
              record.metadata["ended_by"] == "duration",
              record.metadata["ended_by"])
        check("sample indices are contiguous",
              [r["sample_index"] for r in record.readings]
              == list(range(1, len(record.readings) + 1)))
    finally:
        bench.close()


# ------------------------------------------------------------------
# fault 9: the time axis is measured, not reconstructed
# ------------------------------------------------------------------
def test_the_time_column_is_measured_not_reconstructed(check):
    """`i * interval` would hide every reason the loop fell behind.

    Against an instrument that cannot meet the requested rate, a
    reconstructed axis lands exactly on the grid and a measured one
    cannot. That is the discriminating question: an assertion that the
    times are *roughly* right would pass either way, which is fault 19 -
    a probe whose interesting answer is not the correct one.
    """
    bench = Bench(duration="0.4", interval="0.1")
    try:
        bench.run()
        record = bench.only_run()
        times = [r["time_s"] for r in record.readings]
        check("five samples landed", len(times) == 5, str(len(times)))

        # Only t = 0 can legitimately sit on the grid. Every later
        # sample carries the host's real latency, so a reconstructed
        # axis is the *only* way they land on it exactly.
        on_the_grid = [t for i, t in enumerate(times)
                       if abs(t - i * 0.1) < 1e-9]
        check("the times are not the requested grid",
              len(on_the_grid) <= 1, f"{len(on_the_grid)} of {len(times)}")

        achieved = record.metadata["interval_achieved_s"]
        check("the achieved interval is measured, not copied",
              achieved != 0.1, str(achieved))
        check("and is still close to what was asked for",
              abs(achieved - 0.1) < 0.02, str(achieved))
        check("the requested one is recorded beside it",
              record.metadata["interval_requested_s"] == 0.1)
    finally:
        bench.close()


def test_samples_that_land_late_are_counted_and_reported(check):
    """A rate that was not achieved has to be visible in the file.

    30 ms readings against a 20 ms request: every sample after the first
    lands more than half an interval late. The count and the worst case
    are recorded, and the run still commits - falling behind is a fact
    about the measurement, not a reason to bin it.
    """
    bench = Bench(smu_cls=SlowSMU, cost_s=0.03,
                  duration="0.4", interval="0.02")
    try:
        bench.run()
        record = bench.only_run()
        check("the run still committed",
              bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome))
        check("late samples were counted",
              record.metadata["overruns"] > 0,
              str(record.metadata["overruns"]))
        check("the worst overrun is recorded",
              record.metadata["worst_overrun_s"] > 0.005,
              str(record.metadata["worst_overrun_s"]))
        check("the achieved interval shows the real rate",
              record.metadata["interval_achieved_s"] > 0.025,
              str(record.metadata["interval_achieved_s"]))
    finally:
        bench.close()


# ------------------------------------------------------------------
# fault 5: the schedule is absolute, not a sleep between readings
# ------------------------------------------------------------------
def test_the_schedule_does_not_drift_by_the_cost_of_each_reading(check):
    """Aim at deadlines, not at gaps.

    Eleven samples at 20 ms with a 10 ms reading cost:

        absolute deadlines -> the run takes about 200 ms
        sleep-the-interval -> it takes about 300 ms, and every sample
                              after the first is late by a growing
                              amount that nothing records

    The margin between those two is 100 ms, which is wide enough that a
    loaded machine cannot turn one into the other.
    """
    bench = Bench(smu_cls=SlowSMU, cost_s=0.01,
                  duration="0.2", interval="0.02")
    try:
        bench.run()
        record = bench.only_run()
        elapsed = record.readings[-1]["time_s"]
        check("eleven samples landed", len(record.readings) == 11,
              str(len(record.readings)))
        check("the run tracked the clock rather than accumulating drift",
              elapsed < 0.26, f"{elapsed:.4f} s for a 0.2 s run")
        check("the achieved interval is close to the requested one",
              abs(record.metadata["interval_achieved_s"] - 0.02) < 0.006,
              str(record.metadata["interval_achieved_s"]))
    finally:
        bench.close()


def test_a_late_run_still_takes_the_sample_due_at_the_duration(check):
    """The ceiling must not eat the last sample it was meant to protect.

    Five samples are due at 0, 0.05 ... 0.20. The fourth reading is made
    slow enough that the clock passes 0.20 s while it is still in
    flight - so by the time the loop comes round for the sample due at
    exactly 0.20, elapsed time is already past the duration.

    That sample is *inside* the window the operator agreed to, and a
    ceiling checked without grace drops it: the run returns four samples
    where five were nominal, looks entirely healthy, and sits well
    inside the shortfall floor that would otherwise have refused it.

    This is the shape Windows CI found by way of its 15.6 ms timer
    granularity, reproduced here without depending on any platform's
    clock.
    """
    bench = Bench(smu_cls=OneSlowReadSMU, slow_on=4, extra_s=0.06,
                  duration="0.2", interval="0.05")
    try:
        bench.run()
        record = bench.only_run()
        check("the run completed",
              bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome))
        check("all five samples landed", len(record.readings) == 5,
              str(len(record.readings)))
        check("the collected count matches the nominal one",
              len(record.readings) == record.metadata["samples_nominal"],
              f"{len(record.readings)} of "
              f"{record.metadata['samples_nominal']}")
        check("the last sample really is past the duration",
              record.readings[-1]["time_s"] > 0.2,
              str(record.readings[-1]["time_s"]))
    finally:
        bench.close()


def test_a_runaway_run_is_still_stopped_by_the_clock(check):
    """The grace is one interval, not an amnesty.

    The pair to the test above. Giving the ceiling room to admit the
    final sample must not give a slow instrument room to walk the whole
    nominal grid - which is the ten-minute run the timer exists to
    prevent. Half a second of nominal grid at 5 ms is 101 samples; on a
    50 ms instrument that is five seconds of energised sample.

    Asserting the wall-clock length rather than only the sample count,
    because the count is what the floor already checks and the *time the
    output was live* is what this guard is actually for.

    The bound is derived, not picked. The contract says a run may
    overshoot by at most one interval, so the ceiling fires at 0.505 s
    and the reading in flight can add one more cost: 0.5 + 0.005 + 0.05,
    call it 0.56 s. 0.8 s allows a slow runner half again as much and
    still fails a grace of two durations, which would land past 1.0 s.
    A looser bound passed such a mutation, which is how this number
    stopped being 2.0.
    """
    bench = Bench(smu_cls=SlowSMU, cost_s=0.05,
                  duration="0.5", interval="0.005")
    try:
        started = time.monotonic()
        bench.run()
        elapsed = time.monotonic() - started
        check("the run did not walk the whole nominal grid",
              elapsed < 0.8, f"{elapsed:.2f} s for a 0.5 s run")
        check("and was refused for falling short",
              bench.status.outcome is not Outcome.COMPLETED,
              str(bench.status.outcome))
    finally:
        bench.close()


# ------------------------------------------------------------------
# the floor that replaces expect()
# ------------------------------------------------------------------
def test_a_run_that_could_not_keep_up_is_refused(check):
    """Half the samples is not a slower run, it is a different one.

    50 ms readings against a 5 ms request: the loop can deliver about a
    tenth of the nominal count. Committing that would put a trace at an
    unknown fraction of the requested rate into the results table, which
    is worse than no trace.
    """
    bench = Bench(smu_cls=SlowSMU, cost_s=0.05,
                  duration="0.5", interval="0.005")
    try:
        bench.run()
        check("the run did not complete",
              bench.status.outcome is not Outcome.COMPLETED,
              str(bench.status.outcome))
        check("nothing reached the results table", bench.rows() == (),
              f"{len(bench.rows())} row(s)")
        check("nothing reached the store", len(bench.exp.run_store) == 0)
        check("the reason names the shortfall",
              "sample(s) collected" in (bench.status.detail or ""),
              bench.status.detail or "")
    finally:
        bench.close()


def test_the_floor_does_not_apply_to_a_run_the_operator_ended(check):
    """The operator chose the length, so shortness is not a fault.

    Same instrument and same impossible interval as the test above; the
    only difference is who ended the run. This is the pair that proves
    the floor is conditional rather than absolute - a single test of
    either half would pass against code that always refused, or against
    code that never did.
    """
    bench = Bench(smu_cls=SlowSMU, cost_s=0.02,
                  duration="60", interval="0.005")
    exp = bench.exp

    # The instrument presses the button, from inside the reading, after
    # exactly four samples. Deterministic where a sleeping test would
    # not be, and it is a legal call from a worker: `finish_pressed`
    # sets an event and queues a console line.
    original = bench.smu.measure

    def measure(timeout_s=3.0):
        result = original(timeout_s=timeout_s)
        if bench.smu.measure_calls >= 4:
            exp.finish_pressed()
        return result

    bench.smu.measure = measure

    try:
        bench.run()
        check("the run completed",
              bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome))
        record = bench.only_run()
        check("it kept what had been collected",
              len(record.readings) == 4, str(len(record.readings)))
        check("and says the operator ended it",
              record.metadata["ended_by"] == "operator",
              record.metadata["ended_by"])
        check("the output is off", bench.smu._output_on is False)
    finally:
        bench.close()


def test_finishing_before_two_samples_is_still_refused(check):
    """A time series of one point has no time in it.

    The operator's floor is two, not zero. One row would be committed to
    a results table whose plot cannot draw it and whose interval column
    would be meaningless.
    """
    bench = Bench(duration="60", interval="0.05")
    exp = bench.exp
    original = bench.smu.measure
    calls = []

    def measure(timeout_s=3.0):
        calls.append(1)
        result = original(timeout_s=timeout_s)
        exp.finish_pressed()          # after the very first reading
        return result

    bench.smu.measure = measure

    try:
        bench.run()
        check("exactly one reading was taken", len(calls) == 1, str(len(calls)))
        check("the run did not complete",
              bench.status.outcome is not Outcome.COMPLETED,
              str(bench.status.outcome))
        check("nothing reached the results table", bench.rows() == ())
        check("the output is off", bench.smu._output_on is False)
    finally:
        bench.close()


# ------------------------------------------------------------------
# a read that fails part way through
# ------------------------------------------------------------------
def test_a_failed_read_stops_sampling_and_keeps_what_came_before(check):
    """Everything before the glitch is real; everything after is not.

    A timed-out read on a 2401 leaves its reply in the buffer and puts
    every later reading one step out of phase - the trace stays
    plausible and becomes wrong about when. There is no resynchronising
    from up here, so sampling stops, the collected part is kept, and the
    file says where it stopped.
    """
    bench = Bench(smu_cls=FailingSMU, fail_after=3,
                  duration="60", interval="0.02")
    try:
        bench.run()
        check("the run completed with what it had",
              bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome))
        record = bench.only_run()
        check("the three good samples were kept",
              len(record.readings) == 3, str(len(record.readings)))
        check("it says a read ended it",
              record.metadata["ended_by"] == "read_error",
              record.metadata["ended_by"])
        check("and names the exception",
              "TimeoutError" in record.metadata["ended_detail"],
              record.metadata["ended_detail"])
        check("the output is off", bench.smu._output_on is False)
        check("it stopped at the first failure rather than retrying",
              bench.smu.measure_calls == 4,
              f"{bench.smu.measure_calls} reads for a 3-good-read run")
    finally:
        bench.close()


# ------------------------------------------------------------------
# fault 3: a missing value is blanked in place, never dropped
# ------------------------------------------------------------------
def test_a_missing_reading_keeps_its_row(check):
    """Dropping the row would shift the time axis by one interval.

    A sentinel arrives here as `None`. Omitting that sample would leave
    the file one row short with every later `time_s` still correct and
    every later `sample_index` off by one - the table and the clock
    disagreeing with nothing to say so.
    """
    bench = Bench(smu_cls=BlankingSMU, blank_on=(2,),
                  duration="0.4", interval="0.1")
    try:
        bench.run()
        record = bench.only_run()
        check("no row was dropped", len(record.readings) == 5,
              str(len(record.readings)))
        check("indices stay contiguous",
              [r["sample_index"] for r in record.readings] == [1, 2, 3, 4, 5])
        check("the missing value is an empty cell, in place",
              record.readings[1]["current_A"] == "",
              repr(record.readings[1]["current_A"]))
        check("the voltage beside it is untouched",
              record.readings[1]["voltage_V"] != "")
        check("the count is recorded", record.metadata["no_reading_n"] == 1,
              str(record.metadata["no_reading_n"]))
        check("and the run still completed",
              bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome))
    finally:
        bench.close()


def test_a_run_where_nothing_read_is_refused(check):
    """One dropout is a blemish; every sample missing is a broken run."""
    bench = Bench(smu_cls=BlankingSMU, blank_on=tuple(range(1, 50)),
                  duration="0.4", interval="0.1")
    try:
        bench.run()
        check("the run did not complete",
              bench.status.outcome is not Outcome.COMPLETED,
              str(bench.status.outcome))
        check("nothing reached the results table", bench.rows() == ())
        check("the reason names the quantity",
              "current" in (bench.status.detail or ""),
              bench.status.detail or "")
    finally:
        bench.close()


# ------------------------------------------------------------------
# compliance: three different statements, kept apart
# ------------------------------------------------------------------
def test_the_compliance_columns_distinguish_three_situations(check):
    """"No trips", "not watched" and "cannot say" are not the same.

    Collapsing any two of them turns a silence into a reassurance, which
    is fault 21 exactly: an instrument answering honestly to a question
    nobody asked.
    """
    watched = Bench(smu_cls=TrippingSMU, tripped=True,
                    duration="0.3", interval="0.1")
    try:
        watched.run()
        record = watched.only_run()
        check("a watched trip is counted on every sample",
              record.metadata["compliance_trips"] == len(record.readings),
              f"{record.metadata['compliance_trips']} trips, "
              f"{len(record.readings)} samples")
        check("and there were four samples, not three",
              len(record.readings) == 4, str(len(record.readings)))
        check("the nominal count agrees with what landed",
              record.metadata["samples_nominal"] == 4,
              str(record.metadata["samples_nominal"]))
        check("every row says it was clamped",
              all(r["compliance"] == "yes" for r in record.readings))
        check("and the run records that watching was on",
              record.metadata["compliance_watched"] == "yes")
    finally:
        watched.close()

    unwatched = Bench(smu_cls=TrippingSMU, tripped=True, watch=False,
                      duration="0.3", interval="0.1")
    try:
        unwatched.run()
        record = unwatched.only_run()
        check("with watching off the instrument is never asked",
              unwatched.smu.trip_queries == 0,
              str(unwatched.smu.trip_queries))
        check("the trip count is blank, not zero",
              record.metadata["compliance_trips"] == "",
              repr(record.metadata["compliance_trips"]))
        check("and the run says watching was off",
              record.metadata["compliance_watched"] == "no")
        check("every row's compliance cell is blank",
              all(r["compliance"] == "" for r in record.readings))
    finally:
        unwatched.close()

    silent = Bench(duration="0.3", interval="0.1")     # DummySMU: None
    try:
        silent.run()
        record = silent.only_run()
        check("an instrument that cannot answer leaves blanks",
              all(r["compliance"] == "" for r in record.readings))
        check("while still recording that watching was on",
              record.metadata["compliance_watched"] == "yes")
    finally:
        silent.close()


# ------------------------------------------------------------------
# house rule 12, and the turn-on transient
# ------------------------------------------------------------------
def test_nothing_is_configured_while_the_sample_is_energised(check):
    """House rule 12. Once the output is on, this run only reads."""
    bench = Bench(duration="0.3", interval="0.1")
    recorder = Recorder(bench.smu)
    bench.app.instruments["source"] = recorder
    try:
        bench.run()
        during = set(recorder.while_energised())
        allowed = {"measure", "compliance_tripped"}
        check("only reads happen while live", during <= allowed,
              str(sorted(during - allowed)))
    finally:
        bench.close()


def test_the_level_is_set_before_the_output_goes_on(check):
    """t = 0 is a step from nothing to the full level.

    Setting the level after energising would put an unmeasured ramp of
    unknown length between t = 0 and the first sample, and the turn-on
    transient is the part of this measurement people most often want.
    """
    bench = Bench(duration="0.2", interval="0.1")
    recorder = Recorder(bench.smu)
    bench.app.instruments["source"] = recorder
    try:
        bench.run()
        calls = recorder.calls
        check("a level was set", "set_voltage_level" in calls, str(calls))
        check("the output went on", "output_on" in calls, str(calls))
        check("and the level came first",
              calls.index("set_voltage_level") < calls.index("output_on"),
              str(calls))
        check("the source range was fixed before the limit",
              calls.index("apply_ranges") < calls.index("set_current_limit"),
              str(calls))
    finally:
        bench.close()


# ------------------------------------------------------------------
# the form
# ------------------------------------------------------------------
def test_an_interval_longer_than_the_run_is_refused(check):
    """One sample is not a time series, and the message says why."""
    bench = Bench(duration="1", interval="5")
    try:
        try:
            bench.exp._params()
            check("an interval longer than the duration is refused", False,
                  "no error raised")
        except ValueError as exc:
            check("an interval longer than the duration is refused", True)
            check("and the message names both numbers",
                  "1" in str(exc) and "Sample every" in str(exc), str(exc))
    finally:
        bench.close()


def test_zero_is_a_legal_level(check):
    """Holding at zero and watching the current is a real measurement.

    Leakage, and the relaxation after a bias, are both runs at zero. A
    `positive_number` validator here would have refused them.
    """
    bench = Bench(level="0", duration="0.2", interval="0.1")
    try:
        params = bench.exp._params()
        check("zero is accepted", params.level == 0.0, str(params.level))
        bench.run()
        check("and a run at zero commits",
              bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome))
    finally:
        bench.close()


def test_the_measured_quantity_is_the_one_not_sourced(check):
    """Getting this backwards is fault 21, and it is one line to get
    backwards."""
    bench = Bench(mode="current", level="1e-4", compliance="2",
                  duration="0.2", interval="0.1")
    try:
        params = bench.exp._params()
        check("sourcing current measures voltage",
              params.measured_quantity == "voltage",
              params.measured_quantity)
        bench.run()
        record = bench.only_run()
        check("the run records it too",
              record.metadata["measured_quantity"] == "voltage")
        check("and the plot trace draws volts against time",
              bench.exp._traces[bench.rows()[0]]["measured_unit"] == "V")
    finally:
        bench.close()
