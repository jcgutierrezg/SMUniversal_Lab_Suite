"""
Null transport - the wire that isn't there.

Exists so demo mode flows through exactly the same connect path as real
hardware: open a transport, ask *IDN?, look up a driver. It answers the
identification query with a dummy ID string, which the registry maps to
DummySMU, and discards everything else.

Doing it this way rather than special-casing demo mode in the app means
the demo exercises the real connection, threading, and panel-refresh
code. A bug in that path shows up on the bench *and* at your desk,
instead of only on the bench.
"""
from .base import Transport

DUMMY_IDN = "LAB SUITE,MODEL DUMMY SMU,SIMULATED,1.0"


class NullTransport(Transport):
    """Always connects, never sends anything anywhere."""

    def __init__(self):
        super().__init__()
        self.sent = []      # kept so tests can assert on command order

    def connect(self, address=None, **kwargs):
        """Succeeds unconditionally. `address` is ignored - there's
        nothing to address."""
        self._begin_session()
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)

    def _read(self, timeout_s):
        """Only *IDN? gets a meaningful answer. Everything else returns
        an empty string, because DummySMU overrides the methods that
        would otherwise need a reply."""
        last = self.sent[-1] if self.sent else ""
        if "IDN" in last.upper():
            return DUMMY_IDN
        return ""

    @staticmethod
    def list_available():
        """One pseudo-address, so the dropdown isn't empty."""
        return ["<simulated sample>"]
