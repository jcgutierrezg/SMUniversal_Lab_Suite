"""The 487 bench sitting, walked offline against the fake instrument.

The first time this meets the real 487 is not the time to find a typo
in it. Each part is run with scripted answers at full speed, and what
the parts record is checked against what the fake was made to do.
"""
from test_keithley487 import Fake487

from tools.bench_487 import (
    MAX_OHMS,
    MIN_OHMS,
    Session,
    _ohms,
    build_report,
    resistor_plan,
)

#: What belongs to the instrument rather than to one connection to it.
INSTRUMENT = ("state", "u1", "u9", "level", "v_range", "v_limit",
              "autorange", "m_range", "delay", "last_reading", "converting",
              "buffer", "zero_corrected", "resistance")


def session_with(answers, resistance=None):
    made = []

    def connect():
        transport = Fake487(resistance=resistance)
        if made:
            for name in INSTRUMENT:
                setattr(transport, name, getattr(made[-1], name))
        made.append(transport)
        return transport

    replies = iter(answers)

    def ask(prompt):
        answer = next(replies)
        return answer(made[-1]) if callable(answer) else answer

    session = Session(connect, log=lambda message: None, ask=ask,
                      sleep=lambda seconds: None)
    return session, made


def front_panel(v_range, limit, m_range):
    """Stands in for the operator turning the knobs."""
    def turn(fake):
        fake.v_range, fake.v_limit = v_range, limit
        fake.autorange, fake.m_range = False, m_range
        return ""
    return turn


def test_the_plan_keeps_inside_the_limit_and_50_v(check):
    plan, why = resistor_plan(100e3)
    check("a plan for 100 kohm", plan is not None, why)
    check("half the limit, below", plan["below_v"] == 1.25)
    check("twice it, to trip", plan["trip_v"] == 5.0)
    plan, why = resistor_plan(MAX_OHMS * 2)
    check("too large is refused, with a reason", plan is None and why)
    plan, why = resistor_plan(MIN_OHMS / 2)
    check("too small too", plan is None and why)
    check("100k", _ohms("100k") == 100e3)
    check("1M", _ohms("1M") == 1e6)
    check("4700", _ohms("4700") == 4700)


def test_part_one_alone(check):
    session, made = session_with(["s", ""])
    session.run()
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")
    idn = [s for s in session.steps if s["part"] == "1.1 *IDN?"]
    check("the *IDN? exchange is recorded verbatim",
          any(e["sent"].startswith("*IDN?")
              for s in idn for e in s["exchanges"]), f"{idn[:1]}")
    check("the IDDC it caused is in the error word",
          any(str(s["result"]).startswith("4871") for s in idn),
          f"{[s['result'] for s in idn]}")
    check("and it answers again after a clear",
          any(s["result"] == "487A03" for s in idn))
    zero = [h for h in session.headlines if "open-input mean" in h]
    check("an offset for each low range", len(zero) == 4, f"{zero}")
    check("zero corrected on each", made[-1].zero_corrected == {1, 2, 3, 4},
          f"{made[-1].zero_corrected}")
    check("output off at the end", made[-1].state["O"] == "0")


def test_the_front_panel_readback(check):
    session, made = session_with([
        front_panel(1, 1, 4), front_panel(0, 0, 3), ""])
    session.run()
    reads = {s["what"]: s["result"] for s in session.steps
             if s["part"] == "1.3 front panel"
             and "set by hand: 500 V" in s["note"]}
    check("the 500 V range read back", reads.get(
        "read_source_voltage_range()") == 505.0, f"{reads}")
    check("2.5 mA", reads.get("read_current_limit()") == 2.5e-3)
    check("2 uA", reads.get("read_measure_current_range()") == 2e-6)


def test_part_two_with_a_resistor(check):
    session, made = session_with(["s", "100k"], resistance=100e3)
    session.run()
    check("finished", session.stopped_early is None,
          f"{session.stopped_early}")
    heads = " | ".join(session.headlines)
    late = next(h for h in session.headlines if "late readings" in h)
    check("every reading matched its own level",
          late == "late readings: 20 matched their own level, 0 the "
                  "previous one", late)
    trip = next(h for h in session.headlines if "compliance_tripped" in h)
    check("the trip is seen in limit", "'in limit': [True" in trip, trip)
    check("and not below", "'below': [False, False, False]" in trip, trip)
    check("the sign follows at every small level",
          "does not follow" not in heads, heads)
    report = build_report(session, "GPIB0::3::INSTR", {})
    for part in ("2.4", "2.5", "2.6", "2.7"):
        check(f"part {part} in the report", f"## {part}" in report)
    check("output off at the end", made[-1].state["O"] == "0")


def test_a_resistance_it_cannot_use_skips_part_two(check):
    session, made = session_with(["s", "10M"])
    session.run()
    check("skipped, saying why", any(
        "outside" in s["what"] for s in session.steps), "")
    check("nothing energised", all(
        not t.startswith("O1") for t in made[-1].sent))


def test_an_open_circuit_stops_part_two_with_a_reason(check):
    """What the first sitting ran into: no current anywhere, recorded as
    seven sections of nothing."""
    session, made = session_with(["100k"], resistance=None)
    session.run(parts=("2",))
    wiring = [h for h in session.headlines if h.startswith("wiring")]
    check("said so", wiring and "no current is reaching" in wiring[0],
          f"{wiring}")
    check("and went no further", not any(
        s["part"].startswith(("2.4", "2.5", "2.6", "2.7"))
        for s in session.steps))
    check("output off", made[-1].state["O"] == "0")


def test_part_two_alone(check):
    session, made = session_with(["100k"], resistance=100e3)
    session.run(parts=("2",))
    check("no part 1", not any(s["part"].startswith("1.")
                               for s in session.steps))
    check("the wiring carried current", any(
        "carrying current" in h for h in session.headlines),
        f"{session.headlines}")
    check("and every part ran", {"2.4 one conversion late?",
                                 "2.5 current-limit trip", "2.6 settling",
                                 "2.7 smallest step"}
          <= {s["part"] for s in session.steps})
