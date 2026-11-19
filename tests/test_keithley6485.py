"""The Keithley 6485 driver, and the meter checkup that grades it.

Written before the picoammeter had been asked anything, so the fake
below is the manual's 6485, not a measured one. It matters that the fake
**rejects** what the manual says the instrument rejects - an unknown
header, an integration time outside its span, a range above 21 mA - into
an error queue the driver has to read, and that `*RST` leaves zero check
on, where every reading is the meter's own offset. A fake that accepted
everything, or measured with zero check on, would let the one trap that
matters most through as if it had been handled.

Most of the checkup half breaks the driver or the instrument on purpose
and requires the report to notice.
"""
import pytest

from smuniversal_lab_suite.core.checkup import MeterCheckup, checkup_for
from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.core.transports.base import Transport
from smuniversal_lab_suite.drivers.base_meter import BaseMeter
from smuniversal_lab_suite.drivers.keithley_6485 import Keithley6485
from smuniversal_lab_suite.drivers.registry import (
    KNOWN_DRIVERS,
    KNOWN_METERS,
    driver_for_idn,
    fleet_of,
)

IDN = "KEITHLEY INSTRUMENTS INC.,MODEL 6485,1234567,B03   Jun 17 2003 10:24:15/A02  /F"

RANGES = (2e-9, 2e-8, 2e-7, 2e-6, 2e-5, 2e-4, 2e-3, 2e-2)

#: What a shunted input reads: the meter's own offset, a plausible
#: number and not an error.
ZERO_CHECK_READING = 3.2e-15


class PicoammeterTransport(Transport):
    """A 6485 as its instruction manual describes it.

    State is what Table 1-3 lists for `*RST`. Commands are parsed in the
    short forms the driver uses, with the optional `SENS:` root allowed;
    anything not understood files -113 and, for a query, sends no reply
    - which on a real link latches the transport, and here returns an
    empty string so a test can see the complaint instead of a hang.

    `amps` is the current into the input. `lie_about` names a readback
    that answers the wrong value, for the checkup's mutation tests.
    """

    def __init__(self, amps=4e-14, idn=IDN, lie_about=()):
        super().__init__()
        self.connected = True
        self.idn = idn
        self.amps = amps
        self.lie_about = set(lie_about)
        self.sent = []
        self.timeouts = []
        self.errors = []
        self._reply = ""
        self._power_on()

    def _power_on(self):
        self.autorange = True
        self.range = 2e-4
        self.llim = 2.1e-9
        self.ulim = 2.1e-2
        self.nplc = 5.0
        self.autozero = True
        self.zero_check = True
        self.zero_correct = False
        self.median = False
        self.average = False
        self.math = False
        self.rel = False
        self.elements = ("READ", "UNIT", "TIME", "STAT")
        self.arm_count = 1
        self.trigger_count = 1

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
        upper = text.strip().upper()
        if upper.startswith("SENS:"):
            upper = upper[len("SENS:"):]
        self._reply = ""
        head, _, arg = upper.partition(" ")
        arg = arg.strip()
        on = arg in ("ON", "1")

        def number():
            try:
                return float(arg)
            except ValueError:
                self._error(-224, "Illegal parameter value")
                return None

        if upper == "*IDN?":
            self._reply = self.idn
        elif upper == "*RST":
            self._power_on()
        elif upper == "*CLS":
            self.errors.clear()
        elif upper == "SYST:ERR?":
            self._reply = (self.errors.pop(0) if self.errors
                           else '0,"No error"')
        elif head == "FORM:ELEM":
            items = tuple(i.strip()[:4] for i in arg.split(","))
            if not all(i in ("READ", "UNIT", "TIME", "STAT") for i in items):
                self._error(-224, "Illegal parameter value")
                return
            self.elements = items
        elif head == "CURR:RANG:AUTO":
            self.autorange = on
        elif upper == "CURR:RANG:AUTO?":
            value = self.autorange != ("autorange" in self.lie_about)
            self._reply = "1" if value else "0"
        elif head in ("CURR:RANG:AUTO:LLIM", "CURR:RANG:AUTO:ULIM"):
            value = number()
            if value is None:
                return
            if abs(value) > 0.021:
                self._error(-222, "Parameter data out of range")
                return
            setattr(self, "llim" if head.endswith("LLIM") else "ulim", value)
        elif head == "CURR:RANG":
            value = number()
            if value is None:
                return
            if abs(value) > 0.021:
                self._error(-222, "Parameter data out of range")
                return
            self.range = next(r for r in RANGES
                              if r >= abs(value) * (1 - 1e-9))
            self.autorange = False
        elif upper == "CURR:RANG?":
            value = self.range * (10 if "range" in self.lie_about else 1)
            self._reply = f"{value:.6E}"
        elif head == "CURR:NPLC":
            value = number()
            if value is None:
                return
            if not 0.01 <= value <= 5.0 + 1e-9:
                self._error(-222, "Parameter data out of range")
                return
            self.nplc = value
        elif upper == "CURR:NPLC?":
            value = 5.0 if "nplc" in self.lie_about else self.nplc
            self._reply = f"{value:.6E}"
        elif head == "SYST:AZER":
            self.autozero = on
        elif upper == "SYST:AZER?":
            self._reply = "1" if self.autozero else "0"
        elif head == "SYST:ZCH":
            self.zero_check = on
        elif upper == "SYST:ZCH?":
            value = self.zero_check != ("zero_check" in self.lie_about)
            self._reply = "1" if value else "0"
        elif head == "SYST:ZCOR":
            self.zero_correct = on
        elif head == "MED":
            self.median = on
        elif head == "AVER":
            self.average = on
        elif head in ("CALC1:STAT", "CALC:STAT"):
            self.math = on
        elif head == "CALC2:NULL:STAT":
            self.rel = on
        elif head in ("ARM:SOUR", "TRIG:SOUR"):
            if arg not in ("IMM", "IMMEDIATE"):
                self._error(-224, "Illegal parameter value")
        elif head == "ARM:COUN":
            self.arm_count = int(float(arg))
        elif head == "TRIG:COUN":
            self.trigger_count = int(float(arg))
        elif head == "TRIG:DEL":
            pass
        elif upper == "READ?":
            self._reply = ",".join(
                [self._reading()] * (self.arm_count * self.trigger_count))
        else:
            self._error(-113, "Undefined header")

    def _reading(self):
        amps = ZERO_CHECK_READING if self.zero_check else self.amps
        if not self.autorange and abs(amps) > self.range * 1.05:
            value = "+9.9E37"
        else:
            value = f"{amps:+.6E}"
        parts = []
        for element in self.elements:
            if element == "READ":
                parts.append(value + ("A" if "UNIT" in self.elements
                                      else ""))
            elif element == "TIME":
                parts.append("+1.234500E+02")
            elif element == "STAT":
                parts.append("+0.000000E+00")
        return ",".join(parts)

    def _error(self, code, message):
        self.errors.append(f'{code:+d},"{message}"')

    def _read(self, timeout_s=3.0):
        return self._reply


def build(**kwargs):
    transport = PicoammeterTransport(**kwargs)
    return Keithley6485(transport), transport


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


def test_its_identity_resolves_to_the_driver_and_nothing_else(check):
    check("the manual's reply resolves",
          driver_for_idn(IDN) is Keithley6485, f"{driver_for_idn(IDN)}")
    sibling = IDN.replace("MODEL 6485", "MODEL 6487")
    check("a 6487 - a 6485 with a source - does not",
          driver_for_idn(sibling) is not Keithley6485,
          f"{driver_for_idn(sibling)}")
    others = [cls.__name__ for cls in KNOWN_DRIVERS if cls is not Keithley6485
              and any(m in IDN for m in cls.MODEL_IDS)]
    check("no other driver claims its reply", not others, others)


def test_it_is_a_meter_that_reads_current(check):
    check("on the meter contract", issubclass(Keithley6485, BaseMeter))
    check("filed under meter", fleet_of(Keithley6485) == "meter",
          f"{fleet_of(Keithley6485)}")
    check("registered", Keithley6485 in KNOWN_METERS)
    check("sets nothing", not Keithley6485.supports_sourcing()
          and not Keithley6485.source_functions()
          and not Keithley6485.supports_current_sourcing())
    check("cannot sweep", not Keithley6485.supports_sweep())
    check("no compliance", not Keithley6485.supports_compliance())
    check("reads current only",
          Keithley6485.measure_functions() == ("current",),
          f"{Keithley6485.measure_functions()}")
    check("its quantity is current",
          Keithley6485.measured_quantity() == "current"
          and Keithley6485.measured_unit() == "A")
    check("eight ranges, 2 nA to 20 mA",
          Keithley6485.measure_ranges() == list(RANGES),
          f"{Keithley6485.measure_ranges()}")
    check("declares a caveat", bool(Keithley6485.ROLE_CAVEATS))
    check("has a shunt it can read", Keithley6485.supports_input_shunt())
    check("one input, no terminal switch",
          not Keithley6485.has_terminal_switch())
    check("no input-impedance setting",
          not Keithley6485.supports_high_impedance())
    check("no high-voltage hazard - it sets no level",
          Keithley6485.hazardous_above_v() is None)


# ---------------------------------------------------------------
# What it sends
# ---------------------------------------------------------------


def test_reset_sends_every_setting_and_zero_check_off_last(check):
    meter, wire = build()
    meter.reset()
    sent = wire.sent
    check("starts with *RST, *CLS", sent[:2] == ["*RST", "*CLS"], sent[:4])
    for wanted in ("FORM:ELEM READ", "CURR:RANG:AUTO ON",
                   "CURR:RANG:AUTO:LLIM 2e-09", "CURR:RANG:AUTO:ULIM 0.02",
                   "CURR:NPLC 5", "SYST:AZER ON", "MED OFF", "AVER OFF",
                   "CALC1:STAT OFF", "CALC2:NULL:STAT OFF", "ARM:SOUR IMM",
                   "ARM:COUN 1", "TRIG:SOUR IMM", "TRIG:COUN 1", "TRIG:DEL 0",
                   "SYST:ZCOR OFF"):
        check(f"sends {wanted}", wanted in sent, sent)
    check("zero check off is the last thing sent",
          sent[-1] == "SYST:ZCH OFF", sent[-3:])
    check("and it landed", not wire.zero_check)
    check("nothing was rejected", not wire.errors, wire.errors)


def test_a_previous_users_offsets_and_filters_are_switched_off(check):
    meter, wire = build()
    wire.rel = wire.math = wire.median = wire.average = True
    wire.zero_correct = True
    meter.reset()
    check("Rel off", not wire.rel)
    check("math off", not wire.math)
    check("filters off", not wire.median and not wire.average)
    check("zero correct off", not wire.zero_correct)


def test_it_never_sends_what_it_must_not(check):
    """Across a whole checkup and a release, nothing the module
    docstring lists as never sent reaches the wire."""
    meter, wire = build()
    MeterCheckup(meter).run()
    meter.release_front_panel()
    forbidden = ("*SAV", "*RCL", "SYST:POS", "SYST:PRES", "SYST:REM",
                 "SYST:LOC", "SYST:RWL", "SYST:ZCOR:ACQ", "SYST:ZCOR ON",
                 "SYST:KEY", "TRAC", "DATA:", "DISP", "CAL:", "CALIB",
                 "CALC1:STAT ON", "CALC:STAT ON", "CALC2:NULL:STAT ON",
                 "CALC2:LIM", "CALC3", "FORM:DATA", "STAT:")
    for text in wire.sent:
        upper = text.upper()
        bad = [f for f in forbidden if upper.startswith(f)]
        check(f"{text!r} is allowed", not bad, bad)


def test_an_integration_time_is_clamped_into_its_span(check):
    for asked, landed in ((0.001, 0.01), (0.01, 0.01), (0.5, 0.5),
                          (1.0, 1.0), (5.0, 5.0), (60.0, 5.0)):
        check(f"{asked:g} -> {landed:g}",
              Keithley6485.snap_nplc(asked) == landed,
              f"{Keithley6485.snap_nplc(asked)}")
    meter, wire = build()
    got = meter.set_nplc(10.0)
    check("set_nplc reports what it sent", got == 5.0, f"{got}")
    check("and only a value in the span is sent",
          wire.sent[-1] == "CURR:NPLC 5", wire.sent[-1])
    check("which the instrument accepts", not wire.errors, wire.errors)


def test_a_range_is_the_smallest_that_holds_the_request(check):
    meter, wire = build()
    for asked, landed in ((1e-12, 2e-9), (2e-9, 2e-9), (3e-9, 2e-8),
                          (-1.5e-6, 2e-6), (2e-4, 2e-4), (0.015, 0.02)):
        got = meter.set_current_range(asked)
        check(f"{asked:g} A -> {landed:g} A range", got == landed, f"{got}")
        check(f"{asked:g} A: autorange off first",
              wire.sent[-2:] == ["CURR:RANG:AUTO OFF",
                                 f"CURR:RANG {landed:g}"], wire.sent[-2:])
        check(f"{asked:g} A: landed", wire.range == landed
              and not wire.autorange)
    with pytest.raises(LimitError):
        meter.set_current_range(0.05)
    meter.set_current_range(None)
    check("None is autorange", wire.autorange and
          wire.sent[-1] == "CURR:RANG:AUTO ON", wire.sent[-1])
    check("nothing rejected", not wire.errors, wire.errors)


def test_it_has_no_voltage_to_range(check):
    meter, wire = build()
    with pytest.raises(NotImplementedError, match="does not read voltage"):
        meter.set_voltage_range(1.0)
    check("the neutral layer picks the current range",
          meter.set_measure_range(5e-9) == 2e-8)
    check("nothing rejected", not wire.errors, wire.errors)


def test_release_puts_zero_check_back_on_with_a_write_only(check):
    meter, wire = build()
    meter.reset()
    queries_before = len(wire.timeouts)
    meter.release_front_panel()
    check("SYST:ZCH ON sent", wire.sent[-1] == "SYST:ZCH ON", wire.sent[-1])
    check("landed", wire.zero_check)
    check("nothing asked - it must work on a link that stopped answering",
          len(wire.timeouts) == queries_before)


# ---------------------------------------------------------------
# Reading
# ---------------------------------------------------------------


def test_a_reading_is_one_number_in_the_current_column(check):
    meter, wire = build(amps=1.234567e-11)
    meter.reset()
    volts, amps = meter.measure()
    check("amps read", amps is not None and abs(amps - 1.234567e-11) < 1e-17,
          f"{amps}")
    check("nothing in the voltage column", volts is None, f"{volts}")
    check("by READ?", wire.sent[-1] == "READ?", wire.sent[-1])


def test_before_reset_the_reading_is_the_shunt_not_the_circuit(check):
    """Why reset must switch zero check off: left on, the reading is a
    plausible femtoamp number whatever is on the input."""
    meter, wire = build(amps=1e-6)
    wire.elements = ("READ",)
    _, amps = meter.measure()
    check("a shunted reading looks like data", amps == ZERO_CHECK_READING,
          f"{amps}")
    meter.reset()
    _, amps = meter.measure()
    check("after reset it is the circuit's", amps == 1e-6, f"{amps}")


def test_a_units_suffix_is_stripped(check):
    meter, wire = build(amps=-5e-10)
    meter.reset()
    wire.elements = ("READ", "UNIT")
    _, amps = meter.measure()
    check("read through the A", amps == -5e-10, f"{amps}")


@pytest.mark.parametrize("input_a", [5e-6, -5e-6],
                         ids=["positive", "negative"])
def test_overflow_is_not_data(input_a, check):
    meter, wire = build(amps=input_a)
    meter.reset()
    meter.set_current_range(2e-6)
    volts, amps = meter.measure()
    check("the sentinel is dropped", volts is None and amps is None,
          f"{volts}, {amps}")


def test_several_elements_are_refused_rather_than_guessed(check):
    meter, wire = build()
    meter.reset()
    wire.elements = ("READ", "TIME", "STAT")
    with pytest.raises(RuntimeError, match="FORM:ELEM"):
        meter.measure()


def test_the_read_timeout_covers_the_slowest_reading(check):
    meter, wire = build()
    meter.reset()
    meter.measure(timeout_s=0.1)
    _, timeout = wire.timeouts[-1]
    check("twice a 5 PLC autozeroed, autoranging reading, and a second",
          timeout >= 2 * (5 * 0.02 * 3 + 0.3) + 1.0, f"{timeout}")
    meter.set_nplc(0.01)
    meter.set_autozero(False)
    meter.set_current_range(2e-3)
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
    meter, wire = build()
    meter.reset()
    meter.set_current_range(2e-7)
    described = meter.describe_configuration()
    check("current range", described["current_range_a"] == 2e-7,
          f"{described}")
    check("autorange off", described["autorange"] is False, f"{described}")
    check("nplc", described["nplc"] == 5.0, f"{described}")
    check("autozero", described["autozero"] is True, f"{described}")
    check("input connected", described["input_connected"] is True,
          f"{described}")
    check("no voltage range, function or terminals asked",
          described["voltage_range_v"] is None
          and described["function"] is None
          and described["terminals"] is None, f"{described}")
    check("nothing rejected", not wire.errors, wire.errors)


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
            ("set_current_level", lambda: meter.set_current_level(1e-9),
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
            check(f"{name} says why",
                  "is a meter" in str(exc) or "sense" in str(exc), str(exc))
        else:
            check(f"{name} refused", False, "it was accepted")
    check("nothing reached the wire", not wire.sent, wire.sent)


def test_output_off_succeeds_and_sends_nothing(check):
    meter, wire = build()
    meter.output_off()
    meter.safe_output_off()
    check("nothing sent", not wire.sent, wire.sent)


# ---------------------------------------------------------------
# The checkup
# ---------------------------------------------------------------


def test_a_working_picoammeter_has_no_failures(check):
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
    for row, wanted in (
            ("integration menu", "pass"),
            ("read_terminals()", "skip"),
            ("reset: function is DC current", "skip"),
            ("reset: input connected (not shunted)", "pass"),
            ("input connected reads False", "pass"),
            ("input connected reads True", "pass"),
            ("set_current_range(2e-09)", "pass"),
            ("set_current_range(0.02)", "pass"),
            ("refuses a range above its highest", "pass"),
            ("set_nplc(0.01)", "pass"),
            ("set_nplc(1)", "pass"),
            ("set_nplc(5)", "pass"),
            ("a reading at NPLC 5", "pass"),
            ("open-input reading is near zero", "pass")):
        check(f"{row}: {wanted}", severity(results, row) == wanted,
              f"{by_name(results).get(row)}")
    untrusted = [r.name for r in results if r.severity == "warn"
                 and "never been checked" in str(r.detail)]
    check("the readbacks are not trusted until the bench says so",
          bool(untrusted), untrusted)


def test_the_dispatcher_picks_the_meter_checkup(check):
    meter, _ = build()
    got = checkup_for(meter)
    check("a MeterCheckup", isinstance(got, MeterCheckup), type(got).__name__)


def test_it_is_left_as_a_connect_leaves_it(check):
    meter, wire = build()
    MeterCheckup(meter).run()
    check("input connected", not wire.zero_check)
    check("autorange", wire.autorange)
    check("5 PLC", wire.nplc == 5.0, f"{wire.nplc}")


@pytest.mark.parametrize("lie,row", [
    ("range", "current range read back"),
    ("nplc", "integration time read back"),
    ("autorange", "a fixed range turns autorange off"),
    ("zero_check", "reset: input connected (not shunted)"),
])
def test_a_readback_that_disagrees_is_flagged(lie, row, check):
    meter, _ = build(lie_about=(lie,))
    results = MeterCheckup(meter).run()
    rows = [r for r in results if r.name == row]
    check(f"{row} is in the report", bool(rows))
    check(f"{lie}: graded as a failure or warning on that row",
          any(r.severity in ("fail", "warn") for r in rows),
          [(r.severity, r.detail) for r in rows])


def test_a_reset_that_leaves_zero_check_on_fails(check):
    """The trap the driver exists to avoid: every reading would be the
    shunt's offset, and only the readback can tell."""
    class Forgetful(Keithley6485):
        def reset(self):
            super().reset()
            self.transport.write("SYST:ZCH ON")
    meter = Forgetful(PicoammeterTransport())
    results = MeterCheckup(meter).run()
    check("the reset row fails",
          severity(results, "reset: input connected (not shunted)")
          == "fail", f"{by_name(results).get('reset: input connected (not shunted)')}")


def test_a_reading_in_the_voltage_column_fails(check):
    meter, _ = build()
    meter.measure = lambda timeout_s=3.0: (0.0001, 1e-12)
    results = MeterCheckup(meter).run()
    check("measure() fails", severity(results, "measure()") == "fail")
    check("and says which column",
          "voltage column" in by_name(results)["measure()"].detail,
          by_name(results)["measure()"].detail)


def test_an_open_input_reading_current_is_flagged(check):
    meter, _ = build(amps=5e-9)
    results = MeterCheckup(meter).run()
    check("warned", severity(results, "open-input reading is near zero")
          == "warn")
    detail = by_name(results)["open-input reading is near zero"].detail
    check("in amps, without a terminal switch to blame",
          " A" in detail and "front/rear" not in detail, detail)
    meter, _ = build(amps=5e-9)
    results = MeterCheckup(meter, open_circuit=False).run()
    check("recorded, not graded, with something connected",
          severity(results, "open-input reading is near zero") == "skip")
