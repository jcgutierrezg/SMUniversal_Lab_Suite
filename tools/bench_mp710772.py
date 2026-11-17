"""
The first sitting with the Multicomp Pro MP710772: learn its dialect.

There is no command manual for this instrument. The documents in
`manuals/MP710772/` cover the front panel and the LAN settings
(`:SYST:IPAD` and friends); nothing lists the commands that set a mode,
a level or the input. What there is instead is circumstantial:

  * the USB driver installs a Korad "USB-K-R-Com Port", the same maker
    as the 72-13200 (a rebadged KEL102), so the 72-13200's dialect is
    the first hypothesis;
  * a community driver for the MP71077x family (mayermakes/lab_UI,
    `lab_api/dcload_device/mp71077x.py`) agrees with that dialect
    almost everywhere - and sets the mode with `:MODE CC|CV`, where the
    72-13200 takes `:FUNCtion CC|CV`. Nobody has checked which is right.

The 72-13200's own manual was wrong about `:FUNCtion`, and that unit has
no error queue, so the wrong spelling was ignored in silence. This tool
is how that does not happen twice: it asks before any driver exists,
and grades every write on what the instrument reports afterwards.

    uv run tools/bench_mp710772.py --address COM7

Part 1 - nothing connected to the input
  1.0 What the USB port says it is, and what the suite would call it
      today. The 72-13200 is recognised by its USB ids, and a second
      Korad load may well share them.
  1.1 `*IDN?`.
  1.2 Every query either dialect might have, read-only, each reply
      verbatim. Silence is an answer here.
  1.3 The mode spelling: `:FUNC` and `:MODE`, with `CV/CC` and
      `VOLT/CURR`, each written A, B, A and read back after every write.
  1.4 Whether a level needs its unit (`:CURR 0.123` against
      `:CURR 0.234A`), and whether the long header form lands.
  1.5 The smallest CV setpoint it will hold.
  1.6 Whether the ceilings (`:CURR:UPP`, `:VOLT:UPP`) can be written,
      checked twice over: by the query, and by a setpoint above the
      ceiling clamping to it. Put back as found afterwards.
  1.7 The input spelling, `:INP 1/0`, `:INP ON/OFF`, `:INPut ON/OFF`,
      off-on-off - harmless with nothing attached.
  1.8 What `*RST` does, last, because nothing here says it is harmless
      to the link.

Part 2 - a bench supply across the input, + to +, at about 5 V
  2.1 The supply's voltage, read unloaded with the input off.
  2.2 One CC reading against the supply's own display - which also shows
      the sign the instrument uses for a sink.
  2.3 How often the reading refreshes, from a fast poll.
  2.4 How long a CC step takes to settle.
  2.5 With the supply current-limited: how long a CV step takes, and the
      CV ladder down past the point where it stops following - the
      headroom floor.
  2.6 The same ladder at a second current, because two currents a factor
      of two apart are what made the 72-13200's floor a resistance
      rather than a number.

Never above 10 A, never on a source above 12 V. CR, CW, SHORT, the LIST
sequencer and the OCP/OPP test profiles are never sent.

It does not interpret, and it expects silence. An unanswered query
latches the transport, so after one the tool reconnects, waits for
anything arriving late and records it, and carries on - the late bytes
are drained, never read as the next reply. Every write is followed by a
look for an unsolicited reply, for the same reason. The input goes off
between parts, at the end, and on any error or Ctrl-C - by every
spelling that might work, because which one does is what part 1 is
finding out.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smuniversal_lab_suite.core import addresses  # noqa: E402
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

#: Seconds to wait for a reply. The 72-13200 answers in 4-6 ms; this is
#: long enough for anything that is going to answer at all, and short
#: enough that the silences part 1 expects cost seconds, not minutes.
QUERY_TIMEOUT_S = 1.5

#: After reconnecting from a silence: how long to wait for a reply that
#: was only late, before draining whatever arrived.
LATE_REPLY_WAIT_S = 1.0

#: After every write: how long to wait before looking for an unsolicited
#: reply - an error string, an echo, anything the next query would
#: otherwise collect as its own answer.
UNSOLICITED_WAIT_S = 0.15

#: Every query part 1 asks, in the order it asks them. Both dialects'
#: mode queries, the setpoints and ceilings, the readings, and the
#: places an error queue or status could be.
INVENTORY = (
    ":INP?", ":FUNC?", ":MODE?",
    ":VOLT?", ":CURR?", ":RES?", ":POW?",
    ":VOLT:UPP?", ":VOLT:LOW?", ":CURR:UPP?", ":CURR:LOW?",
    ":POW:UPP?", ":RES:UPP?",
    ":MEAS:VOLT?", ":MEAS:CURR?", ":MEAS:POW?",
    ":SYST:ERR?", ":STAT?", "*STB?", "*ESR?",
    ":SYST:DEVINFO?", ":SYST:BAUD?",
)

#: The mode queries, in the order they are trusted.
MODE_QUERIES = (":FUNC?", ":MODE?")

#: Mode spellings: header, then the word for CV and the word for CC.
#: `CV`/`CC` is what both known drivers send; `VOLT`/`CURR` is what the
#: 72-13200's manual documents, and was wrong there.
MODE_SPELLINGS = (
    (":FUNC", "CV", "CC"),
    (":MODE", "CV", "CC"),
    (":FUNC", "VOLT", "CURR"),
    (":MODE", "VOLT", "CURR"),
)

#: Input spellings: (on, off). The first is the community driver's, the
#: last the 72-13200's.
INPUT_SPELLINGS = (
    (":INP 1", ":INP 0"),
    (":INP ON", ":INP OFF"),
    (":INPut ON", ":INPut OFF"),
)

#: Sent to switch the input off when nothing has been learned yet.
#: Every spelling, because one that is not understood is ignored and
#: one that is, works.
OFF_SPELLINGS = tuple(off for _, off in INPUT_SPELLINGS)

#: Level forms: (template, what it tests), in the order sent. Each
#: sends a different value, so a readback can only match the one that
#: landed.
CURRENT_FORMS = (
    (":CURR {v:g}", "bare number", 0.123),
    (":CURR {v:g}A", "short header, with unit", 0.234),
    (":CURRent {v:g}A", "long header, with unit", 0.345),
)
VOLTAGE_FORMS = (
    (":VOLT {v:g}", "bare number", 1.23),
    (":VOLT {v:g}V", "short header, with unit", 2.34),
    (":VOLTage {v:g}V", "long header, with unit", 3.45),
)
#: Which landed form a later part uses, best first.
FORM_PREFERENCE = (1, 2, 0)

#: CV setpoints for the floor, largest first.
CV_FLOOR_LEVELS = (0.5, 0.2, 0.1, 0.05, 0.01, 0.0)

#: Ceilings tried, and the setpoint that should clamp to the first.
CURRENT_CEILINGS = (3.0, 5.0)
CURRENT_ABOVE_CEILING = 10.0
VOLTAGE_CEILINGS = (18.0, 30.0)
VOLTAGE_ABOVE_CEILING = 20.0
#: What a ceiling is put back to when its original could not be read:
#: the model's maximum, which never clamps a level.
WIDEST_CEILINGS = {"current": 40.0, "voltage": 150.0}

#: The distinctive setpoint `*RST` is asked to clear.
RST_MARKER_A = 0.321

#: Part 2's guards. 10 A is the larger supply on this bench; 12 V keeps
#: the load's dissipation under 75 W at that current.
MAX_TEST_A = 10.0
MAX_SOURCE_V = 12.0
SOURCE_PRESENT_V = 0.5

#: The CC levels part 2 uses, as caps; each is also kept to a fraction
#: of the supply's limit so the supply stays in voltage regulation.
CC_LOW_A, CC_HIGH_A = 0.2, 1.0

#: How long to poll for the refresh rate, and after a step, in seconds.
REFRESH_WINDOW_S = 3.0
STEP_WINDOW_S = 1.5

#: How long each rung of the CV ladder is held before it is read. Over
#: twice the 72-13200's measured 0.45 s.
HOLD_S = 1.0

#: The CV ladder, in volts, largest first; rungs at or above the
#: starting level are dropped.
CV_LADDER = (2.0, 1.5, 1.0, 0.7, 0.5, 0.4, 0.3, 0.25, 0.2, 0.15, 0.1,
             0.05)

_NUMBER = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")


def number(reply):
    """The leading number of a reply - `'0.7890A'` is 0.789 - or None.

    Tolerant on purpose: this is a probe, and a reply in a format nobody
    expected must still be legible. The raw reply is beside it in the
    report whatever this makes of it.
    """
    if reply is None:
        return None
    match = _NUMBER.match(str(reply))
    return float(match.group(1)) if match else None


def same(value, wanted):
    """A readback matching what was sent, to the instrument's 5 digits."""
    return (value is not None
            and abs(value - wanted) <= max(abs(wanted) * 1e-3, 1e-4))


def pending_text(transport):
    """Whatever bytes are waiting on the link, as text; None when this
    transport cannot be looked into (VISA)."""
    port = getattr(transport, "ser", None)
    if port is None:
        return None
    waiting = port.in_waiting
    if not waiting:
        return ""
    return port.read(waiting).decode(errors="replace")


class Session:
    """Runs the parts and records what happened.

    `connect` returns a connected transport. `ask`, `sleep` and `clock`
    are injected so the whole sitting can be walked offline against a
    fake instrument. `port` is `(address, pyserial facts, what the
    suite calls it)`, or None.
    """

    def __init__(self, connect, log=print, ask=None, sleep=None,
                 clock=None, port=None):
        self.connect = connect
        self.log = log
        self.ask = ask or input
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self.port = port
        self.started = self.clock()
        self.steps = []
        self.headlines = []
        self.answers = {}
        self.stopped_early = None
        self.part = ""
        self.trace = []
        self.transport = None
        #: Query -> verbatim reply, for the queries that answered.
        self.answered = {}
        #: Queries that went unanswered, in order.
        self.silent = []
        #: (command, text) for every write that drew a reply.
        self.unsolicited = []
        #: What part 1 found to work: "cv", "cc", "on", "off",
        #: "current", "voltage" (level templates).
        self.found = {}
        self.watching = False
        self.idn = None
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
        """After a silence: reconnect, wait, and record anything late.

        The late bytes are the reason this exists. Read by the next
        query they would be its answer - well-formed, plausible, and the
        reply to a different question.
        """
        self._open()
        self.sleep(LATE_REPLY_WAIT_S)
        late = pending_text(self.transport)
        if late is None:
            note = "this transport cannot be looked into"
        elif late:
            note = f"arrived late: {late.strip()!r} - drained, not used"
        else:
            note = "nothing arrived late"
        self._step(f"reconnected after {command} went unanswered", None,
                   note)

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
        """One write, then a look for anything it drew back."""
        mark = len(self.trace)
        self.transport.write(command)
        self.sleep(UNSOLICITED_WAIT_S)
        extra = pending_text(self.transport)
        result = None
        if extra:
            result = f"<UNSOLICITED REPLY: {extra.strip()!r}>"
            self.unsolicited.append((command, extra.strip()))
        self._step(what or command, result, note, since=mark)

    def operator(self, prompt, key):
        answer = self.ask(prompt).strip()
        self.answers.setdefault(key, []).append(answer)
        return answer

    def off(self):
        """The input off by the spelling that worked, and every other."""
        spellings = ([self.found["off"]] if "off" in self.found else [])
        spellings += [s for s in OFF_SPELLINGS if s not in spellings]
        for command in spellings:
            try:
                self.send(command, note="input off")
            except Exception:
                pass

    # ---- part 1: nothing attached ----------------------------------
    def part_port(self):
        self.part = "1.0 the port"
        if self.port is None:
            self._step("not a serial port, or pyserial cannot see it")
            return
        address, info, name = self.port
        if not info:
            self._step(f"{address}: pyserial has nothing on this port")
            return
        vid, pid = info.get("ids", (None, None))
        ids = ("not a USB device" if vid is None
               else f"{vid:04X}:{pid:04X}")
        self._step("USB vendor:product", ids)
        self._step("what the port says about itself", info.get("text"))
        self._step("what the suite would call it today", name)
        self.headline(f"port: {address} is {ids} ({info.get('description')})"
                      f"; the suite would call it {name or 'nothing'}")

    def part_identity(self):
        self.part = "1.1 identity"
        self.idn = self.raw("*IDN?")
        self.headline(f"*IDN?: {self.idn!r}" if self.idn is not None
                      else "*IDN?: no reply")

    def part_inventory(self):
        self.part = "1.2 what answers"
        for command in INVENTORY:
            reply = self.raw(command)
            if reply is not None:
                self.answered[command] = reply
        quiet = [c for c in INVENTORY if c not in self.answered]
        self.headline(f"inventory: {len(self.answered)} of "
                      f"{len(INVENTORY)} queries answered; silent: "
                      f"{', '.join(quiet) or 'none'}")

    def _mode_now(self, note):
        """The mode as every answering mode query reports it, plus the
        operator's reading of the screen when no query answers."""
        seen = {}
        for query in MODE_QUERIES:
            if query in self.answered:
                seen[query] = self.raw(query, note=note)
        if not seen and self.watching:
            seen["screen"] = self.operator(
                "  What MODE does the load's screen show now? "
                "(Enter to skip): ", "screen").upper() or None
            self._step("the operator reads the screen", seen["screen"],
                       note)
        return seen

    def part_mode(self):
        self.part = "1.3 the mode"
        reported = [q for q in MODE_QUERIES if q in self.answered]
        if not reported and not self.watching:
            self._step("no mode query answered and nobody is watching "
                       "the screen: the mode cannot be read back, so "
                       "this part cannot tell a write that took from one "
                       "that did not")
            self.headline("mode: cannot be read back - skipped")
            return
        verdicts = []
        for header, cv, cc in MODE_SPELLINGS:
            readings = []
            for word in (cv, cc, cv):
                command = f"{header} {word}"
                self.send(command)
                readings.append(self._mode_now(f"after {command}"))
            # A, B, A: it took only if B changed the reading and the
            # second A changed it back. A pair whose CC word works and
            # whose CV word is ignored moves once and never returns.
            took = any(
                readings[0].get(k) is not None
                and readings[0].get(k) != readings[1].get(k)
                and readings[2].get(k) == readings[0].get(k)
                for k in readings[0])
            shown = " / ".join(
                ",".join(f"{r.get(k)}" for r in readings)
                for k in readings[0])
            verdicts.append(f"{header} {cv}/{cc} -> {shown}"
                            f" ({'moved' if took else 'did not move'})")
            if took and "cv" not in self.found:
                self.found["cv"] = f"{header} {cv}"
                self.found["cc"] = f"{header} {cc}"
        self.headline("mode: " + "; ".join(verdicts))
        if "cv" in self.found and reported and self.watching:
            # One look at the screen against the query: a readback that
            # repeats the last command rather than reporting the
            # instrument would pass everything above.
            self.send(self.found["cc"])
            readback = self._mode_now("the readback, against the screen")
            screen = self.operator(
                "  What MODE does the load's screen show now? "
                "(Enter to skip): ", "screen")
            self._step("the operator reads the screen", screen or None)
            self.headline(f"mode against the screen: queries say "
                          f"{readback}, the screen {screen or 'unread'}")

    def _level_forms(self, quantity, forms, query):
        if query not in self.answered:
            self._step(f"{query} never answered: no {quantity} readback, "
                       f"so whether a level lands cannot be seen")
            return []
        landed = []
        for index, (template, label, value) in enumerate(forms):
            command = template.format(v=value)
            self.send(command, note=label)
            reply = self.raw(query, note=f"{value:g} if it landed")
            ok = same(number(reply), value)
            landed.append((index, command, reply, ok))
        for index in FORM_PREFERENCE:
            if any(i == index and ok for i, _, _, ok in landed):
                self.found[quantity] = forms[index][0]
                break
        return landed

    def part_levels(self):
        self.part = "1.4 levels and units"
        lines = []
        for quantity, forms, query in (
                ("current", CURRENT_FORMS, ":CURR?"),
                ("voltage", VOLTAGE_FORMS, ":VOLT?")):
            for _, command, reply, ok in self._level_forms(
                    quantity, forms, query):
                lines.append(f"{command} -> {reply} "
                             f"({'landed' if ok else 'did not land'})")
        self.headline("levels: " + ("; ".join(lines) or "no readback"))

    def part_cv_floor(self):
        self.part = "1.5 CV floor"
        template = self.found.get("voltage")
        if template is None:
            self._step("no voltage form landed: skipped")
            return
        seen = []
        for level in CV_FLOOR_LEVELS:
            self.send(template.format(v=level))
            seen.append((level, self.raw(":VOLT?")))
        low = (self.raw(":VOLT:LOW?") if ":VOLT:LOW?" in self.answered
               else None)
        self.headline("CV floor: " + "; ".join(
            f"{level:g} V -> {reply}" for level, reply in seen)
            + f"; :VOLT:LOW? {low}")

    def _ceiling(self, quantity, header, unit, query, tries, above,
                 setpoint_query):
        if query not in self.answered:
            self._step(f"{query} never answered: skipped")
            return f"{quantity}: {query} silent"
        found = number(self.raw(query, note="as found"))
        results = []
        for value in tries:
            self.send(f"{header} {value:g}{unit}")
            reply = self.raw(query, note=f"{value:g} if it is writable")
            results.append(f"{value:g}{unit} -> {reply}")
            if value == tries[0] and self.found.get(quantity) \
                    and setpoint_query in self.answered:
                self.send(self.found[quantity].format(v=above),
                          note=f"above the {value:g}{unit} ceiling")
                clamp = self.raw(setpoint_query,
                                 note=f"{value:g} if the ceiling clamps")
                results.append(f"then {above:g}{unit} -> {clamp}")
        back = found if found is not None else WIDEST_CEILINGS[quantity]
        self.send(f"{header} {back:g}{unit}",
                  note="put back" if found is not None
                  else "original unreadable: the widest")
        restored = self.raw(query, note=f"{back:g}")
        results.append(f"put back {back:g}{unit} -> {restored}")
        return f"{quantity} (found {found}): " + ", ".join(results)

    def part_ceilings(self):
        self.part = "1.6 ceilings"
        current = self._ceiling("current", ":CURR:UPP", "A", ":CURR:UPP?",
                                CURRENT_CEILINGS, CURRENT_ABOVE_CEILING,
                                ":CURR?")
        voltage = self._ceiling("voltage", ":VOLT:UPP", "V", ":VOLT:UPP?",
                                VOLTAGE_CEILINGS, VOLTAGE_ABOVE_CEILING,
                                ":VOLT?")
        if self.found.get("current"):
            self.send(self.found["current"].format(v=0.0),
                      note="CC setpoint to zero before the input part")
        self.headline(f"ceilings: {current}; {voltage}")

    def part_input(self):
        self.part = "1.7 the input"
        if ":INP?" not in self.answered:
            self._step(":INP? never answered: the input state cannot be "
                       "read back - skipped")
            self.headline("input: cannot be read back - skipped")
            return
        verdicts = []
        for on, off in INPUT_SPELLINGS:
            readings = []
            for command in (off, on, off):
                self.send(command)
                readings.append(self.raw(":INP?", note=f"after {command}"))
            took = (readings[0] is not None
                    and readings[0] != readings[1]
                    and readings[2] == readings[0])
            verdicts.append(f"{on}/{off} -> {','.join(map(str, readings))}"
                            f" ({'moved' if took else 'did not move'})")
            if took and "on" not in self.found:
                self.found["on"], self.found["off"] = on, off
        self.headline("input: " + "; ".join(verdicts))
        if "on" in self.found and self.watching:
            self.send(self.found["on"])
            readback = self.raw(":INP?", note="against the screen")
            screen = self.operator(
                "  Is the load's input shown ON? (y/n, Enter to skip): ",
                "input screen")
            self._step("the operator reads the screen", screen or None)
            self.off()
            self.headline(f"input against the screen: :INP? said "
                          f"{readback}, the operator {screen or 'unread'}")

    def part_reset(self):
        self.part = "1.8 *RST"
        template = self.found.get("current")
        if template is None or ":CURR?" not in self.answered:
            self._step("no current readback: *RST cannot be seen - "
                       "skipped")
            return
        self.send(template.format(v=RST_MARKER_A), note="the marker")
        before = {q: self.raw(q, note="before *RST") for q in (
            ":CURR?", ":INP?",
            *[m for m in MODE_QUERIES if m in self.answered],
            ":CURR:UPP?", ":VOLT:UPP?") if q in self.answered}
        self.send("*RST")
        after = {q: self.raw(q, note="after *RST") for q in before}
        idn = self.raw("*IDN?", note="is the link still there?")
        changed = [f"{q} {before[q]} -> {after[q]}" for q in before
                   if before[q] != after[q]]
        self.headline("*RST: " + ("; ".join(changed) if changed
                                  else "changed nothing that was read")
                      + f"; *IDN? afterwards {idn!r}")

    # ---- part 2: a supply ------------------------------------------
    #: What part 2 cannot do without.
    NEEDED = ("cv", "cc", "on", "off", "current", "voltage")

    def _read_vi(self, note):
        volts = number(self.raw(":MEAS:VOLT?", note=note))
        amps = number(self.raw(":MEAS:CURR?", note=note))
        return volts, amps

    def _poll(self, command, window_s, what, origin=None):
        """Query as fast as the link allows for `window_s`; one step,
        every exchange in it.

        Times are from `origin` when given - the moment before the write
        that started a step, so a settling time includes the look for an
        unsolicited reply that `send()` makes between the two.
        """
        mark = len(self.trace)
        started = self.clock()
        origin = started if origin is None else origin
        seen = []
        while self.clock() - started < window_s:
            try:
                reply = str(self.transport.query(
                    command, timeout_s=QUERY_TIMEOUT_S)).strip()
            except TransportDesynchronised:
                self._step(what, f"<NO REPLY after {len(seen)} polls>",
                           since=mark)
                self._recover(command)
                return seen
            seen.append((self.clock() - origin, reply))
        self._step(what, f"{len(seen)} polls", since=mark)
        return seen

    def part_source(self):
        self.part = "2 a supply"
        missing = [k for k in self.NEEDED if k not in self.found]
        missing += [q for q in (":MEAS:VOLT?", ":MEAS:CURR?")
                    if q not in self.answered]
        if missing:
            self._step("part 2 skipped: part 1 did not find "
                       + ", ".join(missing))
            self.headline("part 2: skipped - nothing confirmed to drive "
                          "it with (" + ", ".join(missing) + ")")
            return
        first = self._amps(self.operator(
            "\nPart 2 needs a bench supply across the load's input, + to "
            "+, set to about 5 V, output on.\nSet its current limit to the "
            "first test current (2 A is a good start, at most "
            f"{MAX_TEST_A:g} A)\nand type it here, or Enter to skip part "
            "2: ", "first test current"))
        if first is None:
            self._step("part 2 skipped at the operator's request")
            return
        self.off()
        source = number(self.raw(":MEAS:VOLT?",
                                 note="unloaded, input off"))
        if source is None or source < SOURCE_PRESENT_V:
            self.headline(f"part 2: {source} V across the input with it "
                          f"off - no supply seen. Stopped")
            return
        if source > MAX_SOURCE_V:
            self.headline(f"part 2: {source:g} V is above the "
                          f"{MAX_SOURCE_V:g} V this tool works with. "
                          f"Stopped")
            return
        self.headline(f"supply: {source:g} V unloaded")
        if not self._ceiling_allows(first):
            return
        self.part_cc(first)
        self.part_headroom(first, source, "2.5")
        second = self._amps(self.operator(
            "\nNow set the supply's current limit to a second test current "
            "- about twice the first,\nat most "
            f"{MAX_TEST_A:g} A - and type it here, or Enter to finish: ",
            "second test current"))
        if second is not None and self._ceiling_allows(second):
            self.part_headroom(second, source, "2.6")

    def _amps(self, answer):
        if not answer:
            return None
        try:
            amps = float(answer.lower().rstrip("a").strip())
        except ValueError:
            self._step(f"{answer!r} is not a current - taken as a skip")
            return None
        if not 0 < amps <= MAX_TEST_A:
            self._step(f"{amps:g} A is outside 0 to {MAX_TEST_A:g} A - "
                       f"taken as a skip")
            return None
        return amps

    def _ceiling_allows(self, amps):
        ceiling = (number(self.raw(":CURR:UPP?"))
                   if ":CURR:UPP?" in self.answered else None)
        if ceiling is not None and ceiling < amps:
            self.headline(f"part 2: the current ceiling is {ceiling:g} A, "
                          f"below {amps:g} A. Raise it at the front panel "
                          f"and run again. Stopped")
            return False
        return True

    def part_cc(self, limit):
        self.part = "2.2 CC"
        low = round(min(CC_LOW_A, limit / 4), 4)
        high = round(min(CC_HIGH_A, limit / 2), 4)
        level = self.found["current"]
        self.send(self.found["cc"])
        self.send(level.format(v=low))
        self.send(self.found["on"])
        self.sleep(HOLD_S)
        replies = []
        for _ in range(3):
            replies.append((self.raw(":MEAS:VOLT?"), self.raw(":MEAS:CURR?"),
                            self.raw(":MEAS:POW?")
                            if ":MEAS:POW?" in self.answered else None))
        supply = self.operator(
            f"  The load is sinking {low:g} A. The current on the supply's "
            f"display, in amps (Enter to skip): ", "supply's display")
        volts, amps, watts = replies[-1]
        self.headline(f"CC at {low:g} A: :MEAS:CURR? {amps}, :MEAS:VOLT? "
                      f"{volts}, :MEAS:POW? {watts}; the supply's display "
                      f"{supply or 'not read'}")

        self.part = "2.3 refresh"
        polls = self._poll(":MEAS:CURR?", REFRESH_WINDOW_S,
                           f"polling :MEAS:CURR? for {REFRESH_WINDOW_S:g} s")
        self.headline("refresh: " + refresh_summary(polls))

        self.part = "2.4 CC step"
        for start, end in ((low, high), (high, low)):
            origin = self.clock()
            self.send(level.format(v=end), note=f"from {start:g} A")
            polls = self._poll(":MEAS:CURR?", STEP_WINDOW_S,
                               f"polling after {start:g} -> {end:g} A",
                               origin=origin)
            self.headline(f"CC step {start:g} -> {end:g} A: "
                          + settle_summary(polls, start, end))
        self.off()

    def part_headroom(self, limit, source, part):
        self.part = f"{part} CV at {limit:g} A"
        level = self.found["voltage"]
        top = round(min(3.0, 0.6 * source), 3)
        step_to = round(top * 2 / 3, 3)
        self.send(self.found["cv"])
        self.send(level.format(v=top))
        self.send(self.found["on"])
        self.sleep(HOLD_S)
        volts, amps = self._read_vi(f"CV {top:g} V, supply limiting")
        if amps is None or amps < 0.9 * limit:
            self.headline(f"CV at {limit:g} A: {amps} A flowing at {top:g} "
                          f"V, not the supply's {limit:g} A - it is not "
                          f"limiting, so the ladder below is not at that "
                          f"current")
        origin = self.clock()
        self.send(level.format(v=step_to), note=f"from {top:g} V")
        polls = self._poll(":MEAS:VOLT?", STEP_WINDOW_S,
                           f"polling after {top:g} -> {step_to:g} V",
                           origin=origin)
        self.headline(f"CV step {top:g} -> {step_to:g} V at {limit:g} A: "
                      + settle_summary(polls, top, step_to))
        rows = []
        for rung in (r for r in CV_LADDER if r < step_to):
            self.send(level.format(v=rung))
            self.sleep(HOLD_S)
            volts, amps = self._read_vi(f"held {HOLD_S:g} s at {rung:g} V")
            rows.append((rung, volts, amps))
        self.off()
        self.headline(f"headroom at {limit:g} A: " + ladder_summary(rows))

    # ---- the whole sitting -----------------------------------------
    def run(self, watching=False, with_source=True):
        self.watching = watching
        try:
            self.part_port()
            self.part_identity()
            self.part_inventory()
            self.part_mode()
            self.part_levels()
            self.part_cv_floor()
            self.part_ceilings()
            self.part_input()
            self.part_reset()
            self.off()
            if with_source:
                self.part_source()
            self.headline("found: " + (", ".join(
                f"{k} = {v!r}" for k, v in self.found.items()) or "nothing")
                + f"; {len(self.silent)} unanswered queries, "
                f"{len(self.unsolicited)} writes that drew a reply")
        except KeyboardInterrupt:
            self.stopped_early = "interrupted by Ctrl-C"
        except Exception as exc:
            self.stopped_early = f"{type(exc).__name__}: {exc}"
        finally:
            self.off()
            try:
                self.transport.close()
            except Exception:
                pass


def refresh_summary(polls):
    """How often the reply changed, from a fast poll. A label, not a
    verdict: a perfectly steady reading changes rarely whatever the
    refresh, and the count says when that is what happened."""
    if len(polls) < 2:
        return f"{len(polls)} polls - too few"
    per_query = polls[-1][0] / len(polls)
    changes = [t for (t, reply), (_, before) in zip(polls[1:], polls)
               if reply != before]
    if len(changes) < 3:
        return (f"{len(polls)} polls at {per_query * 1000:.1f} ms each, "
                f"{len(changes)} changes - too few to time the refresh")
    gaps = sorted(b - a for a, b in zip(changes, changes[1:]))
    return (f"{len(polls)} polls at {per_query * 1000:.1f} ms each; the "
            f"reply changed {len(changes)} times, a median "
            f"{gaps[len(gaps) // 2] * 1000:.0f} ms apart")


def settle_summary(polls, start, end):
    """When the reading came within 2% of the step and stayed there."""
    values = [(t, number(reply)) for t, reply in polls]
    values = [(t, v) for t, v in values if v is not None]
    if len(values) < 5:
        return f"{len(values)} readings - too few"
    tail = sorted(v for _, v in values[-5:])
    final = tail[2]
    band = max(0.02 * abs(end - start), 0.002)
    settled = None
    for t, v in reversed(values):
        if abs(v - final) > band:
            break
        settled = t
    return (f"ended at {final:.4g} (asked {end:g}); inside 2% of the step "
            f"from {settled * 1000:.0f} ms" if settled is not None
            else f"never inside 2% of the step; ended at {final:.4g}")


def ladder_summary(rows):
    """Each rung asked -> measured, and the lowest voltage held while
    current flowed, as volts and as a resistance."""
    if not rows:
        return "no rungs below the starting level"
    shown = "; ".join(f"{rung:g} -> {_v(v)} at {_a(i)}"
                      for rung, v, i in rows)
    flowing = [(v, i) for _, v, i in rows
               if v is not None and i is not None and i > 0]
    if not flowing:
        return shown
    v, i = min(flowing)
    return (f"{shown}. Lowest {v:.4g} V at {i:.4g} A, which is "
            f"{v / i * 1000:.3g} mOhm")


def _v(value):
    return "no reading" if value is None else f"{value:.4g} V"


def _a(value):
    return "no reading" if value is None else f"{value:.4g} A"


def build_report(session, address, provenance):
    lines = [
        "# Multicomp Pro MP710772 - the first sitting at the bench",
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
                        help="the COM port, e.g. COM7")
    parser.add_argument("--transport", default=None, choices=TRANSPORTS,
                        help="default: visa for a VISA resource string, "
                             "serial for anything else")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--out", default="checkups")
    args = parser.parse_args()

    transport_name = (args.transport or inferred_transport(args.address)
                      or "serial")

    def connect():
        transport = TRANSPORTS[transport_name]()
        if transport_name == "serial":
            transport.connect(args.address, baudrate=args.baud)
        else:
            transport.connect(args.address)
        return transport

    print("Part 1 needs NOTHING connected to the load's input.")
    if input("Is the input disconnected? [y/N] ").strip().lower() != "y":
        return 1
    watching = input("Can you see the load's screen from the keyboard? "
                     "[y/N] ").strip().lower() == "y"
    ports = addresses.serial_ports()
    info = addresses.port_info(args.address, ports)
    port = (args.address, info, addresses.describe(args.address, ports))

    session = Session(connect, port=port)
    session.run(watching=watching)

    # No driver exists yet, so there is no code for this report to
    # fingerprint: `bench_code` is left out rather than computed over
    # files that are not what was tested.
    provenance = provenance_of(idn=session.idn)
    stem = f"bench_MP710772_{time.strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(args.out, exist_ok=True)
    md_path = os.path.join(args.out, stem + ".md")
    json_path = os.path.join(args.out, stem + ".json")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(build_report(session, args.address, provenance))
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump({
            "when": datetime.datetime.now().isoformat(timespec="seconds"),
            "address": args.address,
            "port": port,
            "provenance": provenance,
            "stopped_early": session.stopped_early,
            "headlines": session.headlines, "answers": session.answers,
            "found": session.found, "answered": session.answered,
            "silent": session.silent, "unsolicited": session.unsolicited,
            "steps": session.steps,
        }, handle, indent=2, default=repr)
    print(f"\nWrote {md_path}\n      {json_path}")
    print("Bring both back, whole.")
    return 1 if session.stopped_early else 0


if __name__ == "__main__":
    sys.exit(main())
