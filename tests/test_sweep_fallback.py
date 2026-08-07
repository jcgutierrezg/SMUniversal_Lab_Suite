import sys, os

"""The software sweep fallback: any SMU can sweep, not just the 2611A.

The 2611A runs a sweep inside the instrument - one command, results in
its buffer, timing off its own clock. Most SMUs can't. Before this
fallback existed the IV experiment simply refused to run on a 2450,
which defeated the point of having a driver abstraction at all.

BaseSMU now implements the same three-part contract
(start_linear_sweep / sweep_points_ready / read_sweep) by stepping the
source point by point on a worker thread. This test drives a 2450 - a
real driver with no sweep of its own - over a fake transport, and
checks that the sweep comes back correct through the ordinary path.

The instrument is faked, not the sweep: the fallback code under test is
exactly the code that runs on the bench.
"""
import time
from core.transports.base import Transport
from drivers.keithley_2450 import Keithley2450
from drivers.keithley_2611a import Keithley2611A
from drivers.base_smu import BaseSMU

SAMPLE_OHM = 2200.0


class OhmicTransport(Transport):
    """A fake 2450 holding a plain resistor.

    Tracks the last sourced level from the SCPI it is sent, and answers
    measurements with the matching Ohm's-law pair. That is what lets the
    test assert the fallback sourced the levels it was supposed to,
    rather than merely returning the right number of points.
    """

    def __init__(self):
        super().__init__()
        self.sent = []
        self.connected = True
        self.level = 0.0
        self.mode = "voltage"

    def connect(self, address, **kw):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)
        upper = text.upper()
        if ":SOUR:FUNC" in upper:
            self.mode = "current" if "CURR" in upper else "voltage"
        # e.g. ':SOUR:VOLT:LEV 0.5' - take the trailing number
        if ":LEV" in upper:
            try:
                self.level = float(text.strip().split()[-1])
            except ValueError:
                pass

    def _read(self, timeout_s):
        last = self.sent[-1] if self.sent else ""
        if "IDN" in last.upper():
            return "KEITHLEY,MODEL 2450,1,1.0"
        if self.mode == "voltage":
            volts = self.level
            amps = volts / SAMPLE_OHM
        else:
            amps = self.level
            volts = amps * SAMPLE_OHM
        return f"{volts:.6E},{amps:.6E}"


# ---------------------------------------------------------------
# A. the capability report
# ---------------------------------------------------------------


def test_capability_reporting(check):
    check("2450 can sweep now", Keithley2450.supports_sweep())
    check("2450 reports software", Keithley2450.sweep_kind() == "software",
          Keithley2450.sweep_kind())
    check("2611A still reports hardware",
          Keithley2611A.sweep_kind() == "hardware", Keithley2611A.sweep_kind())
    check("2611A overrides the fallback",
          Keithley2611A.start_linear_sweep is not BaseSMU.start_linear_sweep)

    # ---------------------------------------------------------------
    # B. a voltage sweep on an instrument with no hardware sweep
    # ---------------------------------------------------------------


def test_software_voltage_sweep(check):
    transport = OhmicTransport()
    smu = Keithley2450(transport)
    smu.set_source_function("voltage")

    smu.start_linear_sweep("voltage", -1.0, 1.0, 11, 0.0)

    deadline = time.monotonic() + 20
    while smu.sweep_points_ready() < 11 and time.monotonic() < deadline:
        time.sleep(0.01)

    sourced, measured = smu.read_sweep(11)
    check("all points returned", len(measured) == 11, f"{len(measured)}/11")
    check("source values span the request",
          abs(sourced[0] + 1.0) < 1e-9 and abs(sourced[-1] - 1.0) < 1e-9,
          f"{sourced[0]:+.3f} .. {sourced[-1]:+.3f}")

    if len(measured) == 11:
        # Every point should sit on the sample's line. Compared relatively:
        # the fake transport formats readings to 6 significant figures, as
        # a real instrument would, so an absolute tolerance here would be
        # measuring the fake's string formatting rather than the sweep.
        worst = 0.0
        for volts, amps in zip(sourced, measured):
            expected = volts / SAMPLE_OHM
            if abs(expected) > 1e-15:
                worst = max(worst, abs(amps - expected) / abs(expected))
        check("readings follow Ohm's law", worst < 1e-5,
              f"worst {worst:.2e} relative")

        midpoint = sourced[5]
        check("midpoint is zero", abs(midpoint) < 1e-9, f"{midpoint:+.3e}")

    # ---------------------------------------------------------------
    # C. the other direction
    # ---------------------------------------------------------------


def test_software_current_sweep(check):
    transport = OhmicTransport()
    smu = Keithley2450(transport)
    smu.set_source_function("current")

    smu.start_linear_sweep("current", -1e-3, 1e-3, 9, 0.0)
    deadline = time.monotonic() + 20
    while smu.sweep_points_ready() < 9 and time.monotonic() < deadline:
        time.sleep(0.01)
    sourced, measured = smu.read_sweep(9)

    check("all points returned", len(measured) == 9, f"{len(measured)}/9")
    if len(measured) == 9:
        recovered = (measured[-1] - measured[0]) / (sourced[-1] - sourced[0])
        error = abs(recovered - SAMPLE_OHM) / SAMPLE_OHM
        check("resistance recovered", error < 1e-9,
              f"{recovered:.4f} Ω vs {SAMPLE_OHM:g} Ω")

    # ---------------------------------------------------------------
    # D. the sweep is genuinely asynchronous
    # ---------------------------------------------------------------


def test_start_does_not_block(check):
    transport = OhmicTransport()
    smu = Keithley2450(transport)
    smu.set_source_function("voltage")

    began = time.monotonic()
    smu.start_linear_sweep("voltage", 0.0, 1.0, 6, 0.05)   # ~0.30 s of settles
    returned_after = time.monotonic() - began

    # The contract says start returns immediately, exactly as the hardware
    # one does; the experiment's polling loop depends on it.
    check("start_linear_sweep returns immediately", returned_after < 0.10,
          f"returned after {returned_after*1000:.0f} ms")

    partial = smu.sweep_points_ready()
    check("points arrive progressively", partial < 6, f"{partial}/6 so far")

    sourced, measured = smu.read_sweep(6)
    check("read_sweep waits for the rest", len(measured) == 6,
          f"{len(measured)}/6")

    # ---------------------------------------------------------------
    # E. abort stops it early
    # ---------------------------------------------------------------


def test_abort_stops_sweep(check):
    transport = OhmicTransport()
    smu = Keithley2450(transport)
    smu.set_source_function("voltage")

    smu.start_linear_sweep("voltage", 0.0, 1.0, 40, 0.05)   # ~2 s if left alone
    time.sleep(0.12)
    smu.abort_sweep()
    began = time.monotonic()
    sourced, measured = smu.read_sweep(40)
    stopped_after = time.monotonic() - began

    check("aborted before finishing", len(measured) < 40, f"{len(measured)}/40")
    check("abort is prompt", stopped_after < 0.5,
          f"stopped {stopped_after*1000:.0f} ms after abort")
    check("points already taken are kept", len(measured) > 0,
          f"{len(measured)} point(s)")

    # ---------------------------------------------------------------
    # F. a broken instrument surfaces its error
    # ---------------------------------------------------------------


def test_instrument_error_surfaces(check):
    class BrokenTransport(OhmicTransport):
        def _read(self, timeout_s):
            raise IOError("instrument stopped responding")


    smu = Keithley2450(BrokenTransport())
    smu.set_source_function("voltage")
    smu.start_linear_sweep("voltage", 0.0, 1.0, 5, 0.0)

    raised = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            smu.sweep_points_ready()
            time.sleep(0.01)
    except Exception as exc:
        raised = exc

    check("polling raises the instrument's error", raised is not None,
          type(raised).__name__ if raised else "nothing raised")
    check("error is not swallowed into a silent empty sweep",
          isinstance(raised, IOError), str(raised)[:50])
