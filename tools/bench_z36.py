"""
The first sitting with the TDK-Lambda Z36-24: how to reach it over USB.

The Z+ manual is good - a full SCPI command set, an error queue, a fault
register - so unlike the MP710772 the commands are not in doubt. What
the manual leaves open is the **connection**, and that decides how the
suite can connect at all:

  * "Selecting the power supply (INSTrument:NSELect <address>) is
    necessary before using any other command." If `*IDN?` is not
    answered until then, the suite's auto-identification gets silence
    and latches the link, and the driver has to be picked by hand at
    Connect, the way the Keithley 487 is.
  * The baud rate. The Z+ tops out at 57600 (factory 9600); the suite's
    Serial transport is fixed at 115200. Over USB some instruments
    answer at any baud - the Korad loads do - and some do not.
  * The USB ids, for `core/addresses.py`, and the shape of every reply.

So this runs before the driver, and the driver is written from what it
records together with the manual.

    uv run tools/bench_z36.py --address COM8 --baud 9600 --bus-address 6

Before the sitting: the TDK USB driver installed, the cable plugged in
with the AC switch OFF, then on; at the front panel (REM) the interface
set to USB and the language to SCPI, and the address and baud written
down - they are this tool's `--bus-address` and `--baud`.

**Nothing is connected to the output terminals, for the whole sitting.**

Part 1 - output off throughout
  1.0 What the USB port says it is, and what the suite would call it.
  1.1 `*IDN?` before `INST:NSEL`, then after it; then again after the
      port is closed and reopened, which is what every connect does.
  1.2 Whether the baud matters over USB: the same questions at the other
      baud (115200, the Serial transport's, or 9600 if that was given).
  1.3 Every read-only query the driver might use, verbatim.
  1.4 What a refused setting looks like in `SYST:ERR?` and `*ESR?`.
  1.5 How the voltage setting and the over-voltage trip limit each other
      (the manual: PV at most 95% of the trip, the trip at least 105% of
      PV).
  1.6 The setting grid: what an odd level reads back as.
  1.7 What `*RST` does, and whether the selection survives it.
  1.8 Remote and local: whether `SYST:REM LOC` hands the front panel
      back, and what puts it back in remote.
  1.9 The refusals again after `SYST:ERR:ENAB`, and whether that
      outlasts `*RST`. Added after the first sitting (2026-11-17), where
      every refusal in 1.4 and 1.5 was silent: no error in `SYST:ERR?`
      or `*ESR?`, and the setting left as it was.

Part 2 - the output on, open circuit, never above 5 V or 50 mA
  2.1 On at 1 V: how long the output takes to get there, the mode and
      status queries, and what the current meter reads with nothing
      attached - the readback's offset, which the manual puts at up to
      72 mA.
  2.2 How long a reading takes.
  2.3 A step up to 5 V and back down - down is slow on a supply with
      nothing to discharge it.
  2.4 Off: how fast the terminals fall, and what the queries say.

At the end the voltage, current and trip settings are put back as they
were found, with the output off, and the front panel handed back.

Part 4 - a power cycle, if the operator agrees
  With the port closed, the AC switch off and on. Then: is `*IDN?`
  answered without `INST:NSEL`, what settings came back, and is
  `SYST:ERR:ENAB` still in force. Added after the first sitting: every
  selection finding there was made on a unit selected since power-on.

Never sent: `*SAV`, `*RCL`, `FRST`, the `GLOBal` commands, `SYST:REM
LLO`, `LIST`, `WAVE`, `TRIG`, `INIT`, `*PSC`, and no enable register,
foldback, UVP, interlock, relay, trigger-out or auto-restart setting.

It expects silence where the manual says to. An unanswered query
latches the transport, so after one the tool reconnects, waits for
anything arriving late, records it, reselects the supply and carries
on - late bytes are drained, never read as the next reply. Every write
is followed by a look for an unsolicited reply, which is also how a unit
left in the GEN language shows itself: GEN answers every command `OK`.
The output goes off between parts, at the end, and on any error or
Ctrl-C.
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

#: Seconds to wait for a reply. Long enough for anything that is going to
#: answer at all at 9600 baud, short enough that the silences part 1.1
#: expects cost seconds.
QUERY_TIMEOUT_S = 1.5

#: After reconnecting from a silence: how long to wait for a reply that
#: was only late, before draining whatever arrived.
LATE_REPLY_WAIT_S = 1.0

#: After every write: how long to wait before looking for an unsolicited
#: reply - an `OK`, an error string, anything the next query would
#: otherwise collect as its own answer.
UNSOLICITED_WAIT_S = 0.15

#: The manual gives `*CLS` 150 ms to execute.
CLS_WAIT_S = 0.3

#: The baud tried in part 1.2 when the one given is something else: the
#: Serial transport's fixed rate, since that is the question.
SERIAL_TRANSPORT_BAUD = 115200
#: And the one tried when 115200 was given: the factory setting.
FACTORY_BAUD = 9600

#: Every query part 1.3 asks, in order. All read-only, all in the
#: manual. `STAT:OPER:EVEN?` and `STAT:QUES?` clear the event register
#: they read, which is harmless here: nothing has enabled one.
INVENTORY = (
    "*IDN?", "*OPT?", "SYST:VERS?", "SYST:DATE?", "SYST:LANG?",
    "SYST:REM?", "INST:NSEL?", "SYST:PON:TIME?",
    "OUTP?", "OUTP:MODE?", "OUTP:PON?", "OUTP:PROT:FOLD?",
    "OUTP:PROT:DEL?", "OUTP:ILC:MODE?",
    "VOLT?", "VOLT? MAX", "VOLT? MIN", "CURR?", "CURR? MAX", "CURR? MIN",
    "VOLT:PROT:LEV?", "VOLT:PROT:LEV? MIN", "VOLT:PROT:LEV? MAX",
    "VOLT:PROT:LOW:STAT?", "VOLT:PROT:LOW?", "VOLT:MODE?", "CURR:MODE?",
    "MEAS:VOLT?", "MEAS:CURR?", "MEAS:POW?",
    "STAT:OPER:COND?", "STAT:OPER:EVEN?", "STAT:OPER:ENAB?",
    "STAT:QUES:COND?", "STAT:QUES?", "STAT:QUES:ENAB?",
    "*ESR?", "*STB?",
)

#: The settings read before anything is written and put back at the end.
FOUND_SETTINGS = (("VOLT?", "VOLT"), ("CURR?", "CURR"),
                  ("VOLT:PROT:LEV?", "VOLT:PROT:LEV"))

#: Part 1.4: (command, what it tests). Each is harmless if the
#: instrument accepts it, because the output is off and confirmed off
#: first, and each level is put back afterwards.
REFUSALS = (
    ("VOLT:NOSUCH 1", "an unknown header"),
    ("CURR 30", "a current above the 105% the manual says is accepted"),
    ("VOLT 40", "a voltage above 105% of rated"),
    ("VOLT:PROT:LEV 1", "a trip below the 2 V minimum"),
    ("VOLT 37", "a voltage inside the 5% over rated the manual allows"),
    ("CURR 25", "a current inside the 5% over rated"),
)

#: Part 1.5: (command, what the manual predicts). Run in this order from
#: the trip at its maximum and 10 V set.
TRIP_SEQUENCE = (
    ("VOLT:PROT:LEV 10", "refused: below 105% of 10 V (304)"),
    ("VOLT:PROT:LEV 12", "accepted"),
    ("VOLT 11.5", "refused: above 95% of a 12 V trip (301)"),
    ("VOLT 11", "accepted"),
    ("VOLT:PROT:LEV MIN", "the trip to 5% above 11 V, 11.55 V"),
)

#: Part 1.6: (command, readback query). Odd values, to see the grid.
GRID = (("VOLT 1.23456", "VOLT?"), ("CURR 0.123456", "CURR?"),
        ("VOLT 0.0021", "VOLT?"), ("CURR 0.0021", "CURR?"),
        ("CURR 0", "CURR?"))

#: Part 1.7: distinctive settings `*RST` is asked to clear.
RST_MARKERS = ("VOLT 1.11", "CURR 0.111", "VOLT:PROT:LEV 20")
RST_READS = ("VOLT?", "CURR?", "VOLT:PROT:LEV?", "OUTP?", "OUTP:PON?",
             "OUTP:PROT:FOLD?", "VOLT:PROT:LOW:STAT?", "VOLT:PROT:LOW?",
             "SYST:REM?", "INST:NSEL?")

#: Part 2's levels. Open circuit, so nothing flows whatever the current
#: setting - but it is kept small anyway, and the guards below are
#: checked before the output goes on.
PROBE_V, STEP_V, PROBE_A = 1.0, 5.0, 0.05
MAX_ON_V, MAX_ON_A = 5.0, 0.05

#: How long to poll after a change, in seconds. Down is slow: nothing
#: discharges the output capacitor but the supply's own bleed.
UP_WINDOW_S, DOWN_WINDOW_S, OFF_WINDOW_S = 1.5, 3.0, 3.0

#: How many times part 4 tries to reopen the port after the power cycle.
POWER_CYCLE_TRIES = 3

#: Readings timed for part 2.2, and open-circuit current readings.
TIMED_READINGS = 10
CURRENT_READINGS = 5

_NUMBER = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")


def number(reply):
    """The leading number of a reply - `'01.2345'`, `'1.2345E+00'` - or
    None. Tolerant on purpose: the raw reply is beside it in the report
    whatever this makes of it."""
    if reply is None:
        return None
    match = _NUMBER.match(str(reply))
    return float(match.group(1)) if match else None


def error_code(reply):
    """The number at the front of a `SYST:ERR?` reply, or None."""
    value = number(reply)
    return None if value is None else int(value)


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

    `connect(baud)` returns a connected transport; `baud` None means the
    one the operator gave. `ask`, `sleep` and `clock` are injected so the
    whole sitting can be walked offline against a fake. `port` is
    `(address, pyserial facts, what the suite calls it)`, or None.
    """

    def __init__(self, connect, bus_address=6, baud=FACTORY_BAUD,
                 log=print, ask=None, sleep=None, clock=None, port=None,
                 can_set_baud=True):
        self.connect = connect
        self.bus_address = bus_address
        self.baud = baud
        self.can_set_baud = can_set_baud
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
        #: What part 1 settled, for the driver: "nsel_needed",
        #: "nsel_survives_reopen", "other_baud_answers", ...
        self.found = {}
        #: Settings as found, to be put back: command -> value.
        self.as_found = {}
        self.watching = False
        self.idn = None
        #: Whether anything has answered at all. Nothing after 1.1 runs
        #: without it.
        self.alive = False
        self.output_on = False
        self._open()

    # ---- the link --------------------------------------------------
    def _open(self, baud=None):
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
        self.transport = self.connect(baud)
        install_trace(self.transport, self.trace)

    def _recover(self, command):
        """After a silence: reconnect, wait, record anything late, and
        select the supply again so the next command is heard."""
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
        if self.alive:
            self.select("reselect after the reconnect")

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

    def send(self, command, what=None, note="", wait=True):
        """One write, then a look for anything it drew back.

        `wait=False` skips the pause before that look, for a write whose
        settling is being timed: the pause would put a 150 ms floor
        under a response the specification gives as 50 ms. By part 2 the
        unit is known to answer writes with nothing (a GEN unit, which
        answers `OK`, stops at the off check), and the poll that follows
        would collect a stray reply as a reading the report shows."""
        mark = len(self.trace)
        self.transport.write(command)
        if wait:
            self.sleep(UNSOLICITED_WAIT_S)
        extra = pending_text(self.transport)
        result = None
        if extra:
            result = f"<UNSOLICITED REPLY: {extra.strip()!r}>"
            self.unsolicited.append((command, extra.strip()))
        self._step(what or command, result, note, since=mark)

    def select(self, note="select the supply"):
        self.send(f"INST:NSEL {self.bus_address}", note=note)

    def operator(self, prompt, key):
        answer = self.ask(prompt).strip()
        self.answers.setdefault(key, []).append(answer)
        return answer

    def errors(self, note=""):
        """Drain `SYST:ERR?` to `0` (at most twelve reads - the queue is
        ten deep) and read `*ESR?`. Returns the non-zero replies and the
        register, both verbatim."""
        seen = []
        for _ in range(12):
            reply = self.raw("SYST:ERR?", note=note)
            if reply is None or error_code(reply) in (0, None):
                break
            seen.append(reply)
        esr = self.raw("*ESR?", note=note)
        return seen, esr

    def off(self):
        """The output off - selecting the supply first, because a
        command it has not been addressed for is ignored."""
        for command in (f"INST:NSEL {self.bus_address}", "OUTP 0"):
            try:
                self.send(command, note="output off")
            except Exception:
                pass
        self.output_on = False

    def turn_on(self, volts, amps):
        """Set the levels and switch on - refusing, here, anything above
        part 2's guards, so no later edit to the parts can exceed them.
        Returns the clock just before `OUTP 1`, for timing."""
        if volts > MAX_ON_V or amps > MAX_ON_A:
            raise RuntimeError(
                f"refused: {volts:g} V / {amps:g} A is above this tool's "
                f"{MAX_ON_V:g} V / {MAX_ON_A:g} A with the output on")
        self.send(f"CURR {amps:g}")
        self.send(f"VOLT {volts:g}")
        self.output_on = True
        origin = self.clock()
        self.send("OUTP 1", wait=False)
        return origin

    def step_to(self, volts):
        if self.output_on and volts > MAX_ON_V:
            raise RuntimeError(
                f"refused: {volts:g} V is above this tool's {MAX_ON_V:g} V "
                f"with the output on")
        self.send(f"VOLT {volts:g}", wait=False)

    def _poll(self, command, window_s, what, origin=None):
        """Query as fast as the link allows for `window_s`; one step,
        every exchange in it. Times are from `origin` when given."""
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

    # ---- part 1: output off ----------------------------------------
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

    def part_selection(self):
        self.part = "1.1 selection"
        before = self.raw("*IDN?", note="before INST:NSEL")
        self.select()
        after = self.raw("*IDN?", note=f"after INST:NSEL {self.bus_address}")
        self.idn = after or before
        self.alive = self.idn is not None
        if not self.alive:
            self.headline(
                f"selection: nothing answered at {self.baud} baud, before "
                f"or after INST:NSEL {self.bus_address}. Check the "
                f"interface is USB, the language SCPI, and that "
                f"--bus-address and --baud match the front panel. Stopped")
            return
        self.found["nsel_needed"] = before is None
        self._open()
        reopened = self.raw("*IDN?", note="port reopened, no INST:NSEL")
        self.found["nsel_survives_reopen"] = reopened is not None
        if reopened is None:
            self.select("after reopening")
        gen = [c for c, text in self.unsolicited if "OK" in text.upper()]
        self.headline(
            f"selection: *IDN? before INST:NSEL "
            f"{repr(before) if before else 'no reply'}; after it {after!r}; "
            f"after reopening the port without it "
            f"{repr(reopened) if reopened else 'no reply'}"
            + ("; writes answered OK - the language is GEN, not SCPI"
               if gen else ""))

    def part_baud(self):
        self.part = "1.2 baud"
        if not self.can_set_baud:
            self._step("not a pyserial port: the baud is VISA's, skipped")
            return
        other = (FACTORY_BAUD if self.baud == SERIAL_TRANSPORT_BAUD
                 else SERIAL_TRANSPORT_BAUD)
        self._open(other)
        self.send(f"INST:NSEL {self.bus_address}", note=f"at {other} baud")
        reply = self.raw("*IDN?", note=f"at {other} baud")
        self.found["other_baud_answers"] = reply is not None
        self._open()
        self.select(f"back at {self.baud} baud")
        check = self.raw("*IDN?", note=f"back at {self.baud} baud")
        self.headline(
            f"baud: at {other} (front panel {self.baud}) *IDN? "
            f"{'answered ' + repr(reply) if reply else 'got no reply'}"
            f"; back at {self.baud}: "
            f"{'answers' if check else 'NO REPLY'}")

    def part_inventory(self):
        self.part = "1.3 what answers"
        for command in INVENTORY:
            reply = self.raw(command)
            if reply is not None:
                self.answered[command] = reply
        for query, setter in FOUND_SETTINGS:
            value = number(self.answered.get(query))
            if value is not None:
                self.as_found[setter] = value
        drained, esr = self.errors("start clean")
        quiet = [c for c in INVENTORY if c not in self.answered]
        self.headline(f"inventory: {len(self.answered)} of "
                      f"{len(INVENTORY)} queries answered; silent: "
                      f"{', '.join(quiet) or 'none'}; errors waiting: "
                      f"{', '.join(drained) or 'none'}, *ESR? {esr}")
        self.headline("as found: " + (", ".join(
            f"{k} {v:g}" for k, v in self.as_found.items()) or "unreadable"))

    def _output_is_off(self):
        self.send("OUTP 0", note="before any setting is written")
        state = self.raw("OUTP?", note="0 before anything is written")
        if state is not None and number(state) == 0:
            return True
        self.headline(f"OUTP? read {state!r} after OUTP 0 - not confirmed "
                      f"off, so nothing is written. Stopped")
        return False

    def part_refusals(self):
        self.part = "1.4 refusals"
        # The widest trip first, so a voltage refused below is refused
        # for its own sake and not for a trip left low at the front panel.
        self.send("VOLT:PROT:LEV MAX", note="the widest trip")
        self.errors("start clean")
        lines = []
        for command, label in REFUSALS:
            self.send(command, note=label)
            seen, esr = self.errors(f"after {command}")
            readback = None
            header = command.split()[0]
            if header in ("VOLT", "CURR", "VOLT:PROT:LEV"):
                readback = self.raw(f"{header}?", note="did it land?")
            lines.append(f"{command} -> {', '.join(seen) or 'no error'}, "
                         f"*ESR? {esr}"
                         + (f", {header}? {readback}" if readback else ""))
        self.send("VOLT 0", note="put back")
        self.send("CURR 0", note="put back")
        self.send("VOLT:PROT:LEV MAX", note="put back")
        self.headline("refusals: " + "; ".join(lines))

    def part_trip(self):
        self.part = "1.5 voltage and trip"
        self.send("VOLT:PROT:LEV MAX", note="start from the widest trip")
        self.send("VOLT 10")
        self.errors("start clean")
        lines = []
        for command, expected in TRIP_SEQUENCE:
            self.send(command, note=f"manual: {expected}")
            seen, _ = self.errors(f"after {command}")
            volts = self.raw("VOLT?")
            trip = self.raw("VOLT:PROT:LEV?")
            lines.append(f"{command} -> {', '.join(seen) or 'no error'} "
                         f"(VOLT? {volts}, trip {trip})")
        self.send("VOLT 0", note="put back")
        self.send("VOLT:PROT:LEV MAX", note="put back")
        self.headline("voltage and trip: " + "; ".join(lines))

    def part_grid(self):
        self.part = "1.6 the grid"
        lines = []
        for command, query in GRID:
            self.send(command)
            seen, _ = self.errors(f"after {command}")
            lines.append(f"{command} -> {self.raw(query)}"
                         + (f" ({', '.join(seen)})" if seen else ""))
        self.send("VOLT 0", note="put back")
        self.send("CURR 0", note="put back")
        self.headline("grid: " + "; ".join(lines))

    def part_reset(self):
        self.part = "1.7 *RST"
        for command in RST_MARKERS:
            self.send(command, note="a marker")
        before = {q: self.raw(q, note="before *RST") for q in RST_READS}
        self.send("*RST")
        idn = self.raw("*IDN?", note="still selected?")
        if idn is None:
            self.select("after *RST")
        self.found["nsel_survives_rst"] = idn is not None
        after = {q: self.raw(q, note="after *RST") for q in RST_READS}
        changed = [f"{q} {before[q]} -> {after[q]}" for q in RST_READS
                   if before[q] != after[q]]
        mark = len(self.trace)
        started = self.clock()
        self.send("*CLS")
        self.sleep(CLS_WAIT_S)
        done = self.raw("*OPC?", note="after *CLS")
        self._step(f"*CLS then *OPC? in "
                   f"{(self.clock() - started) * 1000:.0f} ms", done,
                   since=mark)
        self.headline("*RST: " + ("; ".join(changed) if changed
                                  else "changed nothing that was read")
                      + f"; still selected afterwards: "
                      f"{'yes' if idn else 'no'}")

    def part_remote(self):
        self.part = "1.8 remote and local"
        now = self.raw("SYST:REM?", note="after all the writes")
        self.send("SYST:REM LOC")
        local = self.raw("SYST:REM?", note="LOC if it took")
        led = None
        if self.watching:
            led = self.operator("  Is the REM LED off now? (y/n, Enter to "
                                "skip): ", "REM LED")
            self._step("the operator reads the REM LED", led or None)
        self.raw("MEAS:VOLT?", note="a query")
        after_query = self.raw("SYST:REM?", note="does a query take it back?")
        self.send("VOLT 0", note="a setting")
        after_write = self.raw("SYST:REM?", note="does a setting?")
        self.headline(
            f"remote: {now} after the writes; {local} after SYST:REM LOC"
            + (f" (REM LED off: {led})" if led else "")
            + f"; {after_query} after a query; {after_write} after a "
              f"setting")

    def _refuse(self, command, header=None):
        """Send one setting expected to be refused; its errors, its
        `*ESR?`, and whether it landed, as one line."""
        self.send(command)
        seen, esr = self.errors(f"after {command}")
        header = header or command.split()[0]
        readback = (self.raw(f"{header}?", note="did it land?")
                    if header in ("VOLT", "CURR", "VOLT:PROT:LEV") else None)
        return seen, (f"{command} -> {', '.join(seen) or 'no error'}, "
                      f"*ESR? {esr}"
                      + (f", {header}? {readback}" if readback else ""))

    def part_errors_enabled(self):
        """The first sitting's refusals were all silent: no error, and
        the setting unchanged. The manual lists `SYST:ERR:ENABle`,
        "Enables Error messages", and nothing had sent it."""
        self.part = "1.9 errors enabled"
        self.send("SYST:ERR:ENAB")
        self.send("VOLT:PROT:LEV MAX", note="the widest trip")
        self.send("VOLT 0")
        self.errors("start clean")
        lines, reported = [], 0
        for command, _ in REFUSALS:
            seen, line = self._refuse(command)
            reported += bool(seen)
            lines.append(line)
        # The two rules that tie the voltage to the trip.
        self.send("VOLT 10")
        seen, line = self._refuse("VOLT:PROT:LEV 10")
        reported += bool(seen)
        lines.append(line + " (with 10 V set)")
        self.send("VOLT:PROT:LEV 12")
        seen, line = self._refuse("VOLT 11.5")
        reported += bool(seen)
        lines.append(line + " (with a 12 V trip)")
        self.send("VOLT 0", note="put back")
        self.send("CURR 0", note="put back")
        self.send("VOLT:PROT:LEV MAX", note="put back")
        self.found["errors_after_enable"] = reported > 0
        # The driver's reset() sends *RST: does the enable outlast it?
        self.send("*RST")
        seen, after_rst = self._refuse("VOLT 40")
        self.found["enable_survives_rst"] = bool(seen)
        self.send("SYST:ERR:ENAB", note="on again for the rest")
        self.headline(f"errors enabled: {reported} of {len(lines)} settings "
                      f"drew an error - " + "; ".join(lines)
                      + f"; after *RST: {after_rst}")

    # ---- part 2: output on, open circuit ---------------------------
    def part_on(self):
        self.part = "2.1 on at 1 V"
        self.errors("start clean")
        origin = self.turn_on(PROBE_V, PROBE_A)
        polls = self._poll("MEAS:VOLT?", UP_WINDOW_S,
                           "polling MEAS:VOLT? after OUTP 1",
                           origin=origin)
        self.headline(f"on at {PROBE_V:g} V: "
                      + settle_summary(polls, 0.0, PROBE_V))
        states = {q: self.raw(q) for q in (
            "OUTP?", "OUTP:MODE?", "STAT:OPER:COND?", "STAT:QUES:COND?",
            "MEAS:POW?")}
        amps = [self.raw("MEAS:CURR?", note="open circuit")
                for _ in range(CURRENT_READINGS)]
        display = None
        if self.watching:
            display = self.operator("  What voltage does the supply's "
                                    "display show? (Enter to skip): ",
                                    "display")
            self._step("the operator reads the display", display or None)
        self.headline("on, open circuit: " + ", ".join(
            f"{q} {r}" for q, r in states.items())
            + f"; MEAS:CURR? {', '.join(map(str, amps))}"
            + (f"; display {display}" if display else ""))

        self.part = "2.2 a reading"
        mark = len(self.trace)
        started = self.clock()
        for _ in range(TIMED_READINGS):
            self.raw("MEAS:VOLT?", note="timed")
        each = (self.clock() - started) / TIMED_READINGS
        self._step(f"{TIMED_READINGS} readings", f"{each * 1000:.1f} ms "
                   f"each", since=mark)
        self.headline(f"a reading: {each * 1000:.1f} ms per MEAS:VOLT?")

        self.part = "2.3 steps"
        for start, end, window in ((PROBE_V, STEP_V, UP_WINDOW_S),
                                   (STEP_V, PROBE_V, DOWN_WINDOW_S)):
            origin = self.clock()
            self.step_to(end)
            polls = self._poll("MEAS:VOLT?", window,
                               f"polling after {start:g} -> {end:g} V",
                               origin=origin)
            mode = self.raw("OUTP:MODE?", note="after the step")
            self.headline(f"step {start:g} -> {end:g} V: "
                          + settle_summary(polls, start, end)
                          + f"; OUTP:MODE? {mode}")

        self.part = "2.4 off"
        origin = self.clock()
        self.send("OUTP 0", wait=False)
        self.output_on = False
        polls = self._poll("MEAS:VOLT?", OFF_WINDOW_S,
                           "polling MEAS:VOLT? after OUTP 0", origin=origin)
        states = {q: self.raw(q) for q in (
            "OUTP?", "OUTP:MODE?", "STAT:OPER:COND?", "STAT:QUES:COND?")}
        seen, esr = self.errors("after the output part")
        self.headline(f"off from {PROBE_V:g} V: "
                      + settle_summary(polls, PROBE_V, 0.0) + "; "
                      + ", ".join(f"{q} {r}" for q, r in states.items())
                      + f"; errors {', '.join(seen) or 'none'}, *ESR? "
                        f"{esr}")

    # ---- the end ---------------------------------------------------
    def put_back(self):
        """The settings as found, output off, and the front panel handed
        back. The trip first: a voltage is refused above 95% of it."""
        self.part = "3 put back"
        self.off()
        order = ("VOLT:PROT:LEV", "CURR", "VOLT")
        for setter in order:
            if setter in self.as_found:
                self.send(f"{setter} {self.as_found[setter]:g}",
                          note="as found")
        seen, _ = self.errors("after putting back")
        self.send("SYST:REM LOC", note="hand the front panel back")
        self.headline("put back: " + (", ".join(
            f"{k} {self.as_found[k]:g}" for k in order
            if k in self.as_found) or "nothing was readable")
            + f"; errors {', '.join(seen) or 'none'}")

    def part_power_cycle(self):
        """What a supply switched on this morning looks like to a
        connect. Every finding about the selection so far was made with
        it selected since power-on; whether a power cycle forgets it -
        and forgets `SYST:ERR:ENAB` - decides what the driver must send
        on every connect.

        The port is closed first and reopened after, which is the
        manual's own recovery for a USB link across an AC cycle."""
        self.part = "4 power cycle"
        if self.operator(
                "\nPart 4 switches the supply off and on at its AC switch, "
                "with the port closed.\nDo it? [y/N] ",
                "power cycle").lower() != "y":
            self._step("skipped at the operator's request")
            return
        self.off()
        self.transport.close()
        self._step("port closed")
        self.operator("  Switch the AC OFF now, wait 10 s, switch it ON, and "
                      "wait for the display.\n  Press Enter when it is on "
                      "again: ", "power cycled")
        for attempt in range(1, POWER_CYCLE_TRIES + 1):
            try:
                self._open()
                break
            except Exception as exc:
                self._step(f"reopening the port, try {attempt}",
                           f"{type(exc).__name__}: {exc}")
                if attempt == POWER_CYCLE_TRIES:
                    self.headline("power cycle: the port could not be "
                                  "reopened. Stopped")
                    self.alive = False
                    return
                self.operator("  The port is not back yet. Press Enter to "
                              "try again: ", "port back")
        self._step("port reopened")
        idn = self.raw("*IDN?", note="after the power cycle, no INST:NSEL")
        self.found["nsel_survives_power_cycle"] = idn is not None
        if idn is None:
            self.select("after the power cycle")
            if self.raw("*IDN?", note="after INST:NSEL") is None:
                self.headline("power cycle: no reply even after INST:NSEL. "
                              "Stopped")
                return
        states = {q: self.raw(q, note="after the power cycle") for q in (
            "OUTP?", "VOLT?", "CURR?", "VOLT:PROT:LEV?", "SYST:REM?")}
        self.errors("start clean")
        if number(states["OUTP?"]) == 0:
            seen, line = self._refuse("VOLT 40")
            self.found["enable_survives_power_cycle"] = bool(seen)
        else:
            self.off()
            line = "not tried: OUTP? did not read 0"
        self.send("SYST:REM LOC", note="hand the front panel back")
        self.headline(
            "power cycle: *IDN? without INST:NSEL "
            + (f"answered {idn!r}" if idn else "got no reply")
            + "; " + ", ".join(f"{q} {r}" for q, r in states.items())
            + f"; errors still enabled? {line}")

    def run(self, watching=False, with_output=True):
        self.watching = watching
        try:
            self.part_port()
            self.part_selection()
            if not self.alive:
                return
            self.part_baud()
            self.part_inventory()
            if not self._output_is_off():
                return
            self.part_refusals()
            self.part_trip()
            self.part_grid()
            self.part_reset()
            self.part_remote()
            self.part_errors_enabled()
            self.off()
            if with_output:
                self.part_on()
            self.put_back()
            self.part_power_cycle()
            self.headline("found: " + (", ".join(
                f"{k} = {v!r}" for k, v in self.found.items()) or "nothing")
                + f"; {len(self.silent)} unanswered queries, "
                f"{len(self.unsolicited)} writes that drew a reply")
        except KeyboardInterrupt:
            self.stopped_early = "interrupted by Ctrl-C"
        except Exception as exc:
            self.stopped_early = f"{type(exc).__name__}: {exc}"
        finally:
            if self.alive:
                self.off()
                try:
                    self.send("SYST:REM LOC", note="hand the front panel "
                                                   "back")
                except Exception:
                    pass
            try:
                self.transport.close()
            except Exception:
                pass


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
    return (f"ended at {final:.4g} V (asked {end:g}); inside 2% of the "
            f"step from {settled * 1000:.0f} ms" if settled is not None
            else f"never inside 2% of the step; ended at {final:.4g} V")


def build_report(session, address, provenance):
    lines = [
        "# TDK-Lambda Z36-24 - the first sitting at the bench",
        "",
        f"- **When:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Address:** {address}, bus address {session.bus_address}, "
        f"{session.baud} baud",
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
                        help="the COM port, e.g. COM8")
    parser.add_argument("--transport", default=None, choices=TRANSPORTS,
                        help="default: visa for a VISA resource string, "
                             "serial for anything else")
    parser.add_argument("--baud", type=int, default=FACTORY_BAUD,
                        help="the baud set at the front panel "
                             "(factory 9600)")
    parser.add_argument("--bus-address", type=int, default=6,
                        help="the address set at the front panel, 1-31 "
                             "(factory 6)")
    parser.add_argument("--out", default="checkups")
    args = parser.parse_args()

    if not 1 <= args.bus_address <= 31:
        parser.error("--bus-address must be 1 to 31")
    transport_name = (args.transport or inferred_transport(args.address)
                      or "serial")

    def connect(baud=None):
        transport = TRANSPORTS[transport_name]()
        if transport_name == "serial":
            transport.connect(args.address, baudrate=baud or args.baud)
        else:
            transport.connect(args.address)
        return transport

    print("This sitting needs NOTHING connected to the output terminals.")
    if input("Are the output terminals disconnected? [y/N] "
             ).strip().lower() != "y":
        return 1
    watching = input("Can you see the supply's front panel from the "
                     "keyboard? [y/N] ").strip().lower() == "y"
    ports = addresses.serial_ports()
    info = addresses.port_info(args.address, ports)
    port = (args.address, info, addresses.describe(args.address, ports))

    session = Session(connect, bus_address=args.bus_address, baud=args.baud,
                      port=port, can_set_baud=transport_name == "serial")
    session.run(watching=watching)

    # No driver exists yet, so there is no code for this report to
    # fingerprint: `bench_code` is left out rather than computed over
    # files that are not what was tested.
    provenance = provenance_of(idn=session.idn)
    stem = f"bench_Z36-24_{time.strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(args.out, exist_ok=True)
    md_path = os.path.join(args.out, stem + ".md")
    json_path = os.path.join(args.out, stem + ".json")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(build_report(session, args.address, provenance))
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump({
            "when": datetime.datetime.now().isoformat(timespec="seconds"),
            "address": args.address, "bus_address": args.bus_address,
            "baud": args.baud, "port": port, "provenance": provenance,
            "stopped_early": session.stopped_early,
            "headlines": session.headlines, "answers": session.answers,
            "found": session.found, "as_found": session.as_found,
            "answered": session.answered, "silent": session.silent,
            "unsolicited": session.unsolicited, "steps": session.steps,
        }, handle, indent=2, default=repr)
    print(f"\nWrote {md_path}\n      {json_path}")
    print("Bring both back, whole.")
    return 1 if session.stopped_early or not session.alive else 0


if __name__ == "__main__":
    sys.exit(main())
