"""
Exclusive instrument ownership, application-wide.

Why a transport lock is not enough
----------------------------------
`Transport` already serialises individual calls, so no two threads can
interleave the bytes of one command. That protects the *wire* and not
the *experiment*. Every call below is individually thread-safe and the
result is nonsense::

    Run A: configure voltage source
    Run B: configure current source
    Run A: set level
    Run B: output on
    Run A: measure

Run A measured a current source it did not configure, at a level it did
not set, with an output somebody else turned on. Nothing errored.

The unit that needs protecting is the whole measurement, from first
configuration command to verified shutdown. That is what a claim is.

The analogy that fits
---------------------
A hotel room key, not a queue ticket. While a run holds the key nobody
else gets in - not another experiment window, not a manual control, not
a reconnect button. The key goes back at checkout, which is after the
room has been tidied (output off, cleanup done), not at the moment the
guest decides to leave.

Keys are physical connections, not driver objects
-------------------------------------------------
Two `Keithley2450` instances pointing at the same GPIB address are two
Python objects and one instrument. Ownership is therefore keyed on the
connection - the VISA resource string, the COM port, the miniSMU device
address - so opening a second experiment window cannot create an
independent path to the same box.

Known limit, stated rather than hidden: the same instrument reached two
different ways (`COM3` through `SerialTransport` and `ASRL3::INSTR`
through VISA) produces two keys and would not collide. Detecting that
needs a per-transport address normaliser and nobody has been bitten by
it yet; if it ever happens, that is where the fix goes.

Scope
-----
The manager is a process-wide singleton (`default_ownership()`), because
"application-wide" means every experiment window in this process shares
one. Two *separate* Python processes cannot see each other's claims -
VISA itself will usually refuse the second connection, but that is the
instrument's doing, not this module's. Running two copies of the suite
against one bench remains a bad idea.
"""
from __future__ import annotations

import threading


class OwnershipError(RuntimeError):
    """Base for ownership faults. Messages are written for a dialog."""


class InstrumentBusy(OwnershipError):
    """Somebody else is using this instrument."""

    def __init__(self, key, owner, label=None):
        who = f"run '{owner}'" if owner else "another run"
        super().__init__(
            f"{label or key} is already in use by {who}.\n\n"
            f"Wait for it to finish, or cancel it, before starting another "
            f"measurement on the same instrument.")
        self.key = key
        self.owner = owner


class InstrumentBlocked(OwnershipError):
    """The instrument is in a state that must be cleared by a person.

    Raised for the two cases where carrying on would be unsafe or
    scientifically worthless: a mandatory reset that failed, and an
    output that could not be confirmed off. Both need somebody to look
    at the hardware and reconnect, which is deliberately not something
    software can do on its own.
    """

    def __init__(self, key, reason, label=None):
        super().__init__(
            f"{label or key} is blocked and cannot be used.\n\n{reason}\n\n"
            f"Reconnect the instrument once you have checked it.")
        self.key = key
        self.reason = reason


def key_for_transport(transport):
    """A stable ownership key for whatever `transport` is connected to.

    Prefers the transport's own `connection_key()`, which is part of the
    `Transport` contract. Falls back to reading the address off the
    object for anything duck-typed - the test fakes, mostly - and to the
    object's identity when there is no address at all, which makes two
    anonymous connections independent rather than accidentally the same
    instrument. That fallback is what keeps two demo-mode windows from
    blocking each other.
    """
    getter = getattr(transport, "connection_key", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            pass
    address = (getattr(transport, "address", None)
               or getattr(transport, "port", None))
    kind = type(transport).__name__
    if not address:
        return f"{kind}:@{id(transport):x}"
    return f"{kind}:{str(address).strip().upper()}"


class Claim:
    """One run's hold on one instrument. A context manager.

    Releasing is idempotent, so an explicit `release()` inside a run and
    the automatic one on the way out do not fight.
    """

    __slots__ = ("_manager", "key", "run_id", "label", "_released")

    def __init__(self, manager, key, run_id, label=None):
        self._manager = manager
        self.key = key
        self.run_id = run_id
        self.label = label or key
        self._released = False

    @property
    def released(self):
        return self._released

    def release(self):
        if self._released:
            return False
        self._released = True
        return self._manager._release(self.key, self.run_id)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False

    def __repr__(self):
        state = "released" if self._released else "held"
        return f"<Claim {self.label} by {self.run_id} ({state})>"


class InstrumentOwnership:
    """Who holds which instrument, and which instruments are blocked."""

    def __init__(self):
        self._lock = threading.RLock()
        self._owners = {}       # key -> [run_id, label, depth]
        self._blocks = {}       # key -> reason

    # ---- claiming ----
    def claim(self, key, run_id, label=None):
        """Take exclusive control of `key` for `run_id`.

        Raises `InstrumentBlocked` if the instrument needs human
        attention, and `InstrumentBusy` if another run holds it. The
        same run re-claiming the same instrument is allowed and counted,
        which is what lets one run drive two declared roles that happen
        to resolve to the same physical box.

        Use it as a context manager, or hand it to
        `RunContext.enter()` so release happens as part of run cleanup::

            session = run.enter(ownership.claim(key, run.run_id))
        """
        with self._lock:
            reason = self._blocks.get(key)
            if reason is not None:
                raise InstrumentBlocked(key, reason, label)
            held = self._owners.get(key)
            if held is not None and held[0] != run_id:
                raise InstrumentBusy(key, held[0], held[1])
            if held is None:
                self._owners[key] = [run_id, label or key, 1]
            else:
                held[2] += 1
            return Claim(self, key, run_id, label)

    def _release(self, key, run_id):
        with self._lock:
            held = self._owners.get(key)
            if held is None or held[0] != run_id:
                return False
            held[2] -= 1
            if held[2] <= 0:
                del self._owners[key]
            return True

    def force_release(self, key):
        """Drop any claim on `key`, whoever holds it.

        For disconnect and application shutdown only. A run that is
        still alive will find itself without a claim, which is why the
        normal path is `Claim.release()` from the run's own cleanup.
        """
        with self._lock:
            return self._owners.pop(key, None) is not None

    # ---- questions ----
    def owner_of(self, key):
        with self._lock:
            held = self._owners.get(key)
            return held[0] if held else None

    def is_owned(self, key):
        return self.owner_of(key) is not None

    def held_keys(self):
        with self._lock:
            return tuple(self._owners)

    # ---- blocking ----
    def block(self, key, reason):
        """Refuse all future claims on `key` until someone clears it.

        The two callers are a failed mandatory reset and an
        unverifiable output shutdown. Both mean the instrument is in an
        unknown state, and an unknown state is exactly what a
        measurement must not be built on.
        """
        with self._lock:
            self._blocks[key] = reason
        return reason

    def unblock(self, key):
        """Clear a block. True if there was one.

        Called on a *successful* reconnect - the point at which the
        instrument has been reset to a known state and somebody has
        plainly been at the bench.
        """
        with self._lock:
            return self._blocks.pop(key, None) is not None

    def is_blocked(self, key):
        with self._lock:
            return key in self._blocks

    def block_reason(self, key):
        with self._lock:
            return self._blocks.get(key)

    def blocked_keys(self):
        with self._lock:
            return tuple(self._blocks)

    # ---- diagnostics ----
    def snapshot(self):
        """Everything held and blocked, for a console line or a test."""
        with self._lock:
            return {
                "held": {k: {"run_id": v[0], "label": v[1], "depth": v[2]}
                         for k, v in self._owners.items()},
                "blocked": dict(self._blocks),
            }

    def reset(self):
        """Forget everything. Tests only - never call this from the app."""
        with self._lock:
            self._owners.clear()
            self._blocks.clear()


_DEFAULT = InstrumentOwnership()


def default_ownership():
    """The one manager every window in this process shares.

    `LabApp` takes an ownership manager as a constructor argument and
    falls back to this, so a test can inject a clean one and the
    application gets the shared instance without having to thread it
    through `main.py`.
    """
    return _DEFAULT
