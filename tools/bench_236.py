"""
One sitting with the Keithley 236: the questions its checkup cannot ask.

The checkup passes on the 236 (2026-11-16). What it leaves open is in
the instrument note's *Open questions*, and each needs a hand on the
front panel or a resistor across the output. This asks them, in two
parts, and records what came back.

    uv run tools/bench_236.py --address GPIB0::16::INSTR

Part 1 - nothing connected to the output
  1. The compliance and measurement-range readbacks against the front
     panel: you set them by hand, it reads `U5` and `U4`. Skippable.
  2. How long after a reading the unit is ready for the next trigger,
     from its serial-poll byte - at 0 V, in operate.

What `*IDN?` does to it and the line frequency were answered by the
first sitting (2026-11-16) and are in the instrument note.

Part 2 - a resistor from OUTPUT HI to OUTPUT LO (1 kOhm to 2 MOhm,
10 kOhm ideal), local sense, and a handheld meter across it. You type
in the resistor's value, and the meter's reading whenever it asks.
  4. Does a new level reach the output on `X`, or only at the next
     trigger? No 236 reading can tell, because every reading is a
     triggered cycle whose source phase applies the level. This is what
     decides whether `LEVEL_NEEDS_TRIGGER` can go.
  5. The same for a compliance, which the manual says needs a trigger
     in dc operation.
  6. A short sweep with the extra trigger and without it: the time
     per point, and whether the readings differ.

Not asked, on purpose: what an overflow looks like. With a fixed range
the compliance *is* the range (manual 3.6.10, note 1), so a passive
sample is clamped before it can overrange; only an external source of
power can (3.6.19). The instrument note says so.

Nothing goes above 2 V, and the levels keep the resistor under 4 mW.
It does not interpret. Every step records what was asked and the raw
answer, with the time; the headlines at the top of the report are
counts and readings copied from the steps, not verdicts. The output goes
off between parts, at the end, and on any error or Ctrl-C.
"""
import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smuniversal_lab_suite.core.provenance import (  # noqa: E402
    as_markdown_lines,
    code_paths_for,
    describe,
)
from smuniversal_lab_suite.core.ranges import RangePlan  # noqa: E402
from smuniversal_lab_suite.core.transports.base import (  # noqa: E402
    TransportDesynchronised,
)
from smuniversal_lab_suite.drivers.keithley_236 import (  # noqa: E402
    CURRENT_RANGES,
    READY_FOR_TRIGGER,
    TRIGGER_GAP_S,
    Keithley236,
)
from tools.smu_checkup import (  # noqa: E402
    TRANSPORTS,
    _driver_source,
    inferred_transport,
    install_trace,
    trace_times,
)

#: The resistances part 2 can work with. Below, 2 V is more than 4 mW;
#: above, the currents are small enough that a handheld meter's input
#: resistance starts to load the resistor.
MIN_OHMS, MAX_OHMS = 1e3, 2e6

#: The two levels the level question steps between, in volts.
LEVEL_A, LEVEL_B = 1.0, 2.0

#: The source range for every level here: 11 V.
SOURCE_RANGE_V = 11.0

#: How long to wait after an untriggered command before asking for the
#: handheld meter's reading. Far longer than the 236's 25 ms response
#: as a source.
SETTLE_S = 1.0

#: Points in the timing sweep, 0 to LEVEL_B.
SWEEP_POINTS = 11

#: Readings timed for the ready bit in part 1.
READINESS_CYCLES = 20


def resistor_plan(ohms):
    """Ranges and compliances for part 2, or `(None, why)`."""
    if not MIN_OHMS <= ohms <= MAX_OHMS:
        return None, (f"{ohms:g} ohm is outside {MIN_OHMS:g} to "
                      f"{MAX_OHMS:g} ohm. 10 kohm is ideal")
    current = LEVEL_B / ohms
    # The smallest current range holding twice the current at LEVEL_B:
    # its full scale is the generous compliance (never clamping), and a
    # fiftieth of it the tight one - above the 100-count floor, and
    # under half the current at LEVEL_B, so a clamp is unmistakable.
    full_scale = next(fs for fs, _ in CURRENT_RANGES if fs >= 2 * current)
    return {
        "ohms": ohms,
        "range_a": full_scale,
        "loose_a": full_scale,
        "tight_a": full_scale / 50.0,
        "clamped_v": full_scale / 50.0 * ohms,
    }, None


class Session:
    """Runs the parts and records what happened.

    `connect` returns a connected transport for the 236. `meter` returns
    the voltage across the resistor, read by something other than the
    236, or None; at the bench it is the operator typing a handheld
    meter's reading. `meter`, `ask`, `sleep` and `clock` are injected so
    the whole session can be walked offline against the fake instrument.
    """

    def __init__(self, connect, meter=None, log=print, ask=None,
                 sleep=None, clock=None):
        self.connect = connect
        self.log = log
        self.ask = ask or input
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self.meter = meter or self._ask_meter
        self.started = self.clock()
        self.steps = []
        self.headlines = []
        self.answers = {}
        self.stopped_early = None
        self.part = ""
        self.trace = []
        self.driver = None
        self.transport = None
        self._open()

    # ---- the link --------------------------------------------------
    def _open(self, clear=False):
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
        self.transport = self.connect()
        install_trace(self.transport, self.trace)
        self.driver = Keithley236(self.transport)
        if clear:
            self.transport.clear()

    def _ask_meter(self):
        answer = self.ask("  Voltage across the resistor on your meter, in "
                          "volts (Enter if you cannot read it): ").strip()
        self.answers.setdefault("meter", []).append(answer)
        try:
            return float(answer)
        except ValueError:
            return None

    # ---- recording -------------------------------------------------
    def _step(self, what, result=None, note="", since=None):
        times = trace_times(self.trace)
        start = len(self.trace) if since is None else since
        entry = {
            "part": self.part,
            "what": what,
            "at_s": round(self.clock() - self.started, 3),
            "result": result,
            "note": note,
            "exchanges": [
                {"at_s": at, "ms": round(elapsed * 1000, 1), "sent": sent,
                 "reply": reply}
                for (elapsed, sent, reply), at in zip(self.trace[start:],
                                                      times[start:])],
        }
        self.steps.append(entry)
        shown = "" if result is None else f" -> {result!r}"
        self.log(f"    {what}{shown}" + (f"   [{note}]" if note else ""))
        return entry

    def headline(self, text):
        self.headlines.append(text)
        self.log(f"  * {text}")

    def call(self, what, action, note=""):
        """A call, its answer, and what it exchanged to get it. A lost
        link is recorded and raised: the caller decides."""
        mark = len(self.trace)
        try:
            result = action()
        except TransportDesynchronised:
            self._step(what, "<LINK OUT OF STEP>", note, since=mark)
            raise
        except Exception as exc:
            result = f"<RAISED {type(exc).__name__}: {exc}>"
        if not isinstance(result, (str, int, float, bool, type(None))):
            result = repr(result)
        self._step(what, result, note, since=mark)
        return result

    def raw(self, what, command, timeout_s=3.0, note=""):
        """One query, the reply verbatim."""
        return self.call(what, lambda: str(self.transport.query(
            command, timeout_s=timeout_s)).strip(), note)

    def send(self, what, command, note=""):
        """One command, straight to the wire, no trigger after it."""
        return self.call(what, lambda: self.transport.write(command), note)

    def outside(self, what, note=""):
        """The resistor's voltage on the handheld meter, after the
        settle. Returns volts or None."""
        self.sleep(SETTLE_S)
        result = self.call(f"{what}: handheld meter", self.meter, note)
        return result if isinstance(result, float) else None

    def reading(self, what, note=""):
        """One 236 reading through the driver: amps, or None."""
        result = self.call(what, lambda: self.driver.measure()[1], note)
        return result if isinstance(result, float) else None

    def off(self):
        try:
            self.driver.safe_output_off()
        except Exception:
            pass

    # ---- part 1: nothing attached ----------------------------------
    #: The front-panel steps for a compliance, from manual 2.12. The
    #: last one is the one the first sitting missed: in dc operation a
    #: compliance entered at the front panel stays "pending" until the
    #: next trigger, and the bus reports the one in force.
    PANEL_STEPS = (
        "  1. Press LOCAL (the RMT light goes out).\n"
        "  2. Press {source} so the display says SOURCE {source}.\n"
        "  3. Press COMPLIANCE - the display shows the limit and COMPLI.\n"
        "  4. Key in {value} on the keypad and press ENTER. It picks the\n"
        "     range itself: {range}.\n"
        "  5. Press COMPLIANCE again to leave the compliance display.\n"
        "  6. Press MANUAL (in the TRIGGER group) once. Until a trigger,\n"
        "     the new limit is only pending and the old one stays in force.\n")

    def part_front_panel(self):
        self.part = "1.1 front panel"
        self.log("\n1.1  The readbacks against the front panel")
        answer = self.ask(
            "\nThis part needs you at the 236's front panel. Set a "
            "compliance:\n" + self.PANEL_STEPS.format(
                source="V", value="50E-6 (50 uA)", range="100 uA")
            + "Press Enter when done, or type s to skip: ").strip().lower()
        self.answers["front panel 1"] = answer
        if answer == "s":
            self.call("skipped at the operator's request", lambda: None)
            return
        self._read_back("set by hand: source V, 50 uA on 100 uA",
                        self.driver.read_current_limit,
                        self.driver.read_measure_current_range)
        answer = self.ask(
            "\nNow the current source's:\n" + self.PANEL_STEPS.format(
                source="I", value="5 (5 V)", range="11 V")
            + "Enter when done: ").strip().lower()
        self.answers["front panel 2"] = answer
        self._read_back("set by hand: source I, 5 V on 11 V",
                        self.driver.read_voltage_limit,
                        self.driver.read_measure_voltage_range)

    def _read_back(self, note, limit, measure_range):
        self.raw("U3X", "U3X", note=note)
        self.raw("U4X", "U4X", note=note)
        self.raw("U5X", "U5X", note=note)
        self.call("compliance read back", limit, note=note)
        self.call("measurement range read back", measure_range, note=note)

    def part_readiness(self):
        """How long after a reading until the ready bit is set.

        At 0 V into the open output, on the 100 uA range: harmless with
        nothing attached. Each cycle goes through the driver, which
        itself waits for the bit before its trigger; this then polls
        straight after the reading and times the bit coming up.
        """
        self.part = "1.2 ready for a trigger"
        self.log("\n1.2  How long after a reading is it ready again?")
        driver = self.driver
        self.call("reset()", driver.reset)
        driver.set_source_function("voltage")
        self.call("apply_ranges()", lambda: driver.apply_ranges(
            RangePlan.for_sourcing("voltage", source_range=SOURCE_RANGE_V,
                                   measure_range=1e-4),
            log=lambda message: None))
        self.call("set_current_limit(1e-4)",
                  lambda: driver.set_current_limit(1e-4))
        self.call("output_on()", driver.output_on)
        waits = []
        for index in range(READINESS_CYCLES):
            self.call(f"reading [{index + 1}]", driver._cycle)
            started = self.clock()
            polls = 0
            try:
                while not self.transport.serial_poll() & READY_FOR_TRIGGER:
                    polls += 1
                    if self.clock() - started > 2.0:
                        break
            except NotImplementedError:
                self.call("this transport cannot serial poll", lambda: None)
                break
            waited = self.clock() - started
            waits.append(waited)
            self._step(f"ready after reading [{index + 1}]",
                       round(waited * 1000, 2),
                       note=f"{polls} poll(s) before the bit was set")
        self.off()
        if waits:
            ordered = sorted(waits)
            self.headline(
                f"ready for a trigger: median "
                f"{ordered[len(ordered) // 2] * 1000:.1f} ms, longest "
                f"{ordered[-1] * 1000:.1f} ms after a reading "
                f"({len(waits)} cycles; the driver's no-poll gap is "
                f"{TRIGGER_GAP_S * 1000:.0f} ms)")

    # ---- part 2: a resistor ----------------------------------------
    def part_resistor(self):
        answer = self.ask(
            "\nPart 2 needs a resistor from OUTPUT HI to OUTPUT LO, local "
            "sense, and a meter across it.\nIts value in ohms (10k is "
            "ideal), or Enter to skip part 2: ").strip().lower()
        self.answers["resistor"] = answer
        self.part = "2 resistor"
        if not answer:
            self.call("part 2 skipped at the operator's request",
                      lambda: None)
            return
        try:
            ohms = _ohms(answer)
        except ValueError:
            self.call(f"part 2 skipped: {answer!r} is not a resistance",
                      lambda: None)
            return
        plan, why = resistor_plan(ohms)
        if plan is None:
            self.call(f"part 2 skipped: {why}", lambda: None)
            return
        self.call("the plan", lambda: plan)
        if not self.wiring_carries_current(plan):
            return
        self.part_level_on_x(plan)
        self.part_compliance_on_x(plan)
        self.part_timing(plan)

    def _energised(self, plan):
        """Reset, voltage source on 11 V, the loose compliance on the
        plan's fixed range, 0 V, output on."""
        driver = self.driver
        self.call("reset()", driver.reset)
        driver.set_source_function("voltage")
        self.call("apply_ranges()", lambda: driver.apply_ranges(
            RangePlan.for_sourcing("voltage", source_range=SOURCE_RANGE_V,
                                   measure_range=plan["range_a"]),
            log=lambda message: None))
        self.call(f"set_current_limit({plan['loose_a']:g})",
                  lambda: driver.set_current_limit(plan["loose_a"]))
        self.call("output_on()", driver.output_on)

    def wiring_carries_current(self, plan):
        """One level, before anything else in part 2: is the resistor
        there, and does the handheld meter see it?"""
        self.part = "2 wiring"
        self._energised(plan)
        expected = LEVEL_A / plan["ohms"]
        self.call(f"set {LEVEL_A:g} V (triggered, through the driver)",
                  lambda: self.driver.set_voltage_level(LEVEL_A))
        amps = self.reading("236 reading", note=f"expected {expected:.4g} A")
        volts = self.outside("at 1 V", note=f"expected {LEVEL_A:g} V")
        self.off()
        if amps is not None and amps >= 0.5 * expected:
            self.headline(f"wiring: the 236 read {amps:.4g} A of "
                          f"{expected:.4g} A expected, the handheld meter "
                          f"{_volts(volts)}")
            return True
        self.headline(
            f"wiring: the 236 read {_amps(amps)} where {expected:.4g} A was "
            f"expected - no current is flowing. Check the resistor is from "
            f"OUTPUT HI to OUTPUT LO. Part 2 stopped here")
        return False

    def part_level_on_x(self, plan):
        self.part = "2.4 level on X?"
        self.log("\n2.4  Does a new level reach the output on X?")
        self._energised(plan)
        option = 2   # the 11 V source range
        seen = []
        applied = 0.0
        for level in (LEVEL_A, LEVEL_B, 0.0):
            self.send(f"B{level:g} with no trigger after it",
                      f"B{level:.4E},{option},0X")
            volts = self.outside(f"after B{level:g}",
                                 note=f"{level:g} V if it went out on X, "
                                      f"{applied:g} V if it waits")
            seen.append((level, applied, volts))
            self.call("H0X and its reading - the trigger",
                      lambda: self.driver._cycle())
            self.outside(f"after the trigger at {level:g} V",
                         note=f"{level:g} V")
            applied = level
        verdicts = [_which(volts, level, before)
                    for level, before, volts in seen]
        self.headline("level on X: " + "; ".join(
            f"B{level:g} -> {_volts(volts)} ({verdict})"
            for (level, _, volts), verdict in zip(seen, verdicts)))
        self.off()

    def part_compliance_on_x(self, plan):
        self.part = "2.5 compliance on X?"
        self.log("\n2.5  Does a new compliance reach the output on X?")
        self._energised(plan)
        driver = self.driver
        self.call(f"set {LEVEL_B:g} V", lambda: driver.set_voltage_level(
            LEVEL_B))
        self.outside(f"at {LEVEL_B:g} V, loose compliance",
                     note=f"{LEVEL_B:g} V")
        option = driver._measure_range["voltage"]
        tight, clamped = plan["tight_a"], plan["clamped_v"]
        self.send(f"L{tight:g} with no trigger after it",
                  f"L{tight:.4E},{option}X")
        volts = self.outside("after the tight L",
                             note=f"{clamped:.3g} V if it went out on X, "
                                  f"{LEVEL_B:g} V if it waits")
        self.call("H0X and its reading - the trigger",
                  lambda: driver._cycle())
        after = self.outside("after the trigger",
                             note=f"{clamped:.3g} V, clamped")
        self.headline(
            f"compliance on X: {_volts(volts)} before a trigger "
            f"({_which(volts, clamped, LEVEL_B)}), {_volts(after)} after "
            f"one; {clamped:.3g} V means clamped")
        self.off()

    def part_timing(self, plan):
        self.part = "2.6 timing"
        self.log("\n2.6  A sweep with the extra trigger and without it")
        levels = [LEVEL_B * i / (SWEEP_POINTS - 1)
                  for i in range(SWEEP_POINTS)]
        passes = {}
        try:
            for needs_trigger in (True, False):
                self._energised(plan)
                # On this instance only, and put back below: the class
                # value is the driver's decision, not this tool's.
                self.driver.LEVEL_NEEDS_TRIGGER = needs_trigger
                label = "with" if needs_trigger else "without"
                started = self.clock()
                amps = []
                for level in levels:
                    self.call(f"{label}: set {level:g} V",
                              lambda v=level: self.driver.set_voltage_level(v))
                    amps.append(self.reading(
                        f"{label}: reading at {level:g} V",
                        note=f"{level / plan['ohms']:.4g} A"))
                elapsed = self.clock() - started
                passes[label] = (elapsed / len(levels), amps)
                self.off()
        finally:
            self.driver.__dict__.pop("LEVEL_NEEDS_TRIGGER", None)
        worst = max((abs(a - b) for a, b in zip(passes["with"][1],
                                                passes["without"][1])
                     if a is not None and b is not None), default=None)
        self.headline(
            f"timing: {passes['with'][0] * 1000:.0f} ms a point with the "
            f"extra trigger, {passes['without'][0] * 1000:.0f} ms without; "
            f"largest difference between the passes "
            f"{_amps(worst)}")

    # ---- the whole sitting -----------------------------------------
    def run(self, parts=("1", "2")):
        try:
            if "1" in parts:
                self.part_front_panel()
                self.part_readiness()
            if "2" in parts:
                self.part_resistor()
        except KeyboardInterrupt:
            self.stopped_early = "interrupted by Ctrl-C"
        except TransportDesynchronised as exc:
            self.stopped_early = f"the link went out of step: {exc}"
        except Exception as exc:
            self.stopped_early = f"{type(exc).__name__}: {exc}"
        finally:
            self.off()
            try:
                self.transport.close()
            except Exception:
                pass


def _which(volts, new, old):
    """Which of two expected voltages a reading is nearer - a label, not
    a verdict: the raw value is beside it in the report."""
    if volts is None:
        return "not read"
    if abs(new - old) < 1e-9:
        return "no change to see"
    return ("as sent" if abs(volts - new) < abs(volts - old)
            else "as before")


def _volts(value):
    return "no reading" if value is None else f"{value:.4g} V"


def _amps(value):
    return "no reading" if value is None else f"{value:.4g} A"


def _ohms(text):
    text = text.strip().lower().replace("ohm", "").replace("Ω", "")
    scale = {"k": 1e3, "m": 1e6}.get(text[-1:], 1.0)
    return float(text[:-1] if scale != 1.0 else text) * scale


def build_report(session, address, provenance):
    lines = [
        "# Keithley 236 - one sitting at the bench",
        "",
        f"- **When:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Address:** {address}",
        *as_markdown_lines(provenance or {}),
        "",
    ]
    if session.stopped_early:
        lines += [f"> **Did not finish:** {session.stopped_early}. "
                  f"Everything below was recorded before that.", ""]
    if session.headlines:
        lines += ["## Headlines", "",
                  *[f"- {text}" for text in session.headlines], ""]
    part = None
    for step in session.steps:
        if step["part"] != part:
            part = step["part"]
            lines += ["", f"## {part}", "", "| At | Step | Result | Note |",
                      "|---|---|---|---|"]
        result = "" if step["result"] is None else _cell(step["result"])
        lines.append(f"| {step['at_s']:.2f} s | {_cell(step['what'])} | "
                     f"{result} | {_cell(step['note'])} |")
    return "\n".join(lines) + "\n"


def _cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--address", required=True)
    parser.add_argument("--transport", default=None, choices=TRANSPORTS)
    parser.add_argument("--out", default="checkups")
    parser.add_argument("--part", choices=("1", "2", "all"), default="all",
                        help="run one part only")
    args = parser.parse_args()
    parts = ("1", "2") if args.part == "all" else (args.part,)

    transport_name = args.transport or inferred_transport(args.address)
    if transport_name is None:
        parser.error(f"{args.address!r} is not a VISA resource string, so "
                     f"--transport has to be given.")
    def connect():
        transport = TRANSPORTS[transport_name]()
        transport.connect(args.address)
        return transport

    if "1" in parts:
        print("Part 1 needs NOTHING connected to the output.")
        if input("Is everything disconnected? [y/N] ").strip().lower() \
                != "y":
            return 1
    session = Session(connect)
    session.run(parts)

    idn = next((reply for _, sent, reply in session.trace
                if sent.startswith("U0X") and reply.startswith("236")),
               None)
    provenance = describe(idn=idn, code_paths=code_paths_for(
        _driver_source(Keithley236), fleet="smu"))
    stem = f"bench_Keithley236_{time.strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(args.out, exist_ok=True)
    md_path = os.path.join(args.out, stem + ".md")
    json_path = os.path.join(args.out, stem + ".json")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(build_report(session, args.address, provenance))
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump({
            "when": datetime.datetime.now().isoformat(timespec="seconds"),
            "address": args.address,
            "provenance": provenance,
            "stopped_early": session.stopped_early,
            "headlines": session.headlines, "answers": session.answers,
            "steps": session.steps,
        }, handle, indent=2, default=repr)
    print(f"\nWrote {md_path}\n      {json_path}")
    print("Bring both back, whole.")
    return 1 if session.stopped_early else 0


if __name__ == "__main__":
    sys.exit(main())
