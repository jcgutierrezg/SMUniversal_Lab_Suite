"""The Wave 5a-i proof: Van der Pauw on the real run lifecycle.

What this file is for
---------------------
`test_saving.py` and `test_demo_mode.py` drive a Van der Pauw run
through `vdp_harness.run_vdp`, which calls `_do_run()` directly on the
main thread. That is the right shape for testing saving, grouping and
physics, and it means those tests say nothing at all about threading,
cancellation or ownership - the worker path is never entered.

This file goes the other way. Every test presses Run through
`run_pressed()`, so the measurement runs on a background thread exactly
as it does at the bench, and then presses Stop at a precisely known
instant.

The shape being tested is not 4PP's
-----------------------------------
`test_4pp_lifecycle.py` proved this machinery on one experiment. This is
not a copy of it, because Van der Pauw's sequence is a different shape
and its failure modes follow from that shape:

* it sources exactly twice per run, once per polarity, where 4PP walks a
  current list;
* the two blocks are **averaged into one number**. A cancellation that
  left the positive block behind would produce an R(ave) that is not an
  average of anything, and would look like a perfectly ordinary
  resistance. That is why `second_polarity` gets its own row;
* the settle is a host-side wait inside the worker (`run.sleep`), not a
  delay handed to the instrument, so cancellation during a settle is
  felt immediately rather than after the reading in progress returns.

The matrix
----------
Review §8 lists where a cancellation check belongs: before output-on,
before a source-function change, before each polarity flip, after every
long wait, and immediately before the final commit. Each is a boundary,
and each boundary gets a row. For every row the same things are
asserted: nothing committed, output off, outcome CANCELLED rather than
FAILED, ownership released, controller back to IDLE.

Determinism
-----------
The instant of cancellation is chosen, not timed. The instrument blocks
at a named stage and waits (`stage_blocking_smu.py`); the test waits for
a fact rather than a duration, presses Stop while the run is parked, and
then releases. A matrix built on sleeps would be a coin toss on a loaded
CI runner and on Windows's 15.6 ms clock, and an intermittently red
matrix teaches everyone to press re-run.

Tk roots are built here, so the file carries the `gui` marker and
`run_tests.py` gives it its own process.
"""
import pytest

pytestmark = [pytest.mark.gui]

import time
import tkinter as tk

import core.base_app as base_app
import experiments.base_experiment as base_experiment
import experiments.vanderpauw.experiment as vdp_experiment
from core.base_app import LabApp
from core.identity import SampleRegistry
from core.ownership import InstrumentOwnership
from core.run_control import Outcome, RunState
from core.transports.null_transport import NullTransport
from drivers.dummy_smu import DummySMU
from experiments.vanderpauw.experiment import VanDerPauwExperiment

from stage_blocking_smu import StageBlockingSMU

OWNERSHIP_KEY = "demo::vdp-lifecycle"


class DialogRecorder:
    """Swallow dialogs so a headless run doesn't block.

    Answers True, which matters more here than on 4PP: `run_pressed()`
    opens an `askokcancel` asking the operator to set the switch box,
    and a recorder that answered False would make every test in this
    file pass by never starting a run at all.
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
vdp_experiment.messagebox = dialogs
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs


# ------------------------------------------------------------------
# harness
# ------------------------------------------------------------------
class Bench:
    """One app, one experiment, one fake instrument, wired for a run."""

    def __init__(self, smu_cls=StageBlockingSMU, points=3, delay_ms="0"):
        self.root = tk.Tk()
        # Its own ownership manager and sample registry, so nothing here
        # can be affected by - or leak into - another test file sharing
        # the process-wide defaults.
        self.app = LabApp(self.root, VanDerPauwExperiment,
                          ownership=InstrumentOwnership(),
                          samples=SampleRegistry())
        self.exp = self.app.experiment

        transport = NullTransport()
        self.smu = smu_cls(transport)
        transport.connect("demo")
        self.app.instruments["source"] = self.smu
        self.app.transports["source"] = transport
        self.app.instrument_keys["source"] = OWNERSHIP_KEY
        self.root.update()

        self.exp.sample_name_var.set("wafer_A")
        self.exp.pos_var.set(1)
        self.exp.points_var.set(str(points))
        self.exp.delay_ms_var.set(delay_ms)
        self.exp.thickness_entry_var.set("180")
        self.points = points
        if hasattr(self.smu, "expect_readings"):
            # Two polarity blocks of `points` readings each. Told to the
            # fake so it knows which `measure()` is the last one - it
            # sees a stream of reads with no idea how many are coming.
            self.smu.expect_readings(points, 2)
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

        Draining afterwards is correctness, not tidiness: the commit
        sink posts `_record_run` to the UI queue, so the controller
        reaches IDLE before the row is in the results table. Asserting
        on the store the instant idle goes true would race the pump.
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
    """The things every cancelled run must be true of."""
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
          not bench.app.ownership.is_owned(OWNERSHIP_KEY),
          str(bench.app.ownership.snapshot()))

    check(f"[{where}] controller is IDLE",
          bench.exp.run_controller.state is RunState.IDLE,
          str(bench.exp.run_controller.state))


# ------------------------------------------------------------------
# the happy path, through the threaded route
# ------------------------------------------------------------------
def test_uncancelled_run_commits(check):
    """The control for the whole matrix.

    A matrix of cancellations proves nothing if the run could not have
    succeeded anyway - every row would pass against an experiment that
    was simply broken.
    """
    bench = Bench(smu_cls=DummySMU, points=3)
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
              not bench.app.ownership.is_owned(OWNERSHIP_KEY))

        runs = bench.exp.run_store.runs_for("wafer_A")
        if runs:
            meta = runs[0].metadata
            check("the run records its own id",
                  str(meta.get("run_id", "")).startswith("vanderpauw-"),
                  str(meta.get("run_id")))
            check("the run records a sample id",
                  str(meta.get("sample_id", "")).startswith("smp-"),
                  str(meta.get("sample_id")))
            check("the run records the sample label",
                  meta.get("sample_label") == "wafer_A",
                  str(meta.get("sample_label")))
            check("both polarity blocks are kept",
                  len(runs[0].readings) == 6,
                  f"{len(runs[0].readings)} readings")
            polarities = {r["polarity"] for r in runs[0].readings}
            check("and are labelled as such", polarities == {"pos", "neg"},
                  str(polarities))
            check("R(ave) is the mean of the two blocks",
                  abs(meta["R_ave_ohm"]
                      - 0.5 * (meta["R_pos_ohm"] + meta["R_neg_ohm"])) < 1e-9,
                  f"{meta['R_ave_ohm']}")
    finally:
        bench.close()


# ------------------------------------------------------------------
# the matrix
# ------------------------------------------------------------------
CANCELLATION_STAGES = [
    # (stage armed on the instrument, human name for the report)
    ("before_output_on", "before output on"),
    ("first_measure", "during the first reading"),
    ("second_polarity", "at the polarity flip"),
    ("last_measure", "after the last point, before commit"),
]


@pytest.mark.parametrize("stage, where", CANCELLATION_STAGES,
                         ids=[s for s, _ in CANCELLATION_STAGES])
def test_cancellation_boundary(check, stage, where):
    """Stop pressed at one exact boundary. Nothing survives it."""
    bench = Bench(points=3)
    try:
        bench.smu.arm(stage)
        bench.press_run()
        bench.smu.wait_until_blocked()

        # The run is parked inside the instrument at a known point.
        # Press Stop here, then let it go and watch it unwind.
        bench.press_stop()
        bench.smu.let_go()

        assert_cancelled_cleanly(bench, check, where)

        # §8's hard requirement: an obsolete worker must not be able to
        # energise anything after cancellation. The only command the
        # instrument may see after release is the shutdown.
        energising = [c for c in bench.smu.after_release
                      if c.startswith("output_on")
                      or c.startswith("set_current_level")]
        check(f"[{where}] nothing energising issued after Stop",
              not energising, "; ".join(energising[:4]))
    finally:
        bench.close()


def test_cancelling_at_the_flip_discards_the_first_block(check):
    """The failure this experiment has that 4PP does not.

    Van der Pauw averages its two polarity blocks. A cancellation that
    left the positive block behind would give an R(ave) that is not an
    average of anything - and it would be a completely ordinary-looking
    resistance, roughly half the size it should be. Nothing on screen
    would say so.

    The guarantee is not "the average is computed carefully". It is that
    the readings never leave the run context at all.
    """
    bench = Bench(points=3)
    try:
        bench.smu.arm("second_polarity")
        bench.press_run()
        bench.smu.wait_until_blocked()

        # The positive block has been measured in full by now - that is
        # what makes this the interesting moment rather than a repeat of
        # the earlier row.
        check("the first block really was measured",
              bench.smu.measure_calls >= 3,
              f"{bench.smu.measure_calls} reading(s) taken")

        bench.press_stop()
        bench.smu.let_go()

        assert_cancelled_cleanly(bench, check, "at the flip")
        check("no half-averaged resistance anywhere",
              len(bench.exp.run_store) == 0 and bench.rows() == ())
    finally:
        bench.close()


def test_cancel_before_the_run_starts(check):
    """Stop pressed between Run and the worker getting going.

    The narrowest window there is, and the one a shared `measuring` flag
    used to lose: cancellation arrives while the run is still PREPARING.
    """
    bench = Bench(points=3)
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
    """Cancelling must leave the bench usable.

    A Stop that released the instrument but left the controller busy, or
    released the controller but kept the instrument, would show up as
    "the next Run press does nothing" - with no error and nothing in the
    log to explain it.
    """
    bench = Bench(points=3)
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()
        bench.press_stop()
        bench.smu.let_go()
        check("first run cancelled", bench.wait_idle())

        # Nothing armed this time: the run should go all the way.
        bench.smu.arm("never_reached_stage")
        bench.smu.release.set()
        bench.press_run()
        check("second run completes", bench.wait_idle(), str(bench.status))
        check("and commits",
              bench.status is not None
              and bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome) if bench.status else "none")
        check("exactly one row, from the second run",
              len(bench.rows()) == 1, f"{len(bench.rows())} row(s)")
    finally:
        bench.close()


def test_run_is_refused_while_one_is_in_flight(check):
    """Two runs on one SMU is the thing ownership exists to prevent."""
    bench = Bench(points=3)
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()

        before = bench.smu.output_on_calls
        bench.press_run()               # second press, mid-run
        bench.pump(0.1)
        check("the second press started nothing",
              bench.smu.output_on_calls == before,
              f"{bench.smu.output_on_calls} vs {before}")

        bench.press_stop()
        bench.smu.let_go()
        check("cleans up regardless", bench.wait_idle())
    finally:
        bench.close()


def test_a_run_holds_the_instrument_for_its_whole_duration(check):
    """Ownership is claimed before the first command and released after
    the terminal status, not when the worker thread happens to end."""
    bench = Bench(points=3)
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()

        check("owned while running",
              bench.app.ownership.is_owned(OWNERSHIP_KEY),
              str(bench.app.ownership.snapshot()))

        bench.press_stop()
        bench.smu.let_go()
        bench.wait_idle()

        check("released once idle",
              not bench.app.ownership.is_owned(OWNERSHIP_KEY),
              str(bench.app.ownership.snapshot()))
    finally:
        bench.close()


def test_stop_when_nothing_is_running_is_harmless(check):
    """Stop is the only interrupt control, so it gets pressed idly.

    It must not raise, must not talk to the instrument, and must not
    leave the controller in a state that refuses the next Run.
    """
    bench = Bench(smu_cls=DummySMU, points=3)
    try:
        bench.press_stop()
        bench.pump(0.05)
        check("no commands issued", bench.smu.output_on_calls == 0
              if hasattr(bench.smu, "output_on_calls") else True)
        check("still idle", bench.exp.run_controller.is_idle)

        bench.press_run()
        check("and a run still starts afterwards", bench.wait_idle())
        check("which commits", len(bench.rows()) == 1)
    finally:
        bench.close()


# ------------------------------------------------------------------
# the snapshot holds
# ------------------------------------------------------------------
def test_editing_the_form_mid_run_changes_nothing(check):
    """Retyping the form while a run is in flight must not reach it.

    The parameters were frozen at the Run press. This is the property
    that makes a run reproducible from its own metadata: what the file
    says was measured is what was measured.
    """
    bench = Bench(points=3)
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()

        # An operator mid-edit, at the worst possible moment.
        bench.exp.pos_var.set(4)
        bench.exp.points_var.set("99")
        bench.exp.thickness_entry_var.set("")
        bench.exp.sample_name_var.set("wafer_B")

        bench.smu.let_go()
        check("run completes", bench.wait_idle(), str(bench.status))

        runs = bench.exp.run_store.runs_for("wafer_A")
        check("the run is filed under the sample it started on",
              len(runs) == 1, f"{len(bench.exp.run_store)} run(s) stored")
        if runs:
            meta = runs[0].metadata
            check("position is the one confirmed at the press",
                  meta["position"] == 1, str(meta["position"]))
            check("points are the ones requested",
                  meta["points_requested"] == 3,
                  str(meta["points_requested"]))
            check("thickness survives the box being blanked",
                  abs(meta["thickness_um"] - 180.0) < 1e-6,
                  str(meta["thickness_um"]))
            check("sample label is the one at the press",
                  meta["sample_label"] == "wafer_A",
                  str(meta["sample_label"]))
    finally:
        bench.close()


def test_a_dropout_is_recorded_as_an_error_not_absorbed(check):
    """A reading that fails must block the commit.

    `_polarity_block` catches the exception so one bad point does not
    abort the run mid-sequence with the output live - but it records the
    failure on the run, and an unresolved error is one of the conditions
    `CompletionPolicy` refuses. Without that, the run would commit with
    a blank reading in the table and an R(ave) averaged over whatever
    did come back.
    """
    bench = Bench(points=3)
    try:
        original = bench.smu.measure
        state = {"n": 0}

        def flaky_measure(*args, **kwargs):
            state["n"] += 1
            if state["n"] > 4:
                raise RuntimeError("simulated instrument dropout")
            return original(*args, **kwargs)

        bench.smu.measure = flaky_measure
        bench.press_run()
        check("the run finishes one way or another", bench.wait_idle(),
              str(bench.exp.run_controller.state))
        check("the dropout really happened", state["n"] > 4,
              f"{state['n']} measure call(s)")

        check("nothing was committed", len(bench.exp.run_store) == 0,
              f"{len(bench.exp.run_store)} run(s)")
        check("and the table stayed empty", bench.rows() == (),
              f"{len(bench.rows())} row(s)")
        check("the outcome is not COMPLETED",
              bench.status is None
              or bench.status.outcome is not Outcome.COMPLETED,
              str(bench.status.outcome) if bench.status else "none")
        check("output is off", bench.smu._output_on is False)
    finally:
        bench.close()


def test_a_short_block_is_refused_by_the_count(check):
    """Losing the connection mid-run must not commit a partial average.

    This is the gap the error check above does *not* cover, and the
    reason `run.expect()` is called at the press. The measurement loop
    breaks out when the instrument stops being connected - quietly, with
    no exception and nothing recorded as an error - so the negative
    block ends short and R(ave) becomes a full positive block averaged
    against a partial negative one. Systematically wrong, entirely
    plausible on screen.

    Nothing but the declared reading count catches it. Removing
    `run.expect(params.readings_n)` from `_do_run` turns this red and
    leaves every other test in this file green.
    """
    bench = Bench(points=3)
    try:
        real_is_connected = bench.app.is_connected
        state = {"n": 0}

        def flaky_is_connected(role):
            if role == "source":
                state["n"] += 1
                if state["n"] > 4:      # drops during the negative block
                    return False
            return real_is_connected(role)

        bench.app.is_connected = flaky_is_connected
        bench.press_run()
        check("the run finishes one way or another", bench.wait_idle(),
              str(bench.exp.run_controller.state))
        check("the connection really did drop", state["n"] > 4,
              f"{state['n']} check(s)")

        check("no partial average was committed",
              len(bench.exp.run_store) == 0,
              f"{len(bench.exp.run_store)} run(s)")
        check("and the table stayed empty", bench.rows() == (),
              f"{len(bench.rows())} row(s)")
        check("the outcome is not COMPLETED",
              bench.status is None
              or bench.status.outcome is not Outcome.COMPLETED,
              str(bench.status.outcome) if bench.status else "none")

        reasons = " ".join(bench.status.detail.split()) if bench.status else ""
        check("and the reason names the shortfall",
              "expected" in reasons and "readings" in reasons,
              reasons[:120])
    finally:
        bench.close()
