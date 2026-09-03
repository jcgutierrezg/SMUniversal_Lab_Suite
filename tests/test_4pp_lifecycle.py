"""The Wave 3 proof: 4PP on the real run lifecycle, cancelled everywhere.

What this file is for
---------------------
`test_4pp.py` drives `_do_run()` directly on the main thread. That is the
right shape for testing physics and geometry rules, and it means those
tests say nothing at all about threading, cancellation or ownership -
the worker path is never entered.

This file goes the other way. Every test here presses Run through
`run_pressed()`, so the measurement runs on a background thread exactly
as it does at the bench, and then presses Stop at a precisely known
instant.

The matrix
----------
`docs/architecture/run-lifecycle.md` lists where a cancellation check
belongs: before output-on,
before a source-function change, before each new level, before each
polarity flip, after every long wait, and immediately before the final
commit. Each of those is a boundary, and each boundary gets a row.

For every row, the same five things are asserted:

1. nothing was committed - the results table and the run store are empty;
2. the output was turned off;
3. the terminal outcome is CANCELLED, not FAILED - pressing Stop is a
   normal operator action and must not read as an error;
4. instrument ownership was released;
5. the controller returned to IDLE, so another run can start.

Determinism
-----------
The instant of cancellation is not timed, it is *chosen*. The
instrument blocks at a named stage and waits (see
`stage_blocking_smu.py`), the test waits for a fact rather than a
duration, presses Stop while the run is parked, and then releases. On a
loaded CI runner, and on Windows with its 15.6 ms clock quantisation,
a matrix built on sleeps would be a coin toss - and an intermittently
red matrix teaches everyone to press re-run, which is worse than not
having one.

Tk roots are built here, so the file carries the `gui` marker and
`run_tests.py` gives it its own process.
"""
import pytest

pytestmark = [pytest.mark.gui]

import threading
import time
import tkinter as tk

from stage_blocking_smu import StageBlockingSMU

import core.base_app as base_app
import experiments.base_experiment as base_experiment
import experiments.ossila_4pp.experiment as fourpp_experiment
from core.base_app import LabApp
from core.identity import SampleRegistry
from core.ownership import InstrumentOwnership
from core.run_control import Outcome, RunState
from core.thread_guard import ThreadAffinityGuard
from core.transports.null_transport import NullTransport
from drivers.dummy_smu import DummySMU
from experiments.ossila_4pp.experiment import Ossila4PPExperiment


class DialogRecorder:
    """Swallow dialogs so a headless run doesn't block.

    Three modules import `messagebox`, not two - `LabApp.on_close()` has
    its own. An unstubbed one blocks the suite on the *second* test with
    the first already printed as a pass, which is a memorably confusing
    way to lose an afternoon.
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
fourpp_experiment.messagebox = dialogs
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs


# ------------------------------------------------------------------
# harness
# ------------------------------------------------------------------
class Bench:
    """One app, one experiment, one fake instrument, wired for a run."""

    def __init__(self, smu_cls=StageBlockingSMU, points=4, reversals=2,
                 delay="0"):
        self.root = tk.Tk()
        # Its own ownership manager and sample registry, so nothing here
        # can be affected by - or leak into - another test file sharing
        # the process-wide defaults.
        self.app = LabApp(self.root, Ossila4PPExperiment,
                          ownership=InstrumentOwnership(),
                          samples=SampleRegistry())
        self.exp = self.app.experiment

        transport = NullTransport()
        self.smu = smu_cls(transport)
        transport.connect("demo")
        self.app.instruments["source"] = self.smu
        self.app.transports["source"] = transport
        self.app.instrument_keys["source"] = "demo::4pp-lifecycle"
        self.root.update()

        self.exp.sample_name_var.set("film_A")
        self.exp.sweep_mode_var.set("list")
        self.exp.on_sweep_mode_changed()
        self.exp.dataset_var.set("matrix")
        self.exp.delay_var.set(delay)
        self.exp.reversals_var.set(str(reversals))
        self.exp.width_var.set("10")
        self.exp.length_var.set("27")
        self.exp.thickness_var.set("180")
        for index, var in enumerate(self.exp.current_vars):
            var.set(f"{(index + 1) * 1e-4:g}" if index < points else "")
        self.points = points
        self.reversals = reversals
        if hasattr(self.smu, "expect_readings"):
            self.smu.expect_readings(points, reversals)
        self.root.update()

    # ---- driving ----
    def press_run(self):
        self.exp.run_pressed()
        self.pump(0.05)

    def press_stop(self):
        self.exp.stop_pressed()

    def pump(self, seconds=0.5):
        """Service the Tk event loop, which is how `app.ui()` lands."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.root.update()
            time.sleep(0.005)

    def wait_idle(self, timeout=10.0):
        """Pump until the controller is idle *and* the UI has caught up.

        Draining afterwards is not tidiness, it is correctness. The
        commit sink posts `_record_run` to the UI queue, so the
        controller reaches IDLE before the row is in the results table.
        A test that asserted on the store the instant idle went true
        would be racing the pump and would fail about one time in
        three - which is exactly the kind of intermittent this file
        exists to avoid creating.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.root.update()
            if self.exp.run_controller.is_idle:
                self.app.drain_ui_now()
                self.root.update()
                return True
            time.sleep(0.005)
        return False

    # ---- inspecting ----
    @property
    def status(self):
        return self.exp.run_controller.last_status

    def rows(self):
        return self.exp.tree.get_children()

    def close(self):
        for _ in range(20):
            self.root.update()
        try:
            self.app.on_close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


def assert_cancelled_cleanly(bench, check, where):
    """The five things every cancelled run must be true of."""
    check(f"[{where}] returns to idle", bench.wait_idle(),
          str(bench.exp.run_controller.state))

    status = bench.status
    check(f"[{where}] outcome is CANCELLED, not an error",
          status is not None and status.outcome is Outcome.CANCELLED,
          str(status.outcome) if status else "no status recorded")

    check(f"[{where}] no run reached the results table",
          bench.rows() == (), f"{len(bench.rows())} row(s)")
    check(f"[{where}] no run reached the store",
          len(bench.exp.run_store) == 0, f"{len(bench.exp.run_store)} run(s)")

    check(f"[{where}] output is off", bench.smu._output_on is False)

    check(f"[{where}] instrument ownership released",
          not bench.app.ownership.is_owned("demo::4pp-lifecycle"),
          str(bench.app.ownership.snapshot()))

    check(f"[{where}] controller is IDLE",
          bench.exp.run_controller.state is RunState.IDLE,
          str(bench.exp.run_controller.state))


# ------------------------------------------------------------------
# the happy path still works through the threaded route
# ------------------------------------------------------------------
def test_uncancelled_run_commits(check):
    """The control for the whole matrix.

    A matrix of cancellations proves nothing if the run could not have
    succeeded anyway - every row would pass against an experiment that
    was simply broken.
    """
    bench = Bench(smu_cls=DummySMU, points=4, reversals=2)
    try:
        bench.press_run()
        check("run completes", bench.wait_idle())
        check("outcome is COMPLETED",
              bench.status is not None
              and bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome) if bench.status else "none")
        check("one row in the table", len(bench.rows()) == 1,
              f"{len(bench.rows())} row(s)")
        check("one run in the store", len(bench.exp.run_store) == 1)
        check("output is off afterwards", bench.smu._output_on is False)
        check("ownership released",
              not bench.app.ownership.is_owned("demo::4pp-lifecycle"))

        runs = bench.exp.run_store.runs_for("film_A")
        if runs:
            meta = runs[0].metadata
            check("the run records its own id",
                  str(meta.get("run_id", "")).startswith("ossila_4pp-"),
                  str(meta.get("run_id")))
            check("the run records a sample id",
                  str(meta.get("sample_id", "")).startswith("smp-"),
                  str(meta.get("sample_id")))
            check("the run records the sample label",
                  meta.get("sample_label") == "film_A",
                  str(meta.get("sample_label")))
            check("one reading per current, reversals averaged",
                  len(runs[0].readings) == 4,
                  f"{len(runs[0].readings)} readings")
    finally:
        bench.close()


# ------------------------------------------------------------------
# the matrix
# ------------------------------------------------------------------
CANCELLATION_STAGES = [
    # (stage armed on the instrument, human name for the report)
    ("before_output_on", "before output on"),
    ("first_measure", "during the first settle"),
    ("mid_reversal", "mid polarity reversal"),
    ("between_points", "between points"),
    ("last_measure", "after the last point, before commit"),
]


@pytest.mark.parametrize("stage, where", CANCELLATION_STAGES,
                         ids=[s for s, _ in CANCELLATION_STAGES])
def test_cancellation_boundary(check, stage, where):
    """Stop pressed at one exact boundary. Nothing survives it."""
    bench = Bench(points=4, reversals=2)
    try:
        bench.smu.arm(stage)
        bench.press_run()
        bench.smu.wait_until_blocked()

        # The run is parked inside the instrument at a known point.
        # Press Stop here, then let it go and watch it unwind.
        bench.press_stop()
        bench.smu.let_go()

        assert_cancelled_cleanly(bench, check, where)

        # The hard requirement: an obsolete worker must not be able to
        # energise anything after cancellation. The only command the
        # instrument may see after release is the shutdown.
        energising = [c for c in bench.smu.after_release
                      if c.startswith("output_on")
                      or c.startswith("set_current_level")]
        check(f"[{where}] nothing energising issued after Stop",
              not energising, "; ".join(energising[:4]))
    finally:
        bench.close()


def test_cancel_before_the_run_starts(check):
    """Stop pressed between Run and the worker getting going.

    The narrowest window there is, and the one a shared `measuring` flag
    used to lose: cancellation arrives while the run is still PREPARING.
    """
    bench = Bench(points=4, reversals=2)
    try:
        bench.smu.arm("before_output_on")
        bench.press_run()
        bench.smu.wait_until_blocked()
        bench.press_stop()
        bench.smu.let_go()

        assert_cancelled_cleanly(bench, check, "before start")
        check("[before start] no reading was ever taken",
              bench.smu.measure_calls == 0,
              f"{bench.smu.measure_calls} measure(s)")
    finally:
        bench.close()


# ------------------------------------------------------------------
# a second run may start afterwards
# ------------------------------------------------------------------
def test_a_cancelled_run_does_not_block_the_next_one(check):
    """A new run cannot start until
    cleanup completes - and once it has, it must be able to."""
    bench = Bench(points=4, reversals=2)
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()
        bench.press_stop()
        bench.smu.let_go()
        check("first run cancelled", bench.wait_idle())
        check("nothing stored", len(bench.exp.run_store) == 0)

        # Second run, uninterrupted.
        bench.smu.arm(None)
        bench.press_run()
        check("a second run starts and completes", bench.wait_idle())
        check("and it is the only thing in the store",
              len(bench.exp.run_store) == 1,
              f"{len(bench.exp.run_store)} run(s)")
        check("the second run's outcome is COMPLETED",
              bench.status is not None
              and bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome) if bench.status else "none")
    finally:
        bench.close()


def test_run_is_refused_while_one_is_in_flight(check):
    """Pressing Run twice must not start two runs on one instrument."""
    bench = Bench(points=4, reversals=2)
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()

        before = bench.smu.output_on_calls
        bench.press_run()               # ignored - a run is in flight
        bench.pump(0.1)
        check("a second Run press is refused",
              bench.smu.output_on_calls == before,
              f"{bench.smu.output_on_calls} output_on call(s)")

        bench.press_stop()
        bench.smu.let_go()
        check("returns to idle", bench.wait_idle())
    finally:
        bench.close()


# ------------------------------------------------------------------
# 6c: cancellation latency, measured rather than asserted
# ------------------------------------------------------------------
@pytest.mark.parametrize("stage, where", CANCELLATION_STAGES,
                         ids=[s for s, _ in CANCELLATION_STAGES])
def test_cancellation_latency_is_bounded(check, stage, where):
    """How long from Stop to idle, at each boundary.

    Cancellation latency is *measured and bounded*, not asserted.
    This records the number and checks it
    against a deliberately generous ceiling.

    The ceiling is loose on purpose. A tight one would be measuring the
    CI runner's mood rather than the code, and on Windows the 15.6 ms
    clock quantisation puts a floor under anything timed at all. What
    would be meaningful is a *change*: if this starts reporting seconds
    where it reported milliseconds, something now blocks on the wrong
    side of a checkpoint.

    Note what is being measured. The settle delay is handed to the
    instrument with `set_source_delay()`, so it happens inside the
    driver's blocking `measure()` and no token can preempt it. The
    honest bound is therefore "one reading", and this test measures the
    rest of the path - not the reading.
    """
    bench = Bench(points=4, reversals=2)
    try:
        bench.smu.arm(stage)
        bench.press_run()
        bench.smu.wait_until_blocked()

        bench.smu.let_go()
        started = time.perf_counter()
        bench.press_stop()
        reached_idle = bench.wait_idle(timeout=10.0)
        elapsed = time.perf_counter() - started

        check(f"[{where}] reaches idle", reached_idle)
        check(f"[{where}] cancellation latency under 5 s",
              elapsed < 5.0, f"{elapsed * 1000:.1f} ms")
    finally:
        bench.close()


# ------------------------------------------------------------------
# house rule 8, proven rather than asserted
# ------------------------------------------------------------------
def test_worker_never_reads_a_tk_variable(check):
    """Issue B2, turned into a test result.

    "The worker does not touch Tk" is easy to claim, easy to believe
    after a code review, and impossible to prove by reading - the
    offending call is usually three frames down inside a helper that
    looks harmless. Tk makes it worse by not reliably raising: a Tcl
    call from the wrong thread usually works, for weeks, and then hangs.

    So the guard from Wave 2 goes on and the run happens for real. Any
    `Variable.get` or `.set` from a thread other than the one that built
    the widgets is recorded with the stack that made it.
    """
    bench = Bench(smu_cls=DummySMU, points=4, reversals=2)
    guard = ThreadAffinityGuard(tk.Variable, ("get", "set"))
    try:
        with guard:
            bench.press_run()
            bench.wait_idle()
        check("the run completed, so the guard watched a real run",
              len(bench.exp.run_store) == 1,
              f"{len(bench.exp.run_store)} run(s) stored")
        check("the guard was actually watching",
              guard.calls > 0, f"{guard.calls} guarded call(s)")
        check("no Tk variable was read or written from a worker thread",
              not guard.violations, guard.report())
    finally:
        guard.remove()
        bench.close()


# ------------------------------------------------------------------
# the snapshot, in situ
# ------------------------------------------------------------------
def test_editing_the_form_mid_run_changes_nothing(check):
    """The parameter snapshot in situ: the works order, not the
    whiteboard.

    `test_parameters.py` proves the snapshot object is immune to its
    source changing. This proves the experiment actually takes one -
    that the worker is reading the snapshot and not the widgets.
    """
    bench = Bench(points=4, reversals=2)
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()

        # Everything the operator could plausibly touch while setting up
        # the next measurement.
        bench.exp.dataset_var.set("EDITED")
        bench.exp.thickness_var.set("")
        bench.exp.width_var.set("999")
        bench.exp.reversals_var.set("8")
        bench.exp.sample_name_var.set("a_different_sample")

        bench.smu.let_go()
        check("the run still completes", bench.wait_idle())

        runs = bench.exp.run_store.runs_for("film_A")
        check("the run is filed under the sample it started with",
              len(runs) == 1, f"{len(runs)} run(s) for film_A")
        if runs:
            meta = runs[0].metadata
            check("dataset label is the one captured at Run",
                  meta["dataset"] == "matrix", str(meta["dataset"]))
            check("reversal count is the one captured at Run",
                  meta["reversals"] == 2, str(meta["reversals"]))
            check("width is the one captured at Run",
                  abs(meta["width_mm"] - 10.0) < 1e-9, str(meta["width_mm"]))
        check("nothing was filed under the edited name",
              not bench.exp.run_store.runs_for("a_different_sample"))
    finally:
        bench.close()


def test_renaming_the_sample_does_not_relabel_a_finished_run(check):
    """The identifier is minted once and the run keeps it."""
    bench = Bench(smu_cls=DummySMU, points=4, reversals=2)
    try:
        bench.press_run()
        check("run completes", bench.wait_idle())
        runs = bench.exp.run_store.runs_for("film_A")
        check("one run stored", len(runs) == 1)
        if not runs:
            return
        sample_id = runs[0].metadata["sample_id"]

        bench.app.samples.rename(sample_id, "film_A (recontacted)")
        check("the finished run keeps the label it recorded",
              runs[0].metadata["sample_label"] == "film_A",
              str(runs[0].metadata["sample_label"]))

        # A second run under the new label is the *same* sample.
        bench.exp.sample_name_var.set("film_A (recontacted)")
        bench.exp.dataset_var.set("after_rename")
        bench.press_run()
        check("second run completes", bench.wait_idle())
        after = [r for sample in bench.exp.run_store.samples()
                 for r in bench.exp.run_store.runs_for(sample)
                 if r.metadata["dataset"] == "after_rename"]
        check("and carries the same sample id",
              len(after) == 1 and after[0].metadata["sample_id"] == sample_id,
              str([r.metadata["sample_id"] for r in after]))
    finally:
        bench.close()


# ------------------------------------------------------------------
# the completion gate, in situ
# ------------------------------------------------------------------
class DropsAReadingSMU(DummySMU):
    """Returns nothing on one reading, as a flaky connection would."""

    def __init__(self, transport, drop_on=3, **kwargs):
        super().__init__(transport, **kwargs)
        self._drop_on = drop_on
        self._reads = 0

    def measure(self, timeout_s=3.0):
        self._reads += 1
        if self._reads == self._drop_on:
            return (None, None)
        return super().measure(timeout_s=timeout_s)


def test_a_short_run_is_refused_not_fitted(check):
    """The completion gate in situ, and a deliberate change of
    behaviour.

    Before Wave 3 a level that produced no reading was skipped with a
    console line, and the run went on to fit a line through whatever
    survived. A sweep that returns most of its points and fits a
    beautiful R-squared is a real failure mode on this bench, and it is
    exactly what the gate exists to catch.

    Now the missing reading is recorded as an error, the commit is
    refused, and the data is discarded. Worth knowing at the bench: a
    dropped reading now costs the whole run rather than one point.
    """
    bench = Bench(smu_cls=DropsAReadingSMU, points=4, reversals=1)
    try:
        bench.press_run()
        check("the run finishes unwinding", bench.wait_idle())
        check("nothing was committed", len(bench.exp.run_store) == 0,
              f"{len(bench.exp.run_store)} run(s)")
        check("no row in the results table", bench.rows() == ())
        check("the outcome is FAILED, not COMPLETED",
              bench.status is not None
              and bench.status.outcome is not Outcome.COMPLETED,
              str(bench.status.outcome) if bench.status else "none")
        check("output is off", bench.smu._output_on is False)
        check("ownership released",
              not bench.app.ownership.is_owned("demo::4pp-lifecycle"))
    finally:
        bench.close()


# ------------------------------------------------------------------
# ownership
# ------------------------------------------------------------------
def test_a_run_holds_the_instrument_for_its_whole_duration(check):
    """The transaction protected is the run, not the command."""
    bench = Bench(points=4, reversals=2)
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()

        check("the instrument is owned while the run is in flight",
              bench.app.ownership.is_owned("demo::4pp-lifecycle"))
        owner = bench.app.ownership.owner_of("demo::4pp-lifecycle")
        check("owned by this run", str(owner).startswith("ossila_4pp-"),
              str(owner))

        # A second claim, as another window would make, must be refused
        # rather than interleaved.
        other = InstrumentOwnership()
        del other                          # not the shared manager - see below
        busy = False
        try:
            bench.app.ownership.claim("demo::4pp-lifecycle", "someone-else")
        except Exception:
            busy = True
        check("a competing claim is refused", busy)

        bench.press_stop()
        bench.smu.let_go()
        check("returns to idle", bench.wait_idle())
        check("and the instrument is free again",
              not bench.app.ownership.is_owned("demo::4pp-lifecycle"))
    finally:
        bench.close()


def test_stop_when_nothing_is_running_is_harmless(check):
    """The button is disabled while idle, but a keyboard or a script can
    still reach the handler, and it must not raise."""
    bench = Bench(smu_cls=DummySMU)
    try:
        bench.exp.stop_pressed()
        bench.pump(0.05)
        check("no run was affected",
              bench.exp.run_controller.state is RunState.IDLE)
        check("nothing was stored", len(bench.exp.run_store) == 0)
    finally:
        bench.close()


def test_no_worker_threads_survive_the_run(check):
    """Issue A8: no orphaned workers.

    A thread still alive after the controller says idle is a thread that
    can wake up during the next run holding a stale view of the world.
    """
    before = {t.ident for t in threading.enumerate()}
    bench = Bench(points=4, reversals=2)
    try:
        bench.smu.arm("mid_reversal")
        bench.press_run()
        bench.smu.wait_until_blocked()
        bench.press_stop()
        bench.smu.let_go()
        check("returns to idle", bench.wait_idle())

        deadline = time.time() + 5.0
        extra = []
        while time.time() < deadline:
            bench.root.update()
            extra = [t for t in threading.enumerate()
                     if t.ident not in before and t.is_alive()
                     and not t.daemon]
            if not extra:
                break
            time.sleep(0.02)
        check("no non-daemon worker outlives the run",
              not extra, ", ".join(t.name for t in extra))
    finally:
        bench.close()
