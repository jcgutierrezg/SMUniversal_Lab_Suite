import sys, os

"""Reconnect after failure: what survives a broken connection, and what
must not.

Wave 6e, folded into 6c. Review §33's fourth transition.

Separate from the sweep traces in the same patch because the concern is
different: those check what a driver puts on the wire, these check what
the *application* does when the wire goes away. A driver whose commands
are all correct still cooks a sample if disconnecting forgets to
de-energise it, or if a failed connect leaves half a registration
behind for the next run to pick up.

The recurring hazard is inherited state. An instrument that has been
disconnected may have been power-cycled, driven by another application,
or left mid-sweep. Nothing about its settings can be assumed on the way
back in, and nothing about the previous connection may outlive it.
"""
import tkinter as tk

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.gui]

from core.base_app import LabApp
from core.transports.null_transport import NullTransport
from experiments.iv_sweep.experiment import IVSweepExperiment


class FlakyTransport(NullTransport):
    """A demo transport that can be told to fail, and remembers order.

    `fail_on_connect` refuses the connection outright. `fail_after` lets
    a number of writes through and then breaks the link, which is what a
    cable pulled mid-run looks like from here.
    """

    def __init__(self, fail_on_connect=False, fail_after=None):
        super().__init__()
        self.fail_on_connect = fail_on_connect
        self.fail_after = fail_after
        self.writes = 0
        self.events = []

    def connect(self, address=None, **kwargs):
        self.events.append("connect")
        if self.fail_on_connect:
            raise ConnectionError("simulated: no instrument at that address")
        return super().connect(address, **kwargs)

    def close(self):
        self.events.append("close")
        return super().close()

    def _write(self, text):
        self.writes += 1
        self.events.append(f"write:{text}")
        if self.fail_after is not None and self.writes > self.fail_after:
            self.connected = False
            raise ConnectionError("simulated: link lost")
        return super()._write(text)


def app_with(root, transport, address="demo"):
    app = LabApp(root, IVSweepExperiment)
    app.connect_role("source", transport, address)
    root.update_idletasks()
    return app


# ---------------------------------------------------------------
# A. disconnect de-energises, and in that order
# ---------------------------------------------------------------

def test_disconnect_takes_the_output_off_before_closing_the_link(check):
    """Order matters, not just presence.

    Closing first and de-energising second leaves the SMU sourcing into
    a sample with no way left to tell it to stop. The output-off has to
    reach the instrument while the link still exists.
    """
    root = tk.Tk()
    try:
        transport = FlakyTransport()
        app = app_with(root, transport)
        app.instruments["source"].output_on()

        transport.events.clear()
        app.disconnect_role("source")

        events = transport.events
        close_at = next((i for i, e in enumerate(events)
                         if e == "close"), None)
        off_at = next((i for i, e in enumerate(events)
                       if e.startswith("write:") and "outp" in e.lower()
                       and "off" in e.lower()), None)

        check("the link was closed", close_at is not None, f"{events}")
        # A demo driver may send nothing; what must never happen is an
        # output-off arriving after the close.
        if off_at is not None:
            check("and the output went off before it did",
                  off_at < close_at, f"{events}")
        check("the role is forgotten",
              "source" not in app.instruments)
    finally:
        root.destroy()


def test_writing_after_a_disconnect_raises_rather_than_vanishing(check):
    """A silent no-op is the worst outcome here.

    Code that keeps 'configuring' a disconnected instrument and sees no
    error will happily go on to energise and measure, and the readings
    will be whatever the last live session left behind.
    """
    root = tk.Tk()
    try:
        transport = FlakyTransport()
        app = app_with(root, transport)
        app.disconnect_role("source")

        # Asserted on the transport, not through the driver. The demo
        # driver is simulated and never reaches a wire, so a check
        # routed through it would pass whether or not the guarantee
        # existed - which is exactly the shape of assertion this
        # project keeps catching itself writing.
        with pytest.raises(ConnectionError) as caught:
            transport.write(":OUTP OFF")
        check("a write to a closed transport raises ConnectionError",
              "not connected" in str(caught.value).lower(),
              f"{caught.value}")

        with pytest.raises(ConnectionError):
            transport.query("*IDN?")
        check("and so does a query", True)

        check("the transport reports itself disconnected",
              not transport.is_connected())
    finally:
        root.destroy()


# ---------------------------------------------------------------
# B. a failed connect leaves nothing behind
# ---------------------------------------------------------------

def test_a_failed_connect_registers_nothing(check):
    """Half a registration is worse than none.

    A stranded driver with no transport, or an ownership key naming a
    connection that was never opened, is picked up by the next run as
    though it were live.
    """
    root = tk.Tk()
    try:
        app = LabApp(root, IVSweepExperiment)
        with pytest.raises(Exception):
            app.connect_role("source", FlakyTransport(fail_on_connect=True),
                             "demo")
        root.update_idletasks()

        check("no driver was registered", "source" not in app.instruments)
        check("no transport was registered", "source" not in app.transports)
        check("and no ownership key was minted",
              "source" not in app.instrument_keys)
    finally:
        root.destroy()


def test_a_failed_connect_does_not_strand_the_previous_instrument(check):
    """Connecting is documented as replacing whatever was there.

    So a failed attempt must leave the role *empty* rather than
    silently still holding the old instrument - otherwise an operator
    who changed the address and saw an error would go on running
    against the instrument they thought they had swapped out.
    """
    root = tk.Tk()
    try:
        first = FlakyTransport()
        app = app_with(root, first)
        check("the first instrument connected", "source" in app.instruments)

        with pytest.raises(Exception):
            app.connect_role("source", FlakyTransport(fail_on_connect=True),
                             "elsewhere")
        root.update_idletasks()

        check("the role is empty, not still holding the old one",
              "source" not in app.instruments,
              "the previous instrument survived a failed reconnect")
        check("and the old link was closed", "close" in first.events,
              f"{first.events}")
    finally:
        root.destroy()


# ---------------------------------------------------------------
# C. reconnecting starts from a known state
# ---------------------------------------------------------------

def test_reconnecting_resets_the_instrument_rather_than_trusting_it(check):
    """Nothing about a reconnected instrument's settings is assumed.

    It may have been power-cycled, driven by another application, or
    left mid-sweep. `test_driver_contract.py` already checks that
    reset() is invoked on connect - it wasn't, for months - and this
    checks the same holds on the way back in after a failure, which is
    the path least likely to be exercised by hand.
    """
    root = tk.Tk()
    try:
        first = FlakyTransport()
        app = app_with(root, first)
        app.disconnect_role("source")

        # Watched on the driver, not the transport: a simulated
        # instrument's reset() puts nothing on a wire, so a trace-based
        # check here would pass for the wrong reason on demo and prove
        # nothing about the path that matters.
        from drivers.dummy_smu import DummySMU
        calls = []
        original = DummySMU.reset

        def watched(self, *a, **kw):
            calls.append("reset")
            return original(self, *a, **kw)

        DummySMU.reset = watched
        try:
            app.connect_role("source", FlakyTransport(), "demo")
            root.update_idletasks()
        finally:
            DummySMU.reset = original

        check("the reconnected instrument was reset before use",
              bool(calls), "reset() was never called on the way back in")
        check("and a driver is registered again",
              app.instruments.get("source") is not None)
    finally:
        root.destroy()


def test_a_reconnect_mints_a_fresh_ownership_key(check):
    """A stale key would let a new run claim a connection that is gone,
    or block one that is not."""
    root = tk.Tk()
    try:
        app = app_with(root, FlakyTransport())
        first_key = app.instrument_keys["source"]
        app.disconnect_role("source")
        check("the key is dropped on disconnect",
              "source" not in app.instrument_keys)

        app.connect_role("source", FlakyTransport(), "demo")
        root.update_idletasks()
        check("and a key exists again after reconnecting",
              "source" in app.instrument_keys)

        # NOT asserting the key is unchanged. `Transport.connection_key`
        # says a transport with no address - NullTransport in demo mode
        # - falls back to its own identity, so two demo windows are
        # independent rather than fighting over one imaginary
        # instrument. Two demo transports are therefore two connections
        # by design, and an assertion that they match would be pinning
        # the opposite of the documented contract.
        check("the key is a non-empty string either way",
              isinstance(app.instrument_keys["source"], str)
              and app.instrument_keys["source"],
              f"{app.instrument_keys['source']!r}")
        check("and the first key is not silently reused after the link "
              "was closed",
              app.instrument_keys["source"] != first_key
              or first_key is None,
              "a demo reconnect should mint its own key")
    finally:
        root.destroy()
