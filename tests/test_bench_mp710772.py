"""The MP710772's first sitting, walked offline against a fake that can
speak either dialect.

There is no manual to check this tool against, so what it must get right
is how it behaves when an answer is not the expected one: a query that
is never answered, a reply that arrives late, a write that draws an
error string, a spelling that moves the mode one way and not back. The
fake is a byte stream rather than a table of replies, so each of those
puts bytes on the line exactly where a real one would, and a tool that
read them as the next answer would be caught here rather than at the
bench.
"""
import math

import pytest

from smuniversal_lab_suite.core.transports.base import Transport
from tools.bench_mp710772 import (
    MAX_SOURCE_V,
    Session,
    build_report,
    ladder_summary,
    number,
    refresh_summary,
    settle_summary,
)

IDN = "Multicomp Pro MP710772 V1.00 SN:00000001"

LONG = {"CURRENT": "CURR", "VOLTAGE": "VOLT", "INPUT": "INP",
        "FUNCTION": "FUNC", "MEASURE": "MEAS", "POWER": "POW",
        "UPPER": "UPP", "LOWER": "LOW", "RESISTANCE": "RES",
        "SYSTEM": "SYST", "STATUS": "STAT"}


def normalise(header):
    return ":".join(LONG.get(t, t) for t in header.upper().split(":"))


class Instrument:
    """The load itself: its state, its physics, and the bytes in flight.

    Outlives any one connection, as the real one does - a reconnect
    gives a new link to the same instrument, with whatever it was last
    told and whatever it was still about to say.
    """

    def __init__(self, mode_header=":MODE", mode_words=None,
                 mode_query=True, input_words=("1", "0", "ON", "OFF"),
                 suffix_required=True, ceilings_writable=True,
                 rst_resets=True, err_on_unknown=False, late_reply=None,
                 cv_floor=0.1, source_v=None, supply_a=None, sat_ohm=0.043,
                 refresh_s=0.2, tau_s=0.05, mode="CC"):
        self.mode_header = mode_header
        self.mode_words = mode_words or {"CV": "CV", "CC": "CC"}
        self.mode_query = mode_query
        self.input_words = input_words
        self.suffix_required = suffix_required
        self.ceilings_writable = ceilings_writable
        self.rst_resets = rst_resets
        self.err_on_unknown = err_on_unknown
        self.late_reply = late_reply
        self.cv_floor = cv_floor
        self.source_v = source_v
        self.supply_a = supply_a
        self.sat_ohm = sat_ohm
        self.refresh_s = refresh_s
        self.tau_s = tau_s
        self.mode = mode
        self.input = False
        self.cset = 0.0
        self.vset = 1.0
        self.cceil = 40.0
        self.vceil = 150.0
        self.now = 0.0
        self.stream = []
        self.sent = []
        self.owed_late = False
        self.true = (0.0, 0.0)
        self.true_at = 0.0
        self.shown = None
        self.shown_tick = None

    def advance(self, seconds):
        self.now += seconds

    # ---- physics ----
    def target(self):
        if not self.input or self.source_v is None:
            return (self.source_v or 0.0, 0.0)
        if self.mode == "CC":
            if self.cset <= self.supply_a:
                return (self.source_v, self.cset)
            return (self.sat_ohm * self.supply_a, self.supply_a)
        volts = max(self.vset, self.cv_floor)
        if volts >= self.source_v:
            return (self.source_v, 0.0)
        return (max(volts, self.sat_ohm * self.supply_a), self.supply_a)

    def reading(self):
        """What the display holds: a first-order lag behind the
        physics, sampled once per refresh, with one count of dither so a
        refresh can be seen."""
        aim = self.target()
        k = 1 - math.exp(-(self.now - self.true_at) / self.tau_s)
        self.true = tuple(t + (a - t) * k for t, a in zip(self.true, aim))
        self.true_at = self.now
        tick = int(self.now / self.refresh_s)
        if tick != self.shown_tick:
            dither = 0.0001 * (tick % 2)
            self.shown = (self.true[0] + dither,
                          self.true[1] + dither if self.true[1] else 0.0)
            self.shown_tick = tick
        return self.shown

    # ---- the command set ----
    def level(self, arg, unit):
        text = arg.upper()
        if text.endswith(unit):
            text = text[:-1]
        elif self.suffix_required:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def handle(self, text):
        """The reply this command puts on the line, or None."""
        header, _, arg = text.strip().partition(" ")
        if header.endswith("?"):
            name = normalise(header[:-1])
            if name == "*IDN":
                return IDN
            if name == ":INP":
                return "ON" if self.input else "OFF"
            if name == normalise(self.mode_header) and self.mode_query:
                return self.mode
            volts, amps = self.reading()
            replies = {
                ":VOLT": f"{self.vset:.4f}V",
                ":CURR": f"{self.cset:.4f}A",
                ":VOLT:UPP": f"{self.vceil:g}V",
                ":CURR:UPP": f"{self.cceil:g}A",
                ":VOLT:LOW": f"{self.cv_floor:.4f}V",
                ":CURR:LOW": "0.0000A",
                ":MEAS:VOLT": f"{volts:.4f}V",
                ":MEAS:CURR": f"{amps:.4f}A",
                ":MEAS:POW": f"{volts * amps:.4f}W",
            }
            if name in replies:
                return replies[name]
            self.owed_late = self.late_reply is not None
            return None
        name = normalise(header)
        arg = arg.strip().upper()
        unit = "V" if name.startswith(":VOLT") else "A"
        if name == ":INP" and arg in self.input_words:
            self.reading()
            self.input = arg in ("1", "ON")
            return None
        if name == normalise(self.mode_header) and arg in self.mode_words:
            self.mode = self.mode_words[arg]
            return None
        if name in (":VOLT", ":CURR"):
            value = self.level(arg, unit)
            if value is not None:
                self.reading()
                if name == ":VOLT":
                    self.vset = min(max(value, self.cv_floor), self.vceil)
                else:
                    self.cset = min(value, self.cceil)
                return None
        if name in (":VOLT:UPP", ":CURR:UPP") and self.ceilings_writable:
            value = self.level(arg, unit)
            if value is not None:
                if name == ":VOLT:UPP":
                    self.vceil = value
                else:
                    self.cceil = value
                return None
        if name == "*RST":
            if self.rst_resets:
                self.cset, self.vset, self.input = 0.0, self.cv_floor, False
            return None
        return "ERR" if self.err_on_unknown else None


class FakeSerial:
    """The two things the tool asks of a pyserial port."""

    def __init__(self, instrument):
        self.instrument = instrument

    @property
    def in_waiting(self):
        return sum(len(line) + 1 for line in self.instrument.stream)

    def read(self, count):
        data = "".join(line + "\n" for line in self.instrument.stream)
        self.instrument.stream.clear()
        return data.encode()


class Link(Transport):
    """One connection to the instrument."""

    def __init__(self, instrument):
        super().__init__()
        self.instrument = instrument
        self.ser = FakeSerial(instrument)
        self.connected = True

    def connect(self, address, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        inst = self.instrument
        inst.advance(0.001)
        inst.sent.append(text)
        reply = inst.handle(text)
        if reply is not None:
            inst.stream.append(reply)

    def _read(self, timeout_s=3.0):
        inst = self.instrument
        inst.advance(0.004)
        if inst.stream:
            return inst.stream.pop(0)
        inst.advance(timeout_s)
        if inst.owed_late:
            inst.stream.append(inst.late_reply)
            inst.owed_late = False
        raise TimeoutError("fake: no reply")


def sitting(answers=None, port=None, **fake):
    """A session on a fresh fake. `answers` maps a phrase in a prompt to
    the operator's answer, or to a callable given the instrument."""
    inst = Instrument(**fake)
    answers = answers or {}

    def ask(prompt):
        for phrase, answer in answers.items():
            if phrase in prompt:
                return answer(inst) if callable(answer) else answer
        return ""

    session = Session(lambda: Link(inst), log=lambda message: None,
                      ask=ask, sleep=inst.advance, clock=lambda: inst.now,
                      port=port)
    return session, inst


def headline(session, start):
    return next(h for h in session.headlines if h.startswith(start))


SUPPLY = {"source_v": 5.0, "supply_a": 5.0}


def turn_the_supply_to(amps):
    """The operator setting the supply's current limit, then typing it."""
    def turn(inst):
        inst.supply_a = amps
        return f"{amps:g}"
    return turn


TWO_CURRENTS = {"first test current": "5",
                "second test current": turn_the_supply_to(10.0),
                "supply's display": "0.2"}


def test_the_community_dialect(check):
    session, inst = sitting(TWO_CURRENTS, **SUPPLY)
    session.run()
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")
    check(":MODE found", session.found.get("cv") == ":MODE CV"
          and session.found.get("cc") == ":MODE CC", f"{session.found}")
    check(":FUNC did not move", ":FUNC CV/CC -> " in headline(
        session, "mode") and "did not move" in headline(session, "mode"))
    check("the community input spelling", session.found.get("on")
          == ":INP 1" and session.found.get("off") == ":INP 0")
    check("the unit is needed, the short header preferred",
          session.found.get("current") == ":CURR {v:g}A"
          and session.found.get("voltage") == ":VOLT {v:g}V",
          f"{session.found}")
    levels = headline(session, "levels")
    check("the bare number did not land",
          ":CURR 0.123 -> 0.0000A (did not land)" in levels, levels)
    check("the silences were asked and survived",
          ":FUNC?" in session.silent and ":SYST:ERR?" in session.silent,
          f"{session.silent}")
    check("input off at the end", inst.input is False)


def test_part_one_reads_the_floor_the_ceilings_and_rst(check):
    session, _ = sitting(**SUPPLY)
    session.run(with_source=False)
    floor = headline(session, "CV floor")
    check("0.05 V clamps to 0.1 V", "0.05 V -> 0.1000V" in floor, floor)
    ceilings = headline(session, "ceilings")
    check("the clamp is seen", "then 10A -> 3.0000A" in ceilings, ceilings)
    check("and the ceiling put back", "put back 40A -> 40A" in ceilings,
          ceilings)
    rst = headline(session, "*RST")
    check("*RST cleared the marker", ":CURR? 0.3210A -> 0.0000A" in rst,
          rst)


def test_part_two_measures_what_the_fake_was_made_to_do(check):
    session, inst = sitting(TWO_CURRENTS, **SUPPLY)
    session.run()
    cc = headline(session, "CC at 0.2 A")
    check("the CC reading in the instrument's own sign",
          ":MEAS:CURR? 0.2" in cc and "display 0.2" in cc, cc)
    refresh = headline(session, "refresh")
    check("the 200 ms refresh", "median 200 ms apart" in refresh, refresh)
    step = headline(session, "CC step 0.2 -> 1 A")
    check("the step settles", "inside 2% of the step from" in step, step)
    first = headline(session, "headroom at 5 A")
    check("43 mOhm at 5 A", "which is 43 mOhm" in first, first)
    second = headline(session, "headroom at 10 A")
    check("and at 10 A, from twice the floor",
          "Lowest 0.43 V at 10 A, which is 43 mOhm" in second, second)
    check("with the supply limiting both times", not any(
        "not limiting" in h for h in session.headlines))
    check("input off at the end", inst.input is False)


def test_a_supply_left_at_the_first_current_is_named(check):
    """The operator types 10 A and leaves the knob at 5 A. The ladder
    then repeats the first current, and a floor at "10 A" would be the
    5 A floor under the wrong label."""
    session, _ = sitting({"first test current": "5",
                          "second test current": "10"}, **SUPPLY)
    session.run()
    text = headline(session, "CV at 10 A")
    check("named", "not the supply's 10 A - it is not limiting" in text,
          text)


def test_the_72_13200_dialect(check):
    session, _ = sitting(mode_header=":FUNC", input_words=("ON", "OFF"))
    session.run(with_source=False)
    check(":FUNC found", session.found.get("cv") == ":FUNC CV",
          f"{session.found}")
    check("and its input spelling", session.found.get("on") == ":INP ON")
    check(":MODE? was the silent one", ":MODE?" in session.silent
          and ":FUNC?" not in session.silent)


def test_a_spelling_that_moves_only_one_way_is_not_taken(check):
    """CC takes, CV is ignored, the unit starts in CV: the readback goes
    CV, CC, CC. It moved - once - and a test of B alone would pass."""
    session, inst = sitting(TWO_CURRENTS, mode="CV",
                            mode_words={"CC": "CC"}, **SUPPLY)
    session.run()
    check("no mode spelling found", "cv" not in session.found,
          f"{session.found}")
    check("the readings are in the report",
          "CV,CC,CC" in headline(session, "mode"),
          headline(session, "mode"))
    check("so part 2 does not run", headline(session, "part 2")
          .startswith("part 2: skipped"))
    check("input off", inst.input is False)


def test_the_screen_stands_in_for_a_silent_mode_query(check):
    session, _ = sitting({"MODE does the load's screen": lambda i: i.mode},
                         mode_query=False)
    session.run(watching=True, with_source=False)
    check("found from the operator's readings",
          session.found.get("cv") == ":MODE CV", f"{session.found}")
    check("and nothing but the screen was asked for the mode",
          not any(s["what"] == ":MODE?" and s["part"] == "1.3 the mode"
                  for s in session.steps))


def test_with_no_mode_readback_and_nobody_watching_it_says_so(check):
    session, _ = sitting(mode_query=False)
    session.run(with_source=False)
    check("skipped, not guessed", headline(session, "mode")
          == "mode: cannot be read back - skipped")
    check("nothing found", "cv" not in session.found)


def test_a_write_that_draws_a_reply_is_not_read_as_the_next_answer(check):
    session, _ = sitting(err_on_unknown=True)
    session.run(with_source=False)
    check("recorded", (":FUNC CV", "ERR") in session.unsolicited,
          f"{session.unsolicited[:3]}")
    check("and the next readbacks are still their own",
          session.found.get("current") == ":CURR {v:g}A"
          and session.found.get("cv") == ":MODE CV", f"{session.found}")
    check("no step took ERR for a reply", not any(
        s["result"] == "ERR" for s in session.steps))


def test_a_late_reply_is_drained_not_used(check):
    session, _ = sitting(late_reply="LATE")
    session.run(with_source=False)
    check("recorded as late", any("arrived late: 'LATE'" in s["note"]
                                  for s in session.steps))
    check("never taken as an answer", not any(
        s["result"] == "LATE" for s in session.steps))
    check("and part 1 still found its spellings",
          session.found.get("cv") == ":MODE CV")


@pytest.mark.parametrize("fake, answers, expected", [
    ({"source_v": MAX_SOURCE_V + 3, "supply_a": 5.0},
     {"first test current": "2"}, "above the 12 V"),
    ({"source_v": None}, {"first test current": "2"}, "no supply seen"),
])
def test_part_two_refuses_what_it_should(check, fake, answers, expected):
    session, inst = sitting(answers, **fake)
    session.run()
    check(expected, any(expected in h for h in session.headlines),
          f"{session.headlines[-3:]}")
    check("input off", inst.input is False)


def test_too_much_current_is_a_skip(check):
    session, _ = sitting({"first test current": "15"}, **SUPPLY)
    session.run()
    check("refused", any("outside 0 to 10 A" in s["what"]
                         for s in session.steps))


def test_a_low_ceiling_stops_part_two(check):
    session, inst = sitting({"first test current": "5"}, **SUPPLY)
    inst.cceil = 3.0
    session.run()
    check("stopped", any("current ceiling is 3 A" in h
                         for h in session.headlines), f"{session.headlines}")


def test_ctrl_c_with_the_input_on_turns_it_off(check):
    def interrupt(inst):
        assert inst.input is True
        raise KeyboardInterrupt

    session, inst = sitting({"first test current": "5",
                             "supply's display": interrupt}, **SUPPLY)
    session.run()
    check("stopped", session.stopped_early == "interrupted by Ctrl-C")
    check("input off", inst.input is False)


def test_every_byte_on_the_wire_is_ascii(check):
    """The 72-13200's manual printed its query mark as U+FF1F. A query
    sent with it is never answered."""
    session, inst = sitting(TWO_CURRENTS, **SUPPLY)
    session.run()
    check("ascii", all(text.isascii() for text in inst.sent),
          f"{[t for t in inst.sent if not t.isascii()]}")
    check("never CR, CW, SHORT, LIST, OCP or OPP", not any(
        word in text.upper().split()
        for text in inst.sent
        for word in ("CR", "CW", "SHORT", "CP")) and not any(
        token in text.upper() for text in inst.sent
        for token in (":LIST", ":OCP", ":OPP")))


def test_the_port(check):
    port = ("COM7", {"ids": (0x0416, 0x5011),
                     "description": "USB-K-R-Com Port",
                     "text": "USB-K-R-Com Port"}, "Multicomp Pro 72-13200")
    session, _ = sitting(port=port)
    session.part_port()
    text = headline(session, "port")
    check("ids and today's name", "0416:5011" in text
          and "Multicomp Pro 72-13200" in text, text)


def test_the_report(check):
    session, _ = sitting(TWO_CURRENTS, **SUPPLY)
    session.run()
    session._step("a reply with a | in it", "x|y")
    report = build_report(session, "COM7", {})
    check("headlines", "## Headlines" in report)
    check("every part", all(f"## {p}" in report for p in (
        "1.2 what answers", "1.3 the mode", "2.3 refresh")))
    check("pipes escaped", "| a reply with a \\| in it | x\\|y |" in report)


def test_the_summaries(check):
    check("a reply's number", number("0.7890A") == 0.789
          and number("-1.2E-3V") == -1.2e-3 and number("ERR") is None)
    check("too few polls", "too few" in refresh_summary([(0.0, "1")]))
    steady = [(i * 0.01, "1.0000A") for i in range(50)]
    check("a steady reading cannot time a refresh",
          "too few to time" in refresh_summary(steady))
    check("a settle", "from 20 ms" in settle_summary(
        [(0.01, "0.5")] + [(0.02 + i * 0.01, "1.0") for i in range(10)],
        0.0, 1.0))
    check("an empty ladder", ladder_summary([])
          == "no rungs below the starting level")
