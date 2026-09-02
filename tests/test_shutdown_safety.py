"""Closing the window, with each of its failures injected in turn.

Why this file exists
--------------------
Closing was the one path in the application with no error handling at
all. Three `except Exception: pass` blocks stood between an operator
pressing the X and the process exiting, and each of them turned a
failure into a silent success:

* the temperature stage's PID was switched off with a fire-and-forget
  write, and any exception from it was swallowed. A heater could stay
  enabled after the application disappeared, with nothing on screen;
* the unsaved-measurement prompt - the safety net for runs that live
  only in memory - was wrapped whole, so an error in counting or in the
  dialog became "nothing to save" and the runs were discarded;
* the close path never waited for a measurement worker, so cancellation
  raced transport teardown.

Every test here injects one of those failures. The existing coverage
asserted the success path (`pid_off()` is called once), which is exactly
the shape of test that passes whether or not the failure handling
exists.

What is asserted, and what is deliberately not
----------------------------------------------
The claims are about **what the operator is told** and **what order
things happen in**, not about implementation. A stage that cannot be
confirmed off must produce a warning naming the stage; a straggling
worker must be named; an unreadable results table must leave the window
open. `LabApp.close_log` exists so the ordering can be read rather than
inferred from side effects.

Dialogs are stubbed in an autouse fixture rather than at import time.
The close path now raises modal warnings of its own, so a file where
only some tests neutralised dialogs would be a file that hangs on the
others - see docs/faults/28-a-dialog-nobody-stubbed.md. Installing in a
fixture also keeps this file out of the recorder-ownership hazard that
`_dialog_recorder_belongs_to_this_file` guards.

Tk roots are built here, so the file carries the `gui` marker and
`run_tests.py` gives it its own process.
"""
import pytest

pytestmark = [pytest.mark.gui]

import threading
import time
import tkinter as tk

import core.base_app as base_app
import devices.temperature_control as tc
import experiments.base_experiment as base_experiment
import experiments.ossila_4pp.experiment as fourpp_experiment
from core.base_app import ClosePhase, LabApp
from core.identity import SampleRegistry
from core.ownership import InstrumentOwnership
from core.run_control import ShutdownStatus
from core.transports.null_transport import NullTransport
from devices.temperature_control import (StageShutdownReport,
                                         TemperatureController)
from drivers.dummy_smu import DummySMU
from experiments.base_experiment import Experiment
from experiments.fixed_source.experiment import FixedSourceExperiment
from experiments.hall.experiment import HallExperiment
from experiments.iv_sweep.experiment import IVSweepExperiment
from experiments.ossila_4pp.experiment import Ossila4PPExperiment
from experiments.vanderpauw.experiment import VanDerPauwExperiment

from stage_blocking_smu import StageBlockingSMU

ALL_EXPERIMENTS = (FixedSourceExperiment, HallExperiment, IVSweepExperiment,
                   Ossila4PPExperiment, VanDerPauwExperiment)


# ------------------------------------------------------------------
# dialogs
# ------------------------------------------------------------------
class Dialogs:
    """Records dialogs instead of showing them.

    Every call returns rather than blocking. `askyesno` answers True -
    the operator saying "yes, discard and close" - because that is the
    answer that lets a test about something *else* reach the rest of the
    close path. The tests that care about the answer set it themselves.
    """

    def __init__(self):
        self.calls = []
        self.answer = True
        self.raise_on = None

    def __getattr__(self, name):
        def record(title="", message="", **kwargs):
            if self.raise_on == name:
                raise RuntimeError("the dialog subsystem is unavailable")
            self.calls.append((name, title, message))
            return self.answer if name.startswith("ask") else None
        record.__name__ = name
        return record

    def titles(self, kind=None):
        return [t for name, t, _ in self.calls if kind is None or name == kind]

    @property
    def text(self):
        return " ".join(f"{t} {m}" for _, t, m in self.calls).lower()


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    stub = Dialogs()
    for seam in (base_app, base_experiment, fourpp_experiment):
        monkeypatch.setattr(seam, "messagebox", stub)
    return stub


# ------------------------------------------------------------------
# fakes
# ------------------------------------------------------------------
class Stage:
    """A temperature stage whose shutdown ending the test chooses.

    Used where the ending is the fixture rather than the thing under
    test. Where the *controller's own* decision matters, the tests below
    drive a real `TemperatureController` over a fake port instead -
    injecting the fault at the wire rather than above the layer that has
    to notice it.
    """

    def __init__(self, report=None, raises=None, close_raises=None):
        self.report = report or StageShutdownReport(
            ShutdownStatus.CONFIRMED, "the stage reports IDLE after OFF")
        self.raises = raises
        self.close_raises = close_raises
        self.calls = 0
        self.closed = 0

    def is_connected(self):
        return True

    def confirm_pid_off(self):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.report

    def close(self):
        self.closed += 1
        if self.close_raises is not None:
            raise self.close_raises


class Port:
    """Just enough pyserial for the stage's reader thread.

    Broadcasts `line` forever, so a status line can arrive *after* an
    OFF - which is what `confirm_pid_off()` looks for. Set `line` to
    None to make the board go quiet mid-test.
    """

    def __init__(self, line=None, write_error=None, close_error=None):
        self.line = line
        self.write_error = write_error
        self.close_error = close_error
        self.written = []
        self.closed = False

    def readline(self):
        time.sleep(0.01)
        line = self.line
        return b"" if line is None else (line + "\n").encode()

    def write(self, data):
        if self.write_error is not None:
            raise self.write_error
        self.written.append(data.decode())
        return len(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        pass

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class SerialModule:
    def __init__(self, port):
        self.port = port

    def Serial(self, port, baudrate, timeout, write_timeout):
        return self.port


def real_stage_on(port, monkeypatch):
    """A genuine `TemperatureController` talking to `port`."""
    monkeypatch.setattr(tc, "serial", SerialModule(port))
    controller = TemperatureController()
    controller.connect("COM_TEST")
    return controller


class UnreadableStore:
    """A results table whose unsaved state cannot be determined.

    Stands in for whatever a real one would do if it went wrong. The
    point is not the cause; it is that the close path must not read the
    failure as "there is nothing to lose".
    """

    def __init__(self, held=3):
        self.held = held

    @property
    def has_unsaved(self):
        raise RuntimeError("the results table is in an unknown state")

    def __len__(self):
        return self.held


class RecordingController:
    """A run controller that only remembers being asked to cancel."""

    def __init__(self):
        self.reasons = []

    def request_cancel(self, reason="operator"):
        self.reasons.append(reason)
        return True


# ------------------------------------------------------------------
# harness
# ------------------------------------------------------------------
class Bench:
    """One 4PP window, one fake instrument, wired for a run."""

    def __init__(self, smu_cls=DummySMU, stage=None, points=2, reversals=2):
        self.root = tk.Tk()
        self.app = LabApp(self.root, Ossila4PPExperiment,
                          ownership=InstrumentOwnership(),
                          samples=SampleRegistry())
        if stage is not None:
            self.app.temp_ctrl = stage
        self.exp = self.app.experiment

        transport = NullTransport()
        self.smu = smu_cls(transport)
        transport.connect("demo")
        self.app.instruments["source"] = self.smu
        self.app.transports["source"] = transport
        self.app.instrument_keys["source"] = "demo::shutdown-safety"
        self.root.update()

        self.exp.sample_name_var.set("film_A")
        self.exp.sweep_mode_var.set("list")
        self.exp.on_sweep_mode_changed()
        self.exp.dataset_var.set("matrix")
        self.exp.delay_var.set("0")
        self.exp.reversals_var.set(str(reversals))
        self.exp.width_var.set("10")
        self.exp.length_var.set("27")
        self.exp.thickness_var.set("180")
        for index, var in enumerate(self.exp.current_vars):
            var.set(f"{(index + 1) * 1e-4:g}" if index < points else "")
        if hasattr(self.smu, "expect_readings"):
            self.smu.expect_readings(points, reversals)
        self.root.update()

    def press_run(self):
        self.exp.run_pressed()
        self.pump(0.05)

    def pump(self, seconds=0.2):
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.root.update()
            time.sleep(0.005)

    def wait_idle(self, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.exp.run_controller.is_idle:
                return True
            time.sleep(0.01)
        return False

    def alive(self):
        """True while the window still exists."""
        try:
            return bool(self.root.winfo_exists())
        except tk.TclError:
            return False

    def phase(self, phase):
        """The detail recorded for `phase`, or None if it never happened."""
        for recorded, detail in self.app.close_log:
            if recorded is phase:
                return detail
        return None

    def teardown(self):
        try:
            if self.alive():
                self.root.destroy()
        except Exception:
            pass


@pytest.fixture
def bench():
    made = []

    def build(**kwargs):
        made.append(Bench(**kwargs))
        return made[-1]

    yield build
    for item in made:
        item.teardown()


# ------------------------------------------------------------------
# A. the temperature stage
# ------------------------------------------------------------------
def test_a_pid_write_that_fails_warns_and_does_not_close_quietly(
        bench, dialogs, monkeypatch, check):
    """The wire fails while OFF is being sent.

    The shipped code wrapped this in `except Exception: pass`, so the
    heater stayed enabled and the window vanished with nothing on
    screen. The fault is injected at the port, not at the controller,
    so the controller's own decision is part of what is under test.
    """
    port = Port("TEMP:80.0,SP:100.0,STATE:HEATING",
                write_error=OSError("ClearCommError failed"))
    b = bench()
    b.app.temp_ctrl = real_stage_on(port, monkeypatch)
    monkeypatch.setattr(tc, "PID_OFF_CONFIRM_S", 0.2)

    b.app.on_close()

    warnings = dialogs.titles("showwarning")
    check("the operator is warned about the stage",
          any("stage" in t.lower() for t in warnings), str(dialogs.calls))
    check("the warning says to switch it off by hand",
          "controller itself" in dialogs.text, dialogs.text[:400])
    check("and the reason reaches the message",
          "could not be sent" in dialogs.text, dialogs.text[:400])
    check("the window still closed - shutdown is bounded", not b.alive())


def test_a_stage_that_stops_answering_is_not_reported_as_off(
        bench, dialogs, monkeypatch, check):
    """The serial link dies during shutdown.

    Distinct from the case above: the OFF write *succeeds*, and the
    board then says nothing. There is no evidence either way, so the
    only honest answer is uncertain - and a port that then refuses to
    close must not turn into a second, competing warning.
    """
    port = Port("TEMP:80.0,SP:100.0,STATE:HEATING",
                close_error=OSError("the device is not connected"))
    b = bench()
    stage = real_stage_on(port, monkeypatch)
    b.app.temp_ctrl = stage
    monkeypatch.setattr(tc, "PID_OFF_CONFIRM_S", 0.3)
    # Wait for the board to be heard from at all, then pull the cable.
    deadline = time.time() + 2.0
    while time.time() < deadline and stage.status().age_s is None:
        time.sleep(0.01)
    port.line = None

    b.app.on_close()

    check("OFF did reach the wire", "OFF\n" in port.written, str(port.written))
    check("but the stage is not reported off",
          any("stage" in t.lower() for t in dialogs.titles("showwarning")),
          str(dialogs.calls))
    check("and the message says the board went quiet",
          "stopped answering" in dialogs.text, dialogs.text[:400])
    check("one warning, not two", len(dialogs.titles("showwarning")) == 1,
          str(dialogs.titles("showwarning")))
    check("the window closed", not b.alive())


def test_a_confirmed_stage_shutdown_raises_no_dialog(bench, dialogs, check):
    """The control. Without it every assertion above would pass against
    an application that warned on every close, which is a warning nobody
    reads by the third day."""
    stage = Stage()
    b = bench(stage=stage)
    b.app.on_close()
    check("the stage was asked", stage.calls == 1, str(stage.calls))
    check("the port was closed", stage.closed == 1, str(stage.closed))
    check("no dialog was raised", dialogs.calls == [], str(dialogs.calls))
    check("the window closed", not b.alive())


def test_a_stage_that_cannot_report_is_uncertain_not_assumed_safe(
        bench, dialogs, check):
    """A stage object that raises out of its own shutdown call.

    `confirm_pid_off()` is the guarded call, so anything escaping it is
    unplanned - and unplanned is not evidence that a heater is off.
    """
    stage = Stage(raises=RuntimeError("the controller object is broken"))
    b = bench(stage=stage)
    b.app.on_close()
    check("the operator is warned",
          any("stage" in t.lower() for t in dialogs.titles("showwarning")),
          str(dialogs.calls))
    check("the window closed", not b.alive())


# ------------------------------------------------------------------
# B. the unsaved-data guard
# ------------------------------------------------------------------
def test_an_unreadable_results_table_refuses_to_close(bench, dialogs, check):
    """Unknown is not zero.

    The shipped guard caught every exception per experiment and moved
    on, so an error became "no unsaved runs" and the window closed over
    the top of work that was only in memory.
    """
    b = bench()
    b.exp.run_store = UnreadableStore()

    state = b.app.unsaved_state()
    check("the state reports itself unknown", not state.is_known,
          str(state))

    b.app.on_close()

    check("the window is still open", b.alive())
    check("nothing was disconnected",
          "source" in b.app.instruments, str(list(b.app.instruments)))
    check("the refusal is recorded",
          b.phase(ClosePhase.REFUSED_TO_CLOSE) is not None,
          str(b.app.close_log))
    check("the operator is told",
          dialogs.titles("showerror") != [], str(dialogs.calls))
    check("and the diagnostic names the cause",
          "unknown state" in dialogs.text, dialogs.text[:400])
    check("the close gate was released again, so a retry can work",
          b.app.is_closing is False)


def test_a_dialog_that_raises_refuses_to_close(bench, dialogs, check):
    """The seam itself fails while asking about unsaved runs.

    Every other caller of a dialog in this application can afford to
    lose one. This one cannot: the question it was asking is "may I
    throw this away", and an unanswered question is not a yes.
    """
    b = bench()
    b.exp.run_store.add("row1", _a_run())
    dialogs.raise_on = "askyesno"

    b.app.on_close()

    check("the window is still open", b.alive())
    check("the refusal is recorded",
          b.phase(ClosePhase.REFUSED_TO_CLOSE) is not None,
          str(b.app.close_log))
    check("the run is still in the store", len(b.exp.run_store) == 1)


def test_an_operator_who_says_no_keeps_the_window(bench, dialogs, check):
    b = bench()
    b.exp.run_store.add("row1", _a_run())
    dialogs.answer = False

    b.app.on_close()

    check("the window is still open", b.alive())
    check("the prompt named the count",
          any("1 run" in m for _, _, m in dialogs.calls), str(dialogs.calls))


def test_an_operator_who_says_yes_closes(bench, dialogs, check):
    """The control for the two refusals above."""
    b = bench()
    b.exp.run_store.add("row1", _a_run())
    dialogs.answer = True

    b.app.on_close()

    check("the window closed", not b.alive())
    check("the operator was asked",
          dialogs.titles("askyesno") == ["Unsaved measurements"],
          str(dialogs.calls))


def test_a_silent_dialog_answer_is_not_taken_as_permission(
        bench, dialogs, check):
    """`askyesno` returning nothing must not read as "yes, discard".

    A dialog seam that has been neutralised - by a test, or by a
    platform that could not raise the window - returns None. That is the
    absence of an answer, and this path may only act on a real one.
    """
    b = bench()
    b.exp.run_store.add("row1", _a_run())
    dialogs.answer = None

    b.app.on_close()

    check("the window is still open", b.alive())


# ------------------------------------------------------------------
# C. workers and the bounded wait
# ------------------------------------------------------------------
def test_closing_during_a_4pp_run_cancels_it_and_waits(bench, check):
    """4PP is the tab that had no `on_close()` at all.

    It inherited an empty hook, so closing the window left its worker
    measuring into an application that was disconnecting underneath it.
    Two claims here, and the second is the one `wait_for_idle()` was
    added for: the run is cancelled, and `on_close()` does not return
    until its cleanup has finished.
    """
    b = bench(smu_cls=StageBlockingSMU)
    b.smu.arm("first_measure")
    b.press_run()
    b.smu.wait_until_blocked()

    # Let the parked worker go partway through the close path.
    #
    # The delay is a margin, not a guess at how long anything takes.
    # Everything `on_close()` does apart from waiting - one unconnected
    # stage, one null transport, `destroy()` - is milliseconds, so a
    # close that returns before this fires is a close that did not wait,
    # and the assertion below sees the worker still parked. Without the
    # margin the mutation "delete the wait" passes: the teardown work
    # alone can outlast a short release.
    release_after_s = 0.75
    threading.Timer(release_after_s, b.smu.let_go).start()
    started = time.monotonic()
    b.app.on_close()
    elapsed = time.monotonic() - started

    check("on_close waited for the worker rather than racing it",
          elapsed >= release_after_s, f"returned in {elapsed:.2f}s")
    check("the controller is idle by the time on_close returns",
          b.exp.run_controller.is_idle, str(b.exp.run_controller.state))
    check("nothing was left straggling",
          b.phase(ClosePhase.WAITED_FOR_IDLE) == "",
          repr(b.phase(ClosePhase.WAITED_FOR_IDLE)))
    check("the run was cancelled, and says so",
          "4" in (b.phase(ClosePhase.CANCELLED_RUNS) or "")
          or (b.phase(ClosePhase.CANCELLED_RUNS) or "") != "",
          repr(b.phase(ClosePhase.CANCELLED_RUNS)))
    check("the output was put away", b.smu._output_on is False)
    check("instrument ownership was released",
          not b.app.ownership.is_owned("demo::shutdown-safety"),
          str(b.app.ownership.snapshot()))
    check("nothing was committed", len(b.exp.run_store) == 0)
    check("the window closed", not b.alive())


def test_a_worker_past_the_budget_is_named_rather_than_waited_on(
        bench, dialogs, monkeypatch, check):
    """Cleanup timeout expiry.

    Bounded is the requirement: a window that cannot be closed is
    answered by killing the process, which skips every de-energise this
    path performs. So the expiry is a warning that names the tab, not a
    hang - and not a silence either.
    """
    monkeypatch.setattr(base_app, "CLEANUP_TIMEOUT_S", 0.3)
    b = bench(smu_cls=StageBlockingSMU)
    b.smu.arm("first_measure")
    b.press_run()
    b.smu.wait_until_blocked()

    started = time.monotonic()
    b.app.on_close()
    elapsed = time.monotonic() - started

    check("the wait was bounded", elapsed < 5.0, f"{elapsed:.2f}s")
    check("the straggler is named",
          (b.phase(ClosePhase.WAITED_FOR_IDLE) or "") != "",
          repr(b.phase(ClosePhase.WAITED_FOR_IDLE)))
    check("the operator is warned",
          any("did not stop" in t.lower()
              for t in dialogs.titles("showwarning")), str(dialogs.calls))
    check("and told to check the instrument",
          "front panel" in dialogs.text, dialogs.text[:400])
    check("the window closed anyway", not b.alive())

    b.smu.let_go()
    check("the abandoned worker still finishes on its own", b.wait_idle())


def test_the_close_path_refuses_a_new_run(bench, check):
    """Step one of the state machine, at the one gate every run passes.

    A run started after the cancellation sweep would be a worker nobody
    is waiting for, energising an instrument whose transport is about to
    be closed.
    """
    b = bench()
    started = []
    guarded = b.app.guard_run(lambda: started.append("ran"))

    guarded()
    check("a run is allowed before the close begins", started == ["ran"])

    b.app._closing = True
    guarded()
    check("and refused once it has", started == ["ran"], str(started))


def test_the_close_log_records_the_steps_in_order(bench, check):
    """The state machine is observable, which is what makes it one.

    Order is the safety argument: cancel before waiting, wait before
    de-energising, de-energise before disconnecting.
    """
    b = bench(stage=Stage())
    b.app.on_close()

    order = [phase for phase, _ in b.app.close_log]
    expected = [ClosePhase.REFUSED_NEW_RUNS, ClosePhase.CANCELLED_RUNS,
                ClosePhase.WAITED_FOR_IDLE, ClosePhase.DE_ENERGISED,
                ClosePhase.DISCONNECTED, ClosePhase.DESTROYED]
    check("every step is recorded, in order", order == expected, str(order))


def test_closing_twice_does_not_run_the_path_twice(bench, check):
    """A second WM_DELETE_WINDOW while the first is still walking."""
    stage = Stage()
    b = bench(stage=stage)
    b.app.on_close()
    b.app.on_close()
    check("the stage was put away once", stage.calls == 1, str(stage.calls))


# ------------------------------------------------------------------
# D. the contract every experiment now inherits
# ------------------------------------------------------------------
def test_every_experiment_cancels_its_run_on_close(check):
    """Four of the five overrode `on_close()` to cancel; 4PP did not.

    An opt-in safety step is one the next experiment forgets in exactly
    the same way, so the cancelling behaviour is the inherited default.
    Instantiated without a window on purpose - the claim is about the
    method, and building five Tk applications to check one line would
    make this the slowest test in the file.
    """
    for cls in ALL_EXPERIMENTS:
        exp = cls.__new__(cls)
        exp.run_controller = RecordingController()
        exp.on_close()
        check(f"{cls.__name__} cancels on close",
              exp.run_controller.reasons != [],
              f"{cls.__name__}.on_close() cancelled nothing")


def test_the_base_hook_is_not_empty(check):
    """The regression guard for the hook itself.

    `Experiment.on_close` used to be a docstring and nothing else. If it
    ever goes back to that, every experiment silently stops cancelling
    and the four assertions above go with it.
    """
    exp = Experiment.__new__(Experiment)
    exp.run_controller = RecordingController()
    exp.on_close()
    check("the base class cancels", exp.run_controller.reasons != [])


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def _a_run():
    from core.run_store import Run
    return Run("film_A", {"meas_number": 1}, [{"current_A": 1e-4}])
