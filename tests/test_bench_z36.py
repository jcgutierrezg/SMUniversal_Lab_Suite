"""The Z36-24's first sitting, walked offline against a fake Z+.

What the tool has to get right is the connection questions the manual
leaves open, and each is a switch on the fake: whether `*IDN?` waits for
`INST:NSEL`, whether a reopened port or a `*RST` forgets the selection,
whether the baud matters over USB, and whether the unit was left in the
GEN language. The fake is a byte stream, so a late reply or an `OK` to a
write lands where a real one would, and a tool that read it as the next
answer would be caught here rather than at the bench.
"""
import math
import re

import pytest

from smuniversal_lab_suite.core.transports.base import Transport
from tools.bench_z36 import (
    MAX_ON_A,
    MAX_ON_V,
    Session,
    build_report,
    error_code,
    number,
    settle_summary,
)

IDN = "TDK-Lambda,Z36-24,TEST001,1.0-C1"

#: Rated plus the 5% the manual says is accepted.
V_ACCEPTED, A_ACCEPTED = 36 * 1.05, 24 * 1.05
OVP_MIN, OVP_MAX = 2.0, 40.0

ESR_BITS = {"command": 32, "execution": 16, "device": 8}


class Instrument:
    """The supply: its settings, its output, and the bytes in flight.
    Outlives any one connection, as the real one does."""

    def __init__(self, needs_nsel=True, address=6, baud=9600,
                 baud_matters=True, language="SCPI", forget_on_reopen=False,
                 rst_deselects=False, silent_queries=(), late_reply=None):
        self.needs_nsel = needs_nsel
        self.address = address
        self.baud = baud
        self.baud_matters = baud_matters
        self.language = language
        self.forget_on_reopen = forget_on_reopen
        self.rst_deselects = rst_deselects
        self.silent_queries = silent_queries
        self.late_reply = late_reply
        self.selected = False
        self.remote = "LOC"
        self.output = False
        # As the last person left it, so putting back can be seen.
        self.vset, self.cset, self.ovp = 12.0, 2.0, 30.0
        self.errors = []
        self.esr = 0
        self.vout = 0.0
        self.now = 0.0
        self.vout_at = 0.0
        self.stream = []
        self.sent = []
        self.owed_late = False
        self.max_on_v = 0.0
        self.max_on_a = 0.0

    def advance(self, seconds):
        self.now += seconds

    # ---- physics ----
    def measured_v(self):
        target = self.vset if self.output else 0.0
        if not self.output:
            tau = 0.8
        else:
            tau = 0.02 if target >= self.vout else 0.5
        k = 1 - math.exp(-(self.now - self.vout_at) / tau)
        self.vout += (target - self.vout) * k
        self.vout_at = self.now
        return self.vout

    def _watch(self):
        if self.output:
            self.max_on_v = max(self.max_on_v, self.vset)
            self.max_on_a = max(self.max_on_a, self.cset)

    def error(self, code, text, kind):
        self.errors.append(f'{code},"{text}"')
        self.esr |= ESR_BITS[kind]

    # ---- the command set ----
    def handle(self, text):
        """The reply this command puts on the line, or None."""
        if self.language == "GEN":
            return "C01" if "?" in text else "OK"
        header, _, arg = text.strip().partition(" ")
        header, arg = header.upper(), arg.strip().upper()
        if header == "INST:NSEL":
            self.selected = number(arg) == self.address
            return None
        if self.needs_nsel and not self.selected:
            return None
        if header.endswith("?"):
            return self.query(header, arg)
        return self.write(header, arg)

    def query(self, header, arg):
        if header in self.silent_queries:
            self.owed_late = self.late_reply is not None
            return None
        if header == "SYST:ERR?":
            return self.errors.pop(0) if self.errors else '0,"No error"'
        if header == "*ESR?":
            value, self.esr = self.esr, 0
            return str(value)
        on = self.output
        if header == "VOLT?":
            return {"MAX": "36.0000", "MIN": "0.0000"}.get(
                arg, f"{self.vset:.4f}")
        if header == "CURR?":
            return {"MAX": "24.0000", "MIN": "0.0000"}.get(
                arg, f"{self.cset:.4f}")
        if header == "VOLT:PROT:LEV?":
            return {"MAX": f"{OVP_MAX:.2f}",
                    "MIN": f"{max(OVP_MIN, 1.05 * self.vset):.2f}"}.get(
                arg, f"{self.ovp:.2f}")
        volts = self.measured_v()
        replies = {
            "*IDN?": IDN, "*OPT?": "0", "SYST:VERS?": "Rev:1.0",
            "SYST:DATE?": "2026/01/01", "SYST:LANG?": "SCPI",
            "SYST:REM?": self.remote, "INST:NSEL?": str(self.address),
            "SYST:PON:TIME?": "1234",
            "OUTP?": "1" if on else "0",
            "OUTP:MODE?": "CV" if on else "OFF",
            "OUTP:PON?": "0", "OUTP:PROT:FOLD?": "OFF",
            "OUTP:PROT:DEL?": "0.1", "OUTP:ILC:MODE?": "OFF",
            "VOLT:PROT:LOW:STAT?": "UVL", "VOLT:PROT:LOW?": "0.0000",
            "VOLT:MODE?": "NONE", "CURR:MODE?": "NONE",
            "MEAS:VOLT?": f"{volts:.4f}",
            "MEAS:CURR?": "0.0120" if on else "0.0000",
            "MEAS:POW?": f"{volts * 0.012:.4f}" if on else "0.0000",
            "STAT:OPER:COND?": "5" if on else "4",
            "STAT:OPER:EVEN?": "0", "STAT:OPER:ENAB?": "0",
            "STAT:QUES:COND?": "0" if on else "64",
            "STAT:QUES?": "0", "STAT:QUES:ENAB?": "0",
            "*STB?": "0", "*OPC?": "1",
        }
        if header in replies:
            return replies[header]
        self.error(-100, "Command Error", "command")
        return None

    def write(self, header, arg):
        value = number(arg)
        if header in ("VOLT", "CURR", "VOLT:PROT:LEV", "OUTP", "*RST"):
            self.remote = "REM"
        if header == "VOLT" and value is not None:
            if value > V_ACCEPTED:
                self.error(-222, "Data Out Of Range", "execution")
            elif value > 0.95 * self.ovp:
                self.error(301, "PV Above OVP", "device")
            else:
                self.measured_v()
                self.vset = round(value, 4)
        elif header == "CURR" and value is not None:
            if value > A_ACCEPTED:
                self.error(-222, "Data Out Of Range", "execution")
            else:
                self.cset = round(value, 4)
        elif header == "VOLT:PROT:LEV":
            if arg == "MAX":
                self.ovp = OVP_MAX
            elif arg == "MIN":
                self.ovp = max(OVP_MIN, 1.05 * self.vset)
            elif value is None or not OVP_MIN <= value <= OVP_MAX:
                self.error(-222, "Data Out Of Range", "execution")
            elif value < 1.05 * self.vset:
                self.error(304, "OVP Below PV", "device")
            else:
                self.ovp = value
        elif header == "OUTP" and arg in ("0", "1"):
            self.measured_v()
            self.output = arg == "1"
        elif header == "*RST":
            self.output, self.vset, self.cset = False, 0.0, 0.0
            self.ovp = OVP_MAX
            if self.rst_deselects:
                self.selected = False
        elif header == "*CLS":
            self.errors, self.esr = [], 0
        elif header == "SYST:REM" and arg in ("LOC", "REM"):
            self.remote = arg
        else:
            self.error(-100, "Command Error", "command")
        self._watch()
        return None


class FakeSerial:
    """The two things the tool asks of a pyserial port."""

    def __init__(self, instrument):
        self.instrument = instrument

    @property
    def in_waiting(self):
        return sum(len(line) + 2 for line in self.instrument.stream)

    def read(self, count):
        data = "".join(line + "\r\n" for line in self.instrument.stream)
        self.instrument.stream.clear()
        return data.encode()


class Link(Transport):
    """One connection, at one baud."""

    def __init__(self, instrument, baud):
        super().__init__()
        self.instrument = instrument
        self.garbled = instrument.baud_matters and baud != instrument.baud
        self.ser = FakeSerial(instrument)
        self.connected = True
        if instrument.forget_on_reopen:
            instrument.selected = False

    def connect(self, address, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        inst = self.instrument
        inst.advance(0.002)
        inst.sent.append(text)
        if self.garbled:
            return
        reply = inst.handle(text)
        if reply is not None:
            inst.stream.append(reply)

    def _read(self, timeout_s=3.0):
        inst = self.instrument
        inst.advance(0.01)
        if inst.stream:
            return inst.stream.pop(0)
        inst.advance(timeout_s)
        if inst.owed_late:
            inst.stream.append(inst.late_reply)
            inst.owed_late = False
        raise TimeoutError("fake: no reply")


def sitting(answers=None, link_baud=9600, **fake):
    """A session on a fresh fake. `answers` maps a phrase in a prompt to
    the operator's answer, or to a callable given the instrument."""
    inst = Instrument(**fake)
    answers = answers or {}

    def ask(prompt):
        for phrase, answer in answers.items():
            if phrase in prompt:
                return answer(inst) if callable(answer) else answer
        return ""

    session = Session(lambda b=None: Link(inst, b or link_baud),
                      baud=link_baud,
                      log=lambda message: None, ask=ask, sleep=inst.advance,
                      clock=lambda: inst.now)
    return session, inst


def headline(session, start):
    return next(h for h in session.headlines if h.startswith(start))


def test_the_manual_s_word(check):
    session, inst = sitting()
    session.run()
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")
    check("INST:NSEL is needed", session.found.get("nsel_needed") is True,
          f"{session.found}")
    check("and kept across a reopened port",
          session.found.get("nsel_survives_reopen") is True)
    check("the other baud got nothing",
          session.found.get("other_baud_answers") is False)
    text = headline(session, "selection")
    check("said so", "before INST:NSEL no reply" in text
          and IDN in text, text)
    check("output off", inst.output is False)
    check("front panel handed back", inst.remote == "LOC")
    check("settings put back", (inst.vset, inst.cset, inst.ovp)
          == (12.0, 2.0, 30.0), f"{(inst.vset, inst.cset, inst.ovp)}")


def test_an_idn_that_does_not_wait_for_selection(check):
    session, _ = sitting(needs_nsel=False)
    session.run()
    check("not needed", session.found.get("nsel_needed") is False,
          f"{session.found}")


def test_the_wrong_baud_stops_before_anything_is_written(check):
    session, inst = sitting(link_baud=9600, baud=19200)
    session.run()
    check("not alive", session.alive is False)
    check("said why", "nothing answered at 9600 baud" in headline(
        session, "selection"))
    check("no crash", session.stopped_early is None)
    check("never switched on", "OUTP 1" not in inst.sent)


def test_a_baud_that_does_not_matter_over_usb(check):
    session, _ = sitting(baud_matters=False)
    session.run(with_output=False)
    check("the other baud answered",
          session.found.get("other_baud_answers") is True,
          f"{session.found}")
    check("said so", "*IDN? answered" in headline(session, "baud"))


def test_a_selection_forgotten_on_every_reopen(check):
    session, inst = sitting(forget_on_reopen=True)
    session.run()
    check("found", session.found.get("nsel_survives_reopen") is False,
          f"{session.found}")
    check("and the sitting still reached the output",
          session.stopped_early is None
          and any(h.startswith("on at 1 V") for h in session.headlines),
          f"{session.stopped_early}")
    check("output off", inst.output is False)


def test_a_selection_forgotten_by_rst(check):
    session, _ = sitting(rst_deselects=True)
    session.run()
    check("found", session.found.get("nsel_survives_rst") is False)
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")


def test_refusals_and_the_trip_rules_are_recorded(check):
    session, _ = sitting()
    session.run(with_output=False)
    refusals = headline(session, "refusals")
    check("out of range", '-222,"Data Out Of Range"' in refusals,
          refusals)
    check("an unknown header", 'VOLT:NOSUCH 1 -> -100' in refusals,
          refusals)
    check("the 5% over rated lands", "VOLT 37 -> no error" in refusals,
          refusals)
    trip = headline(session, "voltage and trip")
    check("PV above 95% of the trip", 'VOLT 11.5 -> 301' in trip, trip)
    check("the trip below 105% of PV", 'VOLT:PROT:LEV 10 -> 304' in trip,
          trip)
    check("MIN lands 5% above", "trip 11.55" in trip, trip)


def test_part_two_measures_what_the_fake_was_made_to_do(check):
    session, _ = sitting()
    session.run()
    on = headline(session, "on at 1 V")
    check("settles", "inside 2% of the step" in on, on)
    # 2% of a step at a 20 ms time constant is 78 ms. The look for a
    # stray reply after a write is 150 ms, and must not be in the time.
    up = re.search(r"from (\d+) ms", headline(session, "step 1 -> 5 V"))
    check("the up step is timed from the write, not after a pause",
          up is not None and int(up.group(1)) < 150, f"{up and up.group()}")
    circuit = headline(session, "on, open circuit")
    check("mode and offset", "OUTP:MODE? CV" in circuit
          and "MEAS:CURR? 0.0120" in circuit, circuit)
    down = headline(session, "step 5 -> 1 V")
    check("down is timed", "inside 2% of the step" in down, down)
    off = headline(session, "off from 1 V")
    check("off reads OFF", "OUTP:MODE? OFF" in off, off)


def test_gen_language_is_named_and_nothing_is_switched_on(check):
    session, inst = sitting(language="GEN")
    session.run()
    check("named", "the language is GEN" in headline(session, "selection"))
    check("stopped at the off check", any(
        "not confirmed off" in h for h in session.headlines))
    check("never switched on", "OUTP 1" not in inst.sent)


def test_a_late_reply_is_drained_not_used(check):
    session, _ = sitting(silent_queries=("SYST:PON:TIME?",),
                         late_reply="LATE")
    session.run(with_output=False)
    check("recorded as late", any("arrived late: 'LATE'" in s["note"]
                                  for s in session.steps))
    check("never taken as an answer", not any(
        s["result"] == "LATE" for s in session.steps))
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")


def test_ctrl_c_with_the_output_on_turns_it_off(check):
    def interrupt(inst):
        assert inst.output is True
        raise KeyboardInterrupt

    session, inst = sitting({"supply's display": interrupt})
    session.run(watching=True)
    check("stopped", session.stopped_early == "interrupted by Ctrl-C")
    check("output off", inst.output is False)
    check("front panel handed back", inst.remote == "LOC")


def test_the_output_never_exceeds_the_guards(check):
    session, inst = sitting()
    session.run()
    check("volts", inst.max_on_v <= MAX_ON_V, f"{inst.max_on_v}")
    check("amps", inst.max_on_a <= MAX_ON_A, f"{inst.max_on_a}")
    with pytest.raises(RuntimeError):
        session.turn_on(MAX_ON_V + 1, MAX_ON_A)
    session.output_on = True
    with pytest.raises(RuntimeError):
        session.step_to(MAX_ON_V + 1)


def test_never_sent(check):
    session, inst = sitting()
    session.run(watching=True)
    writes = [t.upper() for t in inst.sent if "?" not in t]
    banned = ("*SAV", "*RCL", "FRST", "GLOB", "LLO", "LIST", "WAVE",
              "TRIG", "INIT", "*PSC", "*SRE", "*ESE", ":ENAB", "FOLD",
              "PROT:LOW", "ILC", "REL", "TTLT", "PON", "*TRG")
    check("none", not [w for w in writes if any(b in w for b in banned)],
          f"{[w for w in writes if any(b in w for b in banned)]}")
    check("ascii", all(t.isascii() for t in inst.sent))


def test_the_report(check):
    session, _ = sitting()
    session.run()
    session._step("a reply with a | in it", "x|y")
    report = build_report(session, "COM8", {})
    check("headlines", "## Headlines" in report)
    check("every part", all(f"## {p}" in report for p in (
        "1.1 selection", "1.5 voltage and trip", "2.4 off", "3 put back")))
    check("pipes escaped", "| a reply with a \\| in it | x\\|y |" in report)


def test_the_helpers(check):
    check("numbers", number("01.2345") == 1.2345
          and number("1.2E+01") == 12.0 and number("OFF") is None)
    check("error codes", error_code('-222,"Data Out Of Range"') == -222
          and error_code('0,"No error"') == 0)
    check("too few", "too few" in settle_summary([(0.0, "1")], 0, 1))
