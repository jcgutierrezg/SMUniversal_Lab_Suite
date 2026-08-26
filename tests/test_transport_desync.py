"""
A transport that has lost the thread must refuse to read.

The fault being guarded against is not a crash. A read fails; the
instrument answers late into its output buffer; every query afterwards
collects the *previous* command's reply. The numbers stay well-formed
and in range, so nothing downstream can tell. These tests pin the one
behaviour that makes it detectable: the transport stops answering.

They deliberately assert on the *interesting* case. A test that a
healthy transport keeps working would pass whether or not any of this
existed.
"""
import pytest

from core.transports.base import Transport, TransportDesynchronised


class Flaky(Transport):
    """A transport whose reads can be told to fail.

    `fail_reads` makes the next `_read` raise. `fail_writes` does the
    same for `_write`, which is how the write/query asymmetry gets
    tested rather than assumed.
    """

    def __init__(self):
        super().__init__()
        self.connected = True
        self.sent = []
        self.reads = 0
        self.fail_reads = False
        self.fail_writes = False

    def connect(self, address=None, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        if self.fail_writes:
            raise OSError("write failed")
        self.sent.append(text)

    def _read(self, timeout_s):
        if self.fail_reads:
            raise TimeoutError("read timed out")
        self.reads += 1
        return f"reply{self.reads}"


def make():
    t = Flaky()
    assert t.query("*IDN?") == "reply1"
    assert not t.is_desynchronised
    return t


# ---------------------------------------------------------------
# the latch
# ---------------------------------------------------------------
def test_a_failed_read_raises_desynchronised_not_the_original():
    """The first failure is already the interesting one.

    Reporting the raw TimeoutError here and only switching to
    TransportDesynchronised on the *second* query would let the 18
    `except Exception` handlers in the drivers swallow the first one -
    the only one that names the command that went unanswered.
    """
    t = make()
    t.fail_reads = True
    with pytest.raises(TransportDesynchronised):
        t.query("MEAS?")


def test_the_original_cause_is_preserved():
    t = make()
    t.fail_reads = True
    try:
        t.query("MEAS?")
    except TransportDesynchronised as exc:
        assert isinstance(exc.__cause__, TimeoutError)
    else:
        pytest.fail("no exception")


def test_the_state_latches_after_the_link_recovers():
    """The point of the whole change.

    The link coming back is not the stream coming back into step: the
    late reply is still sitting in the buffer. A transport that started
    answering again here would return `reply2` to a caller that asked a
    different question.
    """
    t = make()
    t.fail_reads = True
    with pytest.raises(TransportDesynchronised):
        t.query("MEAS?")

    t.fail_reads = False              # the cable is fine again
    with pytest.raises(TransportDesynchronised):
        t.query("VOLT?")
    with pytest.raises(TransportDesynchronised):
        t.query("VOLT?")


def test_the_first_cause_is_kept_not_the_latest():
    t = make()
    t.fail_reads = True
    with pytest.raises(TransportDesynchronised):
        t.query("MEAS?")
    reason = t.desync_reason
    with pytest.raises(TransportDesynchronised):
        t.query("SOMETHING:ELSE?")
    assert t.desync_reason == reason, "the first cause explains the rest"


def test_the_message_names_the_command_that_went_unanswered():
    t = make()
    t.fail_reads = True
    with pytest.raises(TransportDesynchronised) as caught:
        t.query("MEAS:VOLT?")
    assert "MEAS:VOLT?" in str(caught.value)


def test_a_desynchronised_query_does_not_reach_the_instrument():
    """Refused before the write, not after.

    A refusal that still sent the command would leave another orphan
    reply in the buffer for the next session to trip over.
    """
    t = make()
    t.fail_reads = True
    with pytest.raises(TransportDesynchronised):
        t.query("MEAS?")
    before = list(t.sent)
    with pytest.raises(TransportDesynchronised):
        t.query("SOUR:VOLT?")
    assert t.sent == before


# ---------------------------------------------------------------
# the write/query asymmetry - what makes de-energising possible
# ---------------------------------------------------------------
def test_writes_still_reach_a_desynchronised_instrument():
    """`output_off()` is a write on every driver in the fleet.

    If this ever goes red, a lost link stops being able to de-energise
    a sample, which is a safety regression rather than a test failure.
    """
    t = make()
    t.fail_reads = True
    with pytest.raises(TransportDesynchronised):
        t.query("MEAS?")

    t.write("OUTP OFF")
    assert t.sent[-1] == "OUTP OFF"


def test_a_failed_write_does_not_desynchronise():
    """Nothing was expecting a reply, so nothing can arrive late."""
    t = make()
    t.fail_writes = True
    with pytest.raises(OSError):
        t.write("OUTP OFF")
    assert not t.is_desynchronised


def test_a_failed_write_inside_a_query_does_desynchronise():
    """Because a query has committed to an exchange.

    Whether the command left is not knowable from here, so the
    conservative reading is taken: a reconnect costs a minute, a
    poisoned sweep costs the sample.
    """
    t = make()
    t.fail_writes = True
    with pytest.raises(TransportDesynchronised):
        t.query("MEAS?")
    assert t.is_desynchronised


# ---------------------------------------------------------------
# reconnecting is the only way back
# ---------------------------------------------------------------
def test_reconnecting_clears_it():
    t = make()
    t.fail_reads = True
    with pytest.raises(TransportDesynchronised):
        t.query("MEAS?")

    t.fail_reads = False
    t.close()
    t.connect()
    assert not t.is_desynchronised
    assert t.query("*IDN?").startswith("reply")


def test_clear_does_not_clear_it():
    """clear() was the old recovery path and is no longer evidence.

    It returns whether a device-clear call raised, which is a different
    question from whether the stream is back in step.
    """
    t = make()
    t.fail_reads = True
    with pytest.raises(TransportDesynchronised):
        t.query("MEAS?")
    t.clear()
    assert t.is_desynchronised


# ---------------------------------------------------------------
# it must survive the handlers that legitimately swallow query failures
# ---------------------------------------------------------------
def test_it_is_an_ordinary_exception():
    """Deliberately catchable, so cleanup handlers still work.

    A BaseException here would skip `RunSession.close()`'s
    `except Exception` handler - which is where `confirm_output_off()`
    runs. The de-energise would be bypassed in the name of guaranteeing
    the de-energise, and the run would never return to IDLE.

    The cost is that every broad handler around a query has to name and
    re-raise it. That obligation is enforced by
    tests/test_desync_not_swallowed.py, not by inheritance.
    """
    assert issubclass(TransportDesynchronised, Exception)


def test_finally_blocks_still_run():
    """Unswallowable is not the same as unstoppable.

    Cleanup has to keep working or the cure is worse than the disease.
    """
    t = make()
    t.fail_reads = True
    cleaned = []
    with pytest.raises(TransportDesynchronised):
        try:
            t.query("MEAS?")
        finally:
            cleaned.append("ran")
    assert cleaned == ["ran"]


# ---------------------------------------------------------------
# every transport in the fleet inherits it
# ---------------------------------------------------------------
def test_every_transport_subclass_inherits_the_guard():
    """No transport may implement its own query() and skip the latch.

    Enforced over the subclass tree rather than per file, because the
    failure mode of the per-file version is a transport added later
    that nobody remembers to check.
    """
    import core.transports.minismu_transport   # noqa: F401
    import core.transports.ni_gpib_usb_hs_transport  # noqa: F401
    import core.transports.null_transport      # noqa: F401
    import core.transports.serial_transport    # noqa: F401
    import core.transports.visa_transport      # noqa: F401

    def descendants(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from descendants(sub)

    # Named, not pattern-matched. MiniSMUTransport carries method calls
    # rather than a text request/response stream: `minismu_py` returns
    # or raises at the call site, so there is no output buffer for a
    # late reply to sit in and nothing for a later call to collect. Its
    # query() answers only *IDN? for auto-detection.
    #
    # This is an exemption, not a clean bill of health. The driver's
    # real traffic goes through `transport.client.<method>()` and never
    # touches Transport at all, so whether that path can lose its place
    # is a separate question that has not been asked yet - recorded in
    # docs/open/technical-debt.md.
    exempt = {"MiniSMUTransport"}
    offenders = [c.__name__ for c in descendants(Transport)
                 if "query" in c.__dict__
                 and c.__module__.startswith("core.")
                 and c.__name__ not in exempt]
    assert not offenders, (
        f"{offenders} override query() and bypass the desync latch")


# ---------------------------------------------------------------
# the shutdown report must not claim what it cannot know
# ---------------------------------------------------------------
def test_shutdown_is_uncertain_not_confirmed_on_a_desync():
    """The safety-relevant one.

    `confirm_output_off()` used to return CONFIRMED when the error queue
    could not be read, on the documented grounds that being unable to
    ask is not evidence of a fault. That is right for a dropped reply
    and wrong for a link that has stopped answering: no reply can be
    matched to its question, so "the instrument says the output is off"
    is not a statement this function is in a position to make.

    output_off() is a write and will usually have landed, so the sample
    is usually de-energised. Usually is not confirmed, and the operator
    decides what to do about the difference.
    """
    from core.run_control import confirm_output_off, ShutdownStatus

    class Poisoned:
        """Accepts the write, cannot answer the question after it."""

        def __init__(self):
            self.output_off_called = False

        def output_off(self):
            self.output_off_called = True

        def read_error(self):
            raise TransportDesynchronised("the link stopped answering")

    driver = Poisoned()
    report = confirm_output_off(driver)
    assert driver.output_off_called, (
        "the de-energise must be attempted before anything else - it is a "
        "write, and a write still reaches a desynchronised instrument")
    assert report.status is ShutdownStatus.UNCERTAIN
    assert report.uncertain
    assert "could NOT be confirmed" in report.detail


def test_a_merely_unreadable_queue_still_confirms():
    """The distinction has to cut both ways or it is not a distinction.

    A driver whose read_error() raises something ordinary is the
    dropped-reply case the original rule was written for, and it must
    keep confirming - otherwise every run ends in a front-panel warning
    and the warning stops meaning anything.
    """
    from core.run_control import confirm_output_off, ShutdownStatus

    class Muffled:
        def output_off(self):
            pass

        def read_error(self):
            raise OSError("queue unreadable")

    report = confirm_output_off(Muffled())
    assert report.status is ShutdownStatus.CONFIRMED
