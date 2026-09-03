"""Fixed sourcing vs time on the real run lifecycle, stopped everywhere.

`test_fixed_source.py` drives `_do_run()` on the main thread. That is
the right shape for testing what the measurement records, and it means
those tests say nothing about threading, cancellation or ownership - the
worker path is never entered.

This file goes the other way. Every test presses a button through the
handler, so the run happens on a background thread exactly as it does at
the bench, and then presses Stop or Finish at a precisely known instant.

Two controls, two contracts
---------------------------
This is the only experiment in the suite with two ways to end a run
early, so the matrix has to prove both, and prove they differ:

    Stop and discard    cancel; nothing reaches the table, whatever the
                        progress. The house contract, unchanged.
    Finish and save     stop sampling; what was collected is committed.

A test of either one alone would pass against code that treated both
the same, which is the failure worth designing against here - the two
buttons sit next to each other and one of them throws data away.

Determinism
-----------
The instant is not timed, it is *chosen*. The instrument blocks at a
named stage and waits (`stage_blocking_smu.py`), the test waits for a
fact rather than a duration, acts while the run is parked, then
releases. A matrix built on sleeps would be a coin toss on a loaded
runner, and an intermittently red matrix teaches everybody to press
re-run.

Tk roots are built here, so the file carries the `gui` marker and
`run_tests.py` gives it its own process.
"""
import pytest

pytestmark = [pytest.mark.gui]

import time
import tkinter as tk

from stage_blocking_smu import StageBlockingSMU

import core.base_app as base_app
import experiments.base_experiment as base_experiment
import experiments.fixed_source.experiment as fixed_source
from core.base_app import LabApp
from core.identity import SampleRegistry
from core.ownership import InstrumentOwnership
from core.run_control import Outcome, RunState
from core.transports.null_transport import NullTransport
from drivers.dummy_smu import DummySMU
from experiments.fixed_source.experiment import FixedSourceExperiment

OWNERSHIP_KEY = "demo::fixed-source-lifecycle"


class DialogRecorder:
    """Swallow dialogs so a headless run doesn't block.

    Three modules import `messagebox`, not two - `LabApp.on_close()` has
    its own. An unstubbed one blocks the suite on the *second* test with
    the first already printed as a pass.
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


class Bench:
    """One app, one experiment, one blocking instrument, wired to run."""

    def __init__(self, smu_cls=StageBlockingSMU, duration="0.4",
                 interval="0.1", samples=5):
        self.root = tk.Tk()
        # Its own ownership manager and sample registry, so nothing here
        # can be affected by - or leak into - another test file sharing
        # the process-wide defaults.
        self.app = LabApp(self.root, FixedSourceExperiment,
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

        self.exp.sample_name_var.set("film_A")
        self.exp.mode_var.set("voltage")
        self.exp.on_mode_changed()
        self.exp.level_var.set("0.1")
        self.exp.compliance_var.set("0.01")
        self.exp.duration_var.set(duration)
        self.exp.interval_var.set(interval)
        self.exp.dataset_var.set("trace")
        self.samples = samples
        if hasattr(self.smu, "expect_readings"):
            # One reading per sample; there are no reversals here.
            self.smu.expect_readings(samples, 1)
        self.root.update()

    # ---- driving ----
    def press_run(self):
        self.exp.run_pressed()
        self.pump(0.05)

    def press_stop(self):
        self.exp.stop_pressed()

    def press_finish(self):
        self.exp.finish_pressed()

    def pump(self, seconds=0.5):
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.root.update()
            time.sleep(0.005)

    def wait_idle(self, timeout=15.0):
        """Pump until the controller is idle *and* the UI has caught up.

        Draining afterwards is correctness, not tidiness: the commit
        sink posts `_record_run` to the UI queue, so the controller
        reaches IDLE before the row is in the results table.
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
          not bench.app.ownership.is_owned(OWNERSHIP_KEY),
          str(bench.app.ownership.snapshot()))

    check(f"[{where}] controller is IDLE",
          bench.exp.run_controller.state is RunState.IDLE,
          str(bench.exp.run_controller.state))


# ------------------------------------------------------------------
# the control
# ------------------------------------------------------------------
def test_an_uninterrupted_run_commits(check):
    """The control for the whole matrix.

    A matrix of interruptions proves nothing if the run could not have
    succeeded anyway - every row would pass against an experiment that
    was simply broken.
    """
    bench = Bench(smu_cls=DummySMU)
    try:
        bench.press_run()
        check("run completes", bench.wait_idle())
        check("outcome is COMPLETED",
              bench.status is not None
              and bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome) if bench.status else "none")
        check("one row in the table", len(bench.rows()) == 1,
              f"{len(bench.rows())} row(s)")
        check("output is off afterwards", bench.smu._output_on is False)
        check("ownership released",
              not bench.app.ownership.is_owned(OWNERSHIP_KEY))

        runs = bench.exp.run_store.runs_for("film_A")
        if runs:
            meta = runs[0].metadata
            check("the run records its own id",
                  str(meta.get("run_id", "")).startswith("fixed_source-"),
                  str(meta.get("run_id")))
            check("the run records the sample it was measured under",
                  meta.get("sample_label") == "film_A",
                  str(meta.get("sample_label")))
            check("five samples landed", len(runs[0].readings) == 5,
                  f"{len(runs[0].readings)} readings")
    finally:
        bench.close()


# ------------------------------------------------------------------
# Stop: the house contract, at every boundary
# ------------------------------------------------------------------
CANCELLATION_STAGES = [
    ("before_output_on", "before output on"),
    ("first_measure", "during the first reading"),
    ("last_measure", "after the last sample, before commit"),
]


@pytest.mark.parametrize("stage, where", CANCELLATION_STAGES,
                         ids=[s for s, _ in CANCELLATION_STAGES])
def test_stop_and_discard_at_a_boundary(check, stage, where):
    """Stop pressed at one exact boundary. Nothing survives it."""
    bench = Bench()
    try:
        bench.smu.arm(stage)
        bench.press_run()
        bench.smu.wait_until_blocked()

        bench.press_stop()
        bench.smu.let_go()

        assert_cancelled_cleanly(bench, check, where)

        # An obsolete worker must not be able to energise anything after
        # cancellation. The only command the instrument may see after
        # release is the shutdown.
        energising = [c for c in bench.smu.after_release
                      if c.startswith("output_on")
                      or c.startswith("set_voltage_level")
                      or c.startswith("set_current_level")]
        check(f"[{where}] nothing energising after cancellation",
              energising == [], str(energising))
    finally:
        bench.close()


# ------------------------------------------------------------------
# Finish: the operation that is not Stop
# ------------------------------------------------------------------
def test_finish_and_save_keeps_the_samples_taken_so_far(check):
    """The whole reason this tab has a second button.

    Parked on the last reading of a five-sample run, Finish must commit
    those five rather than throw them away. The paired test below
    presses Stop at the same instant and gets nothing, which is what
    makes this one mean something: on its own it would pass against code
    that never discarded anything.
    """
    bench = Bench()
    try:
        bench.smu.arm("last_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()

        bench.press_finish()
        bench.smu.let_go()

        check("returns to idle", bench.wait_idle(),
              str(bench.exp.run_controller.state))
        check("outcome is COMPLETED, not CANCELLED",
              bench.status.outcome is Outcome.COMPLETED,
              str(bench.status.outcome))
        check("the run reached the results table", len(bench.rows()) == 1,
              f"{len(bench.rows())} row(s)")

        runs = bench.exp.run_store.runs_for("film_A")
        if runs:
            check("its samples were kept", len(runs[0].readings) == 5,
                  f"{len(runs[0].readings)} readings")
            check("and it says the operator ended it",
                  runs[0].metadata["ended_by"] == "operator",
                  runs[0].metadata["ended_by"])

        check("output is off", bench.smu._output_on is False)
        check("ownership released",
              not bench.app.ownership.is_owned(OWNERSHIP_KEY))
    finally:
        bench.close()


def test_stop_at_the_same_instant_keeps_nothing(check):
    """The pair to the test above, at the identical boundary.

    Same instrument, same stage, same moment - only the button differs.
    Together the two prove the buttons are not the same operation
    wearing two labels, which is exactly the confusion two adjacent
    controls invite.
    """
    bench = Bench()
    try:
        bench.smu.arm("last_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()

        bench.press_stop()
        bench.smu.let_go()

        assert_cancelled_cleanly(bench, check, "stop at last sample")
    finally:
        bench.close()


def test_finish_does_not_talk_to_the_instrument(check):
    """The reason this is a flag and not a command.

    Wave 6 removed the OFF buttons because `off_pressed()` called into
    the driver from a *second* thread while the worker was
    mid-`measure()` on the same session. Finish is a new control but it
    must not be a new race: pressing it while a reading is in flight
    must issue nothing at all, and the worker must do the de-energising
    on the thread that owns the session.
    """
    bench = Bench()
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()

        # Counters, not `after_release`: that list stays empty until
        # `let_go()`, so comparing it while the run is parked would be
        # true whatever the button did - an assertion whose interesting
        # answer is not the correct one (fault 19).
        offs_before = bench.smu.output_off_calls
        ons_before = bench.smu.output_on_calls
        levels_before = bench.smu.level_calls

        bench.press_finish()
        bench.pump(0.05)

        check("the press did not put the output away itself",
              bench.smu.output_off_calls == offs_before,
              f"{bench.smu.output_off_calls} vs {offs_before}")
        check("nor touched the output state",
              bench.smu.output_on_calls == ons_before)
        check("nor set a level",
              bench.smu.level_calls == levels_before)

        bench.smu.let_go()
        check("returns to idle", bench.wait_idle())
        check("the output was put away", bench.smu._output_on is False)
        check("and the shutdown is the only thing after release",
              all(c in ("output_off", "safe_output_off", "measure",
                        "compliance_tripped")
                  for c in bench.smu.after_release),
              str(bench.smu.after_release))
    finally:
        bench.close()


def test_a_finish_does_not_leak_into_the_next_run(check):
    """The flag belongs to one run, and only to that run.

    A press that lands as a run is already unwinding would otherwise sit
    there set, and the *next* run would end after its first sample -
    below the two-sample floor, so it would be refused outright with
    nothing on screen to explain why. One shared flag across runs is the
    same class of fault as one shared sweep buffer, which is what
    review §20 was written about.
    """
    bench = Bench()
    try:
        bench.smu.arm("last_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()
        bench.press_finish()
        bench.smu.let_go()
        check("the first run finished", bench.wait_idle())
        check("and committed", len(bench.rows()) == 1,
              f"{len(bench.rows())} row(s)")

        # Nothing armed this time: the second run should be ordinary.
        bench.press_run()
        check("the second run finished", bench.wait_idle())
        check("the second run also committed", len(bench.rows()) == 2,
              f"{len(bench.rows())} row(s)")

        second = bench.exp.run_store.runs_for("film_A")[-1]
        check("it ran to its duration rather than a stale flag",
              second.metadata["ended_by"] == "duration",
              second.metadata["ended_by"])
        check("and collected its full five samples",
              len(second.readings) == 5, str(len(second.readings)))
    finally:
        bench.close()


def test_closing_the_window_cancels_rather_than_saving(check):
    """A window being closed is not an operator keeping their data.

    `on_close()` cancels. Committing a run into a results table that is
    about to be destroyed would write nothing anywhere useful, and the
    part that matters for the sample - de-energising - happens either
    way.
    """
    bench = Bench()
    try:
        bench.smu.arm("first_measure")
        bench.press_run()
        bench.smu.wait_until_blocked()

        bench.exp.on_close()
        bench.smu.let_go()

        check("returns to idle", bench.wait_idle())
        check("the run was cancelled, not completed",
              bench.status.outcome is Outcome.CANCELLED,
              str(bench.status.outcome))
        check("nothing reached the store", len(bench.exp.run_store) == 0)
        check("the output is off", bench.smu._output_on is False)
    finally:
        bench.close()
