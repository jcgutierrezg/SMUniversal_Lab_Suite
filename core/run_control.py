"""
The run lifecycle: states, tokens, provisional data, and the commit gate.

Why this exists
---------------
Run state used to be a handful of booleans per experiment - `measuring`,
`polling`, `stop_requested`, an output lamp - and no two experiments
combined them the same way. Scattered flags have a failure mode that is
hard to see in a code review and easy to hit on a bench: the UI says
idle while a worker is still alive, OFF turns the output off while the
worker turns it straight back on, or a run is cancelled and a row is
committed anyway.

This module replaces those flags with one object per run whose legal
moves are enumerated. Nothing here knows about Tkinter, instruments or
any particular measurement, so it can be tested without either a window
or a bench.

The analogy that fits
---------------------
A run is a **bank transaction**, not a running total.

Readings accumulate in a private ledger (`RunContext.readings`) that
nothing outside the run can see. At the end, one atomic commit moves the
whole thing into the permanent store, or nothing moves at all. There is
no partial credit: a run cancelled at 99 of 100 points commits nothing,
exactly like a transfer interrupted halfway leaves both accounts as they
were.

That is the project's stated rule - *all cancelled runs are discarded
regardless of experiment or progress* - expressed as a mechanism rather
than as a habit each experiment has to remember.

The states
----------
::

    IDLE -> PREPARING -> RUNNING -> COMPLETED -> IDLE
                |            |
                |            +----> FAILED     -> IDLE
                +---> CANCELLING ---> CANCELLED -> IDLE

`RUNNING -> IDLE` is deliberately **not** legal. Every path back to idle
goes through a terminal state, which is what guarantees cleanup runs and
that a status is recorded for the log.

Three endings, not one
----------------------
Cancellation, failure, and an unverifiable shutdown mean different
things and are reported differently (see `Outcome`):

* the operator pressing OFF is a normal action, not an application
  error, and should read like one;
* a failure names the stage it failed in and confirms the output is off;
* a shutdown that could not be *verified* is the serious one - the
  instrument may still be energised, so the run fails, the operator gets
  a prominent warning, and the connection is left blocked until someone
  reconnects it.

Using it
--------
::

    with controller.begin(parameters=snapshot) as run:
        session = run.enter(ownership.claim(key, run.run_id))
        run.start()

        for point in points:
            run.checkpoint("sourcing")      # cancellation + generation
            smu.set_current_level(point)
            run.sleep(settle_s)             # wakes early on cancel
            run.add_reading({...})

        run.confirm_shutdown(smu)
        run.commit(result, self._record_run)

Everything after the `with` block is handled by `__exit__`: the terminal
transition, discarding provisional data, running cleanup (which releases
instrument ownership), and only then returning to IDLE.
"""
from __future__ import annotations

import datetime
import itertools
import threading
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from core import identity
from core.transports.base import TransportDesynchronised


# --------------------------------------------------------------------
# states
# --------------------------------------------------------------------
class RunState(str, Enum):
    """Where a run is in its life.

    Subclassing `str` so a state drops into a log line or an f-string
    without ceremony, while still comparing as an enum.
    """

    IDLE = "idle"
    PREPARING = "preparing"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def __str__(self):
        return self.value


#: States from which no further work happens. A run in one of these has
#: recorded its status; the only move left is back to IDLE after cleanup.
TERMINAL_STATES = frozenset({RunState.COMPLETED, RunState.FAILED,
                             RunState.CANCELLED})

#: The whole state machine, in one readable place.
#:
#: Two absences are deliberate and load-bearing:
#:   * `RUNNING -> IDLE` - would let a run end without cleanup or a
#:     recorded status;
#:   * `CANCELLING -> COMPLETED` - would let a cancelled run commit.
LEGAL_TRANSITIONS = {
    RunState.IDLE: frozenset({RunState.PREPARING}),
    RunState.PREPARING: frozenset({RunState.RUNNING, RunState.FAILED,
                                   RunState.CANCELLING}),
    RunState.RUNNING: frozenset({RunState.COMPLETED, RunState.FAILED,
                                 RunState.CANCELLING}),
    RunState.CANCELLING: frozenset({RunState.CANCELLED, RunState.FAILED}),
    RunState.COMPLETED: frozenset({RunState.IDLE}),
    RunState.FAILED: frozenset({RunState.IDLE}),
    RunState.CANCELLED: frozenset({RunState.IDLE}),
}


class Outcome(str, Enum):
    """How a run ended, for the operator and for the log.

    `UNCERTAIN_SHUTDOWN` is a failure with a specific and worse meaning:
    the output could not be confirmed off. It is separated from ordinary
    failure because the operator response differs - one is "try again",
    the other is "go and look at the instrument".
    """

    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNCERTAIN_SHUTDOWN = "uncertain-shutdown"

    def __str__(self):
        return self.value


class ShutdownStatus(str, Enum):
    """Whether the output was confirmed off at the end of a run."""

    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"
    NOT_ATTEMPTED = "not-attempted"

    def __str__(self):
        return self.value


# --------------------------------------------------------------------
# exceptions
# --------------------------------------------------------------------
class RunControlError(RuntimeError):
    """Base for every fault this module raises."""


class InvalidTransition(RunControlError):
    """An illegal state change was attempted.

    This is a programming error rather than an operating one - it means
    some code path tried to skip cleanup or commit from a cancelled run.
    It is raised rather than logged so it fails a test instead of
    producing a bad CSV.
    """

    def __init__(self, current, target):
        super().__init__(f"cannot move from {current} to {target}; "
                         f"legal from {current}: "
                         f"{sorted(s.value for s in LEGAL_TRANSITIONS[current])}")
        self.current = current
        self.target = target


class RunRejected(RunControlError):
    """A run could not be started, or a result could not be committed.

    Carries a message meant for a dialog box, because the common case -
    pressing Run while the previous run is still cleaning up - is
    something the operator needs to read, not a traceback.
    """


class IncompleteRun(RunRejected):
    """The completion gate refused to let a run commit.

    `reasons` lists every unmet condition rather than only the first,
    so one message tells the whole story.
    """

    def __init__(self, run_id, reasons):
        super().__init__(f"run {run_id} is not complete: " + "; ".join(reasons))
        self.run_id = run_id
        self.reasons = tuple(reasons)


class RunCancelled(Exception):
    """Raised inside a worker when the operator has cancelled.

    Deliberately **not** a subclass of `RunControlError`, and not an
    error in any sense the user should see: pressing OFF is a normal
    action. `RunContext.__exit__` catches it, records a cancellation,
    and suppresses it - so a worker never has to catch it itself, and a
    cancelled run never produces a traceback in the console.
    """

    def __init__(self, run_id, stage=None):
        stage_text = f" during {stage}" if stage else ""
        super().__init__(f"run {run_id} cancelled{stage_text}")
        self.run_id = run_id
        self.stage = stage


# --------------------------------------------------------------------
# cancellation
# --------------------------------------------------------------------
class RunToken:
    """One run's private cancellation flag and identity.

    Private is the point. A single application-wide `stop_requested`
    boolean is shared by consecutive runs, so a worker that outlives its
    run sees the flag cleared for the *next* run and reads that as
    permission to carry on. A token is created per run and never reused,
    so an obsolete worker holds an obsolete token and can be told apart
    from a current one - see `RunController.is_current()`.

    The token is safe to touch from any thread; `threading.Event` does
    the work.
    """

    __slots__ = ("run_id", "cancel_event", "_reason")

    def __init__(self, run_id):
        self.run_id = run_id
        self.cancel_event = threading.Event()
        self._reason = None

    # ---- state ----
    @property
    def is_cancelled(self):
        return self.cancel_event.is_set()

    @property
    def reason(self):
        """Why it was cancelled, for the log. None while running."""
        return self._reason

    def cancel(self, reason="operator"):
        """Request cancellation. Idempotent; the first reason wins."""
        if not self.cancel_event.is_set():
            self._reason = reason
        self.cancel_event.set()

    # ---- what workers call ----
    def raise_if_cancelled(self, stage=None):
        """Abort the worker if cancellation has been requested.

        Call this before anything that energises or alters the output:
        output-on, a source-function change, a new level, a polarity
        flip, the start of a hardware sweep, and immediately before
        commit. Those are the points where a stale worker can undo an
        OFF the operator already pressed.
        """
        if self.cancel_event.is_set():
            raise RunCancelled(self.run_id, stage)

    def sleep(self, seconds, stage=None):
        """Wait, but wake immediately if cancelled.

        `time.sleep(2.0)` makes OFF look broken for up to two seconds,
        and a settle delay of several seconds is normal here. Waiting on
        the cancel event instead costs nothing and makes the button
        feel instant.

        Returns normally if the full time elapsed; raises `RunCancelled`
        if it was cut short.
        """
        if seconds and seconds > 0:
            if self.cancel_event.wait(timeout=seconds):
                raise RunCancelled(self.run_id, stage)
        else:
            self.raise_if_cancelled(stage)


# --------------------------------------------------------------------
# shutdown verification
# --------------------------------------------------------------------
@dataclass(frozen=True)
class ShutdownReport:
    """The result of trying to put an instrument's output away."""

    status: ShutdownStatus = ShutdownStatus.NOT_ATTEMPTED
    detail: str = ""

    #: True when the reason it could not be confirmed is that the link
    #: stopped answering, rather than the instrument reporting a fault.
    #: A flag rather than a phrase matched out of `detail`, because the
    #: operator message branches on it and a message that depended on
    #: the wording of another message would break the first time either
    #: was reworded.
    link_lost: bool = False

    @property
    def confirmed(self):
        return self.status is ShutdownStatus.CONFIRMED

    @property
    def uncertain(self):
        return self.status is ShutdownStatus.UNCERTAIN


def confirm_output_off(driver, log=None):
    """Turn the output off and check the instrument agreed.

    `safe_output_off()` swallows everything, which is right for an exit
    path and wrong here: at the end of a run, whether the output
    actually went off decides whether the data may be kept.

    Two questions, in order:

    1. Did `output_off()` return without raising? A transport error here
       means the command may never have arrived.
    2. Does the error queue agree? A SCPI instrument logs a command it
       did not understand and carries on regardless, so a write that
       returned cleanly is not evidence that anything happened. Asking
       is the only way to tell.

    Being unable to *ask* is not evidence of a fault - that is the
    documented rule for `read_error()`, and it is why an ordinary
    exception from the queue read is recorded but does not by itself
    make the shutdown uncertain. A driver's `read_error()` is contracted
    to report code 0 when it cannot read the queue; one that raises
    something ordinary instead is a driver bug, not an energised output.

    **One exception, and it is deliberate.** A `TransportDesynchronised`
    from either step gives UNCERTAIN with `link_lost` set. The rule
    above holds for a dropped reply, where one question went unheard. It
    does not hold for a link that has stopped answering, where no reply
    can be matched to its question at all - "the instrument says the
    output is off" is then not a statement this function is in a
    position to make. `output_off()` is a write and will usually have
    landed, so the sample is usually de-energised; usually is not
    confirmed, and the operator decides what to do about the difference.
    """
    try:
        driver.output_off()
    except TransportDesynchronised as exc:
        # output_off() is a pure write on every driver in the fleet, so
        # reaching here means the write itself failed - the command may
        # never have left. Uncertain, and said plainly.
        detail = (f"output_off() could not be sent ({exc}). De-energise "
                  f"the instrument at the front panel.")
        if log:
            log("SHUTDOWN UNCERTAIN:", detail)
        return ShutdownReport(ShutdownStatus.UNCERTAIN, detail,
                              link_lost=True)
    except Exception as exc:
        detail = f"output_off() raised: {exc}"
        if log:
            log("SHUTDOWN UNCERTAIN:", detail)
        return ShutdownReport(ShutdownStatus.UNCERTAIN, detail)

    # Drain rather than pop once: several rejected commands leave
    # several entries, and reporting only the first hides the rest.
    faults = []
    try:
        for _ in range(10):
            code, message = driver.read_error()
            if not code:
                break
            faults.append(f"{code}: {message}")
    except TransportDesynchronised as exc:
        # NOT confirmed. The rule below - "being unable to ask is not
        # evidence of a fault" - is right for a dropped reply and wrong
        # here. A dropped reply means one question went unheard. A
        # desynchronised link means no answer can be matched to its
        # question, so "the instrument said the output is off" is not a
        # statement this function is in a position to make.
        #
        # output_off() itself is a write and will have reached the
        # instrument, so this is usually a sample that IS de-energised.
        # Usually is not confirmed, and the operator is the one who gets
        # to decide what to do about the difference.
        detail = (f"output-off was commanded but could NOT be confirmed - "
                  f"the link stopped answering ({exc}). Check the front "
                  f"panel before touching the fixture.")
        if log:
            log("SHUTDOWN UNCERTAIN:", detail)
        return ShutdownReport(ShutdownStatus.UNCERTAIN, detail,
                              link_lost=True)
    except Exception as exc:
        detail = f"output off; error queue unreadable ({exc})"
        if log:
            log("Note:", detail)
        return ShutdownReport(ShutdownStatus.CONFIRMED, detail)

    if faults:
        detail = "instrument reported " + "; ".join(faults)
        if log:
            log("SHUTDOWN UNCERTAIN:", detail)
        return ShutdownReport(ShutdownStatus.UNCERTAIN, detail)

    return ShutdownReport(ShutdownStatus.CONFIRMED, "")


# --------------------------------------------------------------------
# terminal status
# --------------------------------------------------------------------
@dataclass(frozen=True)
class TerminalStatus:
    """How one run ended. Recorded for every run, successful or not."""

    run_id: str
    outcome: Outcome
    stage: str = ""
    detail: str = ""
    shutdown: ShutdownReport = field(default_factory=ShutdownReport)
    readings_discarded: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now().isoformat())

    @property
    def is_success(self):
        return self.outcome is Outcome.COMPLETED

    @property
    def needs_attention(self):
        """True when the operator must do something before running again."""
        return self.outcome is Outcome.UNCERTAIN_SHUTDOWN

    def operator_message(self):
        """One or two lines aimed at a person, not a stack trace.

        The three endings read differently on purpose. Cancellation is a
        normal action and should not look like a crash; an unverifiable
        shutdown should not look like a routine cancellation.
        """
        stage = f" during {self.stage}" if self.stage else ""
        if self.outcome is Outcome.COMPLETED:
            return "Run completed."
        if self.outcome is Outcome.CANCELLED:
            return "Run cancelled. No measurements were retained."
        if self.outcome is Outcome.UNCERTAIN_SHUTDOWN:
            return (f"Run failed{stage} and the output could NOT be confirmed "
                    f"off. The instrument may still be energised - check it "
                    f"before continuing. No measurements were retained."
                    + (f"\n\n{self.detail}" if self.detail else ""))
        confirmed = ("Output shutdown was confirmed."
                     if self.shutdown.confirmed
                     else "Output shutdown was not verified.")
        return (f"Run failed{stage}. No measurements were retained.\n"
                f"{confirmed}" + (f"\n\n{self.detail}" if self.detail else ""))


# --------------------------------------------------------------------
# the completion gate
# --------------------------------------------------------------------
@dataclass(frozen=True)
class CompletionPolicy:
    """What "completed" means, in one place.

    Section 7 of the review asks for a central policy object rather than
    each experiment deciding for itself that a run went well. Every
    condition here has been an actual way to end up with a plausible bad
    row: an empty run, a short run whose missing points nobody counted,
    a run whose errors were logged and then ignored, or one committed
    while the output was still on.

    `require_shutdown_confirmed` is True by default because the project
    decided that an unconfirmable shutdown fails the run. Set it False
    only for a measurement that deliberately holds the output on between
    runs - IV periodic bias is the case that will need it - and say so
    where you set it.
    """

    require_readings: bool = True
    require_shutdown_confirmed: bool = True
    required_metadata: tuple = ()

    def unmet(self, run):
        """Every condition this run fails, as readable phrases."""
        reasons = []

        if run.state is not RunState.RUNNING:
            reasons.append(f"state is {run.state}, not {RunState.RUNNING}")
        if run.token.is_cancelled:
            reasons.append("cancellation was requested")
        if self.require_readings and not run.readings:
            reasons.append("no readings were acquired")
        if run.expected_readings is not None \
                and len(run.readings) != run.expected_readings:
            reasons.append(f"expected {run.expected_readings} readings, "
                           f"got {len(run.readings)}")
        if run.errors:
            reasons.append(f"{len(run.errors)} unresolved error(s): "
                           + "; ".join(run.errors[:3]))
        missing = [k for k in self.required_metadata if not run.metadata.get(k)]
        if missing:
            reasons.append(f"missing metadata: {', '.join(missing)}")
        if self.require_shutdown_confirmed and not run.shutdown.confirmed:
            reasons.append(f"output shutdown is {run.shutdown.status}")
        return reasons


DEFAULT_POLICY = CompletionPolicy()


# --------------------------------------------------------------------
# the run context
# --------------------------------------------------------------------
class RunContext:
    """One run: its identity, its private data, and its ending.

    Created by `RunController.begin()` and used as a context manager.
    Readings added here are **provisional** - they live in this object
    and nowhere else until `commit()` succeeds, which is the whole point
    of the two-phase model. The visible results table is not the buffer;
    a live progress display may show numbers, but it must be labelled as
    live and cleared on cancellation.
    """

    def __init__(self, controller, token, parameters=None, metadata=None):
        self._controller = controller
        self.token = token
        # An earlier version assumed a parameter snapshot was a dict
        # and wrapped it in a MappingProxyType, but the snapshots are
        # frozen dataclasses and `dict(a_dataclass)`
        # raises. Both shapes are now accepted, and neither is copied:
        # a frozen dataclass is already immutable, so wrapping it would
        # add a layer without adding a guarantee. A mapping still gets
        # the read-only proxy, because a plain dict does not.
        #
        # It was the first place this API met a real experiment and was
        # wrong, which is what a pilot experiment is for.
        #
        # `object` rather than a union, and stated rather than inferred:
        # the two shapes have nothing in common structurally, and the
        # honest declaration is that a reader must know which experiment
        # it came from. Without it mypy infers the mapping branch from
        # the first assignment and then calls the dataclass branch an
        # error, which would be the annotation inventing a rule the code
        # deliberately does not have.
        self.parameters: object
        if parameters is None:
            self.parameters = MappingProxyType({})
        elif isinstance(parameters, Mapping):
            self.parameters = MappingProxyType(dict(parameters))
        else:
            self.parameters = parameters
        self.metadata = dict(metadata or {})
        self.readings = []
        self.errors = []
        self.expected_readings = None
        self.stage = ""
        self.shutdown = ShutdownReport()
        self.started_at = datetime.datetime.now().isoformat()

        self._committed = False
        self._result = None
        self._stack = ExitStack()

    # ---- identity ----
    @property
    def run_id(self):
        return self.token.run_id

    @property
    def state(self):
        return self._controller.state

    @property
    def committed(self):
        return self._committed

    def __repr__(self):
        return (f"<RunContext {self.run_id} {self.state} "
                f"{len(self.readings)} provisional reading(s)>")

    # ---- cancellation and generation checks ----
    def checkpoint(self, stage=None):
        """The one call to sprinkle through a measurement sequence.

        Does two things a bare cancellation check does not:

        * records the stage, so a failure says *where* rather than only
          *that*;
        * refuses to let an **obsolete** worker continue. A thread that
          outlived its run and woke up during the next one holds a token
          the controller no longer recognises, and it must not be
          allowed to issue commands into somebody else's run.
        """
        if stage is not None:
            self.stage = stage
        if not self._controller.is_current(self.token):
            raise RunCancelled(self.run_id, stage or "obsolete worker")
        self.token.raise_if_cancelled(stage or self.stage or None)

    def sleep(self, seconds, stage=None):
        """Cancellation-aware wait. See `RunToken.sleep`."""
        self.checkpoint(stage)
        self.token.sleep(seconds, stage or self.stage or None)

    # ---- provisional data ----
    def add_reading(self, reading):
        """Stage one raw reading. Nothing here is visible to the store,
        the calculation panels, or a save until `commit()`."""
        self.readings.append(reading)
        return reading

    def extend_readings(self, readings):
        self.readings.extend(readings)

    def expect(self, count):
        """Declare how many readings a complete run must produce.

        A sweep that returns a third of its points and fits a beautiful
        line is a real failure mode on this bench, and the point count
        is what catches it. Declared up front so the check is against
        the request rather than against whatever arrived.
        """
        self.expected_readings = int(count)

    def record_error(self, message):
        """Note a fault that must block completion.

        Use for anything the run cannot silently absorb. A reading that
        failed and was retried is not an error; a reading that failed and
        was written as a blank is.
        """
        self.errors.append(str(message))

    def set_metadata(self, **values):
        self.metadata.update(values)

    def discard(self):
        """Throw the provisional data away. Returns how many rows went."""
        count = len(self.readings)
        self.readings.clear()
        return count

    # ---- cleanup registration ----
    def enter(self, context_manager):
        """Enter a context manager whose exit belongs to this run.

        Anything registered here is unwound **after** the terminal state
        is recorded and **before** the controller returns to IDLE, which
        is exactly the guarantee the review asks for: the UI goes idle
        only once instrument ownership has been released.
        """
        return self._stack.enter_context(context_manager)

    def on_cleanup(self, fn, *args, **kwargs):
        """Register a plain callback for the same unwind."""
        self._stack.callback(fn, *args, **kwargs)

    # ---- shutdown ----
    def confirm_shutdown(self, driver, log=None):
        """Put the output away and record whether that was verified."""
        self.shutdown = confirm_output_off(driver, log=log)
        return self.shutdown

    def note_shutdown(self, report):
        """Record a shutdown result obtained some other way."""
        self.shutdown = report
        return report

    # ---- the run ----
    def start(self):
        """PREPARING -> RUNNING. Call once setup has succeeded."""
        self.checkpoint("start")
        self._controller._transition(RunState.RUNNING)

    def commit(self, result, sink):
        """The atomic commit gate. Called once, or never.

        `result` is whatever the permanent store holds - a `Run` in this
        project. `sink(result)` is what puts it there.

        Two properties make this a gate rather than a function call:

        * the cancellation check and the handover happen under the
          controller's lock, so OFF pressed one instruction earlier
          cannot slip between them;
        * a second call raises rather than committing twice.

        `sink` must be quick and must not block - post to the UI thread
        (`app.ui(...)`) rather than doing I/O, because the lock is held
        while it runs.
        """
        with self._controller._lock:
            if self._committed:
                raise RunRejected(f"run {self.run_id} has already committed a "
                                  f"result; a run commits once or not at all")
            self.checkpoint("commit")
            reasons = self._controller.policy.unmet(self)
            if reasons:
                raise IncompleteRun(self.run_id, reasons)
            sink(result)
            self._committed = True
            self._result = result
        return result

    # ---- context manager ----
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        """Record how the run ended, clean up, and return to IDLE.

        The ordering here is the contract:

        1. decide the terminal state and record a status;
        2. discard provisional data unless it was committed;
        3. unwind cleanup - releasing instrument ownership;
        4. only then, IDLE.

        `RunCancelled` is suppressed. It is a control-flow signal for a
        normal operator action, and letting it escape would put a
        traceback in the console every time somebody pressed OFF.
        """
        suppress = False
        try:
            if self._committed:
                # Checked first, and before cancellation, because a
                # commit that has already happened cannot be undone -
                # the row is in the store. Reporting the run as
                # discarded here would be a lie about what is on the
                # operator's screen. Anything raised after the commit is
                # recorded on the status instead. Commit last.
                self._finish_completed(
                    f"after commit: {type(exc).__name__}: {exc}" if exc else "")
            elif isinstance(exc, RunCancelled) or self.token.is_cancelled:
                self._finish_cancelled()
                suppress = isinstance(exc, RunCancelled)
            elif exc is not None:
                self._finish_failed(f"{type(exc).__name__}: {exc}")
            else:
                # Reaching the end of the block with nothing committed
                # means the sequence fell through some path that did not
                # produce a result. That is a fault, not a quiet success.
                self._finish_failed("the run ended without committing a result")
        finally:
            self._cleanup()
            self._controller._finish(self)
        return suppress

    # ---- terminal transitions ----
    def _finish_cancelled(self):
        discarded = self.discard()
        if self.state in (RunState.PREPARING, RunState.RUNNING):
            self._controller._transition(RunState.CANCELLING)
        if self.state is RunState.CANCELLING:
            self._controller._transition(RunState.CANCELLED)
        self._controller._record(TerminalStatus(
            run_id=self.run_id, outcome=Outcome.CANCELLED, stage=self.stage,
            detail=self.token.reason or "", shutdown=self.shutdown,
            readings_discarded=discarded), self)

    def _finish_failed(self, detail):
        discarded = self.discard()
        outcome = (Outcome.UNCERTAIN_SHUTDOWN if self.shutdown.uncertain
                   else Outcome.FAILED)
        if self.state in (RunState.PREPARING, RunState.RUNNING,
                          RunState.CANCELLING):
            self._controller._transition(RunState.FAILED)
        self._controller._record(TerminalStatus(
            run_id=self.run_id, outcome=outcome, stage=self.stage,
            detail=detail, shutdown=self.shutdown,
            readings_discarded=discarded), self)

    def _finish_completed(self, detail=""):
        self._controller._transition(RunState.COMPLETED)
        self._controller._record(TerminalStatus(
            run_id=self.run_id, outcome=Outcome.COMPLETED, stage=self.stage,
            detail=detail, shutdown=self.shutdown), self)

    def _cleanup(self):
        """Unwind whatever the run claimed. Never raises.

        A cleanup that throws would leave the controller stuck out of
        IDLE and the application unable to start another run, which is
        worse than a logged failure - so the exception is recorded on
        the status trail and swallowed.
        """
        try:
            self._stack.close()
        except Exception as exc:
            self._controller._note_cleanup_failure(self.run_id, exc)


# --------------------------------------------------------------------
# the controller
# --------------------------------------------------------------------
class RunController:
    """Owns the state of one experiment's runs.

    One per experiment window. It allocates run IDs, validates every
    transition, decides whether a second run may start, holds the
    completion policy, and keeps the status trail.

    The UI should read `state` (or subscribe with `observe`) rather than
    inferring what is happening from button text or from whether a
    thread object exists.
    """

    def __init__(self, name="run", policy=None, log=None, history_limit=50,
                 event_sink=None):
        self.name = name
        self.policy = policy or DEFAULT_POLICY
        self._log = log
        # Called with `(TerminalStatus, RunContext)` once per run, from
        # whichever thread unwound it.
        #
        # A callable rather than a file, on purpose. This module knows
        # about state machines and instruments; giving it a path would
        # make run control depend on the filesystem, and the one-way
        # rule exists so that a layer can be tested without standing up
        # the one below it. `core/event_log.py` supplies the callable
        # and owns everything about where bytes go.
        self._event_sink = event_sink
        self._lock = threading.RLock()
        self._state = RunState.IDLE
        self._run = None
        self._counter = itertools.count(1)
        self._history = []
        self._history_limit = history_limit
        self._observers = []
        self._idle = threading.Event()
        self._idle.set()

    # ---- state ----
    @property
    def state(self):
        with self._lock:
            return self._state

    @property
    def is_idle(self):
        return self.state is RunState.IDLE

    @property
    def is_busy(self):
        """True whenever a run exists, including while it cleans up.

        This - not `state is RUNNING` - is what a Run button should be
        disabled by. Cleanup is part of the run.
        """
        return not self.is_idle

    @property
    def active_run(self):
        with self._lock:
            return self._run

    @property
    def last_status(self):
        with self._lock:
            return self._history[-1] if self._history else None

    @property
    def history(self):
        with self._lock:
            return tuple(self._history)

    # ---- starting ----
    def begin(self, parameters=None, metadata=None):
        """Allocate a run and move IDLE -> PREPARING.

        Raises `RunRejected` if a run is already in flight, with a
        message written for a dialog box. A second run is refused not
        only while measuring but while the previous one is cleaning up,
        because an instrument whose ownership has not been released yet
        is not free.
        """
        with self._lock:
            if self._state is not RunState.IDLE:
                raise RunRejected(
                    f"A {self.name} is already in progress (state: "
                    f"{self._state}). Wait for it to finish, or press OFF "
                    f"to cancel it, before starting another.")
            token = RunToken(self._new_run_id())
            self._run = RunContext(self, token, parameters, metadata)
            self._idle.clear()
            self._transition(RunState.PREPARING)
            return self._run

    def _new_run_id(self):
        # The format is unchanged; it lives in core.identity so
        # that runs, samples, readings and derived results are all
        # minted in one place and cannot drift into four conventions.
        return identity.format_run_id(self.name, next(self._counter))

    # ---- cancelling ----
    def request_cancel(self, reason="operator"):
        """Mark the active run cancelled. Safe to call at any time.

        Returns True if there was something to cancel. Deliberately does
        **not** touch the instrument: the caller decides whether to send
        an output-off, and this returning True is what tells it a worker
        is out there that must be stopped first.

        Idempotent, so a second press of OFF costs nothing.
        """
        with self._lock:
            run = self._run
            if run is None or self._state in TERMINAL_STATES:
                return False
            run.token.cancel(reason)
            if self._state in (RunState.PREPARING, RunState.RUNNING):
                self._transition(RunState.CANCELLING)
            return True

    def is_current(self, token):
        """True if `token` belongs to the run in flight right now.

        The generation check. An obsolete worker holds a token that is
        no longer the active one, and `RunContext.checkpoint()` uses
        this to stop it issuing commands into a later run.
        """
        with self._lock:
            return self._run is not None and self._run.token is token

    def wait_for_idle(self, timeout=None):
        """Block until cleanup has finished. True if it did in time.

        For a caller that must know the instrument is free - closing the
        window, or a test asserting a worker really stopped.
        """
        return self._idle.wait(timeout=timeout)

    # ---- observation ----
    def observe(self, callback):
        """Register `callback(state, run)`, called on every change.

        Callbacks run on whichever thread caused the change, which for a
        measurement is a worker thread - so a Tk observer must bounce
        through `app.ui(...)` rather than touching widgets directly.
        """
        self._observers.append(callback)
        return callback

    # ---- internals used by RunContext ----
    def _transition(self, target):
        with self._lock:
            current = self._state
            if target not in LEGAL_TRANSITIONS[current]:
                raise InvalidTransition(current, target)
            self._state = target
            run = self._run
        for observer in list(self._observers):
            try:
                observer(target, run)
            except Exception as exc:            # an observer must not
                self._say(f"run-state observer failed: {exc}")   # break a run

    def _record(self, status, context=None):
        with self._lock:
            self._history.append(status)
            del self._history[:-self._history_limit]
        self._say(f"[{status.run_id}] {status.outcome}: "
                  f"{status.operator_message().splitlines()[0]}")
        self._emit(status, context)

    def _emit(self, status, context):
        """Hand the terminal status to the operational log, if there is one.

        Wrapped, and the exception swallowed after one complaint,
        because a sink that throws must not turn a completed measurement
        into a failed one. `EventLog.record` already guards itself; this
        is the second belt, for a sink somebody else supplies.
        """
        if self._event_sink is None:
            return
        try:
            self._event_sink(status, context)
        except Exception as exc:
            self._say(f"[{status.run_id}] the run event log raised "
                      f"{type(exc).__name__}: {exc}. The run is unaffected.")

    def _note_cleanup_failure(self, run_id, exc):
        self._say(f"[{run_id}] cleanup failed: {exc}")

    def _finish(self, run):
        """Last step of every run: back to IDLE, after cleanup."""
        with self._lock:
            if run is not self._run:
                return
            if self._state in TERMINAL_STATES:
                self._transition(RunState.IDLE)
            self._run = None
            self._idle.set()

    def _say(self, message):
        if self._log:
            try:
                self._log(message)
            except Exception:
                # Cleanup-only, and the invariant is that nothing here
                # decides anything: `_say` writes a console line, and
                # the run's outcome, its readings and its shutdown
                # report are already recorded elsewhere before this is
                # called. A console sink that raises must not be able to
                # change what a run did - most of these calls are made
                # from cleanup paths, where an exception would replace
                # the real ending with a logging failure.
                pass
