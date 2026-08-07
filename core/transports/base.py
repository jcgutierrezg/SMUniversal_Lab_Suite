"""
The transport contract.

A transport knows *how* bytes travel (GPIB, USB, TCP socket, raw serial).
It does NOT know what they mean - no SCPI, no TSP, no instrument concepts
at all. Drivers sit one layer up and decide *what* to send.

Keeping these separate is what lets a Keithley 2450 move from GPIB to a
serial cable without touching its driver, and lets a Seeed Xiao share the
same plumbing as an SMU.
"""
import threading
from abc import ABC, abstractmethod


class Transport(ABC):
    """Base class for all transports. Subclasses implement _write/_read
    and the connect/close pair; the locking and the query() convenience
    are handled here so every transport behaves the same under threads."""

    def __init__(self):
        self.lock = threading.Lock()
        self.connected = False

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

    # ---- raw I/O, implemented by subclasses ----
    @abstractmethod
    def _write(self, text):
        """Send one command. Line termination is the subclass's problem."""

    @abstractmethod
    def _read(self, timeout_s):
        """Read one reply, waiting at most `timeout_s` seconds."""

    # ---- public API used by drivers ----
    def write(self, text):
        """Send a command that expects no reply."""
        with self.lock:
            if not self.connected:
                raise ConnectionError("Not connected")
            self._write(text)

    def query(self, text, timeout_s=3.0):
        """Send a command and return its reply as a string.

        Write and read happen under one lock so two threads can't
        interleave and end up reading each other's replies.
        """
        with self.lock:
            if not self.connected:
                raise ConnectionError("Not connected")
            self._write(text)
            return self._read(timeout_s)

    # ---- discovery ----
    def clear(self):
        """Try to resynchronise after a failed query. Returns True if a
        resync was actually performed.

        A timed-out read is not a self-contained failure. The
        instrument may still be preparing a reply, and once it arrives
        it sits in the output buffer waiting - so the *next* query
        writes a new command and reads the *previous* command's answer.
        Every reading after that point is one command out of step, and
        nothing about the numbers themselves says so.

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
