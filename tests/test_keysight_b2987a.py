"""The Keysight B2987A driver, against a fake built from its probe sitting.

`FakeB2987A` does what the 2026-11-18 sitting measured, not what a
manual implies: a level its range cannot hold is refused with -222 and
the old one stays; a range change with the output on is refused with
+213 even at 0 V; above 21 V with the interlock open the level is
refused; the source holds 20 mA (1 mA on the 1000 V pair) and sets
status bit 8 rather than tripping; `*RST` leaves the ammeter input off
and does not touch the reply's element list; and **a reading with the
input off is a plausible number**, not "not a number". Each of those is
a way a driver can be wrong without anything failing loudly, so each is
a test here.
"""
import pytest

from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.core.ranges import AUTO, NOT_SOURCED, RangeError
from smuniversal_lab_suite.core.transports.base import Transport
from smuniversal_lab_suite.drivers.keysight_b2987a import (
    HIGH_RANGE_LIMIT_A,
    LOW_RANGE_LIMIT_A,
    KeysightB2987A,
)

IDN = "Keysight Technologies,B2987A,MY54320335,2.0.1608.8800"

#: Range -> (lowest level, highest level, the current the source holds).
SPANS = {20.0: (-21.0, 21.0, 20e-3), 1000.0: (-1.0, 1000.0, 1e-3),
         -1000.0: (-1000.0, 1.0, 1e-3)}
CURRENT_RANGES = (2e-12, 20e-12, 200e-12, 2e-9, 20e-9, 200e-9, 2e-6,
                  20e-6, 200e-6, 2e-3, 20e-3)

#: What a reading with the ammeter input off returned at the bench.
INPUT_OFF_READING = 2.6e-11
#: The open-input offset, about what the bench saw.
OPEN_INPUT_AMPS = -3e-14

ALL_ELEMENTS = "VOLT,CURR,RES,TIME,STAT,SOUR,TEMP,HUM"


def _sci(value):
    return f"{value:+.8E}"


class FakeB2987A(Transport):
    """A B2987A as the probe sitting found it.

    `resistance` sits between Voltage Source HI and the ammeter input, in
    ohms; None is an open circuit. `interlock_open` is the fixture lid.
    `stuck` names command headers the instrument ignores, standing in
    for a setting the reset fails to make; `reject` names headers it
    refuses with -113.
    """

    def __init__(self, resistance=1e6, interlock_open=False, stuck=(),
                 reject=()):
        super().__init__()
        self.connected = True
        self.resistance = resistance
        self.interlock_open = interlock_open
        self.stuck = set(stuck)
        self.reject = set(reject)
        self.sent = []
        self.errors = []
        self.pending = []
        # As somebody left it at the front panel.
        self.output = False
        self.low = "FLO"
        self.off_mode = "ZERO"
        self.inp = False
        self.level, self.rang = 0.0, 20.0
        self.nplc, self.nplc_auto = 2.0, False
        self.rang_auto, self.cur_rang = False, 2e-9
        self.func = '"VOLT","CURR"'
        self.elements = ALL_ELEMENTS
        self.mov = True
        self.levels_on = []     # every level the output actually held

    def connect(self, address, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False

    # ---- the instrument -----------------------------------------------
    def error(self, code, text):
        self.errors.append(f'{code:+d},"{text}"')

    def current(self):
        """What the ammeter reads, and the status word with it."""
        status = 0
        if not self.inp:
            return INPUT_OFF_READING, status
        amps = OPEN_INPUT_AMPS
        if (self.output and self.low == "COMM"
                and self.resistance is not None):
            amps = self.level / self.resistance
            limit = SPANS[self.rang][2]
            if abs(amps) > limit:
                amps = limit if amps > 0 else -limit
                status |= 1 << 8
        ceiling = (CURRENT_RANGES[-1] if self.rang_auto
                   else self.cur_rang) * 1.05
        if abs(amps) > ceiling:
            # A finite number with the overflow bit: what the reply's
            # number holds on an overflow has not been seen, so the bit
            # is made the only thing that says so. The +/-9.9E37 form is
            # `test_sentinel_handling.py`'s.
            return ceiling, status | 1
        return amps, status

    def reading(self):
        amps, status = self.current()
        values = {"CURR": _sci(amps), "STAT": _sci(status),
                  "VOLT": "+9.91000000E+37", "RES": "+9.91000000E+37",
                  "TIME": "+1.00000000E+00", "SOUR": _sci(self.level),
                  "TEMP": "+9.91000000E+37", "HUM": "+9.91000000E+37"}
        return ",".join(values[e] for e in self.elements.split(","))

    def handle(self, text):
        header, _, arg = text.strip().partition(" ")
        header, arg = header.upper(), arg.strip()
        if header in self.reject:
            self.error(-113, "Undefined header")
            return None
        if header.endswith("?"):
            return self.answer(header)
        if header not in self.stuck:
            self.apply(header, arg)
        return None

    def answer(self, header):
        if header == "SYST:ERR?":
            return self.errors.pop(0) if self.errors else '+0,"No error"'
        if header == "MEAS?":
            return self.reading()
        flag = {True: "1", False: "0"}
        replies = {
            "*IDN?": IDN, "*OPC?": "1",
            "SYST:INT:TRIP?": flag[self.interlock_open],
            "OUTP?": flag[self.output], "INP?": flag[self.inp],
            "OUTP:LOW?": self.low, "OUTP:OFF:MODE?": self.off_mode,
            "SENS:CURR:NPLC:AUTO?": flag[self.nplc_auto],
            "SENS:CURR:NPLC?": _sci(self.nplc),
            "FORM:ELEM:SENS?": self.elements,
            "SOUR:VOLT?": _sci(self.level),
            "SOUR:VOLT:RANG?": _sci(self.rang),
            "SENS:CURR:RANG?": _sci(self.cur_rang),
            "SENS:CURR:RANG:AUTO?": flag[self.rang_auto],
        }
        if header in replies:
            return replies[header]
        self.error(-113, "Undefined header")
        return None

    def apply(self, header, arg):
        number = None
        try:
            number = float(arg)
        except ValueError:
            pass
        on = arg.upper() in ("1", "ON")
        if header == "SOUR:VOLT" and number is not None:
            low, high, _ = SPANS[self.rang]
            if self.interlock_open and abs(number) > 21.0:
                self.error(-222, "Data out of range; Interlock open")
            elif not low <= number <= high:
                self.error(-222, "Data out of range; Source voltage level")
            else:
                self.level = number
                if self.output:
                    self.levels_on.append(number)
        elif header == "SOUR:VOLT:RANG" and number in SPANS:
            if self.output:
                self.error(213, "Output relay must be off")
            else:
                self.rang = number
        elif header == "OUTP":
            self.output = on
            if on:
                self.levels_on.append(self.level)
        elif header == "OUTP:LOW" and arg.upper() in ("COMM", "FLO"):
            if self.output:
                self.error(211, "Cannot switch low sense terminal with "
                                "output on")
            else:
                self.low = arg.upper()
        elif header == "OUTP:OFF:MODE":
            self.off_mode = arg.upper()
        elif header == "INP":
            self.inp = on
        elif header == "SENS:FUNC":
            self.func = arg
        elif header == "FORM:ELEM:SENS":
            self.elements = arg.upper()
        elif header == "SENS:CURR:NPLC" and number is not None:
            self.nplc = number
        elif header == "SENS:CURR:NPLC:AUTO":
            self.nplc_auto = on
        elif header == "SENS:CURR:RANG:AUTO":
            self.rang_auto = on
        elif header == "SENS:CURR:RANG" and number is not None:
            self.cur_rang = next((r for r in CURRENT_RANGES
                                  if r >= number * 0.999), CURRENT_RANGES[-1])
        elif header == "SENS:CURR:AVER:MOV":
            self.mov = on
        elif header == "*RST":
            # Measured: the input off, auto aperture on, the low terminal
            # common - and the element list left exactly as it was.
            self.output, self.low, self.off_mode = False, "COMM", "NORM"
            self.inp, self.level, self.rang = False, 0.0, 20.0
            self.nplc, self.nplc_auto = 0.1, True
            self.rang_auto, self.mov = True, False
            self.func = '"VOLT","CURR"'
        elif header == "*CLS":
            self.errors = []
        elif header in ("FORM", "SENS:CURR:MED", "SENS:CURR:REF:STAT",
                        "INP:ZCOR", "SOUR:WAIT", "SOUR:WAIT:AUTO",
                        "SENS:WAIT", "SENS:WAIT:AUTO"):
            pass
        else:
            self.error(-113, "Undefined header")

    # ---- the link -----------------------------------------------------
    def _write(self, text):
        self.sent.append(text)
        reply = self.handle(text)
        if reply is not None:
            self.pending.append(reply)

    def _read(self, timeout_s=3.0):
        if self.pending:
            return self.pending.pop(0)
        raise TimeoutError("fake: no reply")


def connected_fake(**fake):
    """A B2987A as a connect leaves it: reset, nothing else sent since.

    The fleet-wide suites take their fakes from `CASES` and drive the
    driver without calling `reset()`, and from the front panel's state
    this instrument's replies carry eight elements - which the driver
    rightly refuses to parse. Every real connect resets first.
    """
    transport = FakeB2987A(**fake)
    KeysightB2987A(transport).reset()
    transport.sent.clear()
    return transport


def connected(**fake):
    transport = FakeB2987A(**fake)
    driver = KeysightB2987A(transport)
    driver.reset()
    transport.sent.clear()
    return driver, transport


def writes(transport):
    return [t for t in transport.sent if "?" not in t]


# ---- reset ---------------------------------------------------------------

def test_reset_states_everything_and_switches_the_input_on(check):
    transport = FakeB2987A()
    KeysightB2987A(transport).reset()
    sent = writes(transport)
    check("*RST first", sent[:2] == ["*RST", "*CLS"], f"{sent[:2]}")
    for command in ("OUTP:LOW COMM", "OUTP:OFF:MODE NORM",
                    "SOUR:VOLT:RANG 20", 'SENS:FUNC "CURR"',
                    "SENS:CURR:NPLC:AUTO OFF", "SENS:CURR:NPLC 1",
                    "FORM:ELEM:SENS CURR,STAT", "SOUR:WAIT:AUTO ON",
                    "SENS:WAIT:AUTO ON"):
        check(f"sent {command}", command in sent)
    check("the input on, and last", sent[-1] == "INP 1", f"{sent[-1]}")
    check("the instrument took it", transport.inp and transport.low == "COMM"
          and transport.elements == "CURR,STAT"
          and not transport.nplc_auto, "")
    check("no other dialect", not any(
        t.startswith((":SENS:CURR:PROT", "smu", "SYST:BATT")) or t.endswith("X")
        for t in transport.sent), f"{transport.sent}")


@pytest.mark.parametrize("stuck, said", [
    ("INP", "ammeter input is off"),
    ("FORM:ELEM:SENS", "not in the shape"),
    ("SENS:CURR:NPLC:AUTO", "auto aperture"),
])
def test_a_reset_that_did_not_take_is_refused(stuck, said):
    driver = KeysightB2987A(FakeB2987A(stuck={stuck}))
    with pytest.raises(RuntimeError, match=said):
        driver.reset()


def test_a_refused_reset_command_is_refused(check):
    driver = KeysightB2987A(FakeB2987A(reject={"SENS:CURR:MED"}))
    with pytest.raises(RuntimeError, match="-113"):
        driver.reset()


def test_the_input_off_reading_would_have_passed_unnoticed(check):
    """Why reset reads INP? back: without it, a reading is a number."""
    driver, transport = connected()
    transport.inp = False
    _, amps = driver.measure()
    check("a plausible number", amps == INPUT_OFF_READING, f"{amps}")


# ---- source ranges -------------------------------------------------------

@pytest.mark.parametrize("span, expected", [(5.0, 20.0), (21.0, 20.0),
                                            (21.5, 1000.0), (1000.0, 1000.0)])
def test_the_range_for_a_span(check, span, expected):
    driver, transport = connected()
    driver._apply_source_voltage_range(span)
    check(f"{span} V -> {expected} V range", transport.rang == expected,
          f"{transport.rang}")
    check("at 0 V", transport.level == 0.0)


def test_the_1000_v_ranges_need_the_interlock_closed(check):
    driver, transport = connected(interlock_open=True)
    with pytest.raises(RangeError, match="interlock is open"):
        driver._apply_source_voltage_range(50.0)
    check("nothing changed", transport.rang == 20.0
          and not writes(transport), f"{transport.sent}")


@pytest.mark.parametrize("interlock_open, expected", [(True, 20.0),
                                                      (False, 1000.0)])
def test_auto_takes_the_widest_the_interlock_allows(check, interlock_open,
                                                    expected):
    for value in (AUTO, NOT_SOURCED):
        driver, transport = connected(interlock_open=interlock_open)
        driver._apply_source_voltage_range(value)
        check(f"{value} -> {expected}", transport.rang == expected)


def test_beyond_1000_v_is_refused():
    driver, _ = connected()
    with pytest.raises(RangeError):
        driver._apply_source_voltage_range(1001.0)


def test_no_range_change_with_the_output_on(check):
    driver, transport = connected()
    driver.output_on()
    with pytest.raises(RangeError, match="output on"):
        driver._apply_source_voltage_range(50.0)
    check("the instrument was not asked", not transport.errors)


def test_a_level_the_range_cannot_hold_never_reaches_the_wire(check):
    driver, transport = connected()
    driver._apply_source_voltage_range(10.0)
    transport.sent.clear()
    with pytest.raises(RangeError, match="20 V range"):
        driver.set_voltage_level(25.0)
    check("nothing sent", not transport.sent, f"{transport.sent}")


# ---- the two-step sweep --------------------------------------------------

def test_a_level_on_the_other_side_switches_through_zero(check):
    driver, transport = connected(resistance=1e9)
    driver._apply_source_voltage_range(50.0)
    driver.set_voltage_level(-50.0)        # output off: just the range
    check("-1000 V range before output on", transport.rang == -1000.0)
    driver.output_on()
    transport.sent.clear()
    driver.set_voltage_level(-10.0)
    driver.set_voltage_level(0.5)          # reachable on either: no switch
    check("no switch inside +/-1 V", transport.rang == -1000.0
          and "OUTP 0" not in transport.sent, f"{transport.sent}")
    driver.set_voltage_level(10.0)
    sent = transport.sent
    check("0 V, open, range, close, level", sent[-5:] == [
        "SOUR:VOLT 0", "OUTP 0", "SOUR:VOLT:RANG 1000", "OUTP 1",
        "SOUR:VOLT 1.000000e+01"], f"{sent[-5:]}")
    check("on the +1000 V range at 10 V", transport.rang == 1000.0
          and transport.level == 10.0 and transport.output)
    check("counted", driver.crossings == 1)
    check("nothing refused", not transport.errors, f"{transport.errors}")


def test_a_software_sweep_through_zero_beyond_21_v(check):
    """-100 V to +100 V, 21 points, on a 1 GOhm sample: every point is
    read at its own level, the switch happens once, and the output never
    held a level it was not asked for other than the 0 V of the switch."""
    driver, transport = connected(resistance=1e9)
    driver._apply_source_voltage_range(100.0)
    driver.set_current_limit(HIGH_RANGE_LIMIT_A)
    driver.set_voltage_level(-100.0)
    driver.output_on()
    driver.start_linear_sweep("voltage", -100.0, 100.0, 21, 0.0)
    sourced, measured = driver.read_sweep(21)
    check("21 points", len(measured) == 21, f"{len(measured)}")
    check("each current is its own level over R", all(
        abs(i - v / 1e9) < 1e-15 for v, i in zip(sourced, measured)),
        f"{list(zip(sourced, measured))[:3]}")
    check("one switch", driver.crossings == 1, f"{driver.crossings}")
    check("nothing refused", not transport.errors, f"{transport.errors}")
    asked = {round(-100.0 + 10.0 * i, 9) for i in range(21)} | {0.0}
    check("only asked levels and the switch's 0 V", set(
        round(v, 9) for v in transport.levels_on) <= asked,
        f"{sorted(set(transport.levels_on))}")


def test_a_sweep_on_the_20_v_range_never_switches(check):
    driver, transport = connected(resistance=1e6)
    driver._apply_source_voltage_range(20.0)
    driver.output_on()
    driver.start_linear_sweep("voltage", -20.0, 20.0, 11, 0.0)
    driver.read_sweep(11)
    check("never opened", "OUTP 0" not in transport.sent)
    check("the 20 V range throughout", transport.rang == 20.0)


# ---- compliance ----------------------------------------------------------

def test_the_compliance_is_the_range_s(check):
    driver, _ = connected()
    check("a menu, the common case first", driver.compliance_choices(
        "current") == (LOW_RANGE_LIMIT_A, HIGH_RANGE_LIMIT_A))
    driver._apply_source_voltage_range(10.0)
    driver.set_current_limit(20e-3)
    with pytest.raises(LimitError, match="choose 20 mA"):
        driver.set_current_limit(1e-3)
    driver._apply_source_voltage_range(100.0)
    driver.set_current_limit(1e-3)
    with pytest.raises(LimitError, match="choose 1 mA"):
        driver.set_current_limit(20e-3)
    with pytest.raises(LimitError, match="nothing else"):
        driver.set_current_limit(5e-3)


def test_nothing_is_sent_for_a_compliance(check):
    driver, transport = connected()
    driver._apply_source_voltage_range(10.0)
    transport.sent.clear()
    driver.set_current_limit(20e-3)
    check("no command", not transport.sent, f"{transport.sent}")


def test_run_time_validation(check):
    driver, _ = connected()
    driver.validate_source_point(current=20e-3, voltage=21.0,
                                 sourcing="voltage")
    driver.validate_source_point(current=1e-3, voltage=-500.0,
                                 sourcing="voltage")
    with pytest.raises(LimitError, match="Choose the 1 mA"):
        driver.validate_source_point(current=20e-3, voltage=50.0,
                                     sourcing="voltage")
    with pytest.raises(LimitError, match="nothing else"):
        driver.validate_source_point(current=1e-6, voltage=5.0,
                                     sourcing="voltage")
    with pytest.raises(LimitError, match="cannot source current"):
        driver.validate_source_point(current=1e-6, voltage=5.0,
                                     sourcing="current")
    with pytest.raises(LimitError):
        driver.validate_source_point(current=1e-3, voltage=1500.0,
                                     sourcing="voltage")


def test_a_reading_at_the_limit_is_flagged(check):
    driver, transport = connected(resistance=100.0)
    driver._apply_source_voltage_range(10.0)
    transport.sent.clear()
    check("before any reading, it takes one", driver.compliance_tripped()
          is False and transport.sent == ["MEAS?"], f"{transport.sent}")
    driver.set_voltage_level(1.0)
    driver.output_on()
    _, amps = driver.measure()
    check("10 mA, not at the limit", abs(amps - 0.01) < 1e-9
          and driver.compliance_tripped() is False, f"{amps}")
    driver.set_voltage_level(10.0)
    _, amps = driver.measure()
    check("held at 20 mA and flagged", amps == pytest.approx(0.02)
          and driver.compliance_tripped() is True, f"{amps}")


# ---- measurement ---------------------------------------------------------

def test_a_reading_is_the_current_alone(check):
    driver, _ = connected(resistance=1e6)
    driver._apply_source_voltage_range(10.0)
    driver.set_voltage_level(5.0)
    driver.output_on()
    volts, amps = driver.measure()
    check("no voltage", volts is None)
    check("V/R", amps == pytest.approx(5e-6), f"{amps}")
    driver.set_voltage_level(-5.0)
    check("and its sign", driver.measure()[1] == pytest.approx(-5e-6))


def test_an_overflow_is_no_reading(check):
    driver, transport = connected(resistance=1e6)
    driver._apply_source_voltage_range(10.0)
    driver._apply_measure_current_range(2e-9)
    check("fixed range, auto off", not transport.rang_auto
          and transport.cur_rang == 2e-9)
    driver.set_voltage_level(5.0)
    driver.output_on()
    check("none", driver.measure()[1] is None)


def test_the_interlock_opening_mid_run_stops_it(check):
    driver, transport = connected(resistance=1e9)
    driver._apply_source_voltage_range(100.0)
    driver.set_voltage_level(50.0)
    driver.output_on()
    driver.measure()
    transport.interlock_open = True
    transport.output = False            # what the instrument does itself
    with pytest.raises(RuntimeError, match="interlock opened"):
        driver.measure()


def test_the_interlock_is_not_asked_on_the_20_v_range(check):
    driver, transport = connected()
    driver._apply_source_voltage_range(10.0)
    driver.output_on()
    transport.sent.clear()
    driver.measure()
    check("one query", transport.sent == ["MEAS?"], f"{transport.sent}")


def test_a_reading_in_another_shape_is_refused():
    with pytest.raises(ValueError, match="status word"):
        KeysightB2987A._parse_reading("+1.0E-12")
    with pytest.raises(ValueError):
        KeysightB2987A._parse_reading("+1.0E-12,+0.0E+00,+1.0E+00")


def test_the_measure_range_is_snapped_up(check):
    driver, transport = connected()
    driver._apply_measure_current_range(3e-9)
    check("20 nA", transport.cur_rang == 20e-9, f"{transport.cur_rang}")
    driver._apply_measure_current_range(1.0)
    check("the widest", transport.cur_rang == 20e-3)
    driver._apply_measure_current_range(AUTO)
    check("auto", transport.rang_auto)


# ---- output --------------------------------------------------------------

def test_output_off_is_writes_only(check):
    driver, transport = connected()
    driver.output_on()
    transport.sent.clear()
    driver.output_off()
    check("0 V then off", transport.sent == ["SOUR:VOLT 0", "OUTP 0"],
          f"{transport.sent}")


def test_an_output_that_did_not_switch_on_is_refused(check):
    driver, transport = connected(interlock_open=True)
    transport.stuck.add("OUTP")
    with pytest.raises(RuntimeError, match="interlock is open"):
        driver.output_on()


def test_no_current_source_and_no_sense(check):
    driver, _ = connected()
    with pytest.raises(ValueError):
        driver.set_source_function("current")
    with pytest.raises(NotImplementedError):
        driver.set_current_level(1e-6)
    with pytest.raises(NotImplementedError):
        driver.set_remote_sense(True)
    driver.set_remote_sense(False)


def test_nplc_any_value_inside_the_window(check):
    driver, transport = connected()
    driver.set_nplc(0.5)
    check("0.5 as asked", transport.nplc == 0.5)
    driver.set_nplc(500)
    check("clamped", transport.nplc == 100.0)


def test_errors(check):
    driver, transport = connected()
    transport.error(-222, "Data out of range; Interlock open")
    check("parsed", driver.read_error() == (
        -222, "Data out of range; Interlock open"))
    check("then empty", driver.read_error() == (0, "No error"))


def test_identity(check):
    driver, _ = connected()
    check("*IDN?", driver.identify() == IDN)
    check("model id", "B2987A" in KeysightB2987A.MODEL_IDS)


# ---- the checkup -----------------------------------------------------------

def _checkup_rows(**fake):
    from smuniversal_lab_suite.core.checkup import Checkup

    checkup = Checkup(KeysightB2987A(connected_fake(**fake)),
                      open_circuit=False)
    checkup.run()
    return {r.name: r for r in checkup.results}


@pytest.mark.parametrize("interlock_open", [True, False])
def test_the_checkup_reads_back_the_ranges_it_asked_for(check,
                                                        interlock_open):
    """2026-11-18: with the interlock closed the checkup failed its source
    range readback. It read the range while its all-AUTO plan was still
    in force - the 1000 V range, once the interlock allows it - and
    compared that with the 0.1 V probe level."""
    row = _checkup_rows(interlock_open=interlock_open)[
        "range readback: source voltage"]
    check("not a failure", row.severity != "fail",
          f"{row.severity}: {row.detail}")
    check("the 20 V range", "21 V" in row.detail, row.detail)


def test_the_checkup_sees_the_compliance_flag(check):
    """It said "not implemented by this driver" on 2026-11-18: asked with
    the output off and no reading yet, the flag answered None."""
    rows = _checkup_rows()
    row = rows["compliance_tripped()"]
    check("False with the output off", row.severity == "pass",
          f"{row.severity}: {row.detail}")
    check("and the blindness sentence is the milder one", "does report the "
          "compliance *flag*" in rows["compliance survives ranging"].detail,
          rows["compliance survives ranging"].detail)
