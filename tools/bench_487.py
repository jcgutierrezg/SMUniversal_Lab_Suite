"""
One sitting with the Keithley 487: the questions its checkup cannot ask.

The checkup passes on the 487. What it cannot settle is in the
instrument note's *Open questions*, and every one needs either a hand on
the front panel or something across the terminals. This asks them all,
in two parts, and records what came back.

    uv run tools/bench_487.py --address GPIB0::3::INSTR

Part 1 - nothing connected to the source or the triax input
  1. What `*IDN?` does to it - the first thing the app's Connect sends.
  2. The offset on each low range with the input open, before and after
     the instrument's own zero correction (`C2X`).
  3. The status-word readbacks against the front panel: you set a range
     and a limit by hand, it reads them over the bus. Skippable.

Part 2 - a resistor from the source's HI to the triax centre, the two
LOs joined. It asks for the value, and chooses its levels from it.
  4. Whether a reading is ever one conversion late: two levels,
     alternated, read at once.
  5. A deliberate trip of the 25 uA current limit, and what
     `compliance_tripped()` says below, in and after it.
  6. Settling: readings as fast as they come after a step, and after a
     range change made at 0 V.
  7. The smallest voltage step: plus and minus small levels around zero,
     and whether the current follows the sign.

Nothing goes above 50 V. A step to 500 V needs a closed fixture with
the interlock, and is a separate, deliberate session.

It does not interpret. Every step records what was asked and the raw
answer, with the time; the few headlines at the top of the report are
counts copied from the steps, not verdicts. The output goes off between
parts, at the end, and on any error or Ctrl-C.
"""
import argparse
import datetime
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smuniversal_lab_suite.core.provenance import (  # noqa: E402
    as_markdown_lines,
    code_paths_for,
    describe,
)
from smuniversal_lab_suite.core.ranges import AUTO, RangePlan  # noqa: E402
from smuniversal_lab_suite.core.transports.base import (  # noqa: E402
    TransportDesynchronised,
)
from smuniversal_lab_suite.drivers.keithley_487 import (  # noqa: E402
    Keithley487,
)
from tools.smu_checkup import (  # noqa: E402
    TRANSPORTS,
    _driver_source,
    inferred_transport,
    install_trace,
    trace_times,
)

#: The smaller current limit, which every level in part 2 is chosen
#: against: it keeps the power in the resistor under 1.3 mW whatever
#: the resistance.
LIMIT_A = 25e-6

#: Never source more than this here.
MAX_V = 50.0

#: The resistor values part 2 can work with. Below, the levels that
#: keep inside the limit are too small to read well; above, a trip of
#: the 25 uA limit needs more than 50 V.
MIN_OHMS, MAX_OHMS = 10e3, 1.3e6

#: The low ranges whose offset part 1 measures: R1 to R4, 2 nA to 2 uA.
ZERO_RANGES = ((1, 2e-9), (2, 2e-8), (3, 2e-7), (4, 2e-6))
ZERO_READINGS = 10

#: The levels around zero for the smallest-step question, in volts. One
#: count of the 50 V range is 1 mV.
SMALL_LEVELS_V = (0.0005, 0.001, 0.002, 0.005)


def resistor_plan(ohms):
    """Levels for part 2, or `(None, why)` if the resistor will not do."""
    if not MIN_OHMS <= ohms <= MAX_OHMS:
        return None, (
            f"{ohms:g} ohm is outside {MIN_OHMS:g} to {MAX_OHMS:g} ohm. "
            f"100 kohm is ideal")
    return {
        "ohms": ohms,
        # Half the limit: comfortably regulating, never near the clamp.
        "step_v": round(min(0.5 * LIMIT_A * ohms, 10.0), 3),
        "below_v": round(0.5 * LIMIT_A * ohms, 3),
        # Twice the limit's worth: clamping, by a margin the +/-20% on
        # the limit cannot close.
        "trip_v": round(min(2.0 * LIMIT_A * ohms, MAX_V), 3),
    }, None


class Session:
    """Runs the parts and records what happened.

    `connect` returns a connected transport; it is called again when the
    link has to be rebuilt. `ask`, `sleep` and `clock` are injected so
    the whole session can be walked offline against the fake instrument.
    """

    def __init__(self, connect, log=print, ask=None, sleep=None,
                 clock=None):
        self.connect = connect
        self.log = log
        self.ask = ask or input
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
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
        self.driver = Keithley487(self.transport)
        if clear:
            self.transport.clear()

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
        """A driver call, its answer, and what it exchanged to get it.
        A lost link is recorded and raised: the caller decides."""
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

    def reading(self, what, note=""):
        """One reading through the driver. Returns amps, or None."""
        result = self.call(what, lambda: self.driver.measure()[1], note)
        return result if isinstance(result, float) else None

    def prepare(self, limit_a=LIMIT_A, source_v=MAX_V, measure=AUTO):
        """Reset and configure for voltage sourcing; output still off."""
        driver = self.driver
        self.call("reset()", driver.reset)
        driver.set_source_function("voltage")
        self.call("apply_ranges()", lambda: driver.apply_ranges(
            RangePlan.for_sourcing("voltage", source_range=source_v,
                                   measure_range=measure),
            log=lambda message: None))
        self.call("set_current_limit()",
                  lambda: driver.set_current_limit(limit_a))
        self.call("set_voltage_level(0)",
                  lambda: driver.set_voltage_level(0.0))

    def off(self):
        try:
            self.driver.safe_output_off()
        except Exception:
            pass

    # ---- part 1: nothing attached ----------------------------------
    def part_idn(self):
        self.part = "1.1 *IDN?"
        self.log("\n1.1  What *IDN? does to it")
        try:
            self.raw("*IDN? - as the app's Connect sends it", "*IDN?",
                     timeout_s=2.0)
        except TransportDesynchronised:
            pass
        # A fresh link, and the error word asked for at once - before any
        # clear, which is what the app's next step would do and which
        # may hide what the *IDN? left behind.
        self._open()
        try:
            self.raw("U1X on a fresh link, before any clear", "U1X",
                     timeout_s=2.0)
        except TransportDesynchronised:
            self._open()
        self._open(clear=True)
        self.call("device clear (SDC)", lambda: "sent")
        self.raw("U1X after the clear", "U1X")
        self.raw("U2X - is it still answering", "U2X")

    def part_zero(self):
        self.part = "1.2 zero correction"
        self.log("\n1.2  The offset on each low range, input open")
        self.prepare()
        driver = self.driver
        driver.set_nplc(1)
        for option, full_scale in ZERO_RANGES:
            name = f"R{option} ({full_scale:g} A)"
            driver._send(f"R{option}")
            before = [self.reading(f"{name} before C2X [{i + 1}]")
                      for i in range(ZERO_READINGS)]
            self.call(f"{name}: C2X, zero check and correct",
                      lambda: driver._send("C2"))
            self.raw(f"{name}: U0X after C2X", "U0X")
            after = [self.reading(f"{name} after C2X [{i + 1}]")
                     for i in range(ZERO_READINGS)]
            self.headline(
                f"{name}: open-input mean {_mean(before)} before zero "
                f"correction, {_mean(after)} after")
        self.raw("U1X after the zero corrections", "U1X")

    def part_front_panel(self):
        self.part = "1.3 front panel"
        self.log("\n1.3  The readbacks against the front panel")
        answer = self.ask(
            "\nThis part needs you at the 487's front panel. Press LOCAL, "
            "then set:\n  V-source range 500 V, I-limit 2.5 mA, current "
            "range 2 uA with autorange OFF.\nPress Enter when done, or "
            "type s to skip: ").strip().lower()
        self.answers["front panel 1"] = answer
        if answer == "s":
            self.call("skipped at the operator's request", lambda: None)
            return
        self._read_back("set by hand: 500 V range, 2.5 mA, 2 uA range")
        answer = self.ask(
            "\nNow LOCAL again, and set:\n  V-source range 50 V, I-limit "
            "25 uA, current range 200 nA with autorange OFF.\nEnter when "
            "done: ").strip().lower()
        self.answers["front panel 2"] = answer
        self._read_back("set by hand: 50 V range, 25 uA, 200 nA range")

    def _read_back(self, note):
        self.raw("U0X", "U0X", note=note)
        for what, reader in (
                ("read_current_limit()", self.driver.read_current_limit),
                ("read_source_voltage_range()",
                 self.driver.read_source_voltage_range),
                ("read_measure_current_range()",
                 self.driver.read_measure_current_range)):
            self.call(what, reader, note=note)

    # ---- part 2: a resistor ----------------------------------------
    def part_resistor(self):
        answer = self.ask(
            "\nPart 2 needs a resistor from the V-source HI to the triax "
            "centre, with the two LOs joined.\nIts value in ohms (100k "
            "is ideal), or Enter to skip part 2: ").strip().lower()
        self.answers["resistor"] = answer
        if not answer:
            self.part = "2 resistor"
            self.call("part 2 skipped at the operator's request",
                      lambda: None)
            return
        try:
            ohms = _ohms(answer)
        except ValueError:
            self.part = "2 resistor"
            self.call(f"part 2 skipped: {answer!r} is not a resistance",
                      lambda: None)
            return
        plan, why = resistor_plan(ohms)
        self.part = "2 resistor"
        if plan is None:
            self.call(f"part 2 skipped: {why}", lambda: None)
            return
        self.call("the plan", lambda: plan)
        if not self.wiring_carries_current(plan):
            return
        self.part_late(plan)
        self.part_trip(plan)
        self.part_settling(plan)
        self.part_small_steps(plan)

    def wiring_carries_current(self, plan):
        """One level, one reading, before anything else in part 2.

        The first sitting, 2026-10-15, ran every part of part 2 into an
        open circuit - about 1 nA at every level, where 12.5 uA was due -
        and recorded seven sections of nothing. The source floats, so a
        missing link between its LO and the ammeter's LO is enough. So
        part 2 now asks first, and stops with a reason if the current
        is not at least half of what the resistor should pass.
        """
        self.part = "2 wiring"
        self._energised()
        expected = plan["step_v"] / plan["ohms"]
        self.call(f"set {plan['step_v']:g} V",
                  lambda: self.driver.set_voltage_level(plan["step_v"]))
        amps = [self.reading(f"wiring check [{index + 1}]",
                             note=f"expected {expected:.4g} A")
                for index in range(3)]
        self.off()
        mean = _mean_value(amps)
        if mean is not None and mean >= 0.5 * expected:
            self.headline(f"wiring: {mean:.4g} A of {expected:.4g} A "
                          f"expected - carrying current")
            return True
        self.headline(
            f"wiring: {_mean(amps)} where {expected:.4g} A was expected - "
            f"no current is reaching the ammeter. Check that the "
            f"V-source LO is joined to the ammeter LO (the black clip), "
            f"and that the resistor is in series between the V-source HI "
            f"and the triax centre (the red clip). Part 2 stopped here")
        return False

    def _energised(self, source_v=MAX_V):
        self.prepare(source_v=source_v)
        self.call("output_on()", self.driver.output_on)

    def part_late(self, plan):
        self.part = "2.4 one conversion late?"
        self.log("\n2.4  Is a reading ever one conversion late?")
        self._energised()
        ohms, high = plan["ohms"], plan["step_v"]
        own = late = 0
        for index in range(20):
            level = high if index % 2 else 0.0
            self.call(f"set {level:g} V",
                      lambda v=level: self.driver.set_voltage_level(v))
            amps = self.reading(f"reading at {level:g} V, no wait",
                                note=f"expected {level / ohms:.4g} A")
            if amps is None:
                continue
            other = (high if level == 0 else 0.0) / ohms
            if abs(amps - level / ohms) < abs(amps - other):
                own += 1
            else:
                late += 1
        self.headline(f"late readings: {own} matched their own level, "
                      f"{late} the previous one")
        self.off()

    def part_trip(self, plan):
        self.part = "2.5 current-limit trip"
        self.log("\n2.5  A deliberate trip of the 25 uA limit")
        self._energised()
        driver = self.driver
        seen = {}
        for stage, level in (("below", plan["below_v"]),
                             ("in limit", plan["trip_v"]),
                             ("back below", plan["below_v"])):
            self.call(f"{stage}: set {level:g} V",
                      lambda v=level: driver.set_voltage_level(v))
            answers = []
            for index in range(3):
                self.reading(f"{stage}: reading [{index + 1}]")
                answers.append(self.call(
                    f"{stage}: compliance_tripped() [{index + 1}]",
                    driver.compliance_tripped))
            seen[stage] = answers
        self.headline(f"compliance_tripped(): {seen}")
        self.off()

    def part_settling(self, plan):
        self.part = "2.6 settling"
        self.log("\n2.6  Settling after a step, and after a range change")
        self._energised()
        driver = self.driver
        self.call(f"step 0 -> {plan['step_v']:g} V",
                  lambda: driver.set_voltage_level(plan["step_v"]))
        for index in range(10):
            self.reading(f"after the step [{index + 1}]",
                         note=f"settled: {plan['step_v'] / plan['ohms']:.4g} A")
        self.call("back to 0 V", lambda: driver.set_voltage_level(0.0))
        for source_v, name in ((500.0, "500 V"), (50.0, "50 V")):
            self.call(f"range to {name}, at 0 V", lambda v=source_v:
                      driver.apply_ranges(RangePlan.for_sourcing(
                          "voltage", source_range=v, measure_range=AUTO),
                          log=lambda message: None))
            for index in range(5):
                self.reading(f"after the change to {name} [{index + 1}]",
                             note="settled: 0 A")
        self.off()

    def part_small_steps(self, plan):
        self.part = "2.7 smallest step"
        self.log("\n2.7  Does the current follow the sign of a small level?")
        self._energised(source_v=10.0)
        driver = self.driver
        follows = []
        for magnitude in SMALL_LEVELS_V:
            pair = {}
            for sign in (1, -1):
                level = sign * magnitude
                self.call(f"set {level * 1000:+g} mV",
                          lambda v=level: driver.set_voltage_level(v))
                readings = [self.reading(f"{level * 1000:+g} mV [{i + 1}]")
                            for i in range(3)]
                pair[sign] = _mean_value(readings)
            agrees = (pair[1] is not None and pair[-1] is not None
                      and pair[1] > 0 > pair[-1])
            follows.append(f"{magnitude * 1000:g} mV: "
                           f"{'follows' if agrees else 'does not follow'}")
        self.headline("sign at small levels - " + "; ".join(follows))
        self.off()

    # ---- the whole sitting -----------------------------------------
    def run(self, parts=("1", "2")):
        try:
            if "1" in parts:
                self.part_idn()
                self.part_zero()
                self.off()
                self.part_front_panel()
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


def _mean_value(values):
    numbers = [v for v in values if isinstance(v, float)]
    return statistics.fmean(numbers) if numbers else None


def _mean(values):
    mean = _mean_value(values)
    return "no readings" if mean is None else f"{mean:.3g} A"


def _ohms(text):
    text = text.strip().lower().replace("ohm", "").replace("Ω", "")
    scale = {"k": 1e3, "m": 1e6}.get(text[-1:], 1.0)
    return float(text[:-1] if scale != 1.0 else text) * scale


def build_report(session, address, provenance):
    lines = [
        "# Keithley 487 - one sitting at the bench",
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
                        help="run one part only - for a second go at part "
                             "2 once its wiring is right")
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
        print("Part 1 needs NOTHING connected to the source or the triax "
              "input.")
        if input("Is everything disconnected? [y/N] ").strip().lower() \
                != "y":
            return 1
    session = Session(connect)
    session.run(parts)

    idn = next((reply for _, sent, reply in session.trace
                if sent.startswith("U2X") and reply.startswith("487")),
               None)
    provenance = describe(idn=idn, code_paths=code_paths_for(
        _driver_source(Keithley487), fleet="smu"))
    stem = f"bench_Keithley487_{time.strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(args.out, exist_ok=True)
    md_path = os.path.join(args.out, stem + ".md")
    json_path = os.path.join(args.out, stem + ".json")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(build_report(session, args.address, provenance))
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump({
            "when": datetime.datetime.now().isoformat(timespec="seconds"),
            "address": args.address, "provenance": provenance,
            "stopped_early": session.stopped_early,
            "headlines": session.headlines, "answers": session.answers,
            "steps": session.steps,
        }, handle, indent=2, default=repr)
    print(f"\nWrote {md_path}\n      {json_path}")
    print("Bring both back, whole.")
    return 1 if session.stopped_early else 0


if __name__ == "__main__":
    sys.exit(main())
