"""The supply bench session, walked offline before it meets a supply.

`tools/bench_supply.py` is run once, at a bench, on an instrument the
software has never talked to, by someone who has also wired a power
resistor to it. That is the worst possible place to find a typo, a
wrong prompt order, or a level the resistor cannot take.

So the whole session is run here against the fake supply, with
scripted answers, and the things asserted are the ones that would cost
the sitting:

  * it never asks a query the manual does not list - an unanswered
    query latches the link and the session is over;
  * the levels it chooses for a resistor cannot exceed the rating even
    if the current limit does nothing;
  * whatever happens - a part raising, a skipped part, a lost link -
    the output ends off, with the voltage setting at zero;
  * and the record it brings home can tell the two readings of the
    limit register apart, which is the question it was written for.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_tsx_p import SupplyTransport  # noqa: E402

from smuniversal_lab_suite.core.transports.base import (  # noqa: E402
    TransportDesynchronised,
)
from smuniversal_lab_suite.drivers.aimtti_tsx_p import (  # noqa: E402
    AimTTiTSX1820P,
    AimTTiTSX3510P,
)
from tools import bench_supply  # noqa: E402

#: Every query the manual lists for these units. Anything else is never
#: answered.
DOCUMENTED_QUERIES = {"*IDN?", "*STB?", "*ESR?", "EER?", "QER?", "LSR?",
                      "V?", "I?", "OVP?", "VO?", "IO?", "POWER?"}

#: Commands the driver declines, which a probe tool must not send
#: either. A recall is the one with teeth: it can switch the output on.
DECLINED = ("INCV", "DECV", "INCI", "DECI", "DELTAV", "DELTAI", "*SAV",
            "*RCL", "*LRN", "LRN", "STO", "BUZZ", "*SRE", "*ESE", "LSE",
            "*PRE", "LOCAL", "OP?")


class Operator:
    """Answers the session's questions from a script, and attaches the
    resistor when asked about it - which is what a person does."""

    def __init__(self, transport, ohms="10", watts="50", hand=("7.77", "1.23"),
                 go=True, trip=True):
        self.transport = transport
        self.ohms, self.watts, self.hand = ohms, watts, hand
        self.go, self.trip = go, trip
        self.asked = []

    def __call__(self, prompt):
        self.asked.append(prompt)
        if "Resistance" in prompt:
            if self.ohms:
                self.transport.load_ohms = float(self.ohms)
            return self.ohms
        if "power rating" in prompt:
            return self.watts
        if "Go ahead" in prompt:
            return "y" if self.go else "n"
        if "Voltage you set" in prompt:
            if self.hand[0]:
                # A hand on the panel: the instrument holds it, and the
                # software never wrote it.
                self.transport.v_set = float(self.hand[0])
                self.transport.i_set = float(self.hand[1] or 0.01)
            return self.hand[0]
        if "Current limit you set" in prompt:
            return self.hand[1]
        if "Trip it" in prompt:
            if self.trip:
                self.transport.load_ohms = None
            return "y" if self.trip else "n"
        raise AssertionError(f"an unscripted question: {prompt!r}")


def session(cls=AimTTiTSX3510P, operator=None, **fake):
    fake.setdefault("model", cls.MODEL_IDS[0])
    wire = SupplyTransport(**fake)
    driver = cls(wire)
    operator = operator or Operator(wire)
    operator.transport = wire
    ticks = iter(range(10 ** 9))
    run = bench_supply.Session(driver, wire, log=lambda text: None,
                               ask=operator, sleep=lambda s: None,
                               clock=lambda: next(ticks) * 0.01)
    return run, wire, operator


def headline(run, starts):
    found = [h for h in run.headlines if h.startswith(starts)]
    assert found, f"no headline starting {starts!r} in {run.headlines}"
    return found[0]


# ---------------------------------------------------------------
# The levels chosen for a resistor
# ---------------------------------------------------------------

RESISTORS = [(1.0, 10.0), (2.2, 25.0), (4.7, 50.0), (10.0, 50.0),
             (10.0, 5.0), (47.0, 25.0), (100.0, 50.0), (0.1, 100.0),
             (8.0, 100.0), (33.0, 10.0)]


@pytest.mark.parametrize("cls", (AimTTiTSX3510P, AimTTiTSX1820P),
                         ids=lambda c: c.__name__)
@pytest.mark.parametrize("ohms,watts", RESISTORS)
def test_no_plan_can_exceed_the_resistors_rating(cls, ohms, watts, check):
    """Even if the current limit does nothing at all - which, on an
    instrument nobody has tested, is the case to plan for."""
    limits = cls.LIMITS
    plan, why = bench_supply.resistor_plan(ohms, watts, limits)
    if plan is None:
        check("a refusal says why", bool(why), "no reason given")
        return
    check("in limit it dissipates a quarter of the rating or less",
          plan["power_in_limit_w"] <= 0.25 * watts * (1 + 1e-9),
          f"{plan['power_in_limit_w']:.3g} W of {watts:g} W")
    check("with no limit at all it stays within the rating",
          plan["power_if_limit_fails_w"] <= watts * (1 + 1e-9),
          f"{plan['power_if_limit_fails_w']:.3g} W of {watts:g} W")
    check("the forcing voltage really forces the limit",
          plan["forcing_v"] / ohms >= 1.15 * plan["current_a"],
          f"{plan['forcing_v']} V into {ohms} ohm against "
          f"{plan['current_a']} A")
    check("the releasing voltage really releases it",
          plan["releasing_v"] / ohms <= 0.6 * plan["current_a"])
    check("the supply can do all of it",
          plan["forcing_v"] <= limits.max_voltage
          and 0.05 <= plan["current_a"] <= limits.max_current / 2.0,
          f"{plan}")
    check("never more than 2 A, however much the resistor could take",
          plan["current_a"] <= 2.0, f"{plan['current_a']} A")
    check("and every level is on the 10 mV / 10 mA grid",
          all(abs(plan[k] * 100 - round(plan[k] * 100)) < 1e-6
              for k in ("current_a", "forcing_v", "releasing_v")), f"{plan}")


@pytest.mark.parametrize("ohms,watts,says", [
    (1000.0, 0.25, "Use a lower resistance"),
    (5000.0, 100.0, "Use a lower resistance"),
    (0.01, 100.0, "Use a higher resistance"),
    (0.0, 50.0, "positive"),
    (10.0, -1.0, "positive"),
])
def test_an_unsuitable_resistor_is_refused_with_what_to_use(ohms, watts,
                                                            says):
    plan, why = bench_supply.resistor_plan(ohms, watts,
                                           AimTTiTSX3510P.LIMITS)
    assert plan is None and says in why, why


# ---------------------------------------------------------------
# The whole sitting
# ---------------------------------------------------------------


@pytest.mark.parametrize("cls", (AimTTiTSX3510P, AimTTiTSX1820P),
                         ids=lambda c: c.__name__)
def test_the_whole_session_runs_and_leaves_the_supply_safe(cls, check):
    run, wire, operator = session(cls)
    run.run()
    raised = [s for s in run.steps if "raised" in s["what"]
              or "RAISED" in str(s["result"])
              or "EXCEPTION" in str(s["result"])]
    check("nothing raised", not raised,
          [(s["what"], s["result"], s["note"]) for s in raised][:3])
    check("it was not cut short", run.stopped_early is None,
          run.stopped_early)
    check("every part left steps behind",
          {s["part"][0] for s in run.steps} >= {"2", "3", "4", "5", "6"},
          sorted({s["part"] for s in run.steps}))
    check("the output ends off", wire.output is False)
    check("the voltage setting ends at zero", wire.v_set == 0.0, wire.v_set)
    check("the current setting ends at the floor", wire.i_set == 0.01,
          wire.i_set)
    check("the trip ends at its widest", wire.ovp == wire.ovp_high, wire.ovp)
    check("every question was answered from the script",
          len(operator.asked) == 6, operator.asked)


def test_it_never_asks_a_query_the_manual_does_not_list(check):
    """The one that would end the sitting. An unrecognised command is a
    bit in a register; an unrecognised query is never answered."""
    run, wire, _ = session()
    run.run()
    queries = {s.strip() for s in wire.sent if s.strip().endswith("?")}
    check("there were queries to check", len(queries) >= 8, sorted(queries))
    check("all of them are in the manual",
          queries <= DOCUMENTED_QUERIES,
          sorted(queries - DOCUMENTED_QUERIES))
    heads = {s.split()[0].upper() for s in wire.sent}
    for declined in DECLINED:
        check(f"{declined} was never sent", declined not in heads)
    check("and nothing SCPI-shaped went out",
          not [s for s in wire.sent if ":" in s], wire.sent[:5])


def test_the_record_tells_the_two_readings_of_the_register_apart(check):
    """What the tool is for. If the bit is reported once, the polls in
    current limit read 1 then 0; if it is reasserted, 1 every time. A
    record that looked the same either way would have wasted the
    resistor."""
    seen = {}
    for reasserts in (False, True):
        run, _, _ = session(reasserts=reasserts)
        run.run()
        line = headline(run, "in current limit, sourcing voltage")
        seen[reasserts] = line
        check(f"reasserts={reasserts}: the driver said clamped throughout",
              "the driver said [True, True, True, True]" in line, line)
    check("reported once reads 1, 0, 0, 0",
          "LSR? read ['1', '0', '0', '0']" in seen[False], seen[False])
    check("reasserted reads 1 every time",
          "LSR? read ['1', '1', '1', '1']" in seen[True], seen[True])

    run, _, _ = session()
    run.run()
    check("released, the driver says not clamped",
          "the driver said [False, False, False, False]"
          in headline(run, "back in constant voltage"))
    check("sourcing current, the same state reads the other way",
          "the driver said [True, True]"
          in headline(run, "in constant voltage, sourcing current"))


def test_the_resistor_is_driven_at_the_planned_levels_and_no_higher(check):
    run, wire, _ = session(operator=Operator(None, ohms="10", watts="50"))
    plan, _ = bench_supply.resistor_plan(10.0, 50.0, AimTTiTSX3510P.LIMITS)

    highest = {"v": 0.0, "i": 0.0}
    note = wire._note_mode

    def watching():
        note()
        if wire.output and wire.load_ohms is not None:
            highest["v"] = max(highest["v"], wire.v_set)
            highest["i"] = max(highest["i"], wire.i_set)
    wire._note_mode = watching
    run.run()
    check("the resistor was energised", highest["v"] > 0, highest)
    check("never above the forcing voltage",
          highest["v"] <= plan["forcing_v"] + 1e-9, highest)
    check("never above the planned current",
          highest["i"] <= plan["current_a"] + 1e-9, highest)
    check("the plan went into the record",
          run.answers.get("resistor plan") == plan)


def test_a_hand_set_value_is_read_back_not_echoed(check):
    """The fake holds what the "hand" set, which the software never
    wrote, so the readback in the record is the instrument's."""
    run, _, _ = session()
    run.run()
    line = headline(run, "set by hand")
    check("both values came back over the bus",
          "'V 7.77'" in line and "'I 1.230'" in line, line)


def test_the_trip_part_records_the_trip_and_the_recovery(check):
    run, wire, _ = session()
    run.run()
    line = headline(run, "after V 6 with the trip at 5 V")
    step, = [s for s in run.steps
             if s["what"].startswith("protection_tripped()")]
    raw = [int(e["reply"]) for e in step["exchanges"]
           if e["sent"].startswith("LSR?")]
    check("the limit register reported it", raw and raw[0] & 4, raw)
    check("and the driver, asked first, noticed", step["result"] is True,
          "the probe read the register before the driver could - the "
          "event is gone once anyone reads it")
    check("both are in the headline",
          "protection_tripped() said [True]" in line, line)
    check("recovery is recorded", headline(run, "recovery:"))


# ---------------------------------------------------------------
# Skipping, and things going wrong
# ---------------------------------------------------------------


@pytest.mark.parametrize("operator,skipped,ran", [
    (dict(ohms=""), "4", "5"),
    (dict(watts=""), "4", "5"),
    (dict(go=False), "4", "5"),
    (dict(ohms="1000", watts="0.25"), "4", "5"),
    (dict(hand=("", "")), "5", "6"),
    (dict(trip=False), "6", "5"),
])
def test_a_part_can_be_skipped_without_touching_the_output(operator,
                                                           skipped, ran,
                                                           check):
    run, wire, _ = session(operator=Operator(None, **operator))
    energised = []
    note = wire._note_mode
    wire._note_mode = lambda: (note(), energised.append(run.part)
                               if wire.output else None)
    run.run()
    steps = [s for s in run.steps if s["part"].startswith(skipped)]
    check(f"part {skipped} says it was skipped",
          [s["what"] for s in steps] == ["skipped"],
          [s["what"] for s in steps])
    check("and never energised the output",
          not [p for p in energised if p.startswith(skipped)],
          sorted(set(energised)))
    check(f"part {ran} still ran",
          len([s for s in run.steps if s["part"].startswith(ran)]) > 1)
    check("the supply is left safe", wire.output is False
          and wire.v_set == 0.0)


def test_a_part_that_raises_is_recorded_and_the_rest_still_run(check):
    run, wire, _ = session()

    def broken():
        run.part = "3 output on, nothing attached"
        run.driver.set_source_function("voltage")
        run.driver.set_current_limit(0.05)
        run.driver.set_voltage_level(9.0)
        run.driver.output_on()
        raise ValueError("a bug in the tool")
    run.part_open_circuit = broken
    run.run()
    check("the failure is in the record",
          [s for s in run.steps if s["what"] == "part_open_circuit raised"
           and "a bug in the tool" in s["note"]])
    check("the later parts ran",
          {s["part"][0] for s in run.steps} >= {"4", "5", "6"})
    check("and the output did not stay on at 9 V",
          wire.output is False and wire.v_set == 0.0,
          f"{wire.output}, {wire.v_set}")


def test_a_part_that_dies_with_the_trip_lowered_does_not_leave_it_there(
        check):
    """The trip part sets the trip to 5 V. Left there, the next person
    to ask this supply for 6 V gets an output that shuts down."""
    run, wire, _ = session()

    def broken():
        run.part = "6 the over-voltage trip"
        run.driver.set_overvoltage_trip(5.0)
        run.driver.set_current_limit(1.5)
        raise ValueError("died half way")
    run.part_trip = broken
    run.run()
    check("the trip is back at its widest", wire.ovp == wire.ovp_high,
          wire.ovp)
    check("and the current setting at the floor", wire.i_set == 0.01,
          wire.i_set)


def test_a_lost_link_ends_the_session_and_still_writes_what_it_had(
        check, tmp_path):
    run, wire, _ = session()
    real = wire.query
    calls = {"n": 0}

    def dies_later(text, timeout_s=3.0):
        calls["n"] += 1
        if calls["n"] > 40:
            raise TransportDesynchronised("the link is out of step")
        return real(text, timeout_s=timeout_s)
    run.transport.query = dies_later
    run.run()
    check("it stopped", run.stopped_early is not None)
    check("without starting the parts after it",
          not [s for s in run.steps if s["part"][0] in "456"])
    check("the output-off was still sent", wire.writes()[-3:].count("OP 0")
          or "OP 0" in wire.writes()[-6:], wire.writes()[-6:])

    md, js = bench_supply.write_reports(run, "idn", "GPIB0::11::INSTR",
                                        str(tmp_path))
    text = Path(md).read_text(encoding="utf-8")
    check("the report says it did not finish",
          "did not finish" in text, text[:400])
    check("and the JSON loads", json.loads(Path(js).read_text(
        encoding="utf-8"))["stopped_early"] is not None)


# ---------------------------------------------------------------
# The record
# ---------------------------------------------------------------


def test_the_reports_carry_every_step_and_every_exchange(check, tmp_path):
    run, wire, _ = session()
    run.run()
    md, js = bench_supply.write_reports(
        run, "the identity", "GPIB0::11::INSTR", str(tmp_path),
        provenance={"commit": "abc"}, checkup_exit=0)
    data = json.loads(Path(js).read_text(encoding="utf-8"))
    check("every step is in the JSON", len(data["steps"]) == len(run.steps))
    check("and the whole trace", len(data["trace"]) == len(wire.sent),
          f"{len(data['trace'])} of {len(wire.sent)}")
    check("each step keeps what it exchanged",
          all("exchanges" in s for s in data["steps"])
          and any(len(s["exchanges"]) > 1 for s in data["steps"]))
    check("times only go forward",
          [s["at_s"] for s in data["steps"]]
          == sorted(s["at_s"] for s in data["steps"]))

    text = Path(md).read_text(encoding="utf-8")
    check("named for the driver",
          Path(md).name.startswith("supply_bench_AimTTiTSX3510P_"))
    for wanted in ("## Headlines", "## What the operator answered",
                   "## Part 2", "## Part 4", "## Part 6", "exit code 0",
                   "Observations, not verdicts"):
        check(f"the report has {wanted!r}", wanted in text)
    rows = [line for line in text.splitlines() if line.startswith("| ")]
    check("no reply broke a table row",
          all(line.count(" | ") == 3 for line in rows if "---" not in line
              and "At, s" not in line),
          [line for line in rows if line.count(" | ") != 3][:2])


def test_the_range_ends_and_refusals_are_headlines(check):
    """Each is one of the note's open questions, so each has to be
    findable in the report without reading four hundred steps."""
    run, _, _ = session()
    run.run()
    check("the identity", headline(run, "*IDN? is"))
    refusals = headline(run, "refusals (esr/eer)")
    check("a zero current is numbered 103", "'I 0' -> 16/103" in refusals,
          refusals)
    check("a non-command is a command error", "'XYZZY' -> 32/0" in refusals,
          refusals)
    ends = headline(run, "range ends")
    check("the top of the voltage range landed and the step above did not",
          "voltage ('V 35.30', '0', 'V 35.30', '100')" in ends, ends)
    check("rounding", headline(run, "off-grid levels land as"))
    check("reading times", headline(run, "measure() took, ms"))
    turn_on = headline(run, "after OP 1, nothing attached")
    check("turn-on events, with what the driver made of them",
          "LSR? read ['2', '0', '0']" in turn_on
          and "regulation() said ['CV', 'CV', 'CV']" in turn_on, turn_on)


# ---------------------------------------------------------------
# The command line
# ---------------------------------------------------------------


def _out(tmp_path):
    """Where a run writes. A folder of its own: `tmp_path` itself is
    shared with the fixtures that redirect the save folder."""
    return tmp_path / "out"


def _main(monkeypatch, tmp_path, argv, wire, answers):
    """Run `main()` with the fake on the end of the wire."""
    import builtins
    import time

    operator = Operator(wire)
    script = iter(answers)

    def keyboard(prompt=""):
        if "Carry on with the probes" in prompt:
            return next(script)
        return operator(prompt)
    monkeypatch.setattr(builtins, "input", keyboard)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(bench_supply, "TRANSPORTS", {"visa": lambda: wire})
    monkeypatch.setattr(sys, "argv", ["bench_supply.py", "--out",
                                      str(_out(tmp_path)), *argv])
    return bench_supply.main()


def test_the_command_line_runs_the_checkup_first_then_the_probes(
        check, monkeypatch, tmp_path, capsys):
    wire = SupplyTransport()
    ran = []
    monkeypatch.setattr(bench_supply.subprocess, "call",
                        lambda command: ran.append(command) or 0)
    code = _main(monkeypatch, tmp_path,
                 ["--address", "GPIB0::11::INSTR"], wire, [])
    check("it exits cleanly", code == 0, code)
    check("the checkup was run once, first", len(ran) == 1, ran)
    command = ran[0]
    check("as the real tool, on the same address, with a trace",
          command[1].endswith("smu_checkup.py")
          and command[2:5] == ["--address", "GPIB0::11::INSTR", "--trace"],
          command)
    check("writing into the same folder", str(_out(tmp_path)) in command)
    written = sorted(p.name for p in _out(tmp_path).iterdir())
    check("and the session wrote its two files",
          [n.rsplit(".", 1)[1] for n in written] == ["json", "md"]
          and all(n.startswith("supply_bench_AimTTiTSX3510P_")
                  for n in written), written)
    check("the link was closed and the output left off",
          wire.connected is False and wire.output is False)
    out = capsys.readouterr().out
    check("it says what to bring back", "Bring both back" in out)


def test_a_failed_checkup_asks_before_going_on(check, monkeypatch,
                                               tmp_path):
    wire = SupplyTransport()
    monkeypatch.setattr(bench_supply.subprocess, "call", lambda command: 1)
    code = _main(monkeypatch, tmp_path,
                 ["--address", "GPIB0::11::INSTR"], wire, ["n"])
    check("declining stops with the checkup's exit code", code == 1, code)
    check("and nothing was sent to the instrument", wire.sent == [],
          wire.sent[:3])
    check("or written", not _out(tmp_path).exists())


def test_it_refuses_an_instrument_that_is_not_a_supply(check, monkeypatch,
                                                       tmp_path, capsys):
    """Pointed at an SMU by mistake it must not start setting 10 V."""
    from smuniversal_lab_suite.core.transports.null_transport import (
        NullTransport,
    )

    demo = NullTransport()
    monkeypatch.setattr(bench_supply, "TRANSPORTS", {"visa": lambda: demo})
    monkeypatch.setattr(sys, "argv", [
        "bench_supply.py", "--address", "GPIB0::5::INSTR", "--skip-checkup",
        "--out", str(_out(tmp_path))])
    code = bench_supply.main()
    check("refused", code == 1, code)
    check("with the reason", "for power supplies" in capsys.readouterr().out)
    check("and nothing written", not _out(tmp_path).exists())


def test_a_port_name_needs_its_transport_named(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["bench_supply.py", "--address", "COM7",
                                      "--out", str(tmp_path)])
    with pytest.raises(SystemExit):
        bench_supply.main()
