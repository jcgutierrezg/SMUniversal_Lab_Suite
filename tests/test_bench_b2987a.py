"""The B2987A's first sitting, walked offline against a fake B2987A.

Each question the reference leaves open is a switch on the fake: what a
level beyond its range does (refused, clipped, or the range moves),
whether the range can change with the source on, what `*RST` leaves on
the low terminal, whether a reading switches the ammeter input on, and
whether the source holds its 20 mA or trips. The tool has to record the
answer for both settings of each, and a tool that only passed against
the manual's reading would be caught here rather than at the bench.
"""
import math

import pytest

from smuniversal_lab_suite.core.transports.base import Transport
from tools.bench_b2987a import (
    MAX_ON_V,
    Session,
    build_report,
    error_code,
    fixed_range_for,
    number,
    ohms,
    reading,
    settle_summary,
    status_names,
)

IDN = "Keysight Technologies,B2987A,MY00000001,1.0.0000.0000"

#: Each source range: (lowest level, highest level, current limit).
SPANS = {20.0: (-21.0, 21.0, 20e-3), 1000.0: (-1.0, 1000.0, 1e-3),
         -1000.0: (-1000.0, 1.0, 1e-3)}

NAN = "+9.910000E+37"
ESR_BITS = {"command": 32, "execution": 16, "device": 8}


class Instrument:
    """The electrometer: its settings, its output, and what is wired to
    it. Outlives any one connection, as the real one does."""

    def __init__(self, interlock_open=True, beyond_range="error",
                 range_change_on="allowed", low_after_rst="COMM",
                 reading_switches_input=False, limit="holds",
                 off_zeroes_setting=False, silent_queries=(),
                 late_reply=None, sign=1):
        self.interlock_open = interlock_open
        self.beyond_range = beyond_range
        self.range_change_on = range_change_on
        self.low_after_rst = low_after_rst
        self.reading_switches_input = reading_switches_input
        self.limit = limit
        self.off_zeroes_setting = off_zeroes_setting
        self.silent_queries = silent_queries
        self.late_reply = late_reply
        #: -1 for an ammeter that reads current into its input as negative.
        self.sign = sign
        # As somebody left it at the front panel.
        self.output = False
        self.low = "FLO"
        self.off_mode = "NORM"
        self.inp = False
        self.level, self.rang = 0.0, 20.0
        self.nplc, self.mov = 1.0, False
        self.rang_auto, self.cur_rang = True, 20e-3
        self.func = '"VOLT","CURR"'
        self.elements = "CURR"
        self.over = False
        self.errors = []
        self.esr = 0
        #: None, ("ammeter", ohms) or ("across", ohms).
        self.wiring = None
        self.amps = 0.0
        self.now = 0.0
        self.amps_at = 0.0
        self.stream = []
        self.sent = []
        self.owed_late = False
        self.max_on_v = 0.0
        self.self_tests = 0

    def advance(self, seconds):
        self.now += seconds

    def error(self, code, text, kind):
        self.errors.append(f'{code:+d},"{text}"')
        self.esr |= ESR_BITS[kind]

    # ---- physics ----
    def _current(self):
        """The current the ammeter would read now, with a 50 ms time
        constant so part 3's settling has something to time."""
        target = 1e-15
        if (self.output and self.low == "COMM" and self.wiring
                and self.wiring[0] == "ammeter"):
            target = self.sign * self.level / self.wiring[1]
        k = 1 - math.exp(-(self.now - self.amps_at) / 0.05)
        self.amps += (target - self.amps) * k
        self.amps_at = self.now
        return self.amps

    def _source_load(self):
        """Over the limit across part 4's resistor: hold, or trip."""
        self.over = False
        if not (self.output and self.wiring and self.wiring[0] == "across"):
            return
        if abs(self.level) / self.wiring[1] <= SPANS[self.rang][2]:
            return
        if self.limit == "trips":
            self.output = False
            self.error(304, "Emergency; source over current detected",
                       "device")
        else:
            self.over = True

    def _watch(self):
        if self.output:
            self.max_on_v = max(self.max_on_v, abs(self.level))

    # ---- the command set ----
    def handle(self, text):
        header, _, arg = text.strip().partition(" ")
        header, arg = header.upper(), arg.strip().upper()
        if header.endswith("?"):
            return self.query(header, arg)
        self.write(header, arg)
        self._source_load()
        self._watch()
        return None

    def query(self, header, arg):
        if header in self.silent_queries:
            self.owed_late = self.late_reply is not None
            return None
        if header == "SYST:ERR?":
            return self.errors.pop(0) if self.errors else '+0,"No error"'
        if header == "*ESR?":
            value, self.esr = self.esr, 0
            return f"+{value}"
        if header in ("MEAS?", "MEAS:CURR?"):
            return self._measure(header)
        if header == "*TST?":
            self.self_tests += 1
            return "+0"
        flag = {True: "1", False: "0"}
        replies = {
            "*IDN?": IDN, "*OPT?": "0", "SYST:VERS?": "1999.0",
            "SYST:INT:TRIP?": flag[self.interlock_open],
            "SYST:BATT?": "+85", "SYST:LFR?": "+50",
            "OUTP?": flag[self.output], "OUTP:LOW?": self.low,
            "OUTP:OFF:MODE?": self.off_mode, "INP?": flag[self.inp],
            "INP:ZCOR?": "0", "SOUR:FUNC:MODE?": "VOLT",
            "SOUR:VOLT:MODE?": "FIX", "SOUR:VOLT?": f"{self.level:+.6E}",
            "SOUR:VOLT:RANG?": f"{self.rang:+.6E}",
            "SOUR:VOLT:RLIM:STAT?": "0", "SOUR:WAIT?": "1",
            "SOUR:WAIT:AUTO?": "1", "SENS:FUNC?": self.func,
            "SENS:CURR:NPLC?": f"{self.nplc:+.6E}",
            "SENS:CURR:NPLC:AUTO?": "0",
            "SENS:CURR:APER?": f"{self.nplc / 50:+.6E}",
            "SENS:CURR:APER:AUTO?": "0",
            "SENS:CURR:RANG?": f"{self.cur_rang:+.6E}",
            "SENS:CURR:RANG:AUTO?": flag[self.rang_auto],
            "SENS:CURR:RANG:AUTO:LLIM?": "+2.000000E-12",
            "SENS:CURR:AVER:MOV?": flag[self.mov], "SENS:CURR:MED?": "0",
            "SENS:CURR:REF:STAT?": "0", "SENS:WAIT?": "1",
            "SENS:WAIT:AUTO?": "1", "FORM?": "ASC,+0",
            "FORM:ELEM:SENS?": self.elements, "*STB?": "+0", "*OPC?": "+1",
        }
        if header in replies:
            return replies[header]
        self.error(-113, "Undefined header", "command")
        return None

    def _measure(self, header):
        self.advance(0.02 * max(self.nplc, 0.1))
        if not self.inp:
            if not self.reading_switches_input:
                return NAN
            self.inp = True
        amps = f"{self._current():+.6E}"
        if header == "MEAS:CURR?" or "STAT" not in self.elements:
            return amps
        return f"{amps},{256 if self.over else 0:+.6E}"

    def write(self, header, arg):
        value = number(arg)
        if header == "SOUR:VOLT" and value is not None:
            self._set_level(value)
        elif header == "SOUR:VOLT:RANG" and value in SPANS:
            if self.output and self.range_change_on == "refused":
                self.error(214, "Output relay must be off", "execution")
            else:
                self._current()
                self.rang = value
        elif header == "OUTP" and arg in ("0", "1"):
            self._current()
            if arg == "1" and self.interlock_open and abs(self.level) > 21:
                self.error(305, "Interlock open", "device")
            else:
                self.output = arg == "1"
                if arg == "0" and self.off_zeroes_setting:
                    self.level = 0.0
        elif header == "OUTP:LOW" and arg in ("FLO", "COMM"):
            if self.output:
                self.error(211, "Cannot switch low terminal with output "
                                "on", "execution")
            else:
                self.low = arg
        elif header == "OUTP:OFF:MODE" and arg in ("NORM", "ZERO", "HIZ"):
            self.off_mode = arg
        elif header == "INP" and arg in ("0", "1"):
            self.inp = arg == "1"
        elif header == "SENS:FUNC":
            self.func = arg
        elif header == "FORM:ELEM:SENS":
            self.elements = arg
        elif header == "SENS:CURR:NPLC" and value is not None:
            self.nplc = value
        elif header == "SENS:CURR:RANG" and value is not None:
            self.rang_auto = False
            self.cur_rang = fixed_range_for(value / 1.1)
        elif header in ("SENS:CURR:RANG:AUTO", "SENS:CURR:APER:AUTO"):
            if header.endswith("RANG:AUTO"):
                self.rang_auto = arg in ("1", "ON")
        elif header == "SENS:CURR:AVER:MOV":
            self.mov = arg in ("1", "ON")
        elif header == "*RST":
            self.output, self.low, self.off_mode = False, \
                self.low_after_rst, "NORM"
            self.inp, self.level, self.rang = False, 0.0, 20.0
            self.nplc, self.mov, self.rang_auto = 0.1, False, True
            self.func, self.elements = '"VOLT","CURR"', "CURR"
        elif header == "*CLS":
            self.errors, self.esr = [], 0
        else:
            self.error(-113, "Undefined header", "command")

    def _set_level(self, value):
        low, high, _ = SPANS[self.rang]
        if low <= value <= high:
            self.level = value
        elif self.beyond_range == "clip":
            self.level = min(max(value, low), high)
        elif self.beyond_range == "autorange":
            fits = [r for r, (lo, hi, _) in SPANS.items() if lo <= value <= hi]
            if fits and not self.output:
                self.rang, self.level = fits[0], value
            else:
                self.error(-222, "Data out of range", "execution")
        else:
            self.error(-222, "Data out of range", "execution")


class Link(Transport):
    """One connection."""

    def __init__(self, instrument):
        super().__init__()
        self.instrument = instrument
        self.connected = True

    def connect(self, address, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False

    def clear(self):
        self.instrument.stream.clear()
        return True

    def _write(self, text):
        inst = self.instrument
        inst.advance(0.002)
        inst.sent.append(text)
        reply = inst.handle(text)
        if reply is not None:
            inst.stream.append(reply)

    def _read(self, timeout_s=3.0):
        inst = self.instrument
        inst.advance(0.005)
        if inst.stream:
            return inst.stream.pop(0)
        inst.advance(timeout_s)
        if inst.owed_late:
            inst.stream.append(inst.late_reply)
            inst.owed_late = False
        raise TimeoutError("fake: no reply")


def wire(kind, value):
    """An operator answer that wires the fake and types the value."""
    def answer(inst):
        inst.wiring = (kind, ohms(value))
        return value
    return answer


SAMPLE = {"Part 3 needs": wire("ammeter", "10M")}
LIMIT = {"Part 4 asks": wire("across", "220")}


def sitting(answers=None, **fake):
    inst = Instrument(**fake)
    answers = answers or {}

    def ask(prompt):
        for phrase, answer in answers.items():
            if phrase in prompt:
                return answer(inst) if callable(answer) else answer
        return ""

    session = Session(lambda: Link(inst), log=lambda message: None, ask=ask,
                      sleep=inst.advance, clock=lambda: inst.now)
    return session, inst


def headline(session, start):
    return next(h for h in session.headlines if h.startswith(start))


def test_the_whole_sitting_on_the_manual_s_reading(check):
    session, inst = sitting({**SAMPLE, **LIMIT})
    session.run(watching=True)
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")
    check("identified", session.idn == IDN)
    check("interlock read", session.found.get("interlock_open") is True)
    check("every query answered", not session.silent, f"{session.silent}")
    check("output off", inst.output is False)
    check("never above the guard", inst.max_on_v <= MAX_ON_V,
          f"{inst.max_on_v}")
    check("low put back as found", inst.low == "COMM", inst.low)
    check("the input off", inst.inp is False)


def test_nothing_answering_stops_before_anything_is_written(check):
    session, inst = sitting(silent_queries=("*IDN?",))
    session.run()
    check("not alive", session.alive is False)
    check("said why", "GPIB interface" in headline(session, "identity"))
    check("nothing written", not [t for t in inst.sent if "?" not in t
                                  and t not in ("OUTP 0", "SOUR:VOLT 0")],
          f"{inst.sent}")
    check("no crash", session.stopped_early is None)


@pytest.mark.parametrize("behaviour, expected", [
    ("error", "SOUR:VOLT 25 -> -222"),
    ("clip", "SOUR:VOLT 25 -> no error, SOUR:VOLT? +2.100000E+01"),
    ("autorange", "SOUR:VOLT 25 -> no error, SOUR:VOLT? +2.500000E+01, "
                  "SOUR:VOLT:RANG? +1.000000E+03"),
])
def test_a_level_beyond_its_range_is_recorded_whatever_it_does(
        check, behaviour, expected):
    session, inst = sitting(beyond_range=behaviour)
    session.run(with_output=False)
    text = headline(session, "refusals")
    check("recorded", expected in text, text)
    check("the one-sided range too", "SOUR:VOLT -5 ->" in text, text)
    check("and put back", inst.level == 0.0 and inst.rang == 20.0,
          f"{inst.level}, {inst.rang}")


def test_a_stored_level_above_the_guard_is_never_switched_on(check):
    """1.3 stores 25 V on purpose. A put-back that did not land must stop
    the sitting, not reach OUTP 1."""
    session, inst = sitting()
    session.run(with_output=False)
    session._open()
    inst.level = 25.0
    inst._set_level = lambda value: None   # the put-back does not land
    with pytest.raises(RuntimeError, match="reports a level"):
        session.turn_on(1.0)
    check("never on", inst.output is False)


def test_reset_is_recorded_for_both_readings_of_the_low_terminal(check):
    for low in ("COMM", "FLO"):
        session, _ = sitting(low_after_rst=low)
        session.run(with_output=False)
        check(f"{low} found", session.found.get("low_after_rst") == low,
              f"{session.found.get('low_after_rst')}")
        # The fake was left floating at the front panel, so a reset to
        # COMMon is a change and a reset to FLOat is not.
        text = headline(session, "*RST changed")
        changed, _, kept = text.partition("left as it was")
        shown = ("OUTP:LOW? FLO -> COMM" in changed if low == "COMM"
                 else "OUTP:LOW? FLO;" in kept)
        check(f"{low} in the headline", shown and "INP? 1 -> 0" in changed,
              text)


def test_a_reading_with_the_input_off(check):
    session, _ = sitting()
    session.run(with_output=False)
    check("not switched on", session.found.get(
        "reading_switches_input_on") is False)
    check("not a number recorded", NAN in headline(session, "readings"))
    session, _ = sitting(reading_switches_input=True)
    session.run(with_output=False)
    check("switched on", session.found.get(
        "reading_switches_input_on") is True)


def test_the_reading_shape_and_timings(check):
    session, _ = sitting()
    session.run(with_output=False)
    text = headline(session, "readings")
    check("current and status", "+0.000000E+00'" in text, text)
    check("three timings", text.count(" ms") >= 3, text)


@pytest.mark.parametrize("behaviour", ["allowed", "refused"])
def test_a_range_change_with_the_source_on(check, behaviour):
    session, inst = sitting(range_change_on=behaviour)
    session.run()
    text = headline(session, "range change with the source on")
    check("interlock named", "interlock open" in text, text)
    if behaviour == "refused":
        check("the refusal", "SOUR:VOLT:RANG 1000 at 5 V -> +214" in text,
              text)
    else:
        check("all four tried", text.count(" at ") == 4, text)
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")
    check("output off", inst.output is False)


def test_off_and_the_level_setting(check):
    for zeroes in (False, True):
        session, _ = sitting(off_zeroes_setting=zeroes)
        session.run()
        check(f"zeroes={zeroes}",
              session.found.get("off_keeps_level_setting") is not zeroes,
              f"{session.found}")


def test_part_three_against_a_resistor(check):
    session, inst = sitting(SAMPLE)
    session.run()
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")
    check("floating blocks", session.found.get(
        "floating_low_blocks_current") is True, f"{session.found}")
    check("signs agree", session.found.get(
        "positive_volts_read_positive_amps") is True)
    vr = headline(session, "current against V/R")
    check("ratios", vr.count("x1.0000 of V/R") >= 4, vr)
    check("settles", "inside 2% of the step" in headline(
        session, "settling"))
    check("the fixed range", "2e-06 A range" in headline(
        session, "settling"))
    check("output off", inst.output is False)


def test_a_current_of_the_opposite_sign_is_found(check):
    session, _ = sitting(SAMPLE, sign=-1)
    session.run()
    check("found", session.found.get(
        "positive_volts_read_positive_amps") is False, f"{session.found}")
    check("ratios negative", "x-1.0000 of V/R" in headline(
        session, "current against V/R"))


def test_part_three_refuses_a_low_resistor(check):
    session, inst = sitting({"Part 3 needs": wire("ammeter", "1k")})
    session.run()
    check("refused", any(h.startswith("part 3 not run")
                         for h in session.headlines))
    check("never through it", inst.max_on_v <= 5.0)


@pytest.mark.parametrize("limit, found", [("holds", "holds, status bit 8"),
                                          ("trips", "trips")])
def test_the_current_limit(check, limit, found):
    session, inst = sitting({**LIMIT, "run it now": "y"}, limit=limit)
    session.run(watching=True)
    check("found", session.found.get("source_limit") == found,
          f"{session.found}")
    text = headline(session, "limit through 220 ohm")
    if limit == "holds":
        check("bit 8 named", "voltage source over current" in text, text)
        check("no self test", inst.self_tests == 0)
    else:
        check("the emergency", "Emergency" in text, text)
        check("self test on the operator's yes", inst.self_tests == 1)
    check("output off", inst.output is False)
    check("never above the guard", inst.max_on_v <= MAX_ON_V)


def test_part_four_refuses_a_resistor_out_of_its_window(check):
    for value in ("47", "1k"):
        session, inst = sitting({"Part 4 asks": wire("across", value)})
        session.run()
        check(f"{value} refused", any(h.startswith("part 4 not run")
                                      for h in session.headlines))


def test_a_late_reply_is_cleared_not_used(check):
    session, _ = sitting(silent_queries=("SYST:BATT?",), late_reply="LATE")
    session.run(with_output=False)
    check("recorded silent", "SYST:BATT?" in session.silent)
    check("never taken as an answer", not any(
        s["result"] == "LATE" for s in session.steps))
    check("device clear recorded", any("device clear" in s["note"]
                                       for s in session.steps))
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")


def test_ctrl_c_with_the_source_on_turns_it_off(check):
    def interrupt(inst):
        assert inst.output is True
        raise KeyboardInterrupt

    session, inst = sitting({"meter on Voltage Source": interrupt})
    session.run()
    check("stopped", session.stopped_early == "interrupted by Ctrl-C")
    check("output off", inst.output is False)
    check("level 0", inst.level == 0.0)


def test_the_guards(check):
    session, _ = sitting()
    with pytest.raises(RuntimeError):
        session.turn_on(MAX_ON_V + 1)
    session.output_on = True
    with pytest.raises(RuntimeError):
        session.set_level(-(MAX_ON_V + 1))


def test_never_sent(check):
    session, inst = sitting({**SAMPLE, **LIMIT})
    session.run(watching=True)
    writes = [t.upper() for t in inst.sent if "?" not in t]
    banned = ("*SAV", "*RCL", "MMEM", "PROG", "INIT", "TRIG", "ARM",
              "LXI", "SOUR:VOLT:MODE", "SOUR:LIST", "SOUR:ARB", "SOUR:SWE",
              "CHAR", "CALC", "SYST:COMM", "SYST:GPIB", "RLIM")
    check("none", not [w for w in writes if any(b in w for b in banned)],
          f"{[w for w in writes if any(b in w for b in banned)]}")
    check("no self test unasked", "*TST?" not in inst.sent)
    check("ascii", all(t.isascii() for t in inst.sent))


def test_the_report(check):
    session, _ = sitting(SAMPLE)
    session.run()
    session._step("a reply with a | in it", "x|y")
    report = build_report(session, "USB0::FAKE::INSTR", {})
    check("headlines", "## Headlines" in report)
    check("every part", all(f"## {p}" in report for p in (
        "1.1 who it is", "1.3 refusals", "1.4 *RST", "2.2 range change, "
        "source on", "3 a resistor to the ammeter")))
    check("pipes escaped", "| a reply with a \\| in it | x\\|y |" in report)


def test_the_helpers(check):
    check("numbers", number("+1.2E+01") == 12.0 and number("FLO") is None)
    check("error codes", error_code('-222,"Data out of range"') == -222
          and error_code('+0,"No error"') == 0)
    check("a reading", reading("+1.5E-12,+2.560000E+02") == (1.5e-12, 256))
    check("not a number", reading(NAN) == (None, None))
    check("status", status_names(256 + 1) == [
        "current/charge overflow", "voltage source over current"])
    check("ohms", ohms("10M") == 10e6 and ohms("2.2 kOhm") == 2200
          and ohms("x") is None)
    check("fixed range", fixed_range_for(1e-6) == 2e-6
          and fixed_range_for(1.9e-6) == 20e-6)
    check("too few", "too few" in settle_summary([(0.0, 1.0)], 0, 1, "A"))
