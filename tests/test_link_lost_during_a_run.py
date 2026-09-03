
"""What a real run does when the instrument stops answering mid-sweep.

Wave 8b. Wave 8a made the transport refuse to read once an exchange has
failed, and made `confirm_output_off()` stop reporting CONFIRMED on a
link it cannot ask. This file asserts the consequences that reach the
person standing at the bench, through the actual experiment rather than
through the units underneath it:

  * the sample is de-energised
  * the run fails and keeps nothing
  * runs already in the table survive, with their unsaved data
  * the instrument is blocked until it is reconnected
  * the app is still usable - no exit, no wedged state machine

The last two are the ones worth having a test for. Everything else is
what any failed run does; those two are the reason this ending is not
just "the run is spoiled".
"""
import time
import tkinter as tk

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.gui]

import core.base_app as base_app
import experiments.base_experiment as base_experiment
import experiments.iv_sweep.experiment as iv
from core.base_app import LabApp
from core.run_control import Outcome, RunState
from core.transports.base import TransportDesynchronised
from core.transports.null_transport import NullTransport
from experiments.iv_sweep.experiment import IVSweepExperiment


class Link(NullTransport):
    """A transport that answers until armed, then never answers again.

    Modelled on the GSM-20H10's 2026-08-25 failure: a read that times
    out partway through a run, on a link that was working a moment
    earlier. Answers are delegated until then, because a transport that
    failed from the first read would fail the run at connect time and
    prove nothing about a run in flight.
    """

    def __init__(self):
        super().__init__()
        self.armed = False
        self.writes_after_going_quiet = []

    def _write(self, text):
        if self.armed:
            # Writes still land. That asymmetry is what the de-energise
            # depends on, so it is recorded rather than assumed.
            self.writes_after_going_quiet.append(text)
        return super()._write(text)

    def _read(self, timeout_s):
        if self.armed:
            raise TimeoutError("VI_ERROR_TMO (-1073807339)")
        return super()._read(timeout_s)


class OnALink:
    """DummySMU with its readings actually fetched over a transport.

    Demo mode fabricates readings without touching a transport at all,
    so a fault injected into one would never be seen - the first version
    of this test armed a dead link and watched the run complete happily.
    This proxies the real driver and routes the two operations that
    matter over `link`: the reading, which is a query, and the
    output-off, which is a write.

    That split is the whole point. On the bench every driver's
    output_off() is a write and every measurement is a query, so a lost
    link takes the readings away while leaving the de-energise working.
    """

    def __init__(self, inner, link):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_link", link)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __setattr__(self, name, value):
        setattr(self._inner, name, value)

    def measure(self, *args, **kwargs):
        self._link.query(":READ?")
        return self._inner.measure(*args, **kwargs)

    def sweep_points_ready(self, *args, **kwargs):
        # What the IV sweep loop actually polls. On a real instrument
        # this is a query, which is why a lost link is noticed here
        # rather than at the end of the sweep.
        self._link.query(":TRAC:ACT?")
        return self._inner.sweep_points_ready(*args, **kwargs)

    def read_sweep(self, *args, **kwargs):
        self._link.query(":TRAC:DATA?")
        return self._inner.read_sweep(*args, **kwargs)

    def read_error(self, *args, **kwargs):
        # A query on every driver in the fleet, and the one
        # confirm_output_off() uses to decide whether the shutdown can
        # be called confirmed. Routing it over the link is what makes
        # this test exercise that decision rather than assume it.
        self._link.query("SYST:ERR?")
        return self._inner.read_error(*args, **kwargs)

    def output_off(self, *args, **kwargs):
        self._link.write("OUTP OFF")
        return self._inner.output_off(*args, **kwargs)

    def safe_output_off(self, *args, **kwargs):
        try:
            self.output_off()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _fast_settle(monkeypatch):
    monkeypatch.setattr(iv, "PRE_SWEEP_SETTLE_S", 0.0)


class Dialogs:
    """Records dialogs instead of showing them.

    Every call returns rather than blocking, which is the point: a real
    `messagebox` call opens a window and runs its own event loop until
    somebody clicks it, and no one is going to.
    """

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(title="", message="", **kwargs):
            self.calls.append((name, title, message))
            return None
        return record

    @property
    def text(self):
        return " ".join(f"{t} {m}" for _, t, m in self.calls).lower()


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    """Stub the dialog seam for every test in this file.

    Autouse because the failure mode is not a wrong assertion, it is an
    indefinite block: the link-lost ending queues a modal warning about
    a sample that may still be energised, and any test here that arms
    the link reaches it. A file where only some tests neutralise dialogs
    is a file that hangs on the others.

    Installed in a fixture rather than at import time, unlike most of
    the GUI files. Import-time installation is what makes those files
    steal each other's recorder when more than one is imported into a
    process - see `_dialog_recorder_belongs_to_this_file` in
    `tests/conftest.py`. A fixture installs after every import, so the
    question cannot arise.
    """
    stub = Dialogs()
    for seam in (base_app, base_experiment, iv):
        monkeypatch.setattr(seam, "messagebox", stub)
    return stub


def build(root):
    link = Link()
    app = LabApp(root, IVSweepExperiment)
    app.connect_role("source", NullTransport(), "demo")
    root.update_idletasks()
    exp = app.experiment
    exp.start_var.set("0")
    exp.stop_var.set("1")
    exp.points_var.set("5")
    exp.delay_var.set("0")
    exp.runs_var.set("1")
    exp.mode_var.set("voltage")
    exp.on_mode_changed()
    exp.compliance_var.set("0.01")
    exp.standby_var.set("Remain idle")
    exp.on_standby_changed()
    link.connect("demo")
    app.instruments["source"] = OnALink(app.instruments["source"], link)
    return app, exp, link


def pump_until(root, condition, what, timeout_s=30.0):
    """Drive the event loop until `condition` holds, or fail saying so.

    The loop before this one ran a fixed number of `root.update()` calls
    and carried on regardless of what had happened. That is a wait on a
    count, not on a fact, and it made the file's behaviour depend on how
    fast the machine is: `app.ui()` queues work that the main thread
    drains from a 10 ms `after()` timer, so whether a queued item ran at
    all came down to whether those updates happened to span 10 ms of
    wall clock.

    Replacing it with 2000 iterations and a message did not fix that,
    and review A-09 found out how: **a count of `update()` calls is not
    a bound on anything.** `root.update()` returns as soon as nothing is
    pending, so 2000 of them against an idle main thread are over in a
    couple of milliseconds - while the thing being waited for is a sweep
    running on another thread, which cannot possibly have finished. The
    faster the machine, the sooner the wait gave up. It failed
    deterministically here on a quiet Windows machine, and the message
    it produced named a hang that had not happened.

    So the bound is wall clock now. The loop still waits on the **fact**
    and the timeout only decides when a stall gets called a stall - the
    same shape as `run_tests.py`'s group budget and
    `CLEANUP_TIMEOUT_S`, and generous enough that reaching it is a
    finding.

    `tests/README.md` bans a sleep whose job is to *hope* the worker has
    arrived. This sleep has a different job: it yields the interpreter
    so the worker can be scheduled at all, and so the app's 10 ms
    `after()` pump can come due. A tight `update()` loop starves both.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        if condition():
            return
        root.update()
        if time.monotonic() >= deadline:
            break
        time.sleep(0.002)
    pytest.fail(f"waited for {what} and it never happened "
                f"(gave up after {timeout_s:g} s)")


def run_to_completion(root, app, exp):
    before = len(exp.run_controller.history)
    exp.run_pressed()
    pump_until(root,
               lambda: (exp.run_controller.state is RunState.IDLE
                        and len(exp.run_controller.history) > before),
               "the run to finish and record an outcome")
    # Explicitly, rather than by hoping the pump timer fires: anything
    # the run queued for the operator has to have happened before a test
    # can assert about it, or about its absence.
    app.drain_ui_now()


def test_a_link_that_stops_answering_ends_the_run_safely(check, dialogs):
    root = tk.Tk()
    root.withdraw()
    try:
        app, exp, link = build(root)

        # --- a good run first, so there is something to preserve ------
        run_to_completion(root, app, exp)
        check("the first run completed",
              exp.run_controller.history[-1].outcome is Outcome.COMPLETED,
              exp.run_controller.history[-1].outcome)
        kept = len(app.experiment.run_store)
        check("and it is in the store", kept >= 1, kept)
        unsaved_before = app.experiment.run_store.has_unsaved

        # --- now the link goes -----------------------------------
        link.armed = True
        run_to_completion(root, app, exp)

        status = exp.run_controller.history[-1]

        check("the run did not complete",
              status.outcome is not Outcome.COMPLETED, status.outcome)
        check("the operator is told to go and look at the instrument",
              status.needs_attention,
              f"{status.outcome} - a lost link must not read as an "
              f"ordinary 'try again' failure")
        check("the shutdown is not claimed as confirmed",
              status.shutdown.uncertain, status.shutdown.status)
        check("and the reason names the link, not just the output",
              "link" in status.shutdown.detail.lower()
              or "answer" in status.shutdown.detail.lower(),
              status.shutdown.detail)

        # --- the sample --------------------------------------------
        check("an output-off was still written to the instrument",
              any("OUTP" in w.upper() or "output" in w.lower()
                  for w in link.writes_after_going_quiet),
              link.writes_after_going_quiet)
        check("and the operator is told the sample may still be live",
              "front panel" in dialogs.text, dialogs.calls)

        # --- what survives -----------------------------------------
        check("the failed run kept nothing",
              len(app.experiment.run_store) == kept,
              f"{len(app.experiment.run_store)} runs, expected {kept}")
        check("the earlier run is still in the store",
              len(app.experiment.run_store) >= 1)
        check("and its unsaved data is still unsaved, not silently dropped",
              app.experiment.run_store.has_unsaved == unsaved_before,
              f"{app.experiment.run_store.has_unsaved} was {unsaved_before}")

        # --- the app ------------------------------------------------
        check("the app is still alive", bool(root.winfo_exists()))
        check("and the state machine is back at IDLE",
              exp.run_controller.state is RunState.IDLE, exp.run_controller.state)

        # --- and it will not silently try again ---------------------
        key = app.instrument_keys.get("source")
        check("the instrument is blocked until it is reconnected",
              key is not None and app.ownership.is_blocked(key),
              f"key={key!r} blocked="
              f"{app.ownership.is_blocked(key) if key else 'no key'}")
        if key and app.ownership.is_blocked(key):
            check("and the block says why",
                  bool(app.ownership.block_reason(key)),
                  app.ownership.block_reason(key))
    finally:
        root.destroy()


def test_a_healthy_run_is_not_blocked(check):
    """The other half of the claim.

    A block that fired on ordinary runs would be worse than no block:
    the response to an alarm that always sounds is to stop hearing it.
    """
    root = tk.Tk()
    root.withdraw()
    try:
        app, exp, link = build(root)
        run_to_completion(root, app, exp)
        key = app.instrument_keys.get("source")
        check("a completed run leaves the instrument usable",
              key is None or not app.ownership.is_blocked(key))
        check("and can be run again",
              exp.run_controller.state is RunState.IDLE, exp.run_controller.state)
        run_to_completion(root, app, exp)
        check("twice", exp.run_controller.history[-1].outcome is Outcome.COMPLETED,
              exp.run_controller.history[-1].outcome)
    finally:
        root.destroy()


# ---------------------------------------------------------------
# the operator message
# ---------------------------------------------------------------
def test_the_shutdown_report_says_which_kind_of_uncertain_it_is(check):
    """A flag, not a phrase matched out of `detail`.

    The operator message branches on this. Deriving it from the wording
    of another message would break the first time either was reworded,
    and the symptom would be the wrong dialog rather than an error.
    """
    from core.run_control import confirm_output_off

    class LinkGone:
        def output_off(self):
            pass

        def read_error(self):
            raise TransportDesynchronised("stopped answering")

    class FaultReported:
        def output_off(self):
            pass

        def read_error(self):
            if not getattr(self, "_done", False):
                self._done = True
                return (-221, "Settings conflict")
            return (0, "")

    lost = confirm_output_off(LinkGone())
    check("a lost link is flagged", lost.link_lost, lost)

    fault = confirm_output_off(FaultReported())
    check("an instrument-reported fault is uncertain too",
          fault.uncertain, fault.status)
    check("but is NOT a lost link", not fault.link_lost,
          "otherwise both endings get the reconnect message and the "
          "distinction stops meaning anything")


def test_the_operator_is_told_to_reconnect_and_restart(check):
    """What the person at the bench actually reads.

    Asserted on the text because the text is the deliverable here - the
    handling was already correct before this wave, and only the wording
    was generic.
    """
    root = tk.Tk()
    root.withdraw()
    try:
        app, exp, link = build(root)
        shown = []
        app.ui = lambda fn, *a, **kw: shown.append(a)

        link.armed = True
        run_to_completion(root, app, exp)

        check("a warning was raised", bool(shown), shown)
        text = " ".join(str(part) for row in shown for part in row).lower()
        check("it says the link stopped answering",
              "stopped answering" in text, text[:200])
        check("it says to check the front panel",
              "front panel" in text, text[:200])
        check("it says this run was discarded",
              "discarded" in text, text[:200])
        check("it says other runs are untouched",
              "untouched" in text or "already in the table" in text,
              text[:200])
        check("and it says to reconnect and start again",
              "reconnect" in text and "again" in text, text[:200])

        key = app.instrument_keys.get("source")
        check("the block reason mentions reconnecting",
              key and "reconnect" in app.ownership.block_reason(key).lower(),
              app.ownership.block_reason(key) if key else None)
    finally:
        root.destroy()
