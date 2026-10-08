"""
One sitting at the bench with a power supply.

The supply drivers were written from a manual. `smu_checkup.py` settles
whether the driver and the instrument agree on the commands; this runs
it, and then asks the instrument the questions the manual left open -
the ones in the instrument note's *Open questions* - so that both come
home from a single session.

    uv run tools/bench_supply.py --address GPIB0::11::INSTR

It runs in this order, and says what to connect before each part:

  1. **The checkup**, with nothing on the output. Its own report.
  2. **Output off**: the identity, where each setting really stops, how
     a level between two steps is rounded, and what each refusal is
     numbered.
  3. **Output on, nothing attached**: what the limit register says when
     the output comes on, how long a reading takes, and how the output
     moves on a step up, a step down and a switch-off.
  4. **A power resistor attached**: the supply in current limit, out of
     it and back - which is the question the compliance column depends
     on, and the one the checkup cannot ask.
  5. **A hand on the front panel**: a voltage and current you set, read
     back over the bus. The only thing that makes a setpoint readback
     more than the instrument repeating what it was told.
  6. **The over-voltage trip**, if you say yes: what tripping looks like
     in the registers, and whether the output comes back.

Parts 4 to 6 each ask first and can be skipped with Enter.

What it does not do
-------------------
**It does not interpret.** Every step records what was sent and the raw
reply, with the time. The report opens with a few headline observations
- the sequence of `LSR?` values in current limit, say - but they are
observations, copied from the steps, not verdicts. Deciding what they
mean happens afterwards, against the manual.

**It never sends a query the manual does not list.** An unrecognised
command is a line in an error register. An unrecognised *query* is
never answered: the read times out, the link is out of step, and the
session is over. That rules out asking the older units for `OP?`.

SAFETY
------
It energises the output. Part 3 goes to 10 V into nothing. Part 4 asks
for the resistor's value and rating and chooses its own levels from
them: a quarter of the rating in current limit, and a voltage setting
that could not exceed the rating even if the current limit did nothing.
It shows the numbers and waits for a yes. The output is switched off
between parts and in a handler that runs on an exception and on Ctrl-C.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smuniversal_lab_suite.core.provenance import (  # noqa: E402
    as_markdown_lines,
    code_paths_for,
    describe,
)
from smuniversal_lab_suite.core.transports.base import (  # noqa: E402
    TransportDesynchronised,
)
from smuniversal_lab_suite.drivers.base_supply import BaseSupply  # noqa: E402
from smuniversal_lab_suite.drivers.registry import (  # noqa: E402
    UnknownInstrumentError,
    identify,
)
from tools.smu_checkup import (  # noqa: E402
    TRANSPORTS,
    _driver_source,
    inferred_transport,
    install_trace,
)

#: Fraction of the resistor's rating dissipated while the supply is in
#: current limit. A quarter leaves room for a rating that was optimistic
#: and for a resistor sitting on a bench rather than on a heatsink.
POWER_FRACTION = 0.25

#: The smallest current-limit level worth probing at, in amps. Five
#: steps of the 10 mA grid: below that the reading is mostly rounding.
MIN_PROBE_CURRENT_A = 0.05

#: Never probe above this, whatever the resistor could take. The
#: questions here are about registers, not about how much the supply
#: can deliver.
MAX_PROBE_CURRENT_A = 2.0

#: How far above the voltage that current develops the voltage setting
#: is put, to hold the supply in current limit. Twice: clearly limiting,
#: and with a quarter of the rating in limit the resistor sees exactly
#: its rating if the limit fails completely.
OVERDRIVE = 2.0

#: The least overdrive that still counts as "in current limit" when the
#: supply's own maximum voltage is what stops it reaching `OVERDRIVE`.
MIN_OVERDRIVE = 1.2


def resistor_plan(ohms, watts, limits):
    """Levels for the resistor part, or `(None, why)` if it will not do.

    Returns `(plan, None)` where `plan` holds the current setting, the
    voltage it develops, the voltage setting that forces current limit,
    the one that releases it, and the two powers that matter - what the
    resistor dissipates in limit, and what it would if the limit did
    nothing at all.
    """
    if ohms <= 0 or watts <= 0:
        return None, "the resistance and the rating both have to be positive"

    def down(value):
        """Onto the 10 mA / 10 mV grid, rounding toward less power."""
        return int(value * 100 + 1e-9) / 100.0

    amps = min((POWER_FRACTION * watts / ohms) ** 0.5,
               MAX_PROBE_CURRENT_A, limits.max_current / 2.0)
    # A resistor too large for this supply to overdrive: come down
    # until the supply's maximum voltage is `MIN_OVERDRIVE` of what the
    # current develops.
    amps = down(min(amps, limits.max_voltage / (MIN_OVERDRIVE * ohms)))
    if amps < MIN_PROBE_CURRENT_A:
        return None, (
            f"{ohms:g} ohm at {watts:g} W allows {amps:.2f} A on this "
            f"supply, and current limit needs at least "
            f"{MIN_PROBE_CURRENT_A:g} A to read as more than rounding. "
            f"Use a lower resistance or a higher rating - a few ohms at "
            f"25 W or more is ideal")
    develops = amps * ohms
    forcing = down(min(OVERDRIVE * develops, limits.max_voltage))
    releasing = down(develops / 2.0)
    if releasing < 0.05:
        return None, (
            f"{ohms:g} ohm develops only {develops:.3g} V at {amps:.2f} A, "
            f"too little to tell the two modes apart on a 10 mV grid. Use "
            f"a higher resistance")
    return {
        "ohms": ohms,
        "watts": watts,
        "current_a": amps,
        "develops_v": develops,
        "forcing_v": forcing,
        "releasing_v": releasing,
        "power_in_limit_w": amps * amps * ohms,
        "power_if_limit_fails_w": forcing * forcing / ohms,
    }, None


class Session:
    """Runs the parts and records exactly what happened.

    `ask`, `sleep` and `clock` are injected so the whole session can be
    walked offline against a fake instrument, at full speed and with
    scripted answers - which is how it is tested, because the first time
    this meets a real supply is not the time to find a typo in it.
    """

    def __init__(self, driver, transport, log=print, ask=None,
                 sleep=None, clock=None):
        self.driver = driver
        self.transport = transport
        self.log = log
        # Looked up here rather than bound as defaults, so a test of
        # `main()` can stand in for the keyboard and the clock.
        self.ask = ask or input
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self.started = self.clock()
        self.steps = []
        self.headlines = []
        self.answers = {}
        self.stopped_early = None
        self.part = ""
        #: Every exchange with the instrument, from the transport's own
        #: recorder. A step keeps the slice that happened during it.
        self.trace = []
        install_trace(transport, self.trace)

    # ---- recording ----
    def _step(self, what, result=None, note="", since=None):
        entry = {
            "part": self.part,
            "what": what,
            "at_s": round(self.clock() - self.started, 3),
            "result": result,
            "note": note,
            "exchanges": [
                {"ms": round(elapsed * 1000, 1), "sent": sent, "reply": reply}
                for elapsed, sent, reply in self.trace[
                    len(self.trace) if since is None else since:]],
        }
        self.steps.append(entry)
        shown = "" if result is None else f" -> {result!r}"
        self.log(f"    {what}{shown}" + (f"   [{note}]" if note else ""))
        return entry

    def note(self, what, note=""):
        return self._step(what, note=note)

    def headline(self, text):
        self.headlines.append(text)
        self.log(f"  * {text}")

    def query(self, what, command, timeout_s=3.0, note=""):
        """Send one query and record the raw reply, verbatim."""
        mark = len(self.trace)
        try:
            reply = str(self.transport.query(command,
                                             timeout_s=timeout_s)).strip()
        except TransportDesynchronised:
            self._step(what, "<LINK OUT OF STEP>", note, since=mark)
            raise
        except Exception as exc:
            reply = f"<EXCEPTION {type(exc).__name__}: {exc}>"
        self._step(what, reply, note, since=mark)
        return reply

    def write(self, what, command, note=""):
        mark = len(self.trace)
        try:
            self.transport.write(command)
            result = None
        except Exception as exc:
            result = f"<EXCEPTION {type(exc).__name__}: {exc}>"
        self._step(what, result, note, since=mark)

    def call(self, what, action, note=""):
        """Call a driver method and record its answer, with whatever it
        exchanged with the instrument to arrive at it."""
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

    def registers(self, what):
        """The three error registers, raw, each emptied by the read.

        Read directly rather than through `read_error()`: this is the
        evidence the driver's decoding is checked against, so it cannot
        be taken through the decoder.
        """
        mark = len(self.trace)
        values = {}
        for name, command in (("esr", "*ESR?"), ("eer", "EER?"),
                              ("qer", "QER?")):
            try:
                values[name] = str(self.transport.query(command)).strip()
            except TransportDesynchronised:
                self._step(what, "<LINK OUT OF STEP>", since=mark)
                raise
            except Exception as exc:
                values[name] = f"<EXCEPTION {type(exc).__name__}: {exc}>"
        self._step(what, values, since=mark)
        return values

    def poll(self, what, command, count, interval_s, note=""):
        """One query, `count` times, `interval_s` apart. Returns the raw
        replies; each is its own step, so each carries its own time."""
        replies = []
        for index in range(count):
            if index:
                self.sleep(interval_s)
            replies.append(self.query(f"{what} [{index + 1}/{count}]",
                                      command, note=note if not index else ""))
        return replies

    def watch(self, stage, action, polls=4, interval_s=2.0):
        """Ask the driver the same question several times, and keep
        what it read from the limit register to answer each time.

        Through the driver rather than beside it, deliberately. `LSR?`
        empties itself when read, so a probe that polled it directly
        would take each event before the driver saw it - and the record
        would show a driver that noticed nothing, for a reason that
        exists only in the probe.

        Returns `(answers, raw)`: what the driver said, and the `LSR?`
        replies it said it from.
        """
        answers = []
        for index in range(polls):
            if index:
                self.sleep(interval_s)
            answers.append(self.call(f"{stage} [{index + 1}/{polls}]",
                                     action))
        raw = [exchange["reply"] for step in self.steps[-polls:]
               for exchange in step["exchanges"]
               if exchange["sent"].startswith("LSR?")]
        return answers, raw

    def confirm(self, question):
        answer = str(self.ask(f"\n{question} [y/N] ")).strip().lower()
        self.answers[question] = answer
        return answer == "y"

    def number(self, question):
        """A number from the operator, or None for a blank or anything
        that does not parse. Blank is how a part is skipped."""
        answer = str(self.ask(f"{question} ")).strip()
        self.answers[question] = answer
        try:
            return float(answer)
        except ValueError:
            return None

    def safe(self):
        """Output off, and the voltage setting back to zero.

        The second half matters as much as the first: the setting is
        what the front-panel output key energises next.
        """
        try:
            self.driver.safe_output_off()
            self.transport.write("V 0")
        except Exception as exc:
            self.log(f"    ! could not make the output safe: {exc}")

    # ---- part 2: output off ----
    def part_settings(self):
        """Identity, the ends of each range, rounding, and how each
        refusal is numbered. Nothing is energised."""
        self.part = "2 settings, output off"
        driver = self.driver
        limits = driver.LIMITS
        low, high = driver.OVP_RANGE_V

        idn = self.query("identity", "*IDN?")
        self.headline(f"*IDN? is {idn!r}")
        self.call("reset()", driver.reset)
        self.registers("registers after reset")
        self.query("status byte", "*STB?")
        for label, command in (("voltage", "V?"), ("current", "I?"),
                               ("trip", "OVP?")):
            self.query(f"{label} setting after reset", command)

        # The error path, asked for each complaint the driver relies on.
        refusals = {}
        for label, command in (
                ("a current of zero", "I 0"),
                ("a current one step under the floor", "I 0.009"),
                ("a negative voltage", "V -1"),
                ("a word that is not a command", "XYZZY")):
            self.write(f"send {label}", command)
            refusals[command] = self.registers(f"registers after {label}")
        self.headline(
            "refusals (esr/eer): " + ", ".join(
                f"{command!r} -> {r['esr']}/{r['eer']}"
                for command, r in refusals.items()))

        # Where each setting really stops. The top of the range should
        # land; one step above it should be refused and leave the
        # setting where it was.
        edges = {}
        for label, head, query, top in (
                ("voltage", "V", "V?", limits.max_voltage),
                ("current", "I", "I?", limits.max_current),
                ("trip", "OVP", "OVP?", high)):
            self.write(f"{label} to the top of its range",
                       f"{head} {top:.6g}")
            at_top = self.query(f"{label} setting", query)
            at_top_registers = self.registers(f"registers at the top "
                                              f"({label})")
            self.write(f"{label} one step above the top",
                       f"{head} {top + 0.01:.6g}")
            above = self.query(f"{label} setting", query)
            above_registers = self.registers(f"registers above the top "
                                             f"({label})")
            edges[label] = (at_top, at_top_registers["eer"], above,
                            above_registers["eer"])
        self.write("trip one step under the bottom", f"OVP {low - 0.01:.6g}")
        self.registers("registers under the bottom (trip)")
        self.write("trip to the bottom of its range", f"OVP {low:.6g}")
        self.query("trip setting", "OVP?")
        self.registers("registers at the bottom (trip)")
        self.headline(
            "range ends (at top, eer, one step above, eer): " + "; ".join(
                f"{label} {values}" for label, values in edges.items()))

        # Back to somewhere harmless before anything else.
        self.write("voltage back to zero", "V 0")
        self.write("current back to the floor", "I 0.01")
        self.write("trip back to its widest", f"OVP {high:.6g}")

        # Rounding. The manual says "rounded up"; the newer one says
        # "rounded".
        rounding = {}
        for command, query in (("V 1.004", "V?"), ("V 1.005", "V?"),
                               ("V 1.006", "V?"), ("I 0.104", "I?"),
                               ("I 0.106", "I?")):
            self.write("an off-grid level", command)
            rounding[command] = self.query("lands as", query)
        self.headline("off-grid levels land as: " + ", ".join(
            f"{command!r} -> {reply!r}"
            for command, reply in rounding.items()))
        self.registers("registers after the rounding probes")
        self.write("voltage back to zero", "V 0")
        self.write("current back to the floor", "I 0.01")

    # ---- part 3: output on, nothing attached ----
    def part_open_circuit(self):
        """The limit register at turn-on, the cost of a reading, and how
        the output moves. Nothing attached."""
        self.part = "3 output on, nothing attached"
        driver = self.driver

        self.call("set_source_function('voltage')",
                  lambda: driver.set_source_function("voltage"))
        self.call("set_current_limit(0.05)",
                  lambda: driver.set_current_limit(0.05))
        self.call("set_voltage_level(1.0)",
                  lambda: driver.set_voltage_level(1.0))
        self.query("limit register before the output comes on", "LSR?")
        self.call("output_on()", driver.output_on,
                  note="the driver reads LSR? once itself, to discard "
                       "what came before")
        said, raw = self.watch("regulation() after turn-on",
                               driver.regulation, polls=3, interval_s=1.0)
        self.headline(f"after OP 1, nothing attached, 1 s apart: LSR? read "
                      f"{raw}, regulation() said {said}")
        self.call("compliance_tripped()", driver.compliance_tripped)
        self.registers("registers with the output on")

        # What one reading costs. Timed per call, because the first
        # after a change may not be the same as the rest.
        times = []
        for index in range(10):
            started = self.clock()
            self.call(f"measure() [{index + 1}/10]", driver.measure)
            times.append(round((self.clock() - started) * 1000, 1))
        self.headline(f"measure() took, ms: {times}")
        self.query("power", "POWER?")

        # How the output moves. Polled rather than slept through, so
        # the report shows the readback catching up.
        self.write("step up to 10 V", "V 10")
        up = self.poll("output voltage after the step up", "VO?",
                       count=12, interval_s=0.25)
        self.headline(f"VO? after 1 V -> 10 V, 0.25 s apart: {up}")
        self.query("limit register after the step up", "LSR?")
        self.write("step down to 1 V", "V 1")
        down = self.poll("output voltage after the step down", "VO?",
                         count=24, interval_s=0.25,
                         note="nothing attached, and the supply cannot "
                              "sink - this is the output capacitor "
                              "discharging through whatever is there")
        self.headline(f"VO? after 10 V -> 1 V, nothing attached: {down}")
        self.query("limit register after the step down", "LSR?")

        settled = self.call("set_voltage_verified(5.0)",
                            lambda: driver.set_voltage_verified(5.0),
                            note="the instrument's own settle check, VV")
        self.headline(f"VV 5 with nothing attached returned {settled!r}")
        self.registers("registers after the verified set")

        self.call("output_off()", driver.output_off)
        off = self.poll("output voltage after switching off", "VO?",
                        count=12, interval_s=0.25,
                        note="off is not a disconnection")
        self.headline(f"VO? after OP 0 from 5 V: {off}")
        self.registers("registers after switching off")

    # ---- part 4: a resistor ----
    def part_resistor(self):
        """In current limit, out of it and back, with what the register
        says at each stage. The checkup cannot ask this."""
        self.part = "4 a power resistor attached"
        driver = self.driver

        self.log("\nPart 4 needs a power resistor across the output. A few "
                 "ohms at 25 W or more is ideal.\nConnect it now, or press "
                 "Enter at the next question to skip this part.")
        ohms = self.number("Resistance, in ohms?")
        if ohms is None:
            self.note("skipped", "no resistance given")
            return
        watts = self.number("Its power rating, in watts?")
        if watts is None:
            self.note("skipped", "no rating given")
            return
        plan, why_not = resistor_plan(ohms, watts, driver.LIMITS)
        if plan is None:
            self.note("skipped", why_not)
            self.log(f"  Not run: {why_not}.")
            return
        self.answers["resistor plan"] = plan
        self.log(
            f"\n  Current setting   {plan['current_a']:.2f} A\n"
            f"  In current limit  {plan['develops_v']:.2f} V across it, "
            f"{plan['power_in_limit_w']:.1f} W of its {watts:g} W\n"
            f"  Voltage setting   {plan['forcing_v']:.2f} V to force the "
            f"limit, {plan['releasing_v']:.2f} V to release it\n"
            f"  If the limit did nothing it would dissipate "
            f"{plan['power_if_limit_fails_w']:.1f} W")
        if not self.confirm("The resistor is connected and those levels "
                            "are safe for it. Go ahead?"):
            self.note("skipped", "not confirmed")
            return

        def watch(stage, polls=4):
            said, raw = self.watch(f"compliance_tripped() {stage}",
                                   driver.compliance_tripped, polls=polls)
            self.headline(f"{stage}: LSR? read {raw}, the driver said "
                          f"{said}")

        self.call("set_source_function('voltage')",
                  lambda: driver.set_source_function("voltage"))
        self.call("set_current_limit()",
                  lambda: driver.set_current_limit(plan["current_a"]))
        self.call("set_voltage_level() to force the limit",
                  lambda: driver.set_voltage_level(plan["forcing_v"]))
        self.call("output_on()", driver.output_on)
        self.sleep(1.5)
        reading = self.call("measure() in current limit", driver.measure)
        self.headline(
            f"in current limit, set {plan['current_a']:.2f} A into "
            f"{ohms:g} ohm: measure() gave {reading}")
        self.query("power in current limit", "POWER?")

        # The question. Does the bit come back while the limit holds?
        watch("in current limit, sourcing voltage")
        self.call("set_voltage_level() to release the limit",
                  lambda: driver.set_voltage_level(plan["releasing_v"]))
        self.sleep(1.5)
        self.call("measure() out of limit", driver.measure)
        watch("back in constant voltage, sourcing voltage")
        self.call("set_voltage_level() to force the limit again",
                  lambda: driver.set_voltage_level(plan["forcing_v"]))
        self.sleep(1.5)
        watch("in current limit a second time")

        # The same two states read as a current source, where clamped
        # means the opposite thing.
        self.call("set_source_function('current')",
                  lambda: driver.set_source_function("current"))
        watch("in current limit, sourcing current", polls=2)
        self.call("set_voltage_level() to release the limit",
                  lambda: driver.set_voltage_level(plan["releasing_v"]))
        self.sleep(1.5)
        watch("in constant voltage, sourcing current", polls=2)
        self.call("set_source_function('voltage')",
                  lambda: driver.set_source_function("voltage"))

        # Meter damping, on a steady load. Says whether the bus reading
        # changes at all with it; a pulsed load would say more.
        self.call("set_voltage_level() to force the limit",
                  lambda: driver.set_voltage_level(plan["forcing_v"]))
        self.sleep(1.5)
        plain = self.poll("current, damping off", "IO?", count=5,
                          interval_s=0.3)
        self.call("set_meter_damping(True)",
                  lambda: driver.set_meter_damping(True))
        self.sleep(1.5)
        damped = self.poll("current, damping on", "IO?", count=5,
                           interval_s=0.3)
        self.call("set_meter_damping(False)",
                  lambda: driver.set_meter_damping(False))
        self.headline(f"IO? with damping off {plain}, on {damped}")

        # A step down with something to discharge into.
        self.write("step down under load", f"V {plan['releasing_v']:.6g}")
        loaded = self.poll("output voltage after the step down", "VO?",
                           count=12, interval_s=0.25)
        self.headline(f"VO? after {plan['forcing_v']:.2f} V -> "
                      f"{plan['releasing_v']:.2f} V into {ohms:g} ohm: "
                      f"{loaded}")
        self.registers("registers at the end of the resistor part")
        self.call("output_off()", driver.output_off)

    # ---- part 5: the front panel ----
    def part_front_panel(self):
        """A setting made by hand, read back over the bus.

        Over the bus a query that reads the instrument and a query that
        repeats the last thing it was sent give the same reply. Only a
        value the software never wrote tells them apart.
        """
        self.part = "5 set by hand, read over the bus"
        self.log("\nPart 5: the output is off. Press LOCAL on the front "
                 "panel, set a voltage and a current limit of your own "
                 "choosing - odd values, like 7.77 V and 1.23 A - and then "
                 "type them here.\nPress Enter at the first question to "
                 "skip this part.")
        volts = self.number("Voltage you set, in volts?")
        if volts is None:
            self.note("skipped", "no voltage given")
            return
        amps = self.number("Current limit you set, in amps?")
        got_v = self.query("voltage setting, read over the bus", "V?",
                           note=f"set by hand to {volts:g} V")
        got_i = None
        if amps is not None:
            got_i = self.query("current setting, read over the bus", "I?",
                               note=f"set by hand to {amps:g} A")
        self.headline(f"set by hand {volts:g} V / "
                      f"{'-' if amps is None else f'{amps:g} A'}; the bus "
                      f"read {got_v!r} / {got_i!r}")
        self.write("voltage back to zero", "V 0")
        self.write("current back to the floor", "I 0.01")

    # ---- part 6: the trip ----
    def part_trip(self):
        """Trip the over-voltage protection on purpose, and watch.

        Needs the output open: in current limit the voltage across a
        resistor never reaches the trip.
        """
        self.part = "6 the over-voltage trip"
        driver = self.driver
        self.log("\nPart 6 trips the over-voltage protection on purpose: "
                 "trip at 5 V, output asked for 6 V. Disconnect the "
                 "resistor first - it needs nothing on the output.")
        if not self.confirm("Nothing is connected. Trip it?"):
            self.note("skipped", "not confirmed")
            return
        high = driver.OVP_RANGE_V[1]
        self.call("set_source_function('voltage')",
                  lambda: driver.set_source_function("voltage"))
        self.call("set_current_limit(0.05)",
                  lambda: driver.set_current_limit(0.05))
        self.call("set_voltage_level(3.0)",
                  lambda: driver.set_voltage_level(3.0))
        self.call("set_overvoltage_trip(5.0)",
                  lambda: driver.set_overvoltage_trip(5.0))
        self.call("output_on()", driver.output_on)
        self.sleep(1.0)
        self.query("output voltage before", "VO?")
        self.registers("registers before")
        self.write("ask for 6 V, above the trip", "V 6")
        self.sleep(0.5)
        said, raw = self.watch("protection_tripped()",
                               driver.protection_tripped, polls=1)
        seen = []
        for index in range(3):
            self.sleep(0.5)
            seen.append((self.query(f"limit register [{index + 1}/3]",
                                    "LSR?"),
                         self.query(f"output voltage [{index + 1}/3]",
                                    "VO?")))
        after = self.registers("registers after the trip")
        self.headline(f"after V 6 with the trip at 5 V: LSR? read {raw}, "
                      f"protection_tripped() said {said}; then (LSR?, VO?) "
                      f"half a second apart {seen}; esr/eer {after['esr']}/"
                      f"{after['eer']}")

        # Does it come back by itself, and does it come back when asked?
        self.write("voltage back under the trip", "V 3")
        self.sleep(2.0)
        left = self.query("output voltage, left alone for 2 s", "VO?")
        self.call("output_off()", driver.output_off)
        self.write("clear the registers", "*CLS")
        self.call("set_overvoltage_trip() back to its widest",
                  lambda: driver.set_overvoltage_trip(high))
        self.call("set_voltage_level(1.0)",
                  lambda: driver.set_voltage_level(1.0))
        self.call("output_on()", driver.output_on)
        self.sleep(1.5)
        again = self.query("output voltage after switching on again", "VO?")
        self.registers("registers after recovering")
        self.headline(f"recovery: {left!r} left alone at 3 V, {again!r} "
                      f"after OP 0, *CLS, OP 1 at 1 V")
        self.call("output_off()", driver.output_off)

    # ---- running them ----
    PARTS = ("part_settings", "part_open_circuit", "part_resistor",
             "part_front_panel", "part_trip")

    def run(self, parts=None):
        """Every part in order. One that raises is recorded and the rest
        still run; a link out of step ends the session, because nothing
        after it could be matched to its question."""
        for name in parts or self.PARTS:
            self.log(f"\n  {name}")
            try:
                getattr(self, name)()
            except TransportDesynchronised as exc:
                self.stopped_early = f"{name}: {exc}"
                self.log("    ! the link went out of step; stopping here")
                break
            except Exception:
                self._step(f"{name} raised",
                           note=traceback.format_exc(limit=4))
                self.log("    ! this part raised; continuing with the rest")
            finally:
                self.safe()
        self.part = "end"
        try:
            high = self.driver.OVP_RANGE_V[1]
            self.write("trip left at its widest", f"OVP {high:.6g}")
            self.write("current left at the floor", "I 0.01")
        except Exception as exc:
            self.log(f"    ! could not restore the settings: {exc}")
        return self.steps


def build_report(session, idn, address, provenance, checkup_exit):
    """The session as Markdown: headlines, then every step."""
    driver = session.driver
    lines = [
        f"# Supply bench session - {type(driver).DISPLAY_NAME}",
        "",
        f"- **When:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Address:** {address or 'not recorded'}",
        f"- **Driver:** `{type(driver).__name__}`",
        f"- **Identity:** `{idn}`",
        *as_markdown_lines(provenance or {}),
        f"- **Checkup run first:** "
        f"{'not run' if checkup_exit is None else f'exit code {checkup_exit}'}",
        "",
        "> Observations, not verdicts. Each headline is copied from the "
        "steps below it; what it means is decided against the manual.",
        "",
    ]
    if session.stopped_early:
        lines += [f"> **This session did not finish.** The link went out "
                  f"of step in {session.stopped_early}. Everything below "
                  f"was recorded before that.", ""]
    lines += ["## Headlines", ""]
    lines += [f"- {text}" for text in session.headlines] or ["- none"]
    lines += ["", "## What the operator answered", ""]
    for question, answer in session.answers.items():
        lines.append(f"- {question} `{answer}`")
    if not session.answers:
        lines.append("- nothing was asked")
    lines.append("")

    part = None
    for step in session.steps:
        if step["part"] != part:
            part = step["part"]
            lines += [f"## Part {part}", "",
                      "| At, s | Step | Result | Sent -> reply |",
                      "|---|---|---|---|"]
        exchanges = "; ".join(
            f"`{e['sent']}`" + (f" -> `{e['reply']}`" if e["reply"] else "")
            for e in step["exchanges"])
        result = "" if step["result"] is None else f"`{step['result']}`"
        note = f" *{step['note']}*" if step["note"] else ""
        cells = (f"{step['at_s']:.2f}", f"{step['what']}{note}", result,
                 exchanges)
        lines.append("| " + " | ".join(_cell(text) for text in cells) + " |")
    lines.append("")
    return "\n".join(lines)


def _cell(text):
    """One table cell: a reply or a traceback must not be able to end
    the row it is in."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_reports(session, idn, address, out, provenance=None,
                  checkup_exit=None):
    """Write the Markdown and the JSON. Returns both paths."""
    name = type(session.driver).__name__
    stem = f"supply_bench_{name}_{time.strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(out, exist_ok=True)
    md_path = os.path.join(out, stem + ".md")
    json_path = os.path.join(out, stem + ".json")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(build_report(session, idn, address, provenance,
                                  checkup_exit))
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump({
            "driver": name,
            "identity": idn,
            "address": address,
            "when": datetime.datetime.now().isoformat(timespec="seconds"),
            "provenance": provenance or {},
            "checkup_exit": checkup_exit,
            "stopped_early": session.stopped_early,
            "headlines": session.headlines,
            "answers": session.answers,
            "steps": session.steps,
            "trace": [{"ms": round(elapsed * 1000, 1), "sent": sent,
                       "reply": reply}
                      for elapsed, sent, reply in session.trace],
        }, handle, indent=2, default=repr)
    return md_path, json_path


def run_checkup(address, transport, out):
    """`smu_checkup.py` on the same address, in its own process.

    Its own process because it opens and closes its own connection and
    writes its own report - exactly what it does when run by hand, so
    the commissioning record does not depend on this tool.
    """
    command = [sys.executable,
               os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "smu_checkup.py"),
               "--address", address, "--trace", "--out", out]
    if transport:
        command += ["--transport", transport]
    return subprocess.call(command)


def main():
    parser = argparse.ArgumentParser(
        description="The checkup and the open questions for a power "
                    "supply, in one sitting.")
    parser.add_argument("--address", required=True)
    parser.add_argument("--transport", default=None, choices=TRANSPORTS)
    parser.add_argument("--out", default="checkups")
    parser.add_argument("--skip-checkup", action="store_true",
                        help="go straight to the probes - for a second "
                             "attempt at them, not for a first session")
    args = parser.parse_args()

    transport_name = args.transport or inferred_transport(args.address)
    if transport_name is None:
        parser.error(f"{args.address!r} is not a VISA resource string, so "
                     f"--transport has to be given.")

    checkup_exit = None
    if not args.skip_checkup:
        print("Part 1: the checkup. Nothing connected to the output.\n")
        checkup_exit = run_checkup(args.address, args.transport, args.out)
        print(f"\nThe checkup finished with exit code {checkup_exit}.")
        if checkup_exit:
            answer = input("It did not finish cleanly. Carry on with the "
                           "probes anyway? [y/N] ").strip().lower()
            if answer != "y":
                return checkup_exit

    transport = TRANSPORTS[transport_name]()
    print(f"\nConnecting to {args.address} over {transport_name}...")
    try:
        transport.connect(args.address)
    except Exception as exc:
        print(f"Could not connect: {exc}")
        return 1

    session = None
    try:
        try:
            driver, idn = identify(transport)
        except (TypeError, UnknownInstrumentError) as exc:
            print(f"Connected, but could not identify: {exc}")
            return 1
        print(f"Detected: {type(driver).DISPLAY_NAME}")
        print(f"Identity: {idn}")
        if not isinstance(driver, BaseSupply):
            print("This tool is for power supplies. For anything else, "
                  "run smu_checkup.py.")
            return 1

        print("\nLeave the output unconnected until the resistor is asked "
              "for.")
        session = Session(driver, transport)
        try:
            session.run()
        finally:
            provenance = describe(idn=idn, code_paths=code_paths_for(
                _driver_source(type(driver)), fleet="supply"))
            md_path, json_path = write_reports(
                session, idn, args.address, args.out, provenance,
                checkup_exit)
            print(f"\nWrote {md_path}\n      {json_path}")
            print("Bring both back, with the checkup's two files - whole, "
                  "not summarised.")
        return 0
    finally:
        # Runs on an exception and on Ctrl-C. The last thing that
        # happens is the output coming off.
        if session is not None:
            session.safe()
        try:
            transport.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
