"""The Keysight 34401A driver, and the meter checkup that grades it.

Written before the meter had been asked anything, so the fake below is
the manual's 34401A, not a measured one. It matters that the fake
**rejects** what the manual says the instrument rejects - an unknown
header, an off-menu integration time, the RS-232-only commands - into
an error queue the driver has to read, and that `CONFigure` resets the
input resistance the way the manual says it does. A fake that accepted
everything would let a wrong spelling through as if it had landed.

Most of the checkup half breaks the driver or the instrument on purpose
and requires the report to notice: a checkup that only passes a working
driver proves little.
"""
import pytest

from smuniversal_lab_suite.core.checkup import (
    LoadCheckup,
    MeterCheckup,
    checkup_for,
)
from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.core.transports.base import Transport
from smuniversal_lab_suite.drivers.base_meter import BaseMeter
from smuniversal_lab_suite.drivers.keysight_34401a import Keysight34401A
from smuniversal_lab_suite.drivers.registry import (
    KNOWN_METERS,
    driver_for_idn,
    fleet_of,
)

IDN = "HEWLETT-PACKARD,34401A,0,11-5-2"

NPLC_MENU = (0.02, 0.2, 1.0, 10.0, 100.0)
RANGES = (0.1, 1.0, 10.0, 100.0, 1000.0)


class MeterTransport(Transport):
    """A 34401A as its user's guide describes it.

    State is what the guide's reset table lists. Commands are parsed in
    the long and short SCPI forms the driver might use; anything not
    understood files -113 and, for a query, sends no reply - which on a
    real link latches the transport, and here returns an empty string so
    a test can see the complaint instead of a hang.

    `volts` is what is across the input. `lie_about` names a readback
    that answers the wrong value, for the checkup's mutation tests.
    """

    def __init__(self, volts=0.0002, idn=IDN, lie_about=(),
                 terminals="FRON"):
        super().__init__()
        self.connected = True
        self.idn = idn
        self.volts = volts
        self.lie_about = set(lie_about)
        self.terminals = terminals
        self.sent = []
        self.timeouts = []
        self.errors = []
        self._reply = ""
        self._power_on()

    def _power_on(self):
        self.function = "VOLT"
        self.autorange = True
        self.range = 10.0
        self.nplc = 10.0
        self.autozero = True
        self.high_z = False
        self.trigger_source = "IMM"
        self.samples = 1
        self.triggers = 1
        self.math = False

    def connect(self, address, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False

    def query(self, text, timeout_s=3.0):
        self.timeouts.append((text, timeout_s))
        return super().query(text, timeout_s=timeout_s)

    # ---- the parser ----
    def _write(self, text):
        self.sent.append(text)
        command = text.strip()
        upper = command.upper()
        self._reply = ""
        head, _, arg = upper.partition(" ")
        arg = arg.strip()

        def short(word):
            return head.replace("SENS:", "").replace("SENSE:", "") == word

        if upper == "*IDN?":
            self._reply = self.idn
        elif upper == "*RST":
            self._power_on()
        elif upper == "*CLS":
            self.errors.clear()
        elif upper in ("SYST:ERR?", "SYSTEM:ERROR?"):
            self._reply = (self.errors.pop(0) if self.errors
                           else '+0,"No error"')
        elif head in ("SYST:REM", "SYSTEM:REMOTE", "SYST:LOC",
                      "SYSTEM:LOCAL", "SYST:RWL"):
            self._error(514, "Command allowed only with RS-232")
        elif head.startswith("CONF"):
            # The manual: CONFigure presets the input to 10 MOhm.
            self.function = "VOLT"
            self.high_z = False
            self.autozero = True
            self.trigger_source = "IMM"
        elif short("FUNC"):
            if arg.strip('"') in ("VOLT:DC", "VOLTAGE:DC", "VOLT"):
                self.function = "VOLT"
            else:
                self._error(-224, "Illegal parameter value")
        elif upper == "FUNC?":
            self._reply = f'"{self.function}"'
        elif short("VOLT:DC:RANG:AUTO"):
            self.autorange = arg == "ON"
        elif upper == "VOLT:DC:RANG:AUTO?":
            value = self.autorange
            if "autorange" in self.lie_about:
                value = not value
            self._reply = "1" if value else "0"
        elif short("VOLT:DC:RANG"):
            try:
                wanted = float(arg)
            except ValueError:
                self._error(-224, "Illegal parameter value")
                return
            match = [r for r in RANGES if r >= wanted * (1 - 1e-9)]
            if not match:
                self._error(-222, "Data out of range")
                return
            self.range = match[0]
            self.autorange = False
        elif upper == "VOLT:DC:RANG?":
            value = self.range * (10 if "range" in self.lie_about else 1)
            self._reply = f"{value:+.8E}"
        elif short("VOLT:DC:NPLC"):
            try:
                wanted = float(arg)
            except ValueError:
                self._error(-224, "Illegal parameter value")
                return
            if not any(abs(wanted - n) < 1e-9 for n in NPLC_MENU):
                self._error(-222, "Data out of range")
                return
            self.nplc = wanted
        elif upper == "VOLT:DC:NPLC?":
            value = 10.0 if "nplc" in self.lie_about else self.nplc
            self._reply = f"{value:+.8E}"
        elif short("ZERO:AUTO"):
            self.autozero = arg == "ON"
        elif upper == "ZERO:AUTO?":
            self._reply = "1" if self.autozero else "0"
        elif head in ("INP:IMP:AUTO", "INPUT:IMPEDANCE:AUTO"):
            self.high_z = arg == "ON"
        elif upper == "INP:IMP:AUTO?":
            value = self.high_z
            if "high_z" in self.lie_about:
                value = False
            self._reply = "1" if value else "0"
        elif upper == "ROUT:TERM?":
            self._reply = self.terminals
        elif head == "TRIG:SOUR":
            self.trigger_source = arg
        elif head in ("TRIG:DEL:AUTO",):
            pass
        elif head == "TRIG:COUN":
            self.triggers = int(float(arg))
        elif head == "SAMP:COUN":
            self.samples = int(float(arg))
        elif head == "CALC:STAT":
            self.math = arg == "ON"
        elif upper == "READ?":
            if self.trigger_source == "BUS":
                self._error(-214, "Trigger deadlock")
                return
            self._reply = ",".join([self._reading()] * self.samples)
        else:
            self._error(-113, "Undefined header")

    def _reading(self):
        if not self.autorange and abs(self.volts) > self.range * 1.2:
            # Signed like the input: the bench unit read -9.9E+37 for
            # -128 mV on the 100 mV range (2026-11-16).
            return "-9.90000000E+37" if self.volts < 0 else "+9.90000000E+37"
        return f"{self.volts:+.8E}"

    def _error(self, code, message):
        self.errors.append(f'{code:+d},"{message}"')

    def _read(self, timeout_s=3.0):
        return self._reply


def build(**kwargs):
    transport = MeterTransport(**kwargs)
    return Keysight34401A(transport), transport


def by_name(results):
    return {r.name: r for r in results}


def severity(results, name):
    result = by_name(results).get(name)
    return None if result is None else result.severity


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    from smuniversal_lab_suite.core.checkup import meter as meter_checkup
    monkeypatch.setattr(meter_checkup, "QUIET_BUS_PAUSE_S", 0.0)


# ---------------------------------------------------------------
# Identity and fleet
# ---------------------------------------------------------------


def test_every_badge_resolves_to_the_driver(check):
    """The manual's HP string, an Agilent-era one and a Keysight one:
    the unit's own reply is unknown until the first checkup."""
    for idn in (IDN,
                "Agilent Technologies,34401A,0,11-5-3",
                "Keysight Technologies,34401A,MY12345678,11-5-3"):
        check(f"{idn} resolves", driver_for_idn(idn) is Keysight34401A,
              f"{driver_for_idn(idn)}")


def test_it_is_a_meter_and_only_a_meter(check):
    check("on the meter contract", issubclass(Keysight34401A, BaseMeter))
    check("filed under meter", fleet_of(Keysight34401A) == "meter",
          f"{fleet_of(Keysight34401A)}")
    check("registered", Keysight34401A in KNOWN_METERS)
    check("sets nothing", not Keysight34401A.supports_sourcing()
          and not Keysight34401A.source_functions()
          and not Keysight34401A.supports_current_sourcing())
    check("cannot sweep", not Keysight34401A.supports_sweep())
    check("no compliance", not Keysight34401A.supports_compliance())
    check("reads voltage only",
          Keysight34401A.measure_functions() == ("voltage",),
          f"{Keysight34401A.measure_functions()}")
    check("declares a caveat", bool(Keysight34401A.ROLE_CAVEATS))


# ---------------------------------------------------------------
# What it sends
# ---------------------------------------------------------------


def test_reset_sends_every_setting_and_the_input_mode_last(check):
    meter, wire = build()
    wire.high_z = False
    meter.reset()
    sent = wire.sent
    check("starts with *RST, *CLS", sent[:2] == ["*RST", "*CLS"], sent[:4])
    for wanted in ('FUNC "VOLT:DC"', "VOLT:DC:RANG:AUTO ON",
                   "VOLT:DC:NPLC 10", "ZERO:AUTO ON", "TRIG:SOUR IMM",
                   "TRIG:DEL:AUTO ON", "TRIG:COUN 1", "SAMP:COUN 1",
                   "CALC:STAT OFF"):
        check(f"sends {wanted}", wanted in sent, sent)
    check("the input mode is the last thing sent",
          sent[-1] == "INP:IMP:AUTO ON", sent[-3:])
    check("and it landed", wire.high_z)
    check("nothing was rejected", not wire.errors, wire.errors)


def test_a_previous_users_null_offset_is_switched_off(check):
    meter, wire = build()
    wire.math = True
    meter.reset()
    check("math off after reset", not wire.math)


def test_it_never_sends_what_it_must_not(check):
    """Across a whole checkup, nothing the module docstring lists as
    never sent reaches the wire."""
    meter, wire = build()
    MeterCheckup(meter).run()
    forbidden = ("CONF", "MEAS", "SYST:REM", "SYST:LOC", "SYST:RWL",
                 "TRIG:SOUR BUS", "CAL:", "CAL?", "CALIB", "*TST", "DISP",
                 "CALC:STAT ON")
    for text in wire.sent:
        upper = text.upper()
        bad = [f for f in forbidden if upper.startswith(f)]
        check(f"{text!r} is allowed", not bad, bad)
    check("never a language switch",
          not [t for t in wire.sent if t.strip().upper() in ("L1", "L2", "L3")])


def test_an_integration_time_is_moved_up_onto_the_menu(check):
    for asked, landed in ((5.0, 10.0), (0.01, 0.02), (0.02, 0.02),
                          (0.2, 0.2), (0.5, 1.0), (1000.0, 100.0),
                          (100.0, 100.0)):
        check(f"{asked:g} -> {landed:g}",
              Keysight34401A.snap_nplc(asked) == landed,
              f"{Keysight34401A.snap_nplc(asked)}")
    meter, wire = build()
    got = meter.set_nplc(3.0)
    check("set_nplc reports what it sent", got == 10.0, f"{got}")
    check("and only a menu value is sent", wire.sent[-1] == "VOLT:DC:NPLC 10",
          wire.sent[-1])
    check("which the instrument accepts", not wire.errors, wire.errors)


def test_a_range_is_the_smallest_that_holds_the_request(check):
    meter, wire = build()
    for asked, landed in ((0.05, 0.1), (0.5, 1.0), (1.0, 1.0),
                          (-7.0, 10.0), (999.0, 1000.0)):
        got = meter.set_voltage_range(asked)
        check(f"{asked:g} V -> {landed:g} V range", got == landed, f"{got}")
        check(f"{asked:g} V: autorange off first",
              wire.sent[-2:] == ["VOLT:DC:RANG:AUTO OFF",
                                 f"VOLT:DC:RANG {landed:g}"], wire.sent[-2:])
        check(f"{asked:g} V: landed", wire.range == landed
              and not wire.autorange)
    with pytest.raises(LimitError):
        meter.set_voltage_range(2000.0)
    meter.set_voltage_range(None)
    check("None is autorange", wire.autorange and
          wire.sent[-1] == "VOLT:DC:RANG:AUTO ON", wire.sent[-1])
    check("nothing rejected", not wire.errors, wire.errors)


# ---------------------------------------------------------------
# Reading
# ---------------------------------------------------------------


def test_a_reading_is_one_number_in_the_voltage_column(check):
    meter, wire = build(volts=1.2345678)
    meter.reset()
    volts, amps = meter.measure()
    check("volts read", volts is not None and abs(volts - 1.2345678) < 1e-9,
          f"{volts}")
    check("nothing in the current column", amps is None, f"{amps}")
    check("by READ?", wire.sent[-1] == "READ?", wire.sent[-1])


@pytest.mark.parametrize("input_v", [5.0, -5.0],
                         ids=["positive", "negative"])
def test_overload_is_not_data(input_v, check):
    meter, wire = build(volts=input_v)
    meter.reset()
    meter.set_voltage_range(1.0)
    volts, amps = meter.measure()
    check("the sentinel is dropped, whatever its sign",
          volts is None and amps is None, f"{volts}, {amps}")


def test_several_readings_are_refused_rather_than_guessed(check):
    meter, wire = build()
    meter.reset()
    wire.samples = 3
    with pytest.raises(RuntimeError, match="sample count"):
        meter.measure()


def test_the_read_timeout_grows_with_the_integration_time(check):
    """At 100 PLC with autozero a reading takes about 4 s at 50 Hz; a
    3 s timeout would desynchronise the link on every one."""
    meter, wire = build()
    meter.reset()
    meter.set_nplc(100)
    meter.measure(timeout_s=3.0)
    _, timeout = wire.timeouts[-1]
    check("long enough for two integrations of 100 PLC", timeout >= 4.0,
          f"{timeout}")
    meter.set_nplc(0.02)
    meter.set_autozero(False)
    meter.measure(timeout_s=3.0)
    _, timeout = wire.timeouts[-1]
    check("and the caller's own floor holds when that is longer",
          timeout == 3.0, f"{timeout}")


def test_errors_are_read_off_the_queue(check):
    meter, wire = build()
    wire.write("NOT:A:COMMAND")
    code, message = meter.read_error()
    check("the code", code == -113, f"{code}")
    check("the message, unquoted", message == "Undefined header", message)
    check("then empty", meter.read_error()[0] == 0)


def test_the_readbacks_report_the_instrument(check):
    meter, wire = build(terminals="REAR")
    meter.reset()
    described = meter.describe_configuration()
    check("function", described["function"] == "VOLT", f"{described}")
    check("autorange", described["autorange"] is True, f"{described}")
    check("nplc", described["nplc"] == 10.0, f"{described}")
    check("autozero", described["autozero"] is True, f"{described}")
    check("high impedance", described["high_impedance"] is True,
          f"{described}")
    check("rear terminals", described["terminals"] == "rear", f"{described}")


# ---------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------


def test_every_source_method_refuses_and_sends_nothing(check):
    meter, wire = build()
    for name, action, error in (
            ("set_source_function", lambda: meter.set_source_function("voltage"),
             NotImplementedError),
            ("set_voltage_level", lambda: meter.set_voltage_level(1.0),
             NotImplementedError),
            ("set_current_level", lambda: meter.set_current_level(1e-3),
             NotImplementedError),
            ("set_source_delay", lambda: meter.set_source_delay(0.1),
             NotImplementedError),
            ("output_on", meter.output_on, NotImplementedError),
            ("start_linear_sweep",
             lambda: meter.start_linear_sweep("voltage", 0, 1, 3, 0.0),
             NotImplementedError),
            ("set_remote_sense(True)", lambda: meter.set_remote_sense(True),
             NotImplementedError),
            ("validate_source_point",
             lambda: meter.validate_source_point(voltage=1.0,
                                                 sourcing="voltage"),
             LimitError)):
        try:
            action()
        except error as exc:
            check(f"{name} says it is a meter",
                  "multimeter" in str(exc) or "sense" in str(exc), str(exc))
        else:
            check(f"{name} refused", False, "it was accepted")
    check("nothing reached the wire", not wire.sent, wire.sent)


def test_output_off_succeeds_and_sends_nothing(check):
    """Every exit path calls it on every instrument; it must not raise,
    and a write would only be a command for the queue to complain
    about."""
    meter, wire = build()
    meter.output_off()
    meter.safe_output_off()
    meter.set_remote_sense(False)
    check("nothing sent", not wire.sent, wire.sent)


# ---------------------------------------------------------------
# The checkup
# ---------------------------------------------------------------


def test_a_working_meter_has_no_failures(check):
    meter, wire = build()
    checkup = MeterCheckup(meter)
    results = checkup.run()
    failures = [f"{r.name}: {r.detail}" for r in results
                if r.severity == "fail"]
    check("no failures", not failures, failures)
    check("all three tiers ran", {r.tier for r in results} == {1, 2, 3},
          sorted({r.tier for r in results}))
    check("it finished", not checkup._stopped_early)
    check("the burst check ran",
          severity(results, MeterCheckup.BURST_NAME) == "pass",
          f"{by_name(results).get(MeterCheckup.BURST_NAME)}")
    check("the error path was proven",
          severity(results, "the error path reports a rejected command")
          == "pass")
    check("only the probe was ever rejected", not wire.errors, wire.errors)
    check("a reading time was measured",
          checkup._seconds_per_reading is not None)
    untrusted = [r.name for r in results if r.severity == "warn"
                 and "never been checked" in str(r.detail)]
    check("the readbacks are trusted since the bench", not untrusted,
          untrusted)


def test_every_registered_meter_has_a_checkup_case(check):
    covered = {Keysight34401A}
    missing = [c.__name__ for c in KNOWN_METERS if c not in covered]
    check("every registered meter is exercised here", not missing, missing)


def test_the_dispatcher_picks_the_meter_checkup(check):
    meter, _ = build()
    got = checkup_for(meter)
    check("a MeterCheckup", isinstance(got, MeterCheckup), type(got).__name__)
    check("not the load's, which it used to fall through to",
          not isinstance(got, LoadCheckup))


def test_an_instrument_on_no_contract_gets_no_checkup(check):
    with pytest.raises(TypeError, match="no fleet"):
        checkup_for(object())


def test_it_is_left_as_a_connect_leaves_it(check):
    meter, wire = build()
    MeterCheckup(meter).run()
    check("high-impedance input back on", wire.high_z)
    check("autorange", wire.autorange)
    check("10 PLC", wire.nplc == 10.0, f"{wire.nplc}")


@pytest.mark.parametrize("lie,row", [
    ("range", "DC voltage range read back"),
    ("nplc", "integration time read back"),
    ("autorange", "a fixed range turns autorange off"),
    ("high_z", "reset: high-impedance input on"),
])
def test_a_readback_that_disagrees_fails(lie, row, check):
    meter, _ = build(lie_about=(lie,))
    results = MeterCheckup(meter).run()
    rows = [r for r in results if r.name == row]
    check(f"{row} is in the report", bool(rows))
    check(f"{lie}: graded as a failure somewhere on that row",
          any(r.severity in ("fail", "warn") for r in rows),
          [(r.severity, r.detail) for r in rows])


def test_an_error_path_that_reads_nothing_is_caught(check):
    meter, wire = build()
    meter.read_error = lambda: (0, "")
    results = MeterCheckup(meter).run()
    check("the probe row fails",
          severity(results, "the error path reports a rejected command")
          == "fail")


def test_a_reading_in_the_current_column_fails(check):
    meter, _ = build()
    meter.measure = lambda timeout_s=3.0: (0.0001, 0.0001)
    results = MeterCheckup(meter).run()
    check("measure() fails", severity(results, "measure()") == "fail")


def test_an_open_input_reading_volts_is_flagged(check):
    meter, _ = build(volts=0.5)
    results = MeterCheckup(meter).run()
    check("warned", severity(results, "open-input reading is near zero")
          == "warn")
    meter, _ = build(volts=0.5)
    results = MeterCheckup(meter, open_circuit=False).run()
    check("recorded, not graded, with something connected",
          severity(results, "open-input reading is near zero") == "skip")


def test_a_meter_that_sources_is_refused_by_its_own_checkup(check):
    class Sourcing(Keysight34401A):
        CAN_SOURCE = True
    meter = Sourcing(MeterTransport())
    results = MeterCheckup(meter).run()
    check("sets nothing fails", severity(results, "sets nothing") == "fail")


def test_a_meter_with_no_caveat_fails(check):
    class Uninvited(Keysight34401A):
        ROLE_CAVEATS = {}
    meter = Uninvited(MeterTransport())
    results = MeterCheckup(meter).run()
    check("invitation row fails",
          severity(results, "offered to experiments by invitation")
          == "fail")
