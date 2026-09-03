"""The run lifecycle, tested without a window or an instrument.

Wave 1 issues A1 (shared state machine), A2 (per-run tokens and IDs) and
A5 (provisional buffer, atomic commit), plus the completion gate from
section 7 and the three distinct endings from section 9.

These are the tests that have to be convincing, because everything else
in the suite will eventually depend on this module being right. Where a
check looks paranoid - "cancelled one instruction before commit" - it is
guarding a race that a scattered-boolean design actually loses.

No Tk, no hardware, no threads except where a thread is the thing being
tested. It should stay that way: the point of pulling run control out of
the experiments is that it can be reasoned about on its own.
"""
import threading
import time

import pytest

from core.run_control import (
    DEFAULT_POLICY,
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
    CompletionPolicy,
    IncompleteRun,
    InvalidTransition,
    Outcome,
    RunCancelled,
    RunController,
    RunRejected,
    RunState,
    RunToken,
    ShutdownReport,
    ShutdownStatus,
    confirm_output_off,
)

CONFIRMED = ShutdownReport(ShutdownStatus.CONFIRMED)


def _controller(**kwargs):
    kwargs.setdefault("name", "test")
    return RunController(**kwargs)


def _complete(run, sink, rows=1):
    """Drive a run through the shortest legal path to a commit."""
    run.start()
    for n in range(rows):
        run.add_reading({"point": n})
    run.note_shutdown(CONFIRMED)
    return run.commit(f"result-{run.run_id}", sink)


# ------------------------------------------------------------------
# the state machine itself
# ------------------------------------------------------------------
def test_illegal_transitions_are_refused(check):
    """Every pair not in the table must raise, not merely be unused.

    The table is the specification. A transition that is absent from it
    and also unreachable in practice is still worth asserting: the next
    person to add a state will copy this table, and a silent fallthrough
    is how `RUNNING -> IDLE` would creep back in.
    """
    for origin in RunState:
        for target in RunState:
            controller = _controller()
            controller._state = origin
            legal = target in LEGAL_TRANSITIONS[origin]
            try:
                controller._transition(target)
                raised = False
            except InvalidTransition:
                raised = True
            check(f"{origin} -> {target}", raised != legal,
                  f"legal={legal} raised={raised}")


def test_running_cannot_go_straight_to_idle():
    """The single most important absence in the table.

    Allowing it would let a run end without cleanup running, without a
    terminal status recorded, and - worst - with the instrument still
    claimed while the UI says the app is free.
    """
    assert RunState.IDLE not in LEGAL_TRANSITIONS[RunState.RUNNING]
    assert RunState.COMPLETED not in LEGAL_TRANSITIONS[RunState.CANCELLING]


def test_terminal_states_only_lead_back_to_idle():
    for state in TERMINAL_STATES:
        assert LEGAL_TRANSITIONS[state] == frozenset({RunState.IDLE})


def test_a_second_run_is_refused_while_one_is_in_flight():
    controller = _controller()
    with controller.begin():
        with pytest.raises(RunRejected) as excinfo:
            controller.begin()
    # the message is going into a dialog box, so it has to say what to do
    assert "in progress" in str(excinfo.value)
    assert "OFF" in str(excinfo.value)


def test_the_controller_is_idle_again_afterwards_and_accepts_a_new_run():
    controller = _controller()
    committed = []
    with controller.begin() as run:
        _complete(run, committed.append)
    assert controller.state is RunState.IDLE
    assert controller.is_idle and not controller.is_busy
    with controller.begin() as run:
        _complete(run, committed.append)
    assert len(committed) == 2


def test_run_ids_are_unique_and_carry_the_experiment_name():
    controller = _controller(name="vanderpauw")
    seen = []
    for _ in range(3):
        with controller.begin() as run:
            seen.append(run.run_id)
            run.start()
            run.add_reading({})
            run.note_shutdown(CONFIRMED)
            run.commit("r", lambda r: None)
    assert len(set(seen)) == 3
    assert all(rid.startswith("vanderpauw-") for rid in seen)


# ------------------------------------------------------------------
# cancellation
# ------------------------------------------------------------------
def test_a_cancelled_run_commits_nothing(check):
    """Issue A5's headline: cancelled runs are discarded, always."""
    controller = _controller()
    committed = []
    with controller.begin() as run:
        run.start()
        for n in range(50):
            run.add_reading({"point": n})
        controller.request_cancel()
        run.checkpoint("measuring")             # raises RunCancelled
        committed.append("unreachable")

    status = controller.last_status
    check("nothing committed", committed == [], f"{committed}")
    check("outcome is cancelled", status.outcome is Outcome.CANCELLED,
          f"{status.outcome}")
    check("provisional rows discarded", status.readings_discarded == 50,
          f"{status.readings_discarded}")
    check("back to idle", controller.state is RunState.IDLE)


def test_cancellation_one_instruction_before_commit_still_commits_nothing():
    """The race the review calls out by name.

    A sequence that finished measuring, turned the output off, and is
    one statement away from writing a row is *still* cancelled if the
    operator got there first. The check lives inside the commit gate,
    under the same lock cancellation takes, so there is no window
    between deciding and doing.
    """
    controller = _controller()
    committed = []
    with controller.begin() as run:
        run.start()
        run.add_reading({"point": 1})
        run.note_shutdown(CONFIRMED)
        controller.request_cancel()             # OFF pressed right here
        run.commit("result", committed.append)
    assert committed == []
    assert controller.last_status.outcome is Outcome.CANCELLED


def test_a_worker_that_never_checks_the_token_still_cannot_commit():
    """Cancellation must not depend on the worker being well-behaved.

    A sequence with no checkpoints at all runs to the end and tries to
    commit. The gate refuses it anyway, so a missed check costs a
    wasted measurement rather than a bad row in the file.
    """
    controller = _controller()
    committed = []
    with controller.begin() as run:
        run.start()
        run.add_reading({"point": 1})
        run.note_shutdown(CONFIRMED)
        controller.request_cancel()
        with pytest.raises(RunCancelled):
            run.commit("result", committed.append)
    assert committed == []
    assert controller.last_status.outcome is Outcome.CANCELLED


def test_cancelling_produces_no_traceback_for_the_operator():
    """RunCancelled is suppressed by the context manager.

    Pressing OFF is a normal action. If it escaped, every cancellation
    would print an exception into the console and read like a crash.
    """
    controller = _controller()
    with controller.begin() as run:              # no pytest.raises here
        run.start()
        controller.request_cancel()
        run.checkpoint()
    assert controller.last_status.outcome is Outcome.CANCELLED
    assert "cancelled" in controller.last_status.operator_message().lower()
    assert "no measurements were retained" in \
        controller.last_status.operator_message().lower()


def test_cancel_is_idempotent_and_reports_whether_it_did_anything():
    controller = _controller()
    assert controller.request_cancel() is False      # nothing to cancel
    with controller.begin() as run:
        run.start()
        assert controller.request_cancel("first") is True
        assert controller.request_cancel("second") is True
        assert run.token.reason == "first"           # the first reason wins
        run.checkpoint()
    assert controller.request_cancel() is False


# ------------------------------------------------------------------
# generation IDs - issue A2
# ------------------------------------------------------------------
def test_an_obsolete_worker_cannot_command_a_later_run():
    """The failure a shared stop flag cannot prevent.

    A worker from run 1 wakes up late, during run 2. Its token is not
    the current one, so every checkpoint refuses - even though nobody
    has cancelled anything and a shared `stop_requested` flag would by
    then have been cleared for run 2.
    """
    controller = _controller()
    first = controller.begin()
    first.start()
    stale_token = first.token
    stale = first
    first.note_shutdown(CONFIRMED)
    first.add_reading({})
    first.commit("r1", lambda r: None)
    first.__exit__(None, None, None)

    second = controller.begin()
    second.start()
    try:
        assert controller.is_current(second.token)
        assert not controller.is_current(stale_token)
        with pytest.raises(RunCancelled):
            stale.checkpoint("sourcing")         # the late worker tries
    finally:
        second.note_shutdown(CONFIRMED)
        second.add_reading({})
        second.commit("r2", lambda r: None)
        second.__exit__(None, None, None)


def test_tokens_are_never_shared_between_runs():
    controller = _controller()
    tokens = []
    for _ in range(3):
        with controller.begin() as run:
            tokens.append(run.token)
            run.start()
            run.add_reading({})
            run.note_shutdown(CONFIRMED)
            run.commit("r", lambda r: None)
    assert len({id(t) for t in tokens}) == 3
    assert not any(t.is_cancelled for t in tokens)


# ------------------------------------------------------------------
# responsive waits - section 11
# ------------------------------------------------------------------
def test_a_cancelled_sleep_returns_promptly_rather_than_serving_its_time():
    """Cancellation latency during a settle delay is bounded.

    Two-second settles are normal in the Van der Pauw sequence. With
    `time.sleep()` the OFF button appears dead for up to that long,
    which is exactly when an operator presses it twice or reaches for
    the instrument's own output key.
    """
    token = RunToken("latency-test")
    threading.Timer(0.05, token.cancel).start()

    started = time.perf_counter()
    with pytest.raises(RunCancelled):
        token.sleep(5.0, stage="settling")
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"took {elapsed:.2f}s to notice cancellation"


def test_an_uncancelled_sleep_waits_the_full_time():
    token = RunToken("latency-test")
    started = time.perf_counter()
    token.sleep(0.2)
    assert time.perf_counter() - started >= 0.19


def test_sleep_with_no_delay_still_checks_cancellation():
    """A zero settle time must not become a hole in the checking."""
    token = RunToken("zero")
    token.cancel()
    with pytest.raises(RunCancelled):
        token.sleep(0)


# ------------------------------------------------------------------
# failure - section 9
# ------------------------------------------------------------------
def test_an_exception_always_produces_a_terminal_state_and_discards_data():
    controller = _controller()
    committed = []
    with pytest.raises(ZeroDivisionError):
        with controller.begin() as run:
            run.start()
            run.add_reading({"point": 1})
            run.stage = "measuring pos 2"
            # Deliberate: this stands for any bug inside the block, and
            # it is spelled as an accident on purpose. B018 reads it as
            # a discarded expression, which is exactly what it is.
            1 / 0  # noqa: B018
    status = controller.last_status
    assert status.outcome is Outcome.FAILED
    assert status.readings_discarded == 1
    assert committed == []
    assert controller.state is RunState.IDLE
    assert "measuring pos 2" in status.operator_message()


def test_a_run_that_ends_without_committing_is_a_failure_not_a_success():
    """Falling out of the block with no result is a bug, not a quiet win.

    Without this, a sequence that returned early down some error path
    would leave the UI reporting an ordinary idle state and no record
    that anything went wrong.
    """
    controller = _controller()
    with controller.begin() as run:
        run.start()
        run.add_reading({"point": 1})
    status = controller.last_status
    assert status.outcome is Outcome.FAILED
    assert "without committing" in status.detail


def test_the_three_endings_read_differently(check):
    """Section 9: cancellation, failure, and uncertain shutdown.

    They share a cleanup path and must not share a message. An operator
    who cannot tell "I stopped it" from "the output may still be on"
    has been told nothing useful.
    """
    controller = _controller()

    with controller.begin() as run:
        run.start()
        controller.request_cancel()
        run.checkpoint()
    cancelled = controller.last_status.operator_message()

    with pytest.raises(RuntimeError):
        with controller.begin() as run:
            run.start()
            run.note_shutdown(CONFIRMED)
            raise RuntimeError("instrument timeout")
    failed = controller.last_status.operator_message()

    with pytest.raises(RuntimeError):
        with controller.begin() as run:
            run.start()
            run.note_shutdown(ShutdownReport(ShutdownStatus.UNCERTAIN,
                                             "output_off() raised: timeout"))
            raise RuntimeError("instrument timeout")
    uncertain_status = controller.last_status
    uncertain = uncertain_status.operator_message()

    check("cancellation does not read as an error",
          "fail" not in cancelled.lower(), cancelled)
    check("failure confirms the output is off",
          "shutdown was confirmed" in failed.lower(), failed)
    check("uncertain shutdown warns about energised hardware",
          "may still be energised" in uncertain.lower(), uncertain)
    check("uncertain shutdown has its own outcome",
          uncertain_status.outcome is Outcome.UNCERTAIN_SHUTDOWN,
          f"{uncertain_status.outcome}")
    check("uncertain shutdown asks for attention",
          uncertain_status.needs_attention)
    check("plain failure does not",
          not controller.history[-2].needs_attention)


# ------------------------------------------------------------------
# the commit gate - sections 6 and 7
# ------------------------------------------------------------------
def test_a_successful_commit_happens_once_and_only_once():
    controller = _controller()
    committed = []
    with controller.begin() as run:
        run.start()
        run.add_reading({})
        run.note_shutdown(CONFIRMED)
        run.commit("result", committed.append)
        with pytest.raises(RunRejected):
            run.commit("result again", committed.append)
    assert committed == ["result"]
    assert controller.last_status.outcome is Outcome.COMPLETED


def test_provisional_readings_reach_the_sink_only_at_commit():
    """The two-phase model. Nothing outside the run can see the rows.

    The visible results table is not the buffer: a run holds its own
    readings and hands them over once, which is what makes "discard on
    cancel" a deletion of nothing rather than a rollback.
    """
    controller = _controller()
    seen_during = []
    with controller.begin() as run:
        run.start()
        for n in range(5):
            run.add_reading({"point": n})
            seen_during.append(len(run.readings))
        assert run.committed is False
        run.note_shutdown(CONFIRMED)
        run.commit(list(run.readings), lambda rows: seen_during.append("commit"))
    assert seen_during == [1, 2, 3, 4, 5, "commit"]


def test_the_completion_gate_lists_every_unmet_condition(check):
    """Section 7: one policy object decides, and it says why in full.

    Reporting only the first failure means fixing them one bench run at
    a time.
    """
    controller = _controller(policy=CompletionPolicy(
        required_metadata=("sample", "position")))
    with controller.begin(metadata={"sample": "wafer_A"}) as run:
        run.start()
        run.expect(10)
        run.add_reading({"point": 1})
        run.record_error("point 4 returned NAN")
        with pytest.raises(IncompleteRun) as excinfo:
            run.commit("result", lambda r: None)
        reasons = " | ".join(excinfo.value.reasons)

    check("short point count is caught", "expected 10 readings" in reasons, reasons)
    check("recorded errors are caught", "unresolved error" in reasons, reasons)
    check("missing metadata is caught", "position" in reasons, reasons)
    check("unconfirmed shutdown is caught", "shutdown is" in reasons, reasons)


def test_an_empty_run_cannot_commit():
    controller = _controller()
    with controller.begin() as run:
        run.start()
        run.note_shutdown(CONFIRMED)
        with pytest.raises(IncompleteRun):
            run.commit("result", lambda r: None)


def test_a_point_count_that_matches_passes_the_gate():
    """The other half of the point-count check.

    A sweep silently reduced to a third of its points fitted a perfect
    line on this bench. The count is declared from the request, so a
    short return is a refusal rather than a plausible answer.
    """
    controller = _controller()
    committed = []
    with controller.begin() as run:
        run.start()
        run.expect(3)
        for n in range(3):
            run.add_reading({"point": n})
        run.note_shutdown(CONFIRMED)
        run.commit("result", committed.append)
    assert committed == ["result"]


def test_an_experiment_may_relax_the_shutdown_requirement_deliberately():
    """IV periodic bias will hold the output on between runs.

    The escape hatch exists, is per-experiment, and is explicit - which
    is the difference between a documented exception and four
    experiments each inventing their own idea of success.
    """
    controller = _controller(policy=CompletionPolicy(
        require_shutdown_confirmed=False))
    committed = []
    with controller.begin() as run:
        run.start()
        run.add_reading({})
        run.commit("result", committed.append)
    assert committed == ["result"]


def test_the_default_policy_demands_a_confirmed_shutdown():
    assert DEFAULT_POLICY.require_shutdown_confirmed is True
    assert DEFAULT_POLICY.require_readings is True


# ------------------------------------------------------------------
# cleanup ordering
# ------------------------------------------------------------------
def test_cleanup_runs_before_the_controller_returns_to_idle(check):
    """Section 5's acceptance criterion, made executable.

    "The UI returns to IDLE only after instrument ownership is
    released." Anything registered with `enter()` or `on_cleanup()`
    unwinds while the state is still terminal, so a Run button watching
    for IDLE cannot fire while an instrument is still claimed.
    """
    controller = _controller()
    observed = []

    with controller.begin() as run:
        run.on_cleanup(lambda: observed.append(("cleanup", controller.state)))
        run.start()
        run.add_reading({})
        run.note_shutdown(CONFIRMED)
        run.commit("r", lambda r: None)

    check("cleanup ran", len(observed) == 1, f"{observed}")
    check("state was still terminal during cleanup",
          observed[0][1] in TERMINAL_STATES, f"{observed[0][1]}")
    check("idle afterwards", controller.state is RunState.IDLE)


def test_cleanup_runs_on_cancellation_and_on_failure(check):
    controller = _controller()

    released = []
    with controller.begin() as run:
        run.on_cleanup(released.append, "cancelled")
        run.start()
        controller.request_cancel()
        run.checkpoint()

    with pytest.raises(RuntimeError):
        with controller.begin() as run:
            run.on_cleanup(released.append, "failed")
            run.start()
            raise RuntimeError("boom")

    check("released on both paths", released == ["cancelled", "failed"],
          f"{released}")


def test_a_cleanup_that_throws_does_not_wedge_the_controller():
    """A stuck controller is worse than a logged cleanup failure.

    If cleanup could leave the state out of IDLE, one failed disconnect
    would make the application refuse every subsequent run with no way
    back except a restart.
    """
    logged = []
    controller = _controller(log=logged.append)

    def bad_cleanup():
        raise OSError("port already closed")

    with controller.begin() as run:
        run.on_cleanup(bad_cleanup)
        run.start()
        run.add_reading({})
        run.note_shutdown(CONFIRMED)
        run.commit("r", lambda r: None)

    assert controller.state is RunState.IDLE
    assert any("cleanup failed" in line for line in logged)
    with controller.begin() as run:            # and it still works
        run.start()


def test_wait_for_idle_returns_once_cleanup_has_finished():
    controller = _controller()
    assert controller.wait_for_idle(timeout=0) is True

    run = controller.begin()
    assert controller.wait_for_idle(timeout=0.05) is False
    run.start()
    run.add_reading({})
    run.note_shutdown(CONFIRMED)
    run.commit("r", lambda r: None)
    run.__exit__(None, None, None)
    assert controller.wait_for_idle(timeout=1.0) is True


# ------------------------------------------------------------------
# observers
# ------------------------------------------------------------------
def test_observers_see_every_transition_and_cannot_break_a_run():
    controller = _controller(log=lambda m: None)
    seen = []
    controller.observe(lambda state, run: seen.append(state))
    controller.observe(lambda state, run: 1 / 0)      # a badly written panel

    with controller.begin() as run:
        run.start()
        run.add_reading({})
        run.note_shutdown(CONFIRMED)
        run.commit("r", lambda r: None)

    assert seen == [RunState.PREPARING, RunState.RUNNING,
                    RunState.COMPLETED, RunState.IDLE]


# ------------------------------------------------------------------
# shutdown verification - issue A10
# ------------------------------------------------------------------
class _FakeDriver:
    """The smallest driver-shaped thing `confirm_output_off` needs."""

    def __init__(self, off_raises=None, errors=()):
        self.off_raises = off_raises
        self.errors = list(errors)
        self.off_calls = 0

    def output_off(self):
        self.off_calls += 1
        if self.off_raises:
            raise self.off_raises

    def read_error(self):
        return self.errors.pop(0) if self.errors else (0, "No error")


def test_a_clean_output_off_is_confirmed():
    driver = _FakeDriver()
    report = confirm_output_off(driver)
    assert report.confirmed
    assert driver.off_calls == 1


def test_an_output_off_that_raises_is_uncertain_not_confirmed():
    report = confirm_output_off(_FakeDriver(off_raises=TimeoutError("VISA timeout")))
    assert report.uncertain
    assert "VISA timeout" in report.detail


def test_an_instrument_that_rejected_the_command_makes_shutdown_uncertain():
    """The quiet failure mode this exists for.

    A SCPI instrument logs a command it did not understand and carries
    on. `output_off()` returns perfectly normally and the output is
    still on. Only the error queue knows.
    """
    driver = _FakeDriver(errors=[(-113, "Undefined header"), (0, "No error")])
    report = confirm_output_off(driver)
    assert report.uncertain
    assert "-113" in report.detail


def test_several_queued_faults_are_all_reported():
    driver = _FakeDriver(errors=[(-113, "Undefined header"),
                                 (-222, "Parameter data out of range"),
                                 (0, "No error")])
    report = confirm_output_off(driver)
    assert "-113" in report.detail and "-222" in report.detail


def test_being_unable_to_ask_about_errors_is_not_evidence_of_a_fault():
    """`read_error()`'s own contract, honoured here.

    Not being able to *ask* whether a command was understood is not the
    same as learning that it failed. Treating it as a fault would block
    instruments over a dropped reply, which is the opposite of useful.
    """
    class Unreadable(_FakeDriver):
        def read_error(self):
            raise ConnectionError("no reply")

    report = confirm_output_off(Unreadable())
    assert report.confirmed
    assert "unreadable" in report.detail


def test_run_context_records_the_shutdown_it_performed():
    controller = _controller()
    driver = _FakeDriver()
    with controller.begin() as run:
        run.start()
        run.add_reading({})
        run.confirm_shutdown(driver)
        assert run.shutdown.confirmed
        run.commit("r", lambda r: None)
    assert controller.last_status.shutdown.confirmed


# ------------------------------------------------------------------
# threads
# ------------------------------------------------------------------
def test_a_worker_thread_stops_promptly_when_the_ui_thread_cancels():
    """The whole point, exercised across two threads.

    The UI cancels; the worker is inside a long settle; it wakes,
    unwinds, and commits nothing. This is the shape every migrated
    experiment will have.
    """
    controller = _controller()
    committed = []
    started = threading.Event()

    def worker():
        with controller.begin() as run:
            run.start()
            started.set()
            for n in range(100):
                run.checkpoint(f"point {n}")
                run.add_reading({"point": n})
                run.sleep(0.5)
            run.note_shutdown(CONFIRMED)
            run.commit("result", committed.append)

    thread = threading.Thread(target=worker)
    thread.start()
    started.wait(timeout=2.0)
    time.sleep(0.05)
    controller.request_cancel()
    thread.join(timeout=3.0)

    assert not thread.is_alive(), "worker did not stop after cancellation"
    assert committed == []
    assert controller.state is RunState.IDLE
    assert controller.last_status.outcome is Outcome.CANCELLED
