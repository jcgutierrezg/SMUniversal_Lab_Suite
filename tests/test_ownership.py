"""Exclusive instrument ownership - Wave 1, issues A3 and A10.

Section 12's point is that a transport lock protects the *wire* and not
the *experiment*: every individual call can be thread-safe while two
interleaved measurement sequences produce nonsense. So the unit that
gets locked here is the whole run, and the key is the physical
connection rather than the driver object - because two windows on one
GPIB address are two Python objects and one instrument.

No Tk and no hardware. The blocking behaviour (A9's failed reset, A10's
unverifiable shutdown) is wired into `LabApp` and tested in
tests/test_wave1_wiring.py; what is tested here is the mechanism.
"""
import threading

import pytest

from core.ownership import (
    Claim,
    InstrumentBlocked,
    InstrumentBusy,
    InstrumentOwnership,
    default_ownership,
    key_for_transport,
)
from core.transports.null_transport import NullTransport
from core.transports.visa_transport import VisaTransport


@pytest.fixture
def ownership():
    return InstrumentOwnership()


# ------------------------------------------------------------------
# exclusivity
# ------------------------------------------------------------------
def test_one_instrument_has_one_owner(ownership):
    ownership.claim("GPIB0::25::INSTR", "run-1")
    with pytest.raises(InstrumentBusy) as excinfo:
        ownership.claim("GPIB0::25::INSTR", "run-2")
    assert "run-1" in str(excinfo.value)
    # the message goes in a dialog, so it must say what to do about it
    assert "cancel" in str(excinfo.value).lower()


def test_two_experiment_windows_cannot_run_against_one_instrument(check):
    """Section 13's acceptance criterion.

    Ownership is process-wide rather than per-panel, so opening a second
    experiment view does not create an independent path to the hardware.
    Both windows here go through the *same* manager, which is what
    `default_ownership()` guarantees in the application.
    """
    shared = InstrumentOwnership()
    window_a = shared
    window_b = shared

    key = "VisaTransport:TCPIP0::169.254.43.121::5025::SOCKET"
    window_a.claim(key, "vanderpauw-0001")
    with pytest.raises(InstrumentBusy):
        window_b.claim(key, "hall-0001")

    check("the default manager is shared", default_ownership() is
          default_ownership())


def test_releasing_lets_the_next_run_in(ownership):
    claim = ownership.claim("K", "run-1")
    claim.release()
    assert ownership.owner_of("K") is None
    ownership.claim("K", "run-2")
    assert ownership.owner_of("K") == "run-2"


def test_release_is_idempotent(ownership):
    claim = ownership.claim("K", "run-1")
    assert claim.release() is True
    assert claim.release() is False
    assert claim.released is True


def test_a_claim_works_as_a_context_manager(ownership):
    with ownership.claim("K", "run-1") as claim:
        assert isinstance(claim, Claim)
        assert ownership.is_owned("K")
    assert not ownership.is_owned("K")


def test_a_claim_is_released_even_when_the_run_throws(ownership):
    with pytest.raises(RuntimeError):
        with ownership.claim("K", "run-1"):
            raise RuntimeError("instrument timeout")
    assert not ownership.is_owned("K")


def test_one_run_may_claim_the_same_instrument_twice(check):
    """Two declared roles can resolve to one physical box.

    The U2722A has three channels; a dual-role experiment driving two of
    them is one instrument and one run. Refusing that would be the
    exclusivity rule misfiring against the run it is meant to protect.
    Counted rather than ignored, so the first release does not free an
    instrument the run is still using.
    """
    ownership = InstrumentOwnership()
    first = ownership.claim("U2722A", "run-1", label="source")
    second = ownership.claim("U2722A", "run-1", label="sense")

    first.release()
    check("still held after one release", ownership.is_owned("U2722A"))
    second.release()
    check("free after both", not ownership.is_owned("U2722A"))


def test_force_release_drops_a_claim_whoever_holds_it(ownership):
    ownership.claim("K", "run-1")
    assert ownership.force_release("K") is True
    assert ownership.force_release("K") is False
    assert not ownership.is_owned("K")


# ------------------------------------------------------------------
# blocking - issues A9 and A10
# ------------------------------------------------------------------
def test_a_blocked_instrument_refuses_every_claim(ownership):
    ownership.block("K", "The mandatory reset failed.")
    with pytest.raises(InstrumentBlocked) as excinfo:
        ownership.claim("K", "run-1")
    message = str(excinfo.value)
    assert "mandatory reset failed" in message
    assert "Reconnect" in message          # the remedy, not just the fault


def test_blocking_beats_availability(ownership):
    """A free instrument that needs checking is not an available one.

    The distinction matters because "nobody is using it" is exactly the
    state an unverified output is in, and it is the state in which
    starting another run would be worst.
    """
    assert not ownership.is_owned("K")
    ownership.block("K", "Output could not be confirmed off.")
    with pytest.raises(InstrumentBlocked):
        ownership.claim("K", "run-1")


def test_unblocking_restores_it(ownership):
    ownership.block("K", "reason")
    assert ownership.is_blocked("K")
    assert ownership.unblock("K") is True
    assert ownership.unblock("K") is False
    ownership.claim("K", "run-1")           # no longer raises


def test_a_block_survives_a_release(ownership):
    """Ending the run that went wrong does not clear the warning.

    An uncertain shutdown blocks the instrument; the run then finishes
    its cleanup and releases the claim. If release cleared the block,
    A10 would last exactly as long as it took the run to unwind and
    protect nobody.
    """
    claim = ownership.claim("K", "run-1")
    ownership.block("K", "Output could not be confirmed off.")
    claim.release()
    assert ownership.is_blocked("K")
    with pytest.raises(InstrumentBlocked):
        ownership.claim("K", "run-2")


def test_the_reason_is_kept_for_the_console(ownership):
    ownership.block("K", "the reset failed")
    assert ownership.block_reason("K") == "the reset failed"
    assert ownership.blocked_keys() == ("K",)


# ------------------------------------------------------------------
# keys name connections, not objects
# ------------------------------------------------------------------
def test_two_transports_at_one_address_share_a_key(check):
    """The whole reason ownership is not keyed on the driver.

    Two `VisaTransport` objects pointing at one resource string are two
    Python objects and one instrument. Keyed on identity, both windows
    would claim successfully and drive the same box.
    """
    a, b = VisaTransport(), VisaTransport()
    a.address = "GPIB0::25::INSTR"
    b.address = "gpib0::25::instr"          # same resource, typed differently
    check("same key", key_for_transport(a) == key_for_transport(b),
          f"{key_for_transport(a)} vs {key_for_transport(b)}")

    c = VisaTransport()
    c.address = "GPIB0::26::INSTR"
    check("different address, different key",
          key_for_transport(a) != key_for_transport(c))


def test_two_demo_transports_are_independent():
    """Demo mode must not contend for an imaginary shared instrument.

    `NullTransport` has no address, so the key falls back to identity -
    two demo windows are two simulated samples, which is what a person
    running the app at their desk expects.
    """
    a, b = NullTransport(), NullTransport()
    a.connect("<simulated sample>")
    b.connect("<simulated sample>")
    assert key_for_transport(a) != key_for_transport(b)


def test_a_serial_port_keys_off_the_port_name():
    class FakeSerial:
        port = "COM3"

    assert "COM3" in key_for_transport(FakeSerial())


def test_key_derivation_survives_a_transport_that_has_neither(check):
    """Test fakes are duck-typed and must not crash the key lookup."""
    class Odd:
        pass

    # Both kept alive deliberately: CPython reuses the id of a freed
    # object, so comparing the keys of two short-lived objects compares
    # the same address twice and passes for the wrong reason.
    first, second = Odd(), Odd()
    key = key_for_transport(first)
    check("a key was produced", bool(key), key)
    check("and it is unique per object",
          key_for_transport(second) != key)


def test_a_transport_may_override_its_own_key():
    """The hook for an instrument reachable under two spellings."""
    class Normalising:
        def connection_key(self):
            return "minismu:MS01-0042"

    assert key_for_transport(Normalising()) == "minismu:MS01-0042"


def test_a_broken_connection_key_falls_back_rather_than_raising():
    class Broken:
        address = "GPIB0::25::INSTR"

        def connection_key(self):
            raise RuntimeError("not connected")

    assert "GPIB0::25::INSTR" in key_for_transport(Broken())


# ------------------------------------------------------------------
# threads
# ------------------------------------------------------------------
def test_only_one_of_many_racing_claims_succeeds():
    """The interleaving from section 12, attempted in earnest.

    Twenty threads try to claim one instrument at the same moment. If
    the manager's bookkeeping were not locked, two of them could both
    read "unowned" and both proceed - which is precisely the two
    concurrent measurement sequences the review describes.
    """
    ownership = InstrumentOwnership()
    barrier = threading.Barrier(20)
    winners, losers = [], []
    lock = threading.Lock()

    def contend(n):
        barrier.wait()
        try:
            ownership.claim("K", f"run-{n}")
        except InstrumentBusy:
            with lock:
                losers.append(n)
        else:
            with lock:
                winners.append(n)

    threads = [threading.Thread(target=contend, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(winners) == 1, f"{len(winners)} threads claimed one instrument"
    assert len(losers) == 19


def test_snapshot_reports_what_is_held_and_blocked(ownership):
    ownership.claim("A", "run-1", label="SMU")
    ownership.block("B", "reset failed")
    snapshot = ownership.snapshot()
    assert snapshot["held"]["A"]["run_id"] == "run-1"
    assert snapshot["held"]["A"]["label"] == "SMU"
    assert snapshot["blocked"]["B"] == "reset failed"
