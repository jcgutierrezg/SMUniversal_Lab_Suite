"""
The first sitting with the Keysight B2987A, before there is a driver.

The B2980 SCPI reference is a proper one - a command summary with reset
values, an error list, a status-word table - so the spellings are not in
doubt. What it leaves open, or contradicts itself on, is what decides
the driver's shape:

  * **Source ranges.** 20 V (+/-21 V), +1000 V (-1 V to +1000 V) and
    -1000 V (-1000 V to +1 V). The two high ranges are one-sided, so a
    sweep through zero beyond 21 V fits no single range. Does a level
    beyond the range in force get refused, clipped, or move the range?
    Can the range change with the output on, at 0 V?
  * **The interlock.** Open, the output is "limited to +/-21 V". Is a
    higher level refused when it is set, or only at output-on?
  * **The current limit.** No command sets one. The source stops at
    20 mA (1 mA on the high ranges), and status bit 8 is "voltage force
    over current". The only over-current emergencies listed are the
    *ammeter's*. So does the source regulate at its limit, or trip?
  * **The low terminal.** The summary gives `OUTP:LOW` a reset value of
    COMMon, the command's own page says FLOat. Floating, the source has
    no return through the ammeter and the sample sees no current.
  * **The ammeter input.** `*RST` leaves it OFF. Does a spot reading
    switch it on by itself, or read "not a number"?
  * What `*RST` leaves in every setting the driver will depend on, the
    shape of a reading with its status word, how long one takes, and the
    sign of the current a positive voltage drives into the ammeter.

So this runs before the driver, and the driver is written from what it
records together with the manual.

    uv run tools/bench_b2987a.py --address USB0::0x2A8D::...::INSTR

GPIB is off at the factory: over GPIB, enable it at the front panel
first. **`*RST` is sent in part 1.4**, so whatever was set at the front
panel is not there afterwards and is not put back.

Part 1 - nothing connected, the source output off throughout
  1.1 Who it is: `*IDN?`, options, firmware, the interlock, the battery.
  1.2 Every read-only query the driver might use, verbatim.
  1.3 Refusals: an unknown header, a level beyond the 20 V range, then
      on each high range a level above 21 V and one on the wrong side of
      zero; an NPLC off the menu; a current range between two.
  1.4 What `*RST` does to every setting the driver depends on.
  1.5 Readings: with the input off, then on - the reply's shape with the
      status word, the open-input offset, and how long a reading takes
      at 1 PLC autoranged, 1 PLC on a fixed range, and auto aperture.

Part 2 - the source on, nothing connected, never above 10 V
  2.1 On at 1 V on the 20 V range, then 5 V: what the queries say.
  2.2 The range changed with the output on: at 5 V, then at 0 V to each
      high range and back.
  2.3 Off: what `OUTP:OFF:MODE NORM` leaves in the level setting.

Part 3 - a resistor from the source to the ammeter, if there is one
  The daily-use circuit. The low terminal floating, then common; the
  current at +/-1, 5 and 10 V against V/R; how long the current takes to
  settle after a step; and a reading's time on this circuit.

Part 4 - the source's own current limit, if the operator agrees
  A 100-330 ohm resistor across the source alone, the ammeter input
  empty. 1 V, then 10 V - over the 20 mA - and what the output, the
  status word, the error queue and the front panel say.

Never sent: `*SAV`, `*RCL`, `*CAL?`, `MMEM`, `PROG`, `INIT`, `TRIG`,
`ARM`, `LXI`, a sweep, list or square-wave mode, `SYST:BATT:TEST?`, a
charge discharge, `CALC`, or anything that changes the communication
settings. `*TST?` only after an emergency, and only if the operator
says so.

It expects silence where a query is wrong: an unanswered query latches
the transport, so after one the tool reconnects, sends a device clear so
a late reply cannot be read as the next answer, and carries on. The
source goes off between parts, at the end, and on any error or Ctrl-C.
The level it switches on at is read back first, because part 1.3 leaves
levels of up to 25 V stored on purpose.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smuniversal_lab_suite.core.provenance import (  # noqa: E402
    as_markdown_lines,
)
from smuniversal_lab_suite.core.provenance import (  # noqa: E402
    describe as provenance_of,
)
from smuniversal_lab_suite.core.transports.base import (  # noqa: E402
    TransportDesynchronised,
)
from tools.smu_checkup import (  # noqa: E402
    TRANSPORTS,
    inferred_transport,
    install_trace,
    trace_times,
)

#: Seconds to wait for an ordinary reply.
QUERY_TIMEOUT_S = 3.0

#: And for a reading: autoranging down to the 2 pA range at 1 PLC, with
#: the instrument's own measurement wait in force, can take seconds.
READING_TIMEOUT_S = 15.0

#: After reconnecting from a silence: how long to wait before the device
#: clear, so that a reply which was only late is cleared, not read.
LATE_REPLY_WAIT_S = 1.0

#: The longest `*TST?` is given, if the operator asks for one.
SELF_TEST_TIMEOUT_S = 120.0

#: Settling after `*CLS`, and after a level step in part 3 before its
#: reading: a gigaohm resistor and a metre of triax is a time constant
#: of a fraction of a second.
CLS_WAIT_S = 0.3
SETTLE_S = 2.0

#: The highest level the source is ever switched on at, or stepped to
#: while on. Below the 21 V an open interlock allows, so this sitting
#: needs no interlock fixture and makes no hazardous voltage.
MAX_ON_V = 10.0

#: Part 3's resistor: at 10 V, 100 uA at most.
MIN_SAMPLE_OHM = 100e3
#: Part 4's: enough to ask more than 20 mA at 10 V, not so little that a
#: source which did not limit would put more than 1 W into it.
MIN_LIMIT_OHM, MAX_LIMIT_OHM = 100.0, 330.0

#: Readings taken for each timing in 1.5 and 3, and polls of the
#: current after part 3's step.
TIMED_READINGS = 5
STEP_WINDOW_S = 3.0

#: Part 1.2, in order. All read-only, all spelled from the reference.
INVENTORY = (
    "*IDN?", "*OPT?", "SYST:VERS?", "SYST:INT:TRIP?", "SYST:BATT?",
    "SYST:LFR?",
    "OUTP?", "OUTP:LOW?", "OUTP:OFF:MODE?",
    "INP?", "INP:ZCOR?",
    "SOUR:FUNC:MODE?", "SOUR:VOLT:MODE?", "SOUR:VOLT?", "SOUR:VOLT:RANG?",
    "SOUR:VOLT:RLIM:STAT?", "SOUR:WAIT?", "SOUR:WAIT:AUTO?",
    "SENS:FUNC?", "SENS:CURR:NPLC?", "SENS:CURR:NPLC:AUTO?",
    "SENS:CURR:APER?", "SENS:CURR:APER:AUTO?", "SENS:CURR:RANG?",
    "SENS:CURR:RANG:AUTO?", "SENS:CURR:RANG:AUTO:LLIM?",
    "SENS:CURR:AVER:MOV?", "SENS:CURR:MED?", "SENS:CURR:REF:STAT?",
    "SENS:WAIT?", "SENS:WAIT:AUTO?",
    "FORM?", "FORM:ELEM:SENS?",
    "*ESR?", "*STB?",
)

#: Both halves of where a level went: refused, clipped, or the range
#: moved to take it.
_LEVEL = ("SOUR:VOLT?", "SOUR:VOLT:RANG?")

#: Part 1.3: (command, what it tests, the queries that say if it landed).
#: The source is off and confirmed off first, so each is harmless if it
#: is accepted, and the level is put back to 0 V on the 20 V range.
REFUSALS = (
    ("SOUR:VOLT:NOSUCH 1", "an unknown header", ()),
    ("SOUR:VOLT:RANG 20", "the 20 V range", ("SOUR:VOLT:RANG?",)),
    ("SOUR:VOLT 25", "25 V on the 20 V range", _LEVEL),
    ("SOUR:VOLT 1100", "beyond every range", _LEVEL),
    ("SOUR:VOLT 0", "put back", None),
    ("SOUR:VOLT:RANG 20", "put back", None),
    ("SOUR:VOLT:RANG 1000", "the +1000 V range, interlock as found",
     ("SOUR:VOLT:RANG?",)),
    ("SOUR:VOLT 25", "above the 21 V an open interlock allows", _LEVEL),
    ("SOUR:VOLT -5", "below the -1 V the +1000 V range reaches", _LEVEL),
    ("SOUR:VOLT 0", "put back", None),
    ("SOUR:VOLT:RANG -1000", "the -1000 V range", ("SOUR:VOLT:RANG?",)),
    ("SOUR:VOLT 5", "above the +1 V the -1000 V range reaches", _LEVEL),
    ("SOUR:VOLT 0", "put back", None),
    ("SOUR:VOLT:RANG 20", "put back", None),
    ("SENS:CURR:NPLC 0.5", "an NPLC off the front panel's menu",
     ("SENS:CURR:NPLC?",)),
    ("SENS:CURR:RANG 3E-9", "a current range between 2 nA and 20 nA",
     ("SENS:CURR:RANG?",)),
)

#: Part 1.4: distinctive settings `*RST` is asked to clear, then what it
#: leaves. `OUTP:LOW` needs the source off, which it is.
RST_MARKERS = ("SOUR:VOLT 1.234", "SENS:CURR:NPLC 2",
               "SENS:CURR:AVER:MOV ON", "OUTP:OFF:MODE ZERO", "INP 1")
RST_READS = (
    "OUTP?", "OUTP:LOW?", "OUTP:OFF:MODE?", "INP?", "INP:ZCOR?",
    "SOUR:VOLT?", "SOUR:VOLT:RANG?", "SOUR:VOLT:RLIM:STAT?", "SOUR:WAIT?",
    "SENS:FUNC?", "SENS:CURR:NPLC?", "SENS:CURR:NPLC:AUTO?",
    "SENS:CURR:APER:AUTO?", "SENS:CURR:RANG:AUTO?", "SENS:CURR:AVER:MOV?",
    "SENS:CURR:MED?", "SENS:WAIT?", "FORM?", "FORM:ELEM:SENS?",
)

#: The status word that comes with a reading (reference Table 1-2, as
#: far as its layout can be read). Bit 8 is the one this sitting is for.
STATUS_BITS = {
    0: "current/charge overflow", 1: "voltage overflow",
    2: "current/charge out of limit", 3: "voltage out of limit",
    4: "zero correct on", 5: "current/charge null on",
    6: "voltage null on", 7: "resistance null on",
    8: "voltage source over current", 9: "median filter on",
    10: "moving average on", 11: "auto resistance on",
    12: "resistance from the source setting",
}

#: "Not a number" and the two infinities, in an ASCII reading.
NOT_A_NUMBER = 9.91e37

#: The current ranges, for choosing a fixed one that holds a current.
CURRENT_RANGES = (2e-12, 20e-12, 200e-12, 2e-9, 20e-9, 200e-9, 2e-6,
                  20e-6, 200e-6, 2e-3, 20e-3)

_NUMBER = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")


def number(reply):
    """The leading number of a reply, or None. Tolerant on purpose: the
    raw reply is beside it in the report whatever this makes of it."""
    if reply is None:
        return None
    match = _NUMBER.match(str(reply))
    return float(match.group(1)) if match else None


def error_code(reply):
    """The number at the front of a `SYST:ERR?` reply, or None."""
    value = number(reply)
    return None if value is None else int(value)


def reading(reply):
    """`(amps, status)` out of a `CURR,STAT` reply. Either is None when
    absent or not a number."""
    if reply is None:
        return None, None
    fields = [number(f) for f in str(reply).split(",")]
    amps = fields[0] if fields else None
    if amps is not None and abs(amps) >= NOT_A_NUMBER * 0.99:
        amps = None
    status = fields[1] if len(fields) > 1 else None
    return amps, (None if status is None else int(status))


def status_names(status):
    """The set bits of a status word, by name - unknown ones by number."""
    if not status:
        return []
    return [STATUS_BITS.get(bit, f"bit {bit}")
            for bit in range(32) if status >> bit & 1]


def fixed_range_for(amps):
    """The smallest current range that holds `amps` with 10% to spare."""
    for full_scale in CURRENT_RANGES:
        if abs(amps) * 1.1 <= full_scale:
            return full_scale
    return CURRENT_RANGES[-1]


def ohms(text):
    """The operator's resistor value: `10e6`, `10M`, `1.5G`, `220`."""
    match = re.fullmatch(r"\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*"
                         r"([kKMG]?)\s*(?:(?i:ohms?)|Ω)?\s*", text or "")
    if not match:
        return None
    scale = {"": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}[match.group(2)]
    return float(match.group(1)) * scale


class Session:
    """Runs the parts and records what happened.

    `connect()` returns a connected transport. `ask`, `sleep` and `clock`
    are injected so the whole sitting can be walked offline against a
    fake.
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
        self.transport = None
        #: Query -> verbatim reply, for the queries part 1.2 got answers to.
        self.answered = {}
        #: Queries that went unanswered, in order.
        self.silent = []
        #: What the sitting settled, for the driver.
        self.found = {}
        #: Every non-zero `SYST:ERR?` reply, with the command before it.
        self.error_log = []
        self.watching = False
        self.idn = None
        self.alive = False
        self.output_on = False
        self._open()

    # ---- the link --------------------------------------------------
    def _open(self):
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
        self.transport = self.connect()
        install_trace(self.transport, self.trace)

    def _recover(self, command):
        """After a silence: reconnect, wait for anything late, and clear
        it with a device clear - VISA cannot look into the input to
        drain it, so it is cleared rather than read."""
        self._open()
        self.sleep(LATE_REPLY_WAIT_S)
        try:
            cleared = self.transport.clear()
        except Exception as exc:
            cleared = f"{type(exc).__name__}: {exc}"
        self._step(f"reconnected after {command} went unanswered", None,
                   f"device clear: {cleared!r}")

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

    def raw(self, command, what=None, note="", timeout_s=QUERY_TIMEOUT_S):
        """One query, the reply verbatim - or None, recorded as silence
        and recovered from."""
        mark = len(self.trace)
        try:
            reply = str(self.transport.query(
                command, timeout_s=timeout_s)).strip()
        except TransportDesynchronised:
            self._step(what or command, "<NO REPLY>", note, since=mark)
            self.silent.append(command)
            self._recover(command)
            return None
        self._step(what or command, reply, note, since=mark)
        return reply

    def send(self, command, what=None, note=""):
        """One write, recorded."""
        mark = len(self.trace)
        self.transport.write(command)
        self._step(what or command, None, note, since=mark)

    def operator(self, prompt, key):
        answer = self.ask(prompt).strip()
        self.answers.setdefault(key, []).append(answer)
        return answer

    def errors(self, note=""):
        """Drain `SYST:ERR?` to `0` (at most twelve reads) and read
        `*ESR?`. Returns the non-zero replies and the register,
        verbatim."""
        seen = []
        for _ in range(12):
            reply = self.raw("SYST:ERR?", note=note)
            if reply is None or error_code(reply) in (0, None):
                break
            seen.append(reply)
            self.error_log.append((note, reply))
        esr = self.raw("*ESR?", note=note)
        return seen, esr

    def measure(self, command="MEAS?", note=""):
        """One spot reading, given the long timeout. `(amps, status,
        verbatim)`."""
        reply = self.raw(command, note=note, timeout_s=READING_TIMEOUT_S)
        amps, status = reading(reply)
        return amps, status, reply

    # ---- the source ------------------------------------------------
    def off(self):
        """The source off, 0 V. Writes only, each on its own, so one that
        fails does not stop the other."""
        for command in ("OUTP 0", "SOUR:VOLT 0"):
            try:
                self.send(command, note="source off")
            except Exception:
                pass
        self.output_on = False

    def _confirm_off(self, why):
        self.send("OUTP 0", note=why)
        state = self.raw("OUTP?", note="0 before anything is written")
        if state is not None and number(state) == 0:
            return True
        self.headline(f"OUTP? read {state!r} after OUTP 0 - the source is "
                      f"not confirmed off, so nothing more is written. "
                      f"Stopped")
        self.alive = False
        return False

    def turn_on(self, volts):
        """The 20 V range, the level, then on - refusing anything above
        `MAX_ON_V`, here, and refusing again if the level the instrument
        reports is above it. Part 1.3 stores 25 V on purpose; a put-back
        that did not land must not be switched on."""
        if abs(volts) > MAX_ON_V:
            raise RuntimeError(f"refused: {volts:g} V is above this tool's "
                               f"{MAX_ON_V:g} V with the source on")
        self.send("SOUR:VOLT:RANG 20")
        self.send(f"SOUR:VOLT {volts:g}")
        stored = number(self.raw("SOUR:VOLT?", note="before switching on"))
        if stored is None or abs(stored) > MAX_ON_V:
            raise RuntimeError(f"refused: the instrument reports a level of "
                               f"{stored!r} V; not switching on")
        self.output_on = True
        self.send("OUTP 1")
        return self.raw("OUTP?", note="1 if it switched on")

    def set_level(self, volts):
        if self.output_on and abs(volts) > MAX_ON_V:
            raise RuntimeError(f"refused: {volts:g} V is above this tool's "
                               f"{MAX_ON_V:g} V with the source on")
        self.send(f"SOUR:VOLT {volts:g}")

    # ---- part 1: nothing connected, source off ---------------------
    def part_identity(self):
        self.part = "1.1 who it is"
        self.idn = self.raw("*IDN?")
        self.alive = self.idn is not None
        if not self.alive:
            self.headline("identity: *IDN? got no reply. Check the address, "
                          "and over GPIB that the GPIB interface has been "
                          "enabled at the front panel. Stopped")
            return
        facts = {q: self.raw(q) for q in ("*OPT?", "SYST:VERS?",
                                          "SYST:INT:TRIP?", "SYST:BATT?")}
        interlock = number(facts["SYST:INT:TRIP?"])
        self.found["interlock_open"] = (None if interlock is None
                                        else interlock == 1)
        self.headline(f"identity: {self.idn}; " + ", ".join(
            f"{q} {r}" for q, r in facts.items())
            + ("; the interlock is OPEN, so the instrument should hold the "
               "source to 21 V" if interlock == 1 else
               "; the interlock is closed" if interlock == 0 else ""))

    def part_inventory(self):
        self.part = "1.2 what answers"
        for command in INVENTORY:
            reply = self.raw(command)
            if reply is not None:
                self.answered[command] = reply
        drained, esr = self.errors("start clean")
        quiet = [c for c in INVENTORY if c not in self.answered]
        self.headline(f"inventory: {len(self.answered)} of {len(INVENTORY)} "
                      f"queries answered; silent: {', '.join(quiet) or 'none'}"
                      f"; errors waiting: {', '.join(drained) or 'none'}, "
                      f"*ESR? {esr}")

    def part_refusals(self):
        self.part = "1.3 refusals"
        self.errors("start clean")
        lines = []
        for command, label, queries in REFUSALS:
            self.send(command, note=label)
            if label == "put back":
                continue
            seen, esr = self.errors(f"after {command}")
            landed = [f"{q} {self.raw(q, note='did it land?')}"
                      for q in queries]
            lines.append(f"{command} -> {', '.join(seen) or 'no error'}"
                         + "".join(f", {text}" for text in landed)
                         + (f", *ESR? {esr}" if seen else ""))
        # The level is 0 V on the 20 V range again whatever landed above;
        # read it back so the report shows it rather than assumes it.
        self.send("SOUR:VOLT:RANG 20", note="put back")
        self.send("SOUR:VOLT 0", note="put back")
        self.raw("SOUR:VOLT?", note="0 again")
        self.raw("SOUR:VOLT:RANG?", note="20 again")
        self.errors("after putting back")
        self.headline("refusals: " + "; ".join(lines))

    def part_reset(self):
        self.part = "1.4 *RST"
        for command in RST_MARKERS:
            self.send(command, note="a marker")
        before = {q: self.raw(q, note="before *RST") for q in RST_READS}
        mark = len(self.trace)
        started = self.clock()
        self.send("*RST")
        done = self.raw("*OPC?", note="after *RST")
        self._step(f"*RST then *OPC? in "
                   f"{(self.clock() - started) * 1000:.0f} ms", done,
                   since=mark)
        after = {q: self.raw(q, note="after *RST") for q in RST_READS}
        self.found["after_rst"] = after
        self.found["low_after_rst"] = after.get("OUTP:LOW?")
        self.found["input_after_rst"] = after.get("INP?")
        self.send("*CLS")
        self.sleep(CLS_WAIT_S)
        self.errors("after *CLS")
        changed = [f"{q} {before[q]} -> {after[q]}" for q in RST_READS
                   if before[q] != after[q]]
        kept = [f"{q} {after[q]}" for q in RST_READS
                if before[q] == after[q]]
        self.headline("*RST changed: " + ("; ".join(changed) or "nothing")
                      + " | left as it was: " + ("; ".join(kept) or "nothing"))

    def part_readings(self):
        self.part = "1.5 readings"
        self.send("INP 0", note="the input off, as *RST leaves it")
        amps, status, off_reply = self.measure("MEAS:CURR?",
                                               note="with the input off")
        after = self.raw("INP?", note="did the reading switch it on?")
        self.found["reading_switches_input_on"] = number(after) == 1
        self.errors("after a reading with the input off")
        self.send('SENS:FUNC "CURR"', note="current only")
        self.send("FORM:ELEM:SENS CURR,STAT",
                  note="the current and its status word")
        self.send("INP 1")
        _, _, shaped = self.measure(note="the reply's shape")
        offsets = [self.measure(note="open input")[0]
                   for _ in range(TIMED_READINGS)]
        timings = {}
        for label, setup in (
                ("1 PLC autoranged", ("SENS:CURR:NPLC 1",
                                      "SENS:CURR:RANG:AUTO ON")),
                ("1 PLC on the 2 nA range", ("SENS:CURR:RANG 2E-9",)),
                ("auto aperture, autoranged", ("SENS:CURR:RANG:AUTO ON",
                                               "SENS:CURR:APER:AUTO ON"))):
            for command in setup:
                self.send(command)
            timings[label] = self._timed(label)
        self.send("SENS:CURR:NPLC 1", note="back to 1 PLC")
        self.send("INP 0", note="the input off between parts")
        self.errors("after the readings")
        self.headline(
            f"readings: with the input off MEAS:CURR? {off_reply} and INP? "
            f"{after} afterwards; with CURR,STAT a reading is {shaped!r}; "
            f"open input "
            + ", ".join("-" if a is None else f"{a:.3g} A" for a in offsets)
            + "; " + ", ".join(f"{k} {v}" for k, v in timings.items()))

    def _timed(self, label):
        mark = len(self.trace)
        started = self.clock()
        for _ in range(TIMED_READINGS):
            self.measure(note=f"timed: {label}")
        each = (self.clock() - started) / TIMED_READINGS
        self._step(f"{TIMED_READINGS} readings, {label}",
                   f"{each * 1000:.0f} ms each", since=mark)
        return f"{each * 1000:.0f} ms"

    # ---- part 2: source on, nothing connected ----------------------
    def part_source(self):
        self.part = "2.1 on, open circuit"
        if not self._confirm_off("before part 2"):
            return
        self.send("OUTP:OFF:MODE NORM", note="0 V, then the relay open")
        self.send("INP 1", note="so a reading carries the status word")
        self.errors("start clean")
        state = self.turn_on(1.0)
        _, status, _ = self.measure(note="status at 1 V")
        self.set_level(5.0)
        level = self.raw("SOUR:VOLT?", note="after the step to 5 V")
        _, status5, _ = self.measure(note="status at 5 V")
        display = meter = None
        if self.watching:
            display = self.operator("  What source voltage does the front "
                                    "panel show? (Enter to skip): ",
                                    "display at 5 V")
        meter = self.operator("  If you have a meter on Voltage Source HI "
                              "and LO, what does it read? (Enter to skip): ",
                              "meter at 5 V")
        seen, _ = self.errors("after switching on")
        self.headline(
            f"on: OUTP? {state} after OUTP 1; status at 1 V "
            f"{status_names(status) or 'none'}; SOUR:VOLT? {level} at 5 V, "
            f"status {status_names(status5) or 'none'}"
            + (f"; front panel {display}" if display else "")
            + (f"; meter {meter}" if meter else "")
            + f"; errors {', '.join(seen) or 'none'}")

        self.part = "2.2 range change, source on"
        lines = []
        for level_v, command in ((5.0, "SOUR:VOLT:RANG 1000"),
                                 (0.0, "SOUR:VOLT:RANG 1000"),
                                 (0.0, "SOUR:VOLT:RANG -1000"),
                                 (0.0, "SOUR:VOLT:RANG 20")):
            self.set_level(level_v)
            self.send(command, note=f"at {level_v:g} V, the source on")
            seen, _ = self.errors(f"after {command}")
            outp = self.raw("OUTP?", note="still on?")
            rang = self.raw("SOUR:VOLT:RANG?", note="did the range move?")
            volts = self.raw("SOUR:VOLT?", note="and the level?")
            lines.append(f"{command} at {level_v:g} V -> "
                         f"{', '.join(seen) or 'no error'}, OUTP? {outp}, "
                         f"RANG? {rang}, SOUR:VOLT? {volts}")
            if number(outp) == 0:
                self.output_on = False
                break
        interlock = self.found.get("interlock_open")
        self.headline("range change with the source on ("
                      + ("interlock open" if interlock else
                         "interlock closed" if interlock is False else
                         "interlock unknown")
                      + "): " + "; ".join(lines))

        self.part = "2.3 off"
        # Back on the 20 V range at 1 V, wherever 2.2 left it.
        if not self.output_on:
            self.turn_on(1.0)
        else:
            self.send("SOUR:VOLT:RANG 20")
            self.set_level(1.0)
        self.send("OUTP 0")
        self.output_on = False
        states = {q: self.raw(q, note="after OUTP 0 in NORM") for q in (
            "OUTP?", "SOUR:VOLT?", "OUTP:OFF:MODE?")}
        self.found["off_keeps_level_setting"] = (
            number(states["SOUR:VOLT?"]) == 1.0)
        seen, esr = self.errors("after the source part")
        self.send("SOUR:VOLT 0")
        self.send("INP 0")
        self.headline("off: " + ", ".join(f"{q} {r}"
                                          for q, r in states.items())
                      + f"; errors {', '.join(seen) or 'none'}, *ESR? {esr}")

    # ---- part 3: a resistor from the source to the ammeter ---------
    def part_sample(self):
        self.part = "3 a resistor to the ammeter"
        if not self._confirm_off("before wiring part 3"):
            return
        answer = self.operator(
            "\nPart 3 needs a resistor of 1 MOhm to 10 GOhm from Voltage "
            "Source HI to the centre conductor of the ammeter input (a "
            "triax adapter), and nothing else.\nThe source is OFF. Wire "
            "it now, then type its value in ohms (e.g. 10M), or Enter to "
            "skip: ", "part 3 resistor")
        resistance = ohms(answer)
        if not answer:
            self._step("skipped at the operator's request")
            return
        if resistance is None or resistance < MIN_SAMPLE_OHM:
            self._step(f"refused: {answer!r} is not a resistor of at least "
                       f"{MIN_SAMPLE_OHM:g} ohm", None)
            self.headline(f"part 3 not run: {answer!r} is not a resistor "
                          f"of at least {MIN_SAMPLE_OHM / 1e3:g} kOhm")
            return
        self.found["sample_ohm"] = resistance
        low_found = self.raw("OUTP:LOW?", note="as found")
        self.send('SENS:FUNC "CURR"')
        self.send("FORM:ELEM:SENS CURR,STAT")
        self.send("SENS:CURR:NPLC 1")
        self.send("SENS:CURR:RANG:AUTO ON")
        self.send("INP 1")
        self.errors("start clean")

        # The low terminal: floating, the source has no return through
        # the ammeter. The reading at FLO is the evidence either way.
        by_low = {}
        for low in ("FLO", "COMM"):
            self.send("OUTP 0")
            self.output_on = False
            self.send(f"OUTP:LOW {low}", note="the source off, as it must be")
            seen, _ = self.errors(f"after OUTP:LOW {low}")
            self.turn_on(5.0)
            self.sleep(SETTLE_S)
            amps = [self.measure(note=f"5 V, low {low}")[0] for _ in range(3)]
            by_low[low] = (amps, seen)
        expected = 5.0 / resistance
        self.found["floating_low_blocks_current"] = _all_small(
            by_low["FLO"][0], expected)

        # The daily-use measurement: current against V/R, both signs.
        ratios = []
        for volts in (1.0, 5.0, 10.0, -1.0, -5.0, -10.0):
            self.set_level(volts)
            self.sleep(SETTLE_S)
            amps, status, _ = self.measure(note=f"{volts:g} V")
            ratio = None if amps is None else amps * resistance / volts
            ratios.append((volts, amps, ratio, status))
        signs = [r for _, _, r, _ in ratios if r is not None]
        self.found["positive_volts_read_positive_amps"] = (
            bool(signs) and all(r > 0 for r in signs))

        # How long the current takes to settle after a step.
        self.set_level(0.0)
        self.sleep(SETTLE_S)
        origin = self.clock()
        self.set_level(10.0)
        polls = self._poll(STEP_WINDOW_S, "polling after 0 -> 10 V", origin)
        settled = settle_summary(polls, 0.0, 10.0 / resistance, "A")

        fixed = fixed_range_for(10.0 / resistance)
        self.send(f"SENS:CURR:RANG {fixed:g}")
        on_fixed = self._timed(f"1 PLC on the {fixed:g} A range")
        self.send("SENS:CURR:RANG:AUTO ON")
        autoranged = self._timed("1 PLC autoranged")

        self.send("OUTP 0")
        self.output_on = False
        self.send("SOUR:VOLT 0")
        if low_found:
            self.send(f"OUTP:LOW {low_found}", note="put back as found")
        self.send("INP 0")
        seen, esr = self.errors("after part 3")
        self.headline(
            f"low terminal at 5 V through {resistance:.3g} ohm (V/R "
            f"{expected:.3g} A): "
            + "; ".join(f"{low} " + ", ".join(_amps(a) for a in amps)
                        + (f" ({', '.join(errs)})" if errs else "")
                        for low, (amps, errs) in by_low.items()))
        self.headline("current against V/R: " + "; ".join(
            f"{v:+g} V {_amps(a)}"
            + (f" (x{r:.4f} of V/R)" if r is not None else "")
            + (f" [{', '.join(status_names(s))}]" if status_names(s) else "")
            for v, a, r, s in ratios))
        self.headline(f"settling after 0 -> 10 V: {settled}; a reading "
                      f"{on_fixed} on the {fixed:g} A range, {autoranged} "
                      f"autoranged; errors {', '.join(seen) or 'none'}, "
                      f"*ESR? {esr}")

    def _poll(self, window_s, what, origin):
        """Readings as fast as they come for `window_s`; one step."""
        mark = len(self.trace)
        seen = []
        while self.clock() - origin < window_s:
            try:
                reply = str(self.transport.query(
                    "MEAS?", timeout_s=READING_TIMEOUT_S)).strip()
            except TransportDesynchronised:
                self._step(what, f"<NO REPLY after {len(seen)} polls>",
                           since=mark)
                self._recover("MEAS?")
                return seen
            seen.append((self.clock() - origin, reading(reply)[0]))
        self._step(what, f"{len(seen)} polls", since=mark)
        return seen

    # ---- part 4: the source's own current limit --------------------
    def part_limit(self):
        self.part = "4 the current limit"
        if not self._confirm_off("before wiring part 4"):
            return
        answer = self.operator(
            "\nPart 4 asks the source for more than its 20 mA, to see "
            "whether it holds the limit or trips.\nIt needs a resistor of "
            "100 to 330 ohm, rated 1 W or more, across Voltage Source HI "
            "and LO only - NOTHING on the ammeter input.\nThe source is "
            "OFF. Wire it now, then type its value in ohms, or Enter to "
            "skip: ", "part 4 resistor")
        if not answer:
            self._step("skipped at the operator's request")
            return
        resistance = ohms(answer)
        if resistance is None or not (MIN_LIMIT_OHM <= resistance
                                      <= MAX_LIMIT_OHM):
            self.headline(f"part 4 not run: {answer!r} is not a resistor of "
                          f"{MIN_LIMIT_OHM:g} to {MAX_LIMIT_OHM:g} ohm")
            return
        self.send('SENS:FUNC "CURR"')
        self.send("FORM:ELEM:SENS CURR,STAT")
        self.send("INP 1", note="an empty input, for the status word")
        self.errors("start clean")
        self.turn_on(1.0)
        _, below, _ = self.measure(note=f"1 V: {1e3 / resistance:.1f} mA")
        self.set_level(MAX_ON_V)
        over = {q: self.raw(q, note=f"asked {MAX_ON_V * 1e3 / resistance:.0f}"
                                     f" mA") for q in ("OUTP?", "SOUR:VOLT?")}
        _, status, _ = self.measure(note="the status word, over the limit")
        seen, esr = self.errors("over the limit")
        panel = meter = None
        if self.watching:
            panel = self.operator("  Does the front panel show OC, or "
                                  "anything else? (Enter to skip): ",
                                  "panel over the limit")
        meter = self.operator("  If you have a meter across the resistor, "
                              "what does it read? (Enter to skip): ",
                              "meter over the limit")
        _, later, _ = self.measure(note="a moment later")
        still = self.raw("OUTP?", note="still on?")
        self.set_level(0.0)
        _, after, _ = self.measure(note="back at 0 V")
        self.send("OUTP 0")
        self.output_on = False
        self.send("INP 0")
        cleared, _ = self.errors("after part 4")
        held = status is not None and status >> 8 & 1
        tripped = number(over["OUTP?"]) == 0 or number(still) == 0
        self.found["source_limit"] = ("trips" if tripped else
                                      "holds, status bit 8" if held else
                                      "neither seen")
        emergency = [e for e in seen + cleared if "mergency" in e]
        self.headline(
            f"limit through {resistance:g} ohm: status at 1 V "
            f"{status_names(below) or 'none'}; at {MAX_ON_V:g} V OUTP? "
            f"{over['OUTP?']}, SOUR:VOLT? {over['SOUR:VOLT?']}, status "
            f"{status_names(status) or 'none'}, errors "
            f"{', '.join(seen) or 'none'}, *ESR? {esr}"
            + (f"; front panel {panel}" if panel else "")
            + (f"; meter {meter}" if meter else "")
            + f"; a moment later status {status_names(later) or 'none'}, "
              f"OUTP? {still}; at 0 V status {status_names(after) or 'none'}"
            + f"; then errors {', '.join(cleared) or 'none'}")
        if emergency:
            self._self_test(emergency)

    def _self_test(self, emergency):
        if self.operator(
                f"\nThe instrument reported {emergency[0]}. Its manual says "
                f"to run *TST? after one. Disconnect everything, then: run "
                f"it now? [y/N] ", "self test").lower() != "y":
            self._step("*TST? not run, at the operator's request")
            return
        result = self.raw("*TST?", timeout_s=SELF_TEST_TIMEOUT_S)
        seen, _ = self.errors("after *TST?")
        self.headline(f"self test: *TST? {result}; errors "
                      f"{', '.join(seen) or 'none'}")

    # ---- the whole sitting -----------------------------------------
    def run(self, watching=False, with_output=True):
        self.watching = watching
        try:
            self.part_identity()
            if not self.alive:
                return
            self.part_inventory()
            if not self._confirm_off("before anything is written"):
                return
            self.part_refusals()
            self.part_reset()
            self.part_readings()
            if with_output:
                self.part_source()
                if self.alive:
                    self.part_sample()
                if self.alive:
                    self.part_limit()
            self.headline("found: " + (", ".join(
                f"{k} = {v!r}" for k, v in self.found.items()
                if k != "after_rst") or "nothing")
                + f"; {len(self.silent)} unanswered queries")
        except KeyboardInterrupt:
            self.stopped_early = "interrupted by Ctrl-C"
        except Exception as exc:
            self.stopped_early = f"{type(exc).__name__}: {exc}"
        finally:
            if self.idn is not None:
                self.off()
            try:
                self.transport.close()
            except Exception:
                pass


def _amps(value):
    return "no reading" if value is None else f"{value:.4g} A"


def _all_small(values, expected):
    """True when every reading is under a hundredth of `expected` - the
    current a floating low lets through, if the reference is right.
    None when there was no reading to judge by."""
    readable = [v for v in values if v is not None]
    if not readable:
        return None
    return all(abs(v) < abs(expected) / 100
                                  for v in readable)


def settle_summary(polls, start, end, unit):
    """When the reading came within 2% of the step and stayed there."""
    values = [(t, v) for t, v in polls if v is not None]
    if len(values) < 5:
        return f"{len(values)} readings - too few"
    tail = sorted(v for _, v in values[-5:])
    final = tail[2]
    band = 0.02 * abs(end - start)
    settled = None
    for t, v in reversed(values):
        if abs(v - final) > band:
            break
        settled = t
    return (f"ended at {final:.4g} {unit} (expected {end:.4g}); inside 2% "
            f"of the step from {settled * 1000:.0f} ms"
            if settled is not None
            else f"never inside 2% of the step; ended at {final:.4g} {unit}")


def build_report(session, address, provenance):
    lines = [
        "# Keysight B2987A - a probe sitting at the bench",
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
                  *[f"- {_line(text)}" for text in session.headlines], ""]
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


def _line(value):
    return str(value).replace("\n", " ")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--address", required=True,
                        help="a VISA resource string (USB0::..., "
                             "TCPIP0::..., GPIB0::23::INSTR), or a GPIB "
                             "address with --transport gpib-hs")
    parser.add_argument("--transport", default=None,
                        choices=("visa", "visapy", "gpib-hs"),
                        help="default: visa for a VISA resource string")
    parser.add_argument("--out", default="checkups")
    args = parser.parse_args()

    transport_name = args.transport or inferred_transport(args.address)
    if transport_name is None:
        parser.error("not a VISA resource string: name --transport")

    def connect():
        transport = TRANSPORTS[transport_name]()
        transport.connect(args.address)
        return transport

    print("Parts 1 and 2 need NOTHING connected to the Voltage Source or "
          "the ammeter input.\n*RST is sent: front-panel settings are not "
          "kept.")
    if input("Is everything disconnected? [y/N] ").strip().lower() != "y":
        return 1
    watching = input("Can you see the front panel from the keyboard? "
                     "[y/N] ").strip().lower() == "y"

    session = Session(connect)
    session.run(watching=watching)

    # No driver exists yet, so there is no code for this report to
    # fingerprint: `bench_code` is left out rather than computed over
    # files that are not what was tested.
    provenance = provenance_of(idn=session.idn)
    stem = f"bench_B2987A_{time.strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(args.out, exist_ok=True)
    md_path = os.path.join(args.out, stem + ".md")
    json_path = os.path.join(args.out, stem + ".json")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(build_report(session, args.address, provenance))
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump({
            "when": datetime.datetime.now().isoformat(timespec="seconds"),
            "address": args.address, "transport": transport_name,
            "provenance": provenance, "stopped_early": session.stopped_early,
            "headlines": session.headlines, "answers": session.answers,
            "found": session.found, "answered": session.answered,
            "silent": session.silent, "errors": session.error_log,
            "steps": session.steps,
        }, handle, indent=2, default=repr)
    print(f"\nWrote {md_path}\n      {json_path}")
    print("Bring both back, whole.")
    return 1 if session.stopped_early or not session.alive else 0


if __name__ == "__main__":
    sys.exit(main())
