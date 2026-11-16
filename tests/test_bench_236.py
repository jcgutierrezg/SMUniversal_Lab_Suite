"""The 236 bench sitting, walked offline against the fake instrument.

The first time this meets the real 236 is not the time to find a typo in
it. Each part is run with scripted answers at full speed, against a fake
that can be told either answer to the questions part 2 asks, and what
the parts record is checked against what the fake was made to do.
"""
import pytest
from test_keithley236 import Fake236

from tools.bench_236 import (
    LEVEL_A,
    LEVEL_B,
    MAX_OHMS,
    MIN_OHMS,
    Session,
    _ohms,
    build_report,
    resistor_plan,
)

#: What belongs to the instrument rather than to one connection to it.
INSTRUMENT = ("glob", "source", "active", "u1", "u9", "unread", "buffer",
              "pending", "resistance", "level_on_x", "compliance_on_x")


def session_with(answers, meter=True, **fake):
    """`meter` True reads the fake's terminal voltage in place of the
    operator typing a handheld meter's reading."""
    made = []

    def connect():
        transport = Fake236(**fake)
        if made:
            for name in INSTRUMENT:
                setattr(transport, name, getattr(made[-1], name))
        made.append(transport)
        return transport

    replies = iter(answers)

    def ask(prompt):
        answer = next(replies)
        return answer(made[-1]) if callable(answer) else answer

    session = Session(
        connect, meter=(lambda: made[-1].terminal_volts()) if meter else None,
        log=lambda message: None, ask=ask, sleep=lambda seconds: None)
    return session, made


def front_panel(active, compliance, l_range):
    """Stands in for the operator at the front panel."""
    def turn(fake):
        fake.active = active
        fake.source[active]["compliance"] = compliance
        fake.source[active]["l_range"] = l_range
        return ""
    return turn


def headline(session, start):
    return next(h for h in session.headlines if h.startswith(start))


def test_the_plan(check):
    plan, why = resistor_plan(10e3)
    check("a plan for 10 kohm", plan is not None, why)
    check("200 uA at 2 V: the 1 mA range, loose at its full scale",
          plan["range_a"] == 1e-3 and plan["loose_a"] == 1e-3, f"{plan}")
    check("tight at a fiftieth - 2% of the range, above 100 counts",
          plan["tight_a"] == pytest.approx(2e-5))
    check("which clamps 2 V to 0.2 V", plan["clamped_v"] == pytest.approx(0.2))
    for ohms in (MIN_OHMS, 100e3, MAX_OHMS):
        plan, _ = resistor_plan(ohms)
        current = LEVEL_B / ohms
        check(f"{ohms:g} ohm: loose never clamps, tight clamps by 2x",
              plan["loose_a"] >= 2 * current
              and plan["tight_a"] <= current / 2
              and plan["tight_a"] >= plan["range_a"] / 100, f"{plan}")
    check("too large is refused", resistor_plan(MAX_OHMS * 2)[0] is None)
    check("too small too", resistor_plan(MIN_OHMS / 2)[0] is None)
    check("10k", _ohms("10k") == 10e3)


def test_part_one(check):
    session, made = session_with([
        front_panel(0, 5e-5, 6), front_panel(1, 5.0, 2), "50"])
    session.run(parts=("1",))
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")
    idn = [s for s in session.steps if s["part"] == "1.1 *IDN?"]
    check("the *IDN? exchange is recorded verbatim",
          any(e["sent"].startswith("*IDN?")
              for s in idn for e in s["exchanges"]))
    check("the IDDC it caused is in the error word",
          any(str(s["result"]).startswith("ERS01") for s in idn),
          f"{[s['result'] for s in idn]}")
    check("and it answers again after a clear",
          any(s["result"] == "236A01" for s in idn))
    reads = [(s["what"], s["result"], s["note"]) for s in session.steps
             if s["part"] == "1.2 front panel"]
    check("50 uA read back", ("compliance read back", 5e-5,
                              "set by hand: source V, 50 uA on 100 uA")
          in reads, f"{reads}")
    check("the 100 uA range", any(r[:2] == ("measurement range read back",
                                            1e-4) for r in reads))
    check("5 V and the 11 V range", any(
        r[:2] == ("compliance read back", 5.0) for r in reads) and any(
        r[:2] == ("measurement range read back", 11.0) for r in reads))
    check("the menu's answer is a headline",
          "line frequency: the menu says 50" in session.headlines)
    check("output off at the end", made[-1].output is False)


def test_the_front_panel_can_be_skipped(check):
    session, made = session_with(["s", ""])
    session.run(parts=("1",))
    check("skipped", any("skipped" in s["what"] for s in session.steps))
    check("no readback asked", not any(
        "read back" in s["what"] for s in session.steps))


@pytest.mark.parametrize("on_x", [False, True])
def test_part_two_tells_the_two_answers_apart(check, on_x):
    session, made = session_with(["10k"], resistance=10e3,
                                 level_on_x=on_x, compliance_on_x=on_x)
    session.run(parts=("2",))
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")
    check("the wiring carried current", headline(
        session, "wiring").startswith("wiring: the 236 read 0.0001 A"),
        headline(session, "wiring"))
    level = headline(session, "level on X")
    word = "as sent" if on_x else "as before"
    check(f"level on X: every step reads {word}",
          level.count(word) == 3, level)
    compliance = headline(session, "compliance on X")
    check(f"compliance on X: {word} before the trigger, clamped after",
          f"({word})" in compliance and "0.2 V after one" in compliance,
          compliance)
    # Even without the extra trigger the reading is at the new level:
    # the measuring trigger's own source phase applies it. What is lost
    # is the settle, which the fake does not model - at the bench a
    # difference here is the sample not having settled.
    timing = headline(session, "timing")
    check("timing: both passes ran, and read the same",
          "with the extra trigger" in timing
          and "difference between the passes 0 A" in timing, timing)
    check("output off at the end", made[-1].output is False)
    report = build_report(session, "GPIB0::16::INSTR", {})
    for part in ("2.4", "2.5", "2.6"):
        check(f"part {part} in the report", f"## {part}" in report)


def test_without_a_meter_it_asks_for_a_handheld_reading(check):
    answers = ["10k"] + ["1.0"] * 40
    session, made = session_with(answers, meter=False, resistance=10e3)
    session.run(parts=("2",))
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")
    check("the typed readings are kept", len(session.answers["meter"]) >= 9,
          f"{session.answers.get('meter')}")


def test_an_open_circuit_stops_part_two_with_a_reason(check):
    session, made = session_with(["10k"], resistance=None)
    session.run(parts=("2",))
    check("said so", "no current is flowing" in headline(session, "wiring"))
    check("and went no further", not any(
        s["part"].startswith(("2.4", "2.5", "2.6")) for s in session.steps))
    check("output off", made[-1].output is False)


def test_nothing_above_two_volts(check):
    session, made = session_with(["10k"], resistance=10e3)
    session.run(parts=("2",))
    levels = [float(t[1:].split(",")[0]) for f in made for t in f.sent
              if t.startswith("B")]
    check("every level within 2 V", max(abs(v) for v in levels) <= LEVEL_B,
          f"{max(levels)}")
    check("and the first step is the smaller one", LEVEL_A < LEVEL_B)
