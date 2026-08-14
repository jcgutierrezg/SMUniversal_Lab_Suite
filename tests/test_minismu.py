import pytest

pytestmark = [pytest.mark.gui]

import sys, os

"""The Undalogic miniSMU MS01 driver and its adapter transport.

This one is different from every other driver test here: there is no
command dialect to assert, because the driver doesn't send commands. It
calls methods on the vendor's library. So the fake is a fake *library
object*, and what gets checked is which methods are called, in which
order, and what the driver does with the answers.

Four things are worth testing and only one is the happy path.

1. **reset() must not reboot the instrument.** `minismu_py.SMU.reset()`
   sends `*RST`, which reboots the MS01 and invalidates the connection -
   and `LabApp` calls `driver.reset()` on every connect. Wire the
   obvious thing through and connecting to a miniSMU kills the
   connection it just opened, every time, with a symptom that looks like
   a cable fault. The fake raises if `reset()` is ever called.

2. **Firmware gates capability.** Onboard sweeps need 1.3.4+, 4-wire
   needs 1.4.3+, and an unparseable identity must fall to the safe side
   rather than optimistically claiming both.

3. **Sweep kind varies per run.** The onboard sweep is voltage-only, so
   the same instrument is "hardware" for a voltage sweep and "software"
   for a current one. Both have to work and the CSV has to say which.

4. **The NPLC control is a translation.** The instrument has no NPLC,
   only an oversampling ratio, so what the file records must be the
   window actually integrated over rather than the number typed in.
"""
import math
import time

from core.transports.minismu_transport import MiniSMUTransport, _version_tuple
from drivers.registry import driver_for_idn
from drivers.undalogic_minismu import (
    UndalogicMiniSMU, FIRMWARE_ONBOARD_SWEEP, FIRMWARE_FOUR_WIRE,
    MAX_SWEEP_POINTS, MAX_DWELL_MS, SAMPLE_RATE_HZ, LINE_FREQUENCY_HZ,
    MAX_USABLE_OSR)
from drivers.keithley_2450 import Keithley2450

SAMPLE_OHM = 470.0


class FakeStatus:
    def __init__(self, status, current_point, total_points):
        self.status = status
        self.current_point = current_point
        self.total_points = total_points
        self.elapsed_ms = 0
        self.estimated_remaining_ms = 0


class FakePoint:
    def __init__(self, voltage, current):
        self.timestamp = 0
        self.voltage = voltage
        self.current = current


class RebootedError(RuntimeError):
    """Raised by the fake when *RST is sent - which on this instrument
    reboots the box and drops the connection."""


class FakeClient:
    """Stands in for `minismu_py.SMU`, with a resistor on channel 1."""

    def __init__(self, firmware="1.5.0"):
        self.firmware = firmware
        self.calls = []
        self.mode = "FVMI"
        self.voltage = 0.0
        self.current = 0.0
        self.current_protection = 0.18
        self.voltage_protection = 12.0
        self.output = False
        self.autorange = True
        self.current_range_limit = None
        self.voltage_range = "AUTO"
        self.osr = None
        self.four_wire = False
        self.sweep = None
        self.sweep_started = False
        # Some firmware reports the last point index rather than a
        # count once a sweep completes; flip this to model that.
        self.report_zero_on_complete = False
        self.closed = False

    def _log(self, name, *args):
        self.calls.append((name, args))

    # -- identity --
    def get_identity(self):
        self._log("get_identity")
        if self.firmware is None:
            return "Undalogic,miniSMU MS01,SN0001"
        return f"Undalogic,miniSMU MS01,SN0001,v{self.firmware}"

    def reset(self):
        self._log("reset")
        raise RebootedError(
            "*RST reboots the miniSMU and invalidates this connection")

    def close(self):
        self.closed = True

    # -- source --
    def set_mode(self, channel, mode):
        assert mode in ("FVMI", "FIMV")
        self._log("set_mode", channel, mode)
        self.mode = mode

    def set_voltage(self, channel, voltage):
        self._log("set_voltage", channel, voltage)
        self.voltage = float(voltage)

    def set_current(self, channel, current):
        self._log("set_current", channel, current)
        self.current = float(current)

    def set_current_protection(self, channel, limit):
        self._log("set_current_protection", channel, limit)
        self.current_protection = float(limit)

    def set_voltage_protection(self, channel, limit):
        self._log("set_voltage_protection", channel, limit)
        self.voltage_protection = float(limit)

    # -- ranging --
    def set_autorange(self, channel, enabled):
        self._log("set_autorange", channel, enabled)
        self.autorange = bool(enabled)

    def set_current_range_by_limit(self, channel, max_current,
                                   disable_autorange=True):
        self._log("set_current_range_by_limit", channel, max_current)
        self.autorange = not disable_autorange
        self.current_range_limit = float(max_current)
        return 4

    def set_voltage_range(self, channel, range_type):
        assert range_type in ("AUTO", "LOW", "HIGH")
        self._log("set_voltage_range", channel, range_type)
        self.voltage_range = range_type

    # -- measurement --
    def set_oversampling_ratio(self, channel, osr):
        if not 0 <= osr <= 15:
            raise ValueError("OSR must be between 0 and 15")
        self._log("set_oversampling_ratio", channel, osr)
        self.osr = osr

    def measure_voltage_and_current(self, channel):
        self._log("measure_voltage_and_current", channel)
        if not self.output:
            return (0.0, 0.0)
        if self.mode == "FVMI":
            volts = self.voltage
            amps = volts / SAMPLE_OHM
            if abs(amps) > self.current_protection:
                amps = math.copysign(self.current_protection, amps)
                volts = amps * SAMPLE_OHM
        else:
            amps = self.current
            volts = amps * SAMPLE_OHM
            if abs(volts) > self.voltage_protection:
                volts = math.copysign(self.voltage_protection, volts)
                amps = volts / SAMPLE_OHM
        return (volts, amps)

    # -- output --
    def enable_channel(self, channel):
        self._log("enable_channel", channel)
        self.output = True

    def disable_channel(self, channel):
        self._log("disable_channel", channel)
        self.output = False

    # -- four wire --
    def enable_fourwire_mode(self):
        self._log("enable_fourwire_mode")
        self.four_wire = True

    def disable_fourwire_mode(self):
        self._log("disable_fourwire_mode")
        self.four_wire = False

    def get_fourwire_mode(self):
        self._log("get_fourwire_mode")
        return self.four_wire

    # -- sweeps --
    def configure_iv_sweep(self, channel, start_voltage, end_voltage, points,
                           dwell_ms, auto_enable=True, output_format="CSV"):
        if not 1 <= points <= 1000:
            raise ValueError("Points must be between 1 and 1000")
        if not 0 <= dwell_ms <= 10000:
            raise ValueError("Dwell time must be between 0 and 10000 ms")
        self._log("configure_iv_sweep", channel, start_voltage, end_voltage,
                  points, dwell_ms, auto_enable, output_format)
        self.sweep = (start_voltage, end_voltage, points)
        self.sweep_started = False

    def execute_sweep(self, channel):
        self._log("execute_sweep", channel)
        self.sweep_started = True

    def abort_sweep(self, channel):
        self._log("abort_sweep", channel)
        self.sweep_started = False

    def get_sweep_status(self, channel):
        if not self.sweep_started:
            return FakeStatus("IDLE", 0, self.sweep[2] if self.sweep else 0)
        total = self.sweep[2]
        return FakeStatus("COMPLETED",
                          0 if self.report_zero_on_complete else total, total)

    def get_sweep_data_csv(self, channel):
        self._log("get_sweep_data_csv", channel)
        start, stop, points = self.sweep
        step = (stop - start) / (points - 1)
        out = []
        for i in range(points):
            volts = start + step * i
            amps = volts / SAMPLE_OHM
            if abs(amps) > self.current_protection:
                amps = math.copysign(self.current_protection, amps)
                volts = amps * SAMPLE_OHM
            out.append(FakePoint(volts, amps))
        return out

    def get_temperatures(self):
        return (30.0, 31.5, 29.0)


class FakeTransport(MiniSMUTransport):
    """The real adapter, with the library object swapped for a fake.

    Subclassing rather than reimplementing so that `query('*IDN?')`, the
    address parsing and the lifecycle under test are the ones that ship.
    """

    def __init__(self, firmware="1.5.0", network=False):
        super().__init__()
        self._firmware = firmware
        self._network = network

    def connect(self, address, **kwargs):
        self.client = FakeClient(self._firmware)
        self.address = address
        self.is_network = self._network or self.looks_like_host(address)
        self.connected = True


def make(firmware="1.5.0", network=False, **kw):
    transport = FakeTransport(firmware, network)
    transport.connect("192.168.1.106" if network else "COM3")
    smu = UndalogicMiniSMU(transport, **kw)
    smu.identify()
    return transport, smu


def fit_resistance(sourced, measured, mode):
    n = len(sourced)
    mean_x = sum(sourced) / n
    mean_y = sum(measured) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(sourced, measured))
    den = sum((x - mean_x) ** 2 for x in sourced)
    slope = num / den
    return (1.0 / slope) if mode == "voltage" else slope


def run_software_sweep(smu, mode, start, stop, points, timeout=15.0):
    smu.start_linear_sweep(mode, start, stop, points, 0.0)
    deadline = time.monotonic() + timeout
    while smu.sweep_points_ready() < points and time.monotonic() < deadline:
        time.sleep(0.005)
    return smu.read_sweep(points)


# ---------------------------------------------------------------
# A. the adapter transport
# ---------------------------------------------------------------


def test_transport(check):
    global smu
    check("a serial port is not read as a host",
          not MiniSMUTransport.looks_like_host("COM3")
          and not MiniSMUTransport.looks_like_host("/dev/ttyACM0"))
    check("a dotted quad is", MiniSMUTransport.looks_like_host("192.168.1.106"))
    check("with an explicit port too",
          MiniSMUTransport.looks_like_host("192.168.1.106:3333"))
    check("but not something that merely has dots in it",
          not MiniSMUTransport.looks_like_host("smu.lab.local"),
          "narrow on purpose - guessing wrong opens a socket to 'COM3'")

    t, smu = make()
    check("*IDN? is answered, so the registry can auto-detect",
          "miniSMU" in t.query("*IDN?"))
    raised = False
    try:
        t.query("MEAS1:VOLT?")
    except NotImplementedError:
        raised = True
    check("any other query raises rather than returning something plausible",
          raised)
    raised = False
    try:
        t.write("SOUR1:VOLT 1")
    except NotImplementedError:
        raised = True
    check("and text writes raise too", raised,
          "a silent no-op would be a driver configuring an instrument that "
          "never heard it")
    check("library version comparison works",
          _version_tuple("0.4.0") == (0, 4, 0)
          and _version_tuple("0.3.2") < (0, 4, 0))

    # ---------------------------------------------------------------
    # A2. the driver refuses a transport it cannot drive
    # ---------------------------------------------------------------


def test_wrong_transport_is_refused(check):
    # The confusing failure this prevents: the MS01 answers *IDN? over a
    # plain serial connection, so opening it with SerialTransport succeeds,
    # auto-detection correctly says "miniSMU", and the driver is handed a
    # transport it cannot use. The first method call then reported "miniSMU
    # transport is not connected" - about a transport that was connected,
    # working, and simply the wrong kind.
    from core.transports.serial_transport import SerialTransport
    from core.transports.null_transport import NullTransport

    for wrong in (SerialTransport, NullTransport):
        message = ""
        try:
            UndalogicMiniSMU(wrong())
        except TypeError as exc:
            message = str(exc)
        check(f"a {wrong.__name__} is refused at construction", bool(message))
        check(f"  ...and the message names the fix",
              "--transport minismu" in message and "MiniSMUTransport" in message,
              f"got {message[:80]}")

    check("the right transport is accepted",
          isinstance(make()[1], UndalogicMiniSMU))

    # ---------------------------------------------------------------
    # B. identification and firmware
    # ---------------------------------------------------------------


def test_identification(check):
    idn = "Undalogic,miniSMU MS01,SN0001,v1.5.0"
    check("*IDN? resolves to the miniSMU driver",
          driver_for_idn(idn) is UndalogicMiniSMU, f"got {driver_for_idn(idn)}")
    check("a 2450 reply still resolves to the 2450",
          driver_for_idn("KEITHLEY INSTRUMENTS,MODEL 2450,04412345,1.7.12b")
          is Keithley2450)
    check("the firmware version is parsed out of the identity",
          smu.firmware() == (1, 5, 0), f"{smu.firmware()}")

    _, old_fw = make("1.2.0")
    check("an older firmware parses too", old_fw.firmware() == (1, 2, 0))
    _, no_fw = make(None)
    check("an unrecognisable identity gives None rather than a guess",
          no_fw.firmware() is None)

    # The real reply carries TWO version-shaped tokens: a hardware revision
    # in the model field and the firmware at the end. The firmware is the
    # last one.
    real = "Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)"
    check("the bench identity parses to the firmware, not the hardware rev",
          UndalogicMiniSMU._parse_firmware(real) == (1, 4, 6),
          f"{UndalogicMiniSMU._parse_firmware(real)}")
    check("and it still resolves to this driver",
          driver_for_idn(real) is UndalogicMiniSMU)

    # A three-part hardware revision would have been grabbed by a
    # first-match parse, reading as firmware 1.1.2 - below both feature
    # gates, so the onboard sweep and 4-wire would have switched
    # themselves off on a capable instrument with nothing looking wrong.
    hypothetical = ("Undalogic Ltd,miniSMU MS01 v1.1.2,lunar-tuvok-7966,"
                    "v1.4.6(6b82396)")
    check("a three-part hardware revision does not masquerade as firmware",
          UndalogicMiniSMU._parse_firmware(hypothetical) == (1, 4, 6),
          f"{UndalogicMiniSMU._parse_firmware(hypothetical)} - the LAST "
          f"version token is the firmware")

    # and the build suffix must not be mistaken for a fourth component
    check("a git hash after the version is ignored",
          UndalogicMiniSMU._parse_firmware("x,y,z,v2.0.1(deadbeef)")
          == (2, 0, 1))

    # ---------------------------------------------------------------
    # C. reset() MUST NOT reboot the instrument
    # ---------------------------------------------------------------


def test_reset_does_not_reboot(check):
    # The app calls driver.reset() on every connect. If that reached
    # client.reset(), the MS01 would reboot and this connection would die
    # immediately - looking exactly like a bad cable.
    t2, smu2 = make()
    t2.client.four_wire = True
    smu2.reset()
    names = [c[0] for c in t2.client.calls]
    check("client.reset() is never called", "reset" not in names,
          "*RST reboots the MS01 and invalidates the connection")
    check("the output is dropped", "disable_channel" in names)
    check("autoranging is restored", ("set_autorange", (1, True)) in t2.client.calls)
    check("the voltage range goes back to AUTO",
          ("set_voltage_range", (1, "AUTO")) in t2.client.calls)
    check("a 4-wire mode left over from a previous session is cleared",
          not t2.client.four_wire,
          "otherwise it silently commandeers channel 2")
    # And the escape hatch exists, clearly labelled.
    raised = False
    try:
        smu2.reboot()
    except RebootedError:
        raised = True
    check("reboot() is the thing that really sends *RST", raised)

    # older firmware: no 4-wire query at all
    t3, smu3 = make("1.2.0")
    smu3.reset()
    check("no 4-wire call on firmware that has no 4-wire",
          not any(c[0].endswith("fourwire_mode") for c in t3.client.calls))

    # ---------------------------------------------------------------
    # D. firmware gates capability
    # ---------------------------------------------------------------


def test_firmware_gating(check):
    global ancient, new
    _, new = make("1.5.0")
    _, mid = make("1.3.4")
    _, ancient = make("1.2.0")
    _, unknown = make(None)

    check("onboard sweep available on 1.5.0", new.sweep_kind() == "hardware")
    check(f"available exactly at {'.'.join(str(n) for n in FIRMWARE_ONBOARD_SWEEP)}",
          mid.sweep_kind() == "hardware")
    check("not on 1.2.0", ancient.sweep_kind() == "software")
    check("and an unknown version falls to the safe side",
          unknown.sweep_kind() == "software",
          "an unparseable identity is not evidence of a recent build")

    check("4-wire declared on 1.5.0", new.supports_remote_sense_control())
    check("not on 1.3.4 - it needs "
          f"{'.'.join(str(n) for n in FIRMWARE_FOUR_WIRE)}",
          not mid.supports_remote_sense_control())

    raised = False
    try:
        mid.set_remote_sense(True)
    except NotImplementedError as exc:
        raised = "firmware" in str(exc).lower()
    check("asking for 4-wire on old firmware explains why it can't", raised)

    t4, four = make("1.4.3")
    four.set_remote_sense(True)
    check("enabling 4-wire on new enough firmware works", t4.client.four_wire)
    four.set_remote_sense(True)
    check("and setting it twice doesn't send a second command",
          sum(1 for c in t4.client.calls if c[0] == "enable_fourwire_mode") == 1)
    four.set_remote_sense(False)
    check("turning it off restores independent channels",
          not t4.client.four_wire)

    # ---------------------------------------------------------------
    # E. the onboard sweep
    # ---------------------------------------------------------------


def test_onboard_sweep(check):
    t5, smu5 = make()
    smu5.set_source_function("voltage")
    smu5.set_current_limit(0.1)
    smu5.output_on()
    check("a voltage sweep reports hardware", smu5.sweep_kind() == "hardware")

    smu5.start_linear_sweep("voltage", -1.0, 1.0, 11, 0.05)
    config = [c for c in t5.client.calls if c[0] == "configure_iv_sweep"][0]
    check("the sweep was configured on the instrument", t5.client.sweep is not None)
    check("delay seconds become dwell milliseconds", config[1][4] == 50,
          f"dwell was {config[1][4]}")
    check("auto output control is OFF so the experiment keeps the output",
          config[1][5] is False,
          "the periodic bias-hold path needs the output to stay on across "
          "the standby-to-sweep boundary")
    check("CSV format is requested, not JSON", config[1][6] == "CSV",
          "CSV fits ~175 points over TCP where JSON manages ~95")
    check("the instrument was told to run it", t5.client.sweep_started)
    check("all points report ready", smu5.sweep_points_ready() == 11)

    sourced, measured = smu5.read_sweep(11)
    check("11 points come back", len(measured) == 11, f"got {len(measured)}")
    r = fit_resistance(sourced, measured, "voltage")
    check("and recover the resistor", abs(r - SAMPLE_OHM) / SAMPLE_OHM < 5e-4,
          f"{r:.4f} ohm vs {SAMPLE_OHM}")

    # The firmware quirk: COMPLETED with a point index of 0.
    t6, smu6 = make()
    t6.client.report_zero_on_complete = True
    smu6.set_source_function("voltage")
    smu6.start_linear_sweep("voltage", 0.0, 1.0, 5, 0.0)
    check("a COMPLETED sweep reports its full count even if the counter "
          "reads zero", smu6.sweep_points_ready() == 5,
          "otherwise the experiment polls until it times out on a sweep "
          "that already finished")

    # bounds the library enforces, reported before anything is configured
    t7, smu7 = make()
    smu7.set_source_function("voltage")
    # The library validates these too, so a driver-side check only earns
    # its place if it fails *better*: the library says "Points must be
    # between 1 and 1000", which doesn't say what was asked for or what to
    # do instead. So the message is what gets asserted, not just the raise.
    for label, args, must_mention in (
            (f"more than {MAX_SWEEP_POINTS} points",
             ("voltage", 0.0, 1.0, MAX_SWEEP_POINTS + 1, 0.0),
             (str(MAX_SWEEP_POINTS), str(MAX_SWEEP_POINTS + 1))),
            (f"a dwell beyond {MAX_DWELL_MS / 1000:g} s",
             ("voltage", 0.0, 1.0, 10, 11.0),
             ("11", "software sweep"))):
        message = ""
        try:
            smu7.start_linear_sweep(*args)
        except ValueError as exc:
            message = str(exc)
        check(f"{label} is refused", bool(message))
        check(f"  ...and the message says what was asked for and what to do",
              all(fragment in message for fragment in must_mention),
              f"got {message!r}")
    check("and nothing was configured on the instrument",
          t7.client.sweep is None
          and not any(c[0] == "configure_iv_sweep" for c in t7.client.calls))

    # ---------------------------------------------------------------
    # F. current sweeps fall back to software, on the same instrument
    # ---------------------------------------------------------------


def test_current_sweep_falls_back(check):
    t8, smu8 = make()
    smu8.set_source_function("current")
    check("a current sweep reports software on the same instrument",
          smu8.sweep_kind() == "software",
          "the onboard sweep is voltage-only")
    smu8.set_voltage_limit(10.0)
    smu8.output_on()
    sourced8, measured8 = run_software_sweep(smu8, "current", -1e-3, 1e-3, 9)
    check("the run still completes", len(measured8) == 9, f"{len(measured8)}")
    r8 = fit_resistance(sourced8, measured8, "current")
    check("and recovers the resistor", abs(r8 - SAMPLE_OHM) / SAMPLE_OHM < 5e-4,
          f"{r8:.4f} ohm")
    check("the onboard sweep was never configured",
          not any(c[0] == "configure_iv_sweep" for c in t8.client.calls))
    check("switching back to voltage restores the hardware sweep",
          (smu8.set_source_function("voltage") or smu8.sweep_kind()) == "hardware")

    # on old firmware even a voltage sweep goes the software route
    t9, smu9 = make("1.2.0")
    smu9.set_source_function("voltage")
    smu9.set_current_limit(0.1)
    smu9.output_on()
    sourced9, measured9 = run_software_sweep(smu9, "voltage", -1.0, 1.0, 9)
    check("old firmware sweeps in software and still works",
          len(measured9) == 9 and not any(
              c[0] == "configure_iv_sweep" for c in t9.client.calls))

    # ---------------------------------------------------------------
    # G. NPLC is a translation, and the file records the truth
    # ---------------------------------------------------------------


def test_nplc_to_osr(check):
    check("declares NPLC support", UndalogicMiniSMU.supports_nplc())
    low, high = UndalogicMiniSMU.NPLC_RANGE
    # The rate is MEASURED, not documented: the spec sheet's 1000 S/s is the
    # streaming rate, and using it overstated every integration time
    # eighteenfold. Bench figures: 6.4 ms at OSR 0 (1 sample) and 34.4 ms at
    # OSR 9 (512 samples) on the same port, so 511 extra samples cost 28 ms.
    # Measured in a SINGLE run: 6.2 ms at OSR 0 (1 sample) and 87.6 ms at
    # OSR 13 (8192 samples), so 8191 extra samples in 81.4 ms.
    #
    # This value has been wrong twice. 1000 S/s came from the spec sheet and
    # is the streaming rate. 18200 S/s came from two timings taken in
    # different sessions - and per-reading overhead on this instrument
    # varies from 6 ms to 29 ms between sessions, so most of what looked
    # like integration was overhead. Two timings are only comparable when
    # the constant term is the same, which means the same run.
    check("the sample rate is the measured one, not the spec sheet's",
          SAMPLE_RATE_HZ > 50000,
          f"{SAMPLE_RATE_HZ} S/s")
    check("and it predicts the observed reading time",
          abs((6.2 + 8192 / SAMPLE_RATE_HZ * 1000) - 87.6) < 3.0,
          f"predicted {6.2 + 8192 / SAMPLE_RATE_HZ * 1000:.1f} ms at OSR 13, "
          f"observed 87.6 ms")
    check("the range is derived from the OSR ladder",
          abs(low - 1 / SAMPLE_RATE_HZ * LINE_FREQUENCY_HZ) < 1e-12
          and abs(high - 2 ** 15 / SAMPLE_RATE_HZ * LINE_FREQUENCY_HZ) < 1e-12,
          f"({low}, {high})")
    check("the whole hardware OSR range is usable",
          UndalogicMiniSMU.osr_for_nplc(high) == 15,
          "16.4 PLC is the instrument's own ceiling, not a cap we chose")
    check("and asking for more than it can do clamps rather than raising",
          abs(UndalogicMiniSMU.clamp_nplc(100) - high) < 1e-9,
          f"{UndalogicMiniSMU.clamp_nplc(100)} - and the clamped value is "
          f"what lands in the file")

    for nplc in (0.01, 0.1, 1.0, 10.0):
        osr = UndalogicMiniSMU.osr_for_nplc(nplc)
        window = 2 ** osr / SAMPLE_RATE_HZ * LINE_FREQUENCY_HZ
        check(f"NPLC {nplc:g} maps to the nearest achievable window",
              abs(UndalogicMiniSMU.clamp_nplc(nplc) - window) < 1e-9
              and 0 <= osr <= MAX_USABLE_OSR,
              f"OSR {osr} -> {window:.4g} PLC")

    check("clamp returns what the instrument will actually integrate over, "
          "not what was asked for",
          abs(UndalogicMiniSMU.clamp_nplc(1.0) - 1.0) > 1e-6,
          f"{UndalogicMiniSMU.clamp_nplc(1.0)} PLC")
    check("which is a true statement about the window",
          abs(UndalogicMiniSMU.clamp_nplc(1.0) / LINE_FREQUENCY_HZ
              - 2 ** UndalogicMiniSMU.osr_for_nplc(1.0) / SAMPLE_RATE_HZ)
          < 1e-12)
    check("a huge request clamps to the ceiling",
          abs(UndalogicMiniSMU.clamp_nplc(10000) - high) < 1e-9)
    check("a tiny one clamps to the floor",
          abs(UndalogicMiniSMU.clamp_nplc(1e-9) - low) < 1e-9)

    t10, smu10 = make()
    smu10.set_nplc(1.0)
    expected_osr = UndalogicMiniSMU.osr_for_nplc(1.0)
    check("the OSR reaches the instrument",
          ("set_oversampling_ratio", (1, expected_osr)) in t10.client.calls,
          f"{[c for c in t10.client.calls if c[0] == 'set_oversampling_ratio']}")
    check("and is readable back", smu10.oversampling_ratio() == expected_osr)

    # ---------------------------------------------------------------
    # H. limits
    # ---------------------------------------------------------------


def test_limits(check):
    from core.limits import LimitError

    limits = UndalogicMiniSMU.LIMITS
    for label, kwargs, should_pass in (
            ("12 V at 100 mA", dict(voltage=12.0, current=0.1), True),
            ("12 V at 180 mA (2.16 W, over the 2.1 W ceiling)",
             dict(voltage=12.0, current=0.18), False),
            ("15 V", dict(voltage=15.0), False),
            ("200 mA", dict(current=0.2), False)):
        ok = True
        try:
            limits.validate_source_point(**kwargs)
        except LimitError:
            ok = False
        check(f"{label} is {'allowed' if should_pass else 'refused'}",
              ok == should_pass)

    # The 12 V adapter is a stated requirement, not a mode to detect, so
    # the limits are the full envelope unconditionally and the warning
    # lives in the console note (checked below).
    check("the full 180 mA envelope is declared",
          abs(UndalogicMiniSMU.LIMITS.max_current - 0.18) < 1e-12)
    check("and there is no bus-power option to get wrong",
          not hasattr(UndalogicMiniSMU(FakeTransport(), channel=1),
                      "usb_powered"))

    # ---------------------------------------------------------------
    # I. the connect-time note
    # ---------------------------------------------------------------


def test_sweep_note(check):
    note = new.sweep_note().lower()
    # Leads with the power requirement, because it is the one thing about
    # this instrument that software cannot check and that silently changes
    # what a sweep means when it is wrong.
    check("states the 12 V adapter requirement first",
          note.startswith("requires the 12 v dc adapter"), note[:60])
    check("and names the bus-power ceiling it is warning about",
          "50 ma per channel" in note)
    check("names the firmware", "1.5.0" in note)
    check("says onboard sweeps are available", "onboard" in note)
    check("the OSR itself is reported, being the only certain part",
          "oversampling ratio" in new.sweep_note().lower()
          or "oversampling ratio" in (lambda: (new.set_nplc(1),
                                               new.sweep_note())[1])().lower(),
          "the NPLC equivalent rests on a scale the hardware does not follow")
    check("warns that oversampling is not mains-synchronised",
          "not synchronised to the mains" in note,
          "this is the caveat that stops a miniSMU dataset being compared "
          "naively with a Keithley one")
    old_note = ancient.sweep_note().lower()
    check("and on old firmware it says what is missing",
          "software sweep" in old_note and "4-wire" in old_note)
    for label, driver in (("new firmware", new), ("old firmware", ancient)):
        check(f"the power requirement is stated regardless of {label}",
              "12 v dc adapter" in driver.sweep_note().lower())
    _, wifi = make(network=True)
    check("a WiFi connection warns about the sweep truncation limit",
          "wifi" in wifi.sweep_note().lower()
          and "truncate" in wifi.sweep_note().lower())

    # ---------------------------------------------------------------
    # J. end to end through the real experiment
    # ---------------------------------------------------------------


def test_end_to_end_through_the_experiment(check):
    import tkinter as tk

    from core.base_app import LabApp
    from experiments.iv_sweep.experiment import IVSweepExperiment
    import experiments.iv_sweep.experiment as iv_experiment
    import experiments.base_experiment as base_experiment
    import core.base_app as base_app


    class DialogStub:
        def __init__(self):
            self.seen = []

        def _record(self, *args, **kw):
            self.seen.append(args)
            return True

        showinfo = showwarning = showerror = _record

        def askokcancel(self, *a, **kw):
            return True

        def askyesno(self, *a, **kw):
            return False

        def askyesnocancel(self, *a, **kw):
            # Wave 5c-ii save-collision pre-flight: True lets the run go.
            return True


    dialogs = DialogStub()
    iv_experiment.messagebox = dialogs
    base_experiment.messagebox = dialogs
    base_app.messagebox = dialogs
    iv_experiment.PRE_SWEEP_SETTLE_S = 0.01

    root = tk.Tk()
    app = LabApp(root, IVSweepExperiment)
    exp = app.experiment
    app.connect_role("source", FakeTransport("1.5.0"), "COM3")
    for _ in range(20):
        root.update()

    driver = app.instruments["source"]
    check("auto-detected as the miniSMU",
          isinstance(driver, UndalogicMiniSMU))
    check("connecting did not reboot it",
          not any(c[0] == "reset" for c in driver.client.calls),
          "this is the check that would have caught it on the bench")
    check("the sensing checkbox is live on 1.5.0 firmware",
          str(exp.remote_sense_check.cget("state")) != "disabled")
    console = app.console.get("1.0", "end").lower()
    check("the console carries the mains-synchronisation caveat",
          "mains" in console)
    check("and tells the operator the 12 V adapter is required",
          "12 v dc adapter" in console,
          "the one requirement software cannot verify, on screen before "
          "the first sweep")

    exp.mode_var.set("voltage")
    exp.on_mode_changed()
    exp.start_var.set("-1")
    exp.stop_var.set("1")
    exp.points_var.set("11")
    exp.delay_var.set("0.01")
    exp.compliance_var.set("0.1")
    exp.dataset_var.set("minismu")
    exp.nplc_var.set("1")

    params = exp._sweep_params()
    exp._check_limits(params)
    exp._begin_run()
    try:
        exp._do_single(params)
    finally:
        for _ in range(60):
            root.update()

    rows = exp.tree.get_children()
    check("the sweep produced a row", len(rows) == 1, f"{len(rows)} rows")
    if rows:
        run = exp.run_store._runs[rows[0]]
        check("recorded as a hardware sweep",
              run.metadata["sweep_kind"] == "hardware",
              f"{run.metadata['sweep_kind']}")
        expected = UndalogicMiniSMU.clamp_nplc(1.0)
        check("the CSV records the integration actually used, not the "
              "number typed",
              abs(float(run.metadata["nplc"]) - expected) < 1e-9
              and abs(expected - 1.0) > 1e-6,
              f"recorded {run.metadata['nplc']!r} for a requested 1; the "
              f"achievable window is {expected:.4g} PLC")
        check("4-wire is recorded", run.metadata["sensing"] == "4-wire")
        resistance = run.metadata["resistance_ohm"]
        check("and the fit recovers the resistor",
              abs(resistance - SAMPLE_OHM) / SAMPLE_OHM < 5e-4,
              f"{resistance:.4f} ohm")

    for _ in range(20):
        root.update()
    app.on_close()
    try:
        root.destroy()
    except Exception:
        pass
