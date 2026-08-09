"""The Wave 5a-ii proof: Hall on the real run lifecycle.

Same machinery as `test_vdp_lifecycle.py`, different failure modes -
which is the reason this is a separate file rather than a shared
parameterised one. Hall differs from Van der Pauw in two ways that
matter here:

* **A run is one of eight.** The calculation needs Pos1+, Pos1-, Pos2+
  and Pos2-, and each of those runs contributes two voltages. A run that
  half-committed would put a row in the table looking exactly like the
  other seven, and the eight-term average would silently draw on a
  combination that was never measured.
* **The polarities are not averaged.** Van der Pauw folds +I and -I into
  one R(ave); Hall keeps them apart because the difference between them
  *is* the signal. So there is no "average of one block" failure here -
  there is a worse one, a row that claims a field direction it only half
  measured.

The field sign is the other thing under test. A Hall run is defined by
the pair (position, B sign); a run whose recorded sign did not match the
magnet is not slightly wrong, it is uninterpretable. That is why the
sign is in the frozen snapshot and why
`test_editing_the_form_mid_run_changes_nothing` checks it specifically.

Determinism, as everywhere in these files: the instrument blocks at a
named stage and waits, the test waits for a fact rather than a duration,
acts while the run is parked, then releases. See `tests/README.md`.
"""
import pytest

pytestmark = [pytest.mark.gui]

import time
import tkinter as tk

import core.base_app as base_app
import experiments.base_experiment as base_experiment
import experiments.hall.experiment as hall_experiment
from core.base_app import LabApp
from core.identity import SampleRegistry
from core.ownership import InstrumentOwnership
from core.run_control import Outcome, RunState
from core.transports.null_transport import NullTransport
from drivers.dummy_smu import DummySMU
from experiments.hall.experiment import HallExperiment

from stage_blocking_smu import StageBlockingSMU

OWNERSHIP_KEY = "demo::hall-lifecycle"


class DialogRecorder:
    """Swallow dialogs so a headless run doesn't block.

    Answers True: `run_pressed()` opens an `askokcancel` asking the
    operator to set the switch box and the magnet, and a recorder that
    answered False would make every test here pass by never starting a
    run at all.
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
hall_experiment.messagebox = dialogs
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs


class Bench:
    """One app, one experiment, one fake instrument, wired for a run."""

    def __init__(self, smu_cls=StageBlockingSMU, points=3, delay_ms="0",
                 position=1, field_sign="+"):
        self.root = tk.Tk()
        self.app = LabApp(self.root, HallExperiment,
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
        self.exp.pos_var.set(position)
        self.exp.field_sign_var.set(field_sign)
        self.exp.points_var.set(str(points))
        self.exp.delay_ms_var.set(delay_ms)
        self.exp.thickness_entry_var.set("1.5")
        self.points = points
        if hasattr(self.smu, "expect_readings"):
            # Two current polarities of `points` readings each.
            self.smu.expect_readings(points, 2)
        self.root.update()

    def press_run(self):
        self.exp.run_pressed()
        self.pump(0.05)

    def press_stop(self):
        self.exp.stop_pressed()

    def pump(self, seconds=0.5):
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.root.update()
            time.sleep(0.005)

    def wait_idle(self, timeout=10.0):
        """Pump until idle *and* the UI queue has been drained.

        The commit sink posts `_record_run` through `app.ui()`, so the
        controller reaches IDLE before the row is in the table.
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
# the happy path
# ------------------------------------------------------------------
def test_uncancelled_run_commits(check):
    """The control for the matrix.

    A matrix of cancellations proves nothing if the run could not have
    succeeded anyway.
    """
    bench = Bench(smu_cls=DummySMU, points=3, position=2, field_sign="-")
    try:
        bench.press_run()
        check("run completes", bench.wait_idle())
        check("outcome is COMPLETED",
              bench.status is not None
              and bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome) if bench.status else "none")
        check("one row in the table", len(bench.rows()) == 1,
              f"{len(bench.rows())} row(s)")

        runs = bench.exp.run_store.runs_for("wafer_A")
        if runs:
            meta = runs[0].metadata
            check("the run records its own id",
                  str(meta.get("run_id", "")).startswith("hall-"),
                  str(meta.get("run_id")))
            check("the run records a sample id",
                  str(meta.get("sample_id", "")).startswith("smp-"),
                  str(meta.get("sample_id")))
            check("the field direction is recorded",
                  meta.get("b_polarity") == "-", str(meta.get("b_polarity")))
            check("and the position with it",
                  meta.get("position") == 2, str(meta.get("position")))
            check("both current polarities are kept",
                  len(runs[0].readings) == 6,
                  f"{len(runs[0].readings)} readings")
            check("V+ and V- are both recorded, not averaged together",
                  meta.get("V_plus_V") != "" and meta.get("V_minus_V") != ""
                  and meta["V_plus_V"] != meta["V_minus_V"],
                  f"{meta.get('V_plus_V')} / {meta.get('V_minus_V')}")
    finally:
        bench.close()


# ------------------------------------------------------------------
# the matrix
# ------------------------------------------------------------------
CANCELLATION_STAGES = [
    ("before_output_on", "before output on"),
    ("first_measure", "during the first reading"),
    ("second_polarity", "at the current reversal"),
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

        bench.press_stop()
        bench.smu.let_go()

        assert_cancelled_cleanly(bench, check, where)

        energising = [c for c in bench.smu.after_release
                      if c.startswith("output_on")
                      or c.startswith("set_current_level")]
        check(f"[{where}] nothing energising issued after Stop",
              not energising, "; ".join(energising[:4]))
    finally:
        bench.close()


def test_cancelling_at_the_reversal_leaves_no_half_run(check):
    """Hall's own version of the flip failure.

    Van der Pauw would produce an average of one block. Hall would
    produce something worse: a row carrying a V+ and no V-, sitting in
    the table looking exactly like the other seven, feeding an
    eight-term average that draws on a field direction only half
    measured.

    The guarantee is not that the row would be marked incomplete. It is
    that the readings never leave the run context.
    """
    bench = Bench(points=3)
    try:
        bench.smu.arm("second_polarity")
        bench.press_run()
        bench.smu.wait_until_blocked()

        check("the positive block really was measured",
              bench.smu.measure_calls >= 3,
              f"{bench.smu.measure_calls} reading(s) taken")

        bench.press_stop()
        bench.smu.let_go()

        assert_cancelled_cleanly(bench, check, "at the reversal")
        check("no half-measured row anywhere",
              len(bench.exp.run_store) == 0 and bench.rows() == ())
    finally:
        bench.close()


def test_cancel_before_the_run_starts(check):
    """The narrowest window: cancellation while still PREPARING."""
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
# the bench stays usable
# ------------------------------------------------------------------
def test_a_cancelled_run_does_not_block_the_next_one(check):
    bench = Bench(points=3)
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()
        bench.press_stop()
        bench.smu.let_go()
        check("first run cancelled", bench.wait_idle())

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
    bench = Bench(points=3)
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()

        before = bench.smu.output_on_calls
        bench.press_run()
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
    bench = Bench(smu_cls=DummySMU, points=3)
    try:
        bench.press_stop()
        bench.pump(0.05)
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
    """Retyping the form mid-run must not reach the run in flight.

    The field sign is the one that matters most. If the operator flips
    the magnet selector while a run is measuring and the run recorded
    the new value, the file would claim a field direction the sample was
    never in - and the eight-term average would combine it with its
    supposed opposite, which was measured under the same conditions.
    The result is not noisy, it is wrong, and nothing about it looks
    unusual.
    """
    bench = Bench(points=3, position=1, field_sign="+")
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()

        bench.exp.field_sign_var.set("-")
        bench.exp.pos_var.set(2)
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
            check("the field sign is the one confirmed at the press",
                  meta["b_polarity"] == "+", str(meta["b_polarity"]))
            check("position too", meta["position"] == 1, str(meta["position"]))
            check("points are the ones requested",
                  meta["points_requested"] == 3,
                  str(meta["points_requested"]))
            check("thickness survives the box being blanked",
                  abs(meta["thickness_um"] - 1.5) < 1e-9,
                  str(meta["thickness_um"]))
            check("sample label is the one at the press",
                  meta["sample_label"] == "wafer_A",
                  str(meta["sample_label"]))
    finally:
        bench.close()


def test_a_short_block_is_refused_by_the_count(check):
    """Losing the connection mid-run must not commit a partial pair.

    The measurement loop breaks out when the instrument stops being
    connected - quietly, no exception, nothing recorded as an error - so
    the negative block ends short and the run's V- is an average over
    fewer readings than its V+. Nothing but the declared reading count
    catches that.

    Removing `run.expect(params.readings_n)` from `_do_run` turns this
    red and leaves every other test in this file green.
    """
    bench = Bench(points=3)
    try:
        real_is_connected = bench.app.is_connected
        state = {"n": 0}

        def flaky_is_connected(role):
            if role == "source":
                state["n"] += 1
                if state["n"] > 4:
                    return False
            return real_is_connected(role)

        bench.app.is_connected = flaky_is_connected
        bench.press_run()
        check("the run finishes one way or another", bench.wait_idle(),
              str(bench.exp.run_controller.state))
        check("the connection really did drop", state["n"] > 4,
              f"{state['n']} check(s)")

        check("no partial pair was committed",
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
