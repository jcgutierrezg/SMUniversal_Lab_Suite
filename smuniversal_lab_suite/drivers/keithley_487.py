"""
Keithley 487 Picoammeter / Voltage Source.

A picoammeter with a +/-505 V source beside it, in one box, wired to
**separate terminals**: the source comes out of binding posts, the
current goes in through a triax. It holds a voltage and measures the
current that results, and nothing else - it cannot source a current and
nothing on it measures a voltage. So it is an SMU with half its modes
missing, declared as such: `SOURCE_FUNCTIONS = ("voltage",)`, and the
four-contact experiments refuse it at Connect. See
`docs/architecture/devices.md`, "An SMU that sources one quantity".

Written from the Model 486/487 Instruction Manual (a scan; the parts it
was written from are transcribed in `docs/reference/manuals/487-commands.md`)
with no original script behind it.

It is the first instrument here that is not SCPI
-------------------------------------------------
Keithley's device-dependent command language from the 1980s: a capital
letter and an option, executed by `X` - `V10,0,1X`, `O1X`. No `*IDN?`,
no `*RST`, no `*CLS`, no error queue. What changes because of it:

* **Identity is `U2X`**, which answers the model and firmware
  (`487A03`). `*IDN?` would be flagged as an illegal command and never
  answered, and the unanswered query would latch the transport - so the
  487 is never auto-detected. It is connected by choosing its driver,
  and `reset()` confirms the model before it configures anything.
* **One command per `X`.** The manual is explicit that commands in one
  `X`-terminated string execute *simultaneously*, and that one invalid
  command voids every other command in the string. Sending each setting
  on its own costs a few milliseconds per command and makes the trace
  say which one the instrument refused.
* **A rejected command is ignored in silence.** A level beyond the
  selected source range is a CONFLICT; one beyond +/-505 V is an IDDCO;
  in both cases the whole command is dropped and the previous level
  stays on the sample. The only record is a bit in the `U1` error word,
  which clears when read. So the driver refuses those levels itself
  before they reach the wire, and `read_error()` reads `U1`.
* **A reading is taken by being asked for one** - and only then.
  Trigger mode `T1`, one-shot on talk: addressing the instrument to talk
  triggers a conversion and the reply is that conversion. It is the
  only mode the manual describes as returning the reading just
  triggered rather than whatever was last in the output buffer, which
  is why the read in `measure()` is a bare `Transport.read()`.

  But in `T1` *every* talk is a trigger, including the one that fetches
  a status word. Measured 2026-10-14: a status query that came within
  a conversion (about 50 ms) of the previous talk was rejected as a
  trigger overrun, a checkup draining the error word then re-triggered
  it on every poll, and the reading that followed was never produced -
  the talk waited out a 16.8 s timeout. So the instrument idles in `T3`,
  one-shot on GET, a bus command nothing in this suite sends: there a
  talk triggers nothing. `measure()` switches to `T1` for its one talk
  and straight back.

Reset restores somebody's saved setup, not the factory's
--------------------------------------------------------
A device clear (DCL/SDC) returns the 487 to its *saved* default
conditions, and those are whatever the last person saved with `L1` at
the front panel. The factory set has zero check ON - every reading is
zero until it is turned off - triggering on an external pulse, both
filters on and autorange on, and a saved set can be anything at all.
So `reset()` clears and then sends **every** setting explicitly. It
never sends `L0` (factory defaults, *and saves them over the stored
set*) or `L1`: both permanently change a shared instrument.

The compliance is a menu
------------------------
The voltage source current-limits at 25 uA or 2.5 mA (+/-20%) and
nothing else, so `COMPLIANCE_CHOICES` makes it a menu and
`set_current_limit()` refuses anything off it. It does regulate - the
source drops its voltage to hold the limit, which is a compliance in
the SMU sense - and the `U9` word latches "has been in current limit"
until read, which is `compliance_tripped()`.

It is a protection only. The measurement range is a separate knob, and
deriving it from a 25 uA limit would put a picoammeter on its 200 uA
range, so `COMPLIANCE_SETS_MEASURE_RANGE = False` and the experiments
leave the range to autorange.

Off is disconnected
-------------------
Standby opens a relay in series with OUTPUT HI. The manual warns that
the open output lets dielectric absorption recharge a capacitive sample
to an unexpected voltage, so `output_off()` sets 0 V first, holds it
long enough to discharge, then opens the relay.

Not yet confirmed at the bench - each is in the instrument note
---------------------------------------------------------------
The three status words and the reading format are as the manual's
figures draw them, and nothing has yet compared them with a real reply.
Nor is it known whether a range change glitches the output, or how long
a source step takes to settle.
"""
import re
import time

from smuniversal_lab_suite.core.limits import LimitError, SMULimits
from smuniversal_lab_suite.core.ranges import AUTO, NOT_SOURCED, RangeError
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

from .base_smu import BaseSMU

#: Source ranges: (full scale in volts, option of the V command).
#: Full scale is what the range can be set to, 50.500 V and 505.00 V,
#: not the nominal 50 and 500.
SOURCE_RANGES = ((50.5, 0), (505.0, 1))

#: Current limit (amps) -> option of the V command's third field.
CURRENT_LIMITS = {25e-6: 0, 2.5e-3: 1}

#: Measurement ranges (full scale, amps) -> R option. R0 is autorange.
MEASURE_RANGES = ((2e-9, 1), (2e-8, 2), (2e-7, 3), (2e-6, 4), (2e-5, 5),
                  (2e-4, 6), (2e-3, 7))

#: The trigger mode the instrument idles in, and the one a reading uses.
#: `T3` is one-shot on GET, a bus command nothing here sends, so in it a
#: talk - a status query - triggers nothing. `T1`, one-shot on talk, is
#: set for the single talk that fetches a reading.
IDLE_TRIGGER = "T3"
READ_TRIGGER = "T1"

#: The integration periods. `S0` is a fixed 1.6 ms - 0.096 PLC at 60 Hz,
#: 0.08 at 50 Hz - and is declared as 0.1, the nearest round figure;
#: `S1` integrates over one line cycle.
FAST_NPLC = 0.1
LINE_NPLC = 1.0

#: How long `output_off()` holds 0 V before opening the relay. The
#: source's output resistance is under 2.5 ohm, so a sample of a few
#: nanofarads is discharged in microseconds; this is the time for the
#: source itself to slew down from as much as 505 V, which the manual
#: does not give. A guess on the long side, and a bench item.
DISCHARGE_HOLD_S = 0.05

#: A `G0` reading (manual Figure 4-1): a status letter, the function,
#: then the number - `NDCI+1.23456E-09`. N is a normal reading, Z one
#: with rel applied, O an overflow; DCI is current, OHM is V/I ohms.
_READING = re.compile(
    r"^\s*([NZO])(DCI|OHM)\s*([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)")

#: A U1 or U9 word: the model, then a run of 0/1 flags.
_STATUS_WORD = re.compile(r"^\s*(48[67])([01]+)\s*$")

#: One field of the U0 machine status word (manual Figure 4-6). Each is
#: the letter of the command it reports followed by that command's
#: option, so the word is read by letter rather than by position:
#: `487A0B0C1F0G0H05J0K0M000N000O0P3R11S1T6V01Y0Z00c1`. `c` (lower
#: case) is the calibration lock switch.
_U0_FIELD = re.compile(r"([A-Za-z])(\d+)")


class Keithley487(BaseSMU):
    # No *IDN?, so nothing for the registry to match. Connected by
    # choosing the driver; `identify()` and `reset()` confirm the model.
    MODEL_IDS: list[str] = []
    DISPLAY_NAME = "Keithley 487"

    LIMITS = SMULimits(
        max_voltage=505.0,
        # The larger of the two current limits. Measurement tops out at
        # the 2 mA range, but a compliance of 2.5 mA is a legal request
        # and the limit gate has to let it through.
        max_current=2.5e-3,
        voltage_ranges=[r for r, _ in SOURCE_RANGES],
        current_ranges=[r for r, _ in MEASURE_RANGES],
        power_envelope=[],
    )

    # ---- what kind of instrument this is ----
    SOURCE_FUNCTIONS = ("voltage",)
    #: Current only: `measure()` always gives None for the voltage.
    MEASURE_FUNCTIONS = ("current",)
    COMPLIANCE_CHOICES = {"current": tuple(sorted(CURRENT_LIMITS))}
    COMPLIANCE_SETS_MEASURE_RANGE = False

    # Source and ammeter ranges are separate knobs.
    INDEPENDENT_SOURCE_RANGE = True
    HAS_MEASURE_RANGE = True

    # There are no sense terminals: the source and the ammeter are two
    # separate circuits, and the sample sits between them.
    REMOTE_SENSE_CONTROL = False
    FIXED_SENSE = ("2-wire (no sense terminals - the source and the "
                   "ammeter are separate circuits)")

    # A two-setting integration time, declared as the window between
    # them; `clamp_nplc()` snaps a request onto one of the two.
    NPLC_RANGE = (FAST_NPLC, LINE_NPLC)

    # Standby always opens the output relay. There is no choice to offer,
    # so the high-Z control is not declared - see the note above.
    HIGH_Z_OFF = False
    OUTPUT_OFF_DISCONNECTS = True

    # Nothing has measured the source converter's bottom count, and
    # there is no current source to have one.
    SUB_COUNT_LEVELS = {"current": BaseSMU.SUB_COUNT_NOT_APPLICABLE,
                        "voltage": BaseSMU.SUB_COUNT_UNMEASURED}

    def __init__(self, transport):
        super().__init__(transport)
        # The V command's three fields as last sent. Every V command
        # this driver sends states all three, so nothing depends on what
        # the instrument remembered from before.
        self._level = 0.0
        self._range = SOURCE_RANGES[0]
        self._limit_option = CURRENT_LIMITS[25e-6]
        # The settle before each reading, kept here rather than in the
        # instrument - see `set_source_delay()`.
        self._settle_s = 0.0

    # ---- the wire ----------------------------------------------------
    def _send(self, command):
        """One command, executed on its own. See the module docstring."""
        self.transport.write(f"{command}X")

    def _status(self, which, timeout_s=3.0):
        """Ask for a U status word and return it, stripped."""
        return str(self.transport.query(f"U{which}X",
                                        timeout_s=timeout_s)).strip()

    def _machine_status(self):
        """The `U0` word as {letter: option}. Raises ValueError on a reply
        that is not one."""
        word = self._status(0).replace(" ", "")
        if not word.startswith("487"):
            raise ValueError(f"unexpected U0 reply {word!r}")
        fields = dict(_U0_FIELD.findall(word[3:]))
        for letter in ("C", "O", "R", "V"):
            if letter not in fields:
                raise ValueError(f"U0 reply {word!r} has no {letter} field")
        return fields

    def _flags(self, which):
        """The 0/1 flags of a U1 or U9 word, after the model number.

        Raises ValueError on anything else: a reply in a shape this
        driver does not understand is not evidence that nothing is set.
        """
        word = self._status(which)
        # Spaces are not part of the format, wherever they appear - the
        # U2 reply carries two trailing blanks, and nothing says U1 and
        # U9 do not.
        match = _STATUS_WORD.match(word.replace(" ", ""))
        if not match:
            raise ValueError(f"unexpected U{which} reply {word!r}")
        return word, match.group(2)

    # ---- identification ----------------------------------------------
    def identify(self):
        """`U2X` - the model number and firmware revision, e.g. `487A03`.

        The manual notes two trailing blanks, which are stripped.
        """
        return self._status(2)

    def _confirm_model(self):
        """Refuse to configure anything that is not a 487.

        Chosen by hand, so nothing else has checked. A 486 answers
        `U2X` too, and is the same picoammeter without the source -
        every V and O command would be an illegal command to it.
        """
        reply = self.identify()
        if not reply.startswith("487"):
            raise RuntimeError(
                f"{self.DISPLAY_NAME} was chosen, but the instrument at "
                f"this address answers {reply!r} to U2X. Nothing has been "
                f"configured. Check the address, or choose the right "
                f"driver.")
        return reply

    def reset(self):
        """Put the instrument in a known state, every setting stated.

        Clear first, which on this instrument means the *saved* defaults
        and the source in standby. Then each setting this suite depends
        on, one command at a time. Then the error word, so a command the
        instrument refused is a failure here rather than a setting
        silently still in force at the first run.
        """
        # Best effort. Its return value says nothing either way (see
        # Transport.clear), and every setting is sent below regardless.
        self.transport.clear()
        self._confirm_model()

        # Flags latched before this reset - a clear does not empty the
        # error word. Seen 2026-10-14: a reading lost in one session left
        # its trigger overrun set, and the next session's reset reported
        # it as its own. Read and set aside, so the check below grades
        # only what this reset's own commands did. Safe to ask here: the
        # saved defaults do not trigger on talk unless someone saved T0
        # or T1, and then the worst case is that same harmless overrun.
        self._flags(1)
        self._flags(9)

        self._send("O0")       # source in standby - before anything else
        self._send("V0,0,0")   # 0 V, 50 V range, 25 uA limit
        self._level, self._range = 0.0, SOURCE_RANGES[0]
        self._limit_option = CURRENT_LIMITS[25e-6]
        self._settle_s = 0.0
        for command in (
                "C0",   # zero check OFF - the factory default is on
                "F0",   # V/I ohms off: report amps, not ohms
                "Z0",   # relative off
                "B0",   # readings from the A/D, not the data store
                "G0",   # ASCII readings with prefix
                "K0",   # EOI on, bus hold-off on X
                "Y0",   # CR LF terminator
                "P0",   # digital and analog filters off
                "S1",   # line-cycle integration
                "R0",   # autorange
                "W0",   # no trigger delay, ever - see set_source_delay
                "M0",   # no SRQ
                IDLE_TRIGGER):  # see the module docstring - last
            self._send(command)

        # Both words latch and clear when read, so reading them here also
        # means the first run starts from clean flags.
        word, flags = self._flags(1)
        self._flags(9)
        if "1" in flags:
            raise RuntimeError(
                f"{self.DISPLAY_NAME} reported an error during reset: "
                f"U1 = {word}. {self._describe_u1(flags)}")
        self._confirm_reset_took()

    #: What `reset()` must leave in the U0 word, and why it matters.
    #: Read back rather than assumed: a saved default that survived the
    #: commands above would be invisible in every reading.
    _RESET_STATE = {
        "C": ("0", "zero check is on, so every reading would be zero"),
        "F": ("0", "V/I ohms is on, so readings would be ohms"),
        "O": ("0", "the source is in operate"),
        "T": (IDLE_TRIGGER[1:], "the trigger mode is not the idle one, "
                                "so a status query may start a conversion "
                                "and lose the next reading"),
        "G": ("0", "readings are not in the format this driver parses"),
        "B": ("0", "readings come from the data store, not the A/D"),
    }

    def _confirm_reset_took(self):
        fields = self._machine_status()
        wrong = [why for letter, (want, why) in self._RESET_STATE.items()
                 if fields.get(letter) != want]
        if fields.get("Z", "0")[:1] != "0":
            wrong.append("current rel is on, so readings are offset by a "
                         "stored baseline")
        if wrong:
            raise RuntimeError(
                f"{self.DISPLAY_NAME} did not take its reset: "
                + "; ".join(wrong) + ". The instrument should not be used "
                "until this is understood.")

    # ---- source configuration ----------------------------------------
    def set_source_function(self, mode):
        """Voltage, always. There is no command, because there is no
        choice; anything else is refused by name."""
        if mode not in self.SOURCE_FUNCTIONS:
            raise ValueError(
                f"{self.DISPLAY_NAME} can only source voltage, got "
                f"{mode!r}. It has no current source.")

    def set_current_level(self, amps):
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no current source.")

    def set_voltage_level(self, volts):
        """Program the level, refusing one the instrument would ignore.

        A level beyond the selected range is dropped by the instrument
        with nothing but a CONFLICT bit to show for it, and the sample
        stays at the previous level. So it is refused here, loudly,
        before it reaches the wire.
        """
        volts = float(volts)
        full_scale, option = self._range
        if abs(volts) > full_scale:
            raise RangeError(
                f"{volts:g} V is beyond the {full_scale:g} V source range "
                f"in force. The 487 would ignore it and stay at "
                f"{self._level:g} V; the run's ranging plan should have "
                f"selected the 505 V range for it.")
        self._send(f"V{volts:.6g},{option},{self._limit_option}")
        self._level = volts

    def set_current_limit(self, amps):
        """One of two values, and nothing between them."""
        option = self._limit_option_for(amps)
        self._send(f"V{self._level:.6g},{self._range[1]},{option}")
        self._limit_option = option

    def set_voltage_limit(self, volts):
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no current source, so there is "
            f"never a voltage limit to set.")

    @classmethod
    def _limit_option_for(cls, amps):
        for value, option in CURRENT_LIMITS.items():
            if abs(float(amps) - value) <= value * 1e-6:
                return option
        raise LimitError(
            f"The {cls.DISPLAY_NAME} current limit is 25 uA or 2.5 mA and "
            f"nothing else; {float(amps):g} A is neither. Rounding it "
            f"either way would be wrong - up protects the sample less "
            f"than asked, down clips the measurement.")

    def validate_source_point(self, current=None, voltage=None,
                              sourcing=None):
        """The table of corners, plus the menu.

        A compliance off the menu is refused here, at Run, rather than
        in the worker after the form has been accepted.
        """
        super().validate_source_point(current=current, voltage=voltage,
                                      sourcing=sourcing)
        if sourcing == "current":
            raise LimitError(f"{self.DISPLAY_NAME} cannot source current.")
        if current is not None and sourcing == "voltage":
            self._limit_option_for(current)

    # ---- ranging -----------------------------------------------------
    def _apply_source_voltage_range(self, volts):
        """The smallest range that holds the span, at 0 V.

        `AUTO` takes the 505 V range: there is no source autorange, and
        the widest never refuses a level - the U2722A's reasoning.

        The level goes to 0 V with the range. A range change is
        configuration, and configuration happens with the output in
        standby (house rule 12); a level carried over from the previous
        range could be beyond the new one, which would void the whole
        command.
        """
        if volts is AUTO or volts is NOT_SOURCED:
            chosen = SOURCE_RANGES[-1]
        else:
            fitting = [r for r in SOURCE_RANGES if r[0] >= float(volts)]
            if not fitting:
                raise RangeError(
                    f"{float(volts):g} V is beyond the "
                    f"{self.DISPLAY_NAME}'s {SOURCE_RANGES[-1][0]:g} V "
                    f"source range.")
            chosen = fitting[0]
        self._send(f"V0,{chosen[1]},{self._limit_option}")
        self._level, self._range = 0.0, chosen

    def _apply_source_current_range(self, amps):
        if amps is AUTO or amps is NOT_SOURCED:
            return
        raise RangeError(f"{self.DISPLAY_NAME} has no current source.")

    def _apply_measure_current_range(self, amps):
        """Autorange, or the smallest range that holds `amps`.

        Above the 2 mA range - only a 2.5 mA compliance gets there - it
        takes the 2 mA range: the widest there is, so nothing is
        clamped, and an overrange reads as no reading rather than as a
        number.
        """
        if amps is AUTO:
            self._send("R0")
            return
        fitting = [r for r in MEASURE_RANGES if r[0] >= float(amps)]
        self._send(f"R{(fitting[0] if fitting else MEASURE_RANGES[-1])[1]}")

    def _apply_measure_voltage_range(self, volts):
        if volts is AUTO:
            # What `for_sourcing()` puts on the sourced quantity's own
            # measurement axis. Nothing measures a voltage here, so
            # there is nothing to range.
            return
        raise RangeError(f"{self.DISPLAY_NAME} does not measure voltage.")

    # ---- reading state back ------------------------------------------
    # All three come from the U0 word. Not trusted: the layout is the
    # manual's Figure 4-6, never compared at the bench against settings
    # known to be in force - and that figure shows the factory limit as
    # `V01` (2.5 mA, which it misprints "25mA") where Table 4-3 says
    # 25 uA, so the manual does not agree with itself about this field.
    def read_current_limit(self):
        """`V` field, second digit: 0 is 25 uA, 1 is 2.5 mA."""
        option = int(self._machine_status()["V"][1:2])
        return {o: a for a, o in CURRENT_LIMITS.items()}[option]

    def read_source_voltage_range(self):
        """`V` field, first digit: 0 is the 50 V range, 1 the 500 V."""
        option = int(self._machine_status()["V"][:1])
        return {o: v for v, o in SOURCE_RANGES}[option]

    def read_measure_current_range(self):
        """`R` field, second digit: the range now in use, 1 to 7.

        Under autorange this is wherever autorange has gone, which is
        still the honest answer to "what is it on".
        """
        option = int(self._machine_status()["R"][1:2])
        return {o: a for a, o in MEASURE_RANGES}[option]

    def compliance_tripped(self):
        """Has the source been in current limit since this was last asked?

        `U9X`, whose first flag latches "now or previously in current
        limit" and clears on read. Asked once per sample, that is the
        honest answer to "did it clamp during this interval".

        The second flag is the interlock having opened. That puts the
        source in standby with the run still going, so it is raised
        rather than reported as a trip: every reading after it is of a
        sample with no voltage on it.
        """
        try:
            word, flags = self._flags(9)
        except TransportDesynchronised:
            raise
        except Exception:
            return None
        if len(flags) >= 2 and flags[1] == "1":
            raise RuntimeError(
                f"{self.DISPLAY_NAME}: the interlock opened (U9 = {word}), "
                f"so the source dropped to standby. Readings since then "
                f"were taken with no voltage on the sample.")
        return flags[:1] == "1"

    @classmethod
    def interlock_note(cls):
        """Not a voltage threshold: the interlock gates the whole source.

        It is enabled by plugging in the interlock cable, and while it is
        open the source cannot leave standby, at any level.
        """
        return ("with the interlock cable connected, the source will not "
                "leave standby while the fixture lid is open - at any "
                "voltage. If a run refuses to energise, check the lid "
                "before suspecting the driver.")

    # ---- sensing and timing ------------------------------------------
    def set_remote_sense(self, on=True):
        """Refused for 4-wire: there are no sense terminals."""
        if on:
            raise NotImplementedError(
                f"{self.DISPLAY_NAME} has no sense terminals. Sensing is "
                f"{self.FIXED_SENSE}.")

    def set_source_delay(self, seconds):
        """The settle between a source step and its reading - kept here.

        The instrument has its own, `W`, a delay from each trigger to the
        start of integration, and this used to send it. It loses
        readings. Measured 2026-10-14 with `tools/bench_487_trigger.py`:
        with `W` at 10 ms, 4 readings of 432 never came - the talk went
        unanswered, with no flag set in any status word - and with `W` at
        0, none of 1152. Every reading the checkup had lost was taken
        with the 10 ms its own tier 2 leaves in force.

        So `W` stays at the 0 `reset()` sets, and the settle is a wait
        here, before each reading's `T1X`. It means what it meant: time
        between the source step and the reading.
        """
        self._settle_s = max(0.0, min(float(seconds), 999.999))

    @classmethod
    def clamp_nplc(cls, nplc):
        """Snap onto one of the two integration periods.

        Clamping into the declared window would let 0.5 through as 0.5
        and record it, while the instrument integrated for one of two
        fixed periods. Snapping makes the value the run records the
        value the instrument used; `apply_nplc()` logs the difference.
        """
        return FAST_NPLC if float(nplc) < (FAST_NPLC * LINE_NPLC) ** 0.5 \
            else LINE_NPLC

    def set_nplc(self, nplc):
        self._send("S0" if self.clamp_nplc(nplc) == FAST_NPLC else "S1")

    # ---- output ------------------------------------------------------
    def output_on(self):
        """Operate, then make sure it took.

        With the interlock cable fitted and the lid open the 487 refuses
        to leave standby, and says so only in its status words. Without
        this check the run would carry on measuring a sample with no
        voltage on it.
        """
        self._send("O1")
        word, flags = self._flags(9)
        if len(flags) >= 2 and flags[1] == "1":
            self._send("O0")
            raise RuntimeError(
                f"{self.DISPLAY_NAME} stayed in standby: the interlock is "
                f"open (U9 = {word}). Close the fixture lid.")

    def output_off(self):
        """0 V, hold, then standby.

        Writes only, so it still works on a link that has stopped
        answering (see Transport.write). The order is the point: opening
        the relay with the sample charged leaves it floating at that
        voltage, and dielectric absorption can bring it back up after.
        """
        self._send(f"V0,{self._range[1]},{self._limit_option}")
        self._level = 0.0
        time.sleep(DISCHARGE_HOLD_S)
        self._send("O0")

    # ---- measurement -------------------------------------------------
    def measure(self, timeout_s=3.0):
        """One reading, triggered by asking for it. Returns (None, amps).

        No voltage, ever: nothing on this instrument measures one, and
        the programmed level is not a measurement. The sourced level is
        what an experiment records for the voltage axis.

        One-shot on talk for this talk only, and back to idle whatever
        happens - a write, so it still goes out on a link whose read
        just failed.
        """
        if self._settle_s:
            time.sleep(self._settle_s)
        self._send(READ_TRIGGER)
        try:
            reply = self.transport.read(timeout_s=timeout_s)
        finally:
            self._send(IDLE_TRIGGER)
        return (None, self._parse_reading(reply))

    @classmethod
    def _parse_reading(cls, reply):
        """Amps out of a `G0` reading, or None for no reading.

        An overflow is reported twice - an `O` status letter, and
        +/-9.87E37 in the number - and either is enough. A reply in any
        other shape raises: it means the instrument is not in the format
        `reset()` set, and a number pulled out of it would be a guess.
        """
        text = str(reply or "").strip()
        match = _READING.match(text)
        if not match:
            raise ValueError(
                f"{cls.DISPLAY_NAME}: unexpected reading {text!r}")
        status, function, number = match.groups()
        if function == "OHM":
            raise ValueError(
                f"{cls.DISPLAY_NAME} is reporting ohms ({text!r}); V/I "
                f"ohms should be off.")
        if status == "O":
            return None
        if status == "Z":
            raise ValueError(
                f"{cls.DISPLAY_NAME} is reporting a rel'd reading "
                f"({text!r}): it is offset by a stored baseline, and rel "
                f"should be off.")
        return cls.drop_sentinel(float(number))

    # ---- errors ------------------------------------------------------
    #: The U1 flags, in order (manual Figure 4-7).
    U1_FLAGS: tuple[str, ...] = (
        "IDDC (illegal command)", "IDDCO (illegal command option)",
        "no remote", "self-test", "trigger overrun", "conflict",
        "cal locked", "zero check", "calibration", "E2PROM defaults",
        "E2PROM cal constants",
        "V-source conflict (level beyond the selected range)",
        "V-source (operate refused, interlock open)")

    @classmethod
    def _describe_u1(cls, flags):
        positions = [i for i, f in enumerate(flags) if f == "1"]
        if cls.U1_FLAGS and len(cls.U1_FLAGS) == len(flags):
            return "Set: " + ", ".join(cls.U1_FLAGS[i] for i in positions)
        return ("Set at position(s) "
                + ", ".join(str(i + 1) for i in positions)
                + " of the word - see the U1 table in the manual.")

    def read_error(self):
        """The `U1` error word, which latches and clears when read.

        Not a queue: one read returns every flag set since the last, and
        the next read returns none. So the code is the position of the
        first set flag and the message lists them all; a second call
        then returns (0, ""), which is what "the queue is empty" means
        to every caller.

        A failure to ask reports 0, per the contract.
        """
        try:
            word, flags = self._flags(1)
        except TransportDesynchronised:
            raise
        except ValueError as exc:
            return (0, str(exc))
        except Exception:
            return (0, "")
        if "1" not in flags:
            return (0, "")
        return (flags.index("1") + 1,
                f"U1 = {word}. {self._describe_u1(flags)}")
