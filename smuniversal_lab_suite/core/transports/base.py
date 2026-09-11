"""
The transport contract.

A transport knows *how* bytes travel (GPIB, USB, TCP socket, raw serial).
It does NOT know what they mean - no SCPI, no TSP, no instrument concepts
at all. Drivers sit one layer up and decide *what* to send.

Keeping these separate is what lets a Keithley 2450 move from GPIB to a
serial cable without touching its driver, and lets a Seeed Xiao share the
same plumbing as an SMU.
"""
import re
import threading
from abc import ABC, abstractmethod


class TransportDesynchronised(RuntimeError):
    """The request/response stream is one reply out of step.

    Raised when a query fails after the command has been committed, and
    on every query afterwards until the transport is reconnected.

    Two independent things are wrong once an exchange fails, and either
    alone is enough to stop:

    1. **The correspondence is broken.** If the instrument answers late,
       the reply sits in the output buffer and the next query collects
       it instead of its own. Whether that is happening cannot be known
       from here, which is exactly why no later reply can be trusted.

    2. **The measurement did not happen.** A level was sourced, a
       reading was expected, and none came back. That is true even when
       the cable is dead and no reply is ever coming - the sweep has a
       hole in it and its point-to-point timing is no longer the timing
       that was asked for.

    The first is why the transport latches. The second is why a run
    cannot simply resume once the link returns.

    The failure this guards against does not look like a failure. A read
    times out; the instrument finishes late and leaves its reply in the
    output buffer; the next query writes a new command and collects the
    *previous* command's answer. Every reading after that point is one
    command out of step, and nothing about the numbers themselves says
    so - they are well-formed, in range, and answer a question nobody
    asked. On the GSM-20H10 on 2026-08-25 a checkup ran 1386 further
    queries in that state.

    There is deliberately no recovery in place. A device clear that
    works sometimes is a recovery nobody can trust, and on the affected
    backend it reported failure anyway. Reconnecting is the only way
    back, because it is the only path that also re-runs the driver's
    reset() and restores a state the software can vouch for.

    **An ordinary Exception, enforced by a lint rather than by
    inheritance.**

    This codebase swallows failed queries in a lot of places, and it is
    right to: `read_error()` returning code 0 after a dropped reply is
    correct, because being unable to *ask* about errors is not evidence
    that a command failed. There are 18 such handlers across the
    drivers, and every one of them would swallow this too, so each names
    this class and re-raises it first.

    Making it a BaseException would have removed the need to remember -
    and would also have skipped `RunSession.close()`'s cleanup handler,
    which is where `confirm_output_off()` runs. Guaranteeing the
    de-energise by bypassing the de-energise. The run would never return
    to IDLE and the app would wedge with no crash to explain it.

    So the rule is enforced where a missed site is cheap to fix instead:
    `tests/test_desync_not_swallowed.py` walks every `try` containing a
    `.query()` and fails if a broad handler does not re-raise this
    first. The nineteenth site is caught by CI, not by the bench.
    """


_GPIB_RESOURCE = re.compile(
    r"^GPIB(?P<board>\d*)::(?P<primary>\d+)"
    r"(?:::(?P<secondary>\d+))?::INSTR$",
    re.IGNORECASE,
)


def parse_gpib_resource(address):
    """Return ``(board, primary, secondary)`` for a GPIB VISA resource.

    ``secondary`` is ``None`` when the resource uses only primary
    addressing. Non-GPIB strings return ``None`` rather than raising, so
    callers such as ``connection_key()`` can fall back to their normal
    transport-specific identity.
    """
    match = _GPIB_RESOURCE.fullmatch(str(address).strip())
    if match is None:
        return None
    board = int(match.group("board") or 0)
    primary = int(match.group("primary"))
    secondary = match.group("secondary")
    return board, primary, None if secondary is None else int(secondary)


def gpib_connection_key(address):
    """Physical ownership key shared by VISA and direct GPIB paths."""
    parsed = parse_gpib_resource(address)
    if parsed is None:
        return None
    board, primary, secondary = parsed
    suffix = "" if secondary is None else f":{secondary}"
    return f"GPIB:{board}:{primary}{suffix}"


class Transport(ABC):
    """Base class for all transports. Subclasses implement _write/_read
    and the connect/close pair; the locking and the query() convenience
    are handled here so every transport behaves the same under threads."""

    def __init__(self):
        self.lock = threading.Lock()
        self.connected = False
        self._desync_reason = None
        self._desync_command = None

    # ---- session state ----
    #
    # `connected` used to be a property whose setter cleared the
    # desynchronised latch on a False->True transition, so that clearing
    # it could not be forgotten. That was the wrong mechanism, and it
    # opened the hole it was meant to close: NIUSBGPIBTransport's
    # `clear()` reopens the adapter and sets `connected = True` on the
    # way out, which silently un-desynchronised a poisoned session
    # through exactly the kind of unverified recovery the latch exists
    # to refuse.
    #
    # Clearing is now explicit, and the obligation is checked by
    # `tests/test_transport_desync.py` over every Transport subclass
    # rather than enforced by a mechanism that fires in places nobody
    # was thinking about. A missed call fails in CI; a clever setter
    # failed on a bench.
    connected = False

    def _begin_session(self):
        """Start a fresh session. Call from `connect()`, nowhere else.

        A new session does not inherit the previous one's poisoned
        stream. Reopening a link inside `clear()` is not a new session:
        nothing has re-run the driver's reset(), so the instrument's
        state is still unvouched for.
        """
        self._desync_reason = None
        self._desync_command = None

    @property
    def is_desynchronised(self):
        """True once a query has failed after committing its command.

        Latches. Only a reconnect clears it - see
        TransportDesynchronised.
        """
        return self._desync_reason is not None

    @property
    def desync_reason(self):
        """Why this transport was declared desynchronised, or None."""
        return self._desync_reason

    def _desync_message(self):
        command = (f" while exchanging {self._desync_command!r}"
                   if self._desync_command else "")
        return (f"A command was sent{command} and its reply never arrived "
                f"({self._desync_reason}). No later reply can be trusted to "
                f"belong to the question that asked for it, so this "
                f"transport refuses to read. Reconnect the instrument.")

    def _mark_desynchronised(self, exc, command):
        """Latch the desynchronised state. Idempotent - the first cause
        is kept, because it is the one that explains all the others."""
        if self._desync_reason is None:
            self._desync_reason = f"{type(exc).__name__}: {exc}"
            self._desync_command = command

    # ---- lifecycle ----
    @abstractmethod
    def connect(self, address, **kwargs):
        """Open the connection. `address` format is transport-specific
        (a VISA resource string, a COM port name, etc.)."""

    @abstractmethod
    def close(self):
        """Close the connection. Safe to call when already closed."""

    def is_connected(self):
        """True between a successful connect() and the next close()."""
        return self.connected

    def check_synchronised(self):
        """Raise if this transport is known to be out of step.

        For callers that are about to *write* and want the refusal
        anyway - an output-off on a poisoned link is deliberately still
        allowed (see write()), but a caller that would go on to trust a
        reading should ask first.
        """
        if self._desync_reason is not None:
            raise TransportDesynchronised(self._desync_message())

    # ---- raw I/O, implemented by subclasses ----
    @abstractmethod
    def _write(self, text):
        """Send one command. Line termination is the subclass's problem."""

    @abstractmethod
    def _read(self, timeout_s):
        """Read one reply, waiting at most `timeout_s` seconds."""

    # ---- public API used by drivers ----
    def write(self, text):
        """Send a command that expects no reply.

        **Still permitted on a desynchronised transport, deliberately.**
        A write never reads, so it cannot collect the previous
        command's answer - there is no reply for it to be one behind
        of. It either reaches the instrument or it does not.

        That asymmetry is what lets a poisoned session still be made
        safe: `output_off()` is a write on every driver in the fleet,
        so the sample can be de-energised over a link whose readings are
        no longer trustworthy. What a write cannot do is *confirm*
        anything, because confirming means querying. Callers must say
        "commanded" rather than "confirmed" when the link is out of
        step.

        A failed write does not desynchronise: nothing was expecting a
        reply, so nothing can arrive late.
        """
        with self.lock:
            if not self.connected:
                raise ConnectionError("Not connected")
            self._write(text)

    def query(self, text, timeout_s=3.0):
        """Send a command and return its reply as a string.

        Write and read happen under one lock so two threads can't
        interleave and end up reading each other's replies.

        Fails closed. Once an exchange has failed part-way, this
        transport can no longer tell its own replies from the previous
        command's, so it raises TransportDesynchronised rather than
        return a string that would be well-formed and wrong.

        *Any* failure of the exchange latches it, not only a timeout.
        Sorting timeouts from other read failures means matching on
        exception text, and that guess has been wrong here before; what
        matters is not why the read failed but that a command went out
        and its reply was never consumed. A command that never left will
        occasionally be counted as a desync it did not cause - a false
        positive costing one reconnect, chosen over the alternative,
        which costs a file full of plausible numbers.
        """
        with self.lock:
            if self._desync_reason is not None:
                raise TransportDesynchronised(self._desync_message())
            if not self.connected:
                raise ConnectionError("Not connected")
            try:
                self._write(text)
                return self._read(timeout_s)
            except Exception as exc:
                self._mark_desynchronised(exc, text)
                raise TransportDesynchronised(self._desync_message()) from exc

    # ---- identity ----
    def connection_key(self):
        """A stable string naming the *physical* connection behind this
        transport.

        Instrument ownership is keyed on this rather than on the driver
        object, because two driver instances can point at one
        instrument: open a second experiment window on the same GPIB
        address and Python sees two objects while the bench sees one
        box. Comparing objects would let both windows drive it at once.

        The default composes the transport type with whatever address it
        was connected to, which covers every transport here (`address`
        on VISA and miniSMU, `port` on serial). A transport with no
        address - `NullTransport` in demo mode - falls back to its own
        identity, so two demo windows are independent rather than
        contending for an imaginary shared instrument.

        Override only if a transport can reach one instrument under more
        than one spelling and needs to normalise them.
        """
        address = (getattr(self, "address", None)
                   or getattr(self, "port", None))
        kind = type(self).__name__
        if not address:
            return f"{kind}:@{id(self):x}"
        return f"{kind}:{str(address).strip().upper()}"

    # ---- discovery ----
    def clear(self):
        """Discard any pending reply. Returns True if a clear was sent.

        **Not a recovery path.** It used to be one: a timed-out query
        called clear() and, if it returned True, the session carried on
        as though resynchronised. That return value says a device-clear
        call did not raise - not that the stream is aligned again - so
        it was a check that passed whether or not the thing had worked.
        On the affected backend it returned False anyway, and the
        session ran on regardless.

        What it is good for is teardown: clearing before close leaves
        less for the *next* connection to trip over. Nothing may treat
        its return value as evidence that a desynchronised transport is
        usable again. Only a reconnect does that.

        The default is a no-op returning False, which is honest for
        transports where there is nothing to clear. Interfaces that
        support a device clear override it.
        """
        return False

    @staticmethod
    def list_available():
        """Return a list of connectable addresses, for populating a
        dropdown. Transports that can't enumerate return []."""
        return []
