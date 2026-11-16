"""
Keithley 236 Source Measure Unit.

A full SMU from the late 1980s: it sources a voltage (1.1, 11 or 110 V
ranges) and measures current from 1 nA to 100 mA full scale, or sources
a current on those ranges and measures voltage. Triax outputs with
guard and remote sense, an interlock, and a source-delay-measure cycle
behind every reading.

Written from the Model 236/237/238 Operator's Manual, 236-900-01 Rev. E,
section 3 (the IEEE-488 reference), with no original script behind it.
The parts this driver depends on are transcribed in
`docs/reference/manuals/236-commands.md`.

It speaks the same command style as the 487
-------------------------------------------
Keithley's device-dependent commands: a capital letter and its options,
executed by `X`. No `*IDN?`, no `*RST`, no error queue. So, as with the
487:

* **Identity is `U0X`**, which answers the model and firmware
  (`236A01`). The driver is chosen by hand, and `reset()` refuses
  anything else - a 237 reaches 1100 V and a 238 sources 1 A, and both
  answer every command here.
* **One command per `X`.** One illegal command voids the whole string,
  and the instrument executes a string in its own fixed order rather
  than the order sent (manual Table 3-5), so a string of several would
  not even mean what it says.
* **Errors and warnings are latched words**, `U1` and `U9`, each clearing
  when read.

What is different, and why the 487's driver was not reused: the status
words are numbered differently (`U0` is identity here, `U3` the machine
status, `U4` the measurement parameters, `U5` the compliance), the
reading format is different, and so is the trigger model. The two share
habits, not code - see `docs/open/technical-debt.md`.

It measures only the quantity it is not sourcing
------------------------------------------------
Sourcing voltage it measures current, and sourcing current it measures
voltage. Never both. Its output string can carry a "source value", but
the manual is explicit that this is the programmed value, not a
measurement. So `measure()` returns None for the sourced quantity, as
the 487 does for its voltage: the IV sweep already records the level it
commanded where no measurement of it exists. `MEASURES_SOURCED_QUANTITY
= False` says so to the checkup.

That is also why the four-contact tabs refuse it at Connect (decided
2026-11-16): Van der Pauw, Hall and the contact check divide a measured
voltage by a measured current. The caveat is `ROLE_CAVEATS` below; the
IV sweep and Fixed Source accept it.

One reading per trigger, and status queries never trigger
---------------------------------------------------------
The instrument idles in trigger origin 4 - "immediate only", the `H0X`
command or the front-panel key - with an input trigger starting the
source phase of one source-delay-measure cycle (`T4,1,0,0`). `measure()`
sends `H0X` and reads: the reading that comes back is the cycle that
trigger started, after the level was already on the sample. Addressing
the instrument to talk triggers nothing in this mode, so a status query
can never steal a conversion - the race that cost the 487 its readings
(see `keithley_487.py`) cannot happen here by construction.

Every trigger this driver sends is followed by the read of its reading,
so no trigger ever arrives while a cycle is still running (a TRIG
OVERRUN, which the instrument ignores) and no unread reading is ever
left for a later read to collect by mistake.

A level, or a compliance, may need a trigger to take effect
-----------------------------------------------------------
The manual says that "in dc operation, a change [of compliance] must be
triggered to go into effect" (paragraph 3.6.10, note 3), and that the
unit "can be reprogrammed without having to retrigger it" only in
continuous triggering (3.6.18, note 11) - which this driver does not
use. It does not say plainly whether a new bias level goes out on `X`
or on the next trigger. Assuming the first would mean an experiment's
settle could be spent at the *old* level, with the new one applied only
when the reading is triggered.

So while the output is in operate, every level and compliance change is
followed by a trigger and the read of that cycle, which puts it on the
sample whichever way the instrument works. That costs one extra cycle
per point (`LEVEL_NEEDS_TRIGGER`); if the bench shows a level goes out
on `X`, the level half can go. In standby nothing is triggered:
`output_on()` triggers once after operate, and that cycle applies
whatever was programmed in the meantime.

A level beyond the range is clamped, not refused
------------------------------------------------
Worse than the 487, which ignores such a level: the 236 sets "the
maximum (signed) value for the specified range" and raises a VALUE OUT
OF RANGE warning in `U9` (paragraph 3.6.19). Asking for 5 V on the
1.1 V range puts 1.1 V on the sample. The same holds for a compliance
beyond its measurement range. So the driver refuses both before they
reach the wire, and checks `U9` after every compliance it sets.

And a compliance below 100 counts of a fixed range is raised to 100
counts in silence (3.6.10, note 9: `L0E-3,9X` gives 1 mA) - a
protection weaker than the one asked for. Refused too.

Each source remembers its own setup
-----------------------------------
Integration time, filter, sense, compliance, ranges and level are kept
separately for the voltage source and the current source (paragraph
3.6.5, note 3). Changing source brings back whatever the other one last
had. So `reset()` configures both, and `set_source_function()` sends
this driver's settings again after every change.

Off is 0 V, then standby - which is not disconnected
----------------------------------------------------
In standby the 236 holds 0 V on the 1.1 V range rather than opening the
output (paragraph 2.14), so `OUTPUT_OFF_DISCONNECTS = False`. And the
manual's caution under the B command: after standby, operate brings the
*old* bias back for 10 ms before the new one. So `output_off()` sets
0 V before standby, as the manual asks.

What the first bench session settled, and what it did not
---------------------------------------------------------
On 2026-11-16 (firmware A10) every status word and reading matched the
manual's figures, including the comma after `L` in `U4`, and a reading
at compliance came back `O` on both items. Still open, in the
instrument note: whether a level goes out on `X` (which would retire
`LEVEL_NEEDS_TRIGGER`), what an overflow looks like, and whether the
readbacks can be trusted.
"""
import re

from smuniversal_lab_suite.core.limits import LimitError, SMULimits
from smuniversal_lab_suite.core.ranges import AUTO, NOT_SOURCED, RangeError
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

from .base_smu import BaseSMU

#: Voltage ranges: (full scale in volts, range option). Option 0 is auto
#: on every range field of the B and L commands.
VOLTAGE_RANGES = ((1.1, 1), (11.0, 2), (110.0, 3))

#: Current ranges: (full scale in amps, range option), 1 nA to 100 mA.
#: Full scale is the nominal decade on this model (`±1.0000 nA` ...
#: `±100.00 mA` in the specifications).
CURRENT_RANGES = ((1e-9, 1), (1e-8, 2), (1e-7, 3), (1e-6, 4), (1e-5, 5),
                  (1e-4, 6), (1e-3, 7), (1e-2, 8), (1e-1, 9))

AUTO_RANGE = 0

#: The integration times, as NPLC at the lab's 50 Hz mains, and the S
#: option for each. S0 is 416 us, S1 4 ms, S3 20 ms - one 50 Hz cycle.
#: S2 (16.67 ms, the 60 Hz line cycle) is left out: at 50 Hz it rejects
#: nothing, and is slower than S1 for no gain.
MAINS_HZ = 50.0
NPLC_OPTIONS = ((0.416e-3 * MAINS_HZ, 0), (4e-3 * MAINS_HZ, 1),
                (20e-3 * MAINS_HZ, 3))

#: The trigger configuration the instrument idles in: origin 4
#: (immediate - H0X - only), a trigger starts the source phase, no output
#: triggers, no sweep-end trigger. See the module docstring.
TRIGGER_CONFIG = "T4,1,0,0"

#: The output format: source and measure items (1 + 4), ASCII with
#: prefix and no suffix, one line of dc data per talk.
OUTPUT_FORMAT = "G5,1,0"

#: Compliances `reset()` leaves on each source until an experiment sets
#: its own: small, on autorange. 100 uA when sourcing voltage, 1 V when
#: sourcing current.
RESET_COMPLIANCE = {"voltage": 1e-4, "current": 1.0}

#: The largest dc delay the B command takes, in milliseconds.
MAX_DELAY_MS = 65000

#: One item of a reading (manual Figure 3-3), prefix with no suffix:
#: a status letter, S or M for source or measure, DC (or SW/PL in a
#: sweep), V or I, then the number - `NSDCV+1.0000E+00`.
_ITEM = re.compile(
    r"([NOZ])([SM])(DC|SW|PL)([VI])([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)")

#: A U1 or U9 word: three letters, then a run of 0/1 flags.
_FLAG_WORD = re.compile(r"^\s*(ERS|WRS)([01]+)\s*$")

#: One field of a U3 or U4 word: a letter and its option(s). The unit
#: puts a comma after U4's L (`IMPL,00F0,0...`, seen 2026-11-16), which
#: `_fields()` strips.
_FIELD = re.compile(r"([A-Z])([\d,]+)")

#: A U5 reply: ICP or VCP, then the compliance value - `ICP0100.00E-06`
#: on the unit, a zero-padded mantissa.
_U5 = re.compile(r"^\s*([IV])CP\s*([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s*$")

_MODE_OPTION = {"voltage": 0, "current": 1}


def _number(value):
    """A level or limit as the instrument takes it.

    Five significant digits, which is all it keeps ("entered values are
    truncated to five significant digits", manual 3.6), in exponent
    form - `1.0000E-06`.
    """
    return f"{float(value):.4E}"


class Keithley236(BaseSMU):
    # No *IDN?, so nothing for the registry to match. Connected by
    # choosing the driver; `identify()` and `reset()` confirm the model.
    MODEL_IDS: list[str] = []
    DISPLAY_NAME = "Keithley 236"

    LIMITS = SMULimits(
        max_voltage=110.0,
        max_current=0.1,
        voltage_ranges=[fs for fs, _ in VOLTAGE_RANGES],
        current_ranges=[fs for fs, _ in CURRENT_RANGES],
        # A plain rectangle: sourcing 110 V it measures and limits up to
        # 100 mA, and the other way round (manual Figure 1-8A).
        power_envelope=[],
    )

    # ---- what kind of instrument this is ----
    # Both, but never at once: see MEASURES_SOURCED_QUANTITY.
    MEASURE_FUNCTIONS = ("voltage", "current")

    #: False: `measure()` returns None for whichever quantity is being
    #: sourced. Read by the checkup with a default of True, so it lives
    #: on this driver alone and no other instrument's checkup goes stale.
    MEASURES_SOURCED_QUANTITY = False

    #: The four-contact tabs need a measured current, and this instrument
    #: never measures the current it sources. The IV sweep and Fixed
    #: Source accept this caveat; nothing else does.
    ROLE_CAVEATS = {
        "sourced_quantity_not_measured": (
            "it measures only the quantity it is not sourcing - pushing a "
            "current, it reports the current it was told to push, not one "
            "it measured. Van der Pauw, Hall and the contact check divide "
            "a measured voltage by a measured current, so they do not "
            "take it yet. Use it for IV sweeps and fixed sourcing."),
    }

    # One L command sets the compliance and the measurement range
    # together; with a fixed range "compliance range and measurement
    # range are the same" (3.6.10, note 1).
    COMPLIANCE_SETS_MEASURE_RANGE = True

    # The B command's range field and the L command's are separate knobs.
    INDEPENDENT_SOURCE_RANGE = True
    HAS_MEASURE_RANGE = True

    # Local or remote sense, O0 / O1.
    REMOTE_SENSE_CONTROL = True

    # Three integration times; `clamp_nplc()` snaps onto them.
    NPLC_RANGE = (NPLC_OPTIONS[0][0], NPLC_OPTIONS[-1][0])

    # Standby holds 0 V on the 1.1 V range; nothing opens.
    HIGH_Z_OFF = False
    OUTPUT_OFF_DISCONNECTS = False

    # Up to 110 V: the high-voltage warning applies above 50 V, as on
    # every SMU here that can reach it.
    HAZARDOUS_ABOVE_V = 50.0

    #: True: in operate, a level change is followed by a trigger and the
    #: read of its cycle, so the level is on the sample when the setter
    #: returns. Whether the 236 needs it is a bench item - see the
    #: module docstring.
    LEVEL_NEEDS_TRIGGER = True

    def __init__(self, transport):
        super().__init__(transport)
        self._mode = "voltage"
        self._operate = False
        self._level = 0.0
        # Per source, as the instrument keeps them (3.6.5, note 3).
        self._source_range = {"voltage": AUTO_RANGE, "current": AUTO_RANGE}
        self._measure_range = {"voltage": AUTO_RANGE, "current": AUTO_RANGE}
        self._compliance = dict(RESET_COMPLIANCE)
        # This driver's settings, sent to whichever source is active.
        self._nplc_option = 3
        self._sense = 0
        self._delay_ms = 0
        # Whether a reading since compliance_tripped() was last asked
        # came back in compliance.
        self._clamped = False

    # ---- the wire ----------------------------------------------------
    def _send(self, command):
        """One command, executed on its own. See the module docstring."""
        self.transport.write(f"{command}X")

    def _status(self, which, timeout_s=3.0):
        """Ask for a U status word and return it, stripped."""
        return str(self.transport.query(f"U{which}X",
                                        timeout_s=timeout_s)).strip()

    def _fields(self, which, identifiers):
        """A U3 or U4 word as (identifier, {letter: option}).

        Raises ValueError on a reply that is not one: a word this driver
        cannot read is not evidence that every setting is as wanted.
        """
        word = self._status(which).replace(" ", "")
        ident = word[:3]
        if ident not in identifiers:
            raise ValueError(f"unexpected U{which} reply {word!r}")
        fields = {letter: option.strip(",")
                  for letter, option in _FIELD.findall(word[3:])}
        return ident, fields

    def _flags(self, which):
        """The 0/1 flags of a U1 or U9 word, after its identifier."""
        word = self._status(which)
        match = _FLAG_WORD.match(word.replace(" ", ""))
        if not match:
            raise ValueError(f"unexpected U{which} reply {word!r}")
        return word, match.group(2)

    def _cycle(self, timeout_s=3.0):
        """Trigger one source-delay-measure cycle and read its reading.

        The one place a trigger is sent. Reading straight after it is
        what keeps every later trigger clear of a running cycle and
        every later read clear of a stale reading.
        """
        self._send("H0")
        # The cycle includes the dc delay and up to 360 ms of default
        # delay on the 1 nA range (manual Table 2-4), before integrating.
        return self.transport.read(
            timeout_s=max(float(timeout_s), self._delay_ms / 1000.0 + 2.0))

    def _apply_now(self):
        """Put what was just programmed into effect - in operate only.

        In standby nothing is triggered; `output_on()` triggers once
        after operate, and that cycle applies all of it.
        """
        if self._operate:
            self._cycle()

    # ---- identification ----------------------------------------------
    def identify(self):
        """`U0X` - the model number and firmware revision, e.g. `236A01`.

        Sent with two trailing blanks (manual 3.6.19), stripped here.
        """
        return self._status(0)

    def _confirm_model(self):
        """Refuse to configure anything that is not a 236.

        Chosen by hand, so nothing else has checked. A 237 and a 238
        answer every command this driver sends, with ranges this
        driver's limits do not describe: up to 1100 V, or 1 A.
        """
        reply = self.identify()
        if not reply.startswith("236"):
            raise RuntimeError(
                f"{self.DISPLAY_NAME} was chosen, but the instrument at "
                f"this address answers {reply!r} to U0X. Nothing has been "
                f"configured. Check the address, or choose the right "
                f"driver.")
        return reply

    def reset(self):
        """Put the instrument in a known state, every setting stated.

        A device clear first - power-up defaults, standby - then each
        global setting, then each source's own, one command at a time,
        and finally the error and warning words and a read-back of the
        machine status and measurement parameters, so a setting that did
        not take is a failure here rather than at the first run.
        """
        # Best effort. Its return value says nothing either way (see
        # Transport.clear), and every setting is sent below regardless.
        self.transport.clear()
        self._confirm_model()

        # Flags latched before this reset, set aside so the check below
        # grades only what this reset did. The manual says a clear
        # empties both words; the 487's bench found its own did not.
        self._flags(1)
        self._flags(9)

        self._send("N0")              # standby, before anything else
        self._operate = False
        for command in (
                "K0",             # EOI on, bus hold-off on X
                "Y0",             # CR LF terminator
                "M0,0",           # no SRQ
                OUTPUT_FORMAT,    # source + measure, prefix, no suffix
                "R0",             # triggers off while the origin changes
                TRIGGER_CONFIG,   # see the module docstring
                "R1"):            # and back on
            self._send(command)

        self._nplc_option, self._sense, self._delay_ms = 3, 0, 0
        self._compliance = dict(RESET_COMPLIANCE)
        self._source_range = {"voltage": AUTO_RANGE, "current": AUTO_RANGE}
        self._measure_range = {"voltage": AUTO_RANGE, "current": AUTO_RANGE}
        # Current source first, so the voltage source - the one an
        # experiment is likeliest to want - is the one left active.
        for mode in ("current", "voltage"):
            self._send(f"F{_MODE_OPTION[mode]},0")
            self._mode = mode
            self._send("Z0")      # suppression off
            self._send("P0")      # filter off
            self._send("W1")      # default (settling) delay on - factory
            self._configure_source()

        word, flags = self._flags(1)
        if "1" in flags:
            raise RuntimeError(
                f"{self.DISPLAY_NAME} reported an error during reset: "
                f"U1 = {word}. {self._describe(flags, self.U1_FLAGS)}")
        word, flags = self._flags(9)
        serious = [i for i, f in enumerate(flags)
                   if f == "1" and i not in self.U9_HARMLESS]
        if serious:
            raise RuntimeError(
                f"{self.DISPLAY_NAME} raised a warning during reset: "
                f"U9 = {word}. {self._describe(flags, self.U9_FLAGS)}")
        self._confirm_reset_took()

    def _configure_source(self):
        """The active source's own settings, as this driver holds them.

        Each source remembers these separately, so they are sent again
        whenever the source changes. The level goes to 0 V or 0 A.
        """
        self._send(f"O{self._sense}")
        self._send(f"S{self._nplc_option}")
        self._level = 0.0
        self._send(f"B0,{self._source_range[self._mode]},{self._delay_ms}")
        self._send_compliance(self._mode)

    def _send_compliance(self, sourced):
        """The L command for the active source, with its compliance held
        inside its measurement range.

        Outside it the instrument would hold another value and latch
        VALUE OUT OF RANGE - which the next `set_*_limit()` would then
        read as its own. Ranging and a change of source both come before
        the experiment sets its compliance, so they keep what is stored
        within the range rather than send it as it is.
        """
        measured = "current" if sourced == "voltage" else "voltage"
        option = self._measure_range[sourced]
        full_scale = self._range_full_scale(measured, option)
        compliance = self._compliance[sourced]
        if full_scale is not None:
            compliance = min(max(compliance, full_scale / 100.0), full_scale)
        self._compliance[sourced] = compliance
        self._send(f"L{_number(compliance)},{option}")

    #: What `reset()` must leave in the U3 machine status word.
    _RESET_STATE = {
        "G": ("5,1,0", "readings are not in the format this driver parses"),
        "N": ("0", "the output is in operate"),
        "R": ("1", "triggers are disabled, so a reading would never come"),
        "T": ("4,1,0,0", "the trigger configuration is not the idle one, "
                         "so a status query may start a conversion"),
    }

    def _confirm_reset_took(self):
        _, machine = self._fields(3, ("MST",))
        wrong = []
        for letter, (want, why) in self._RESET_STATE.items():
            got = machine.get(letter, "")
            # G's items are two digits in the word (`G05,1,0`).
            if got.lstrip("0") != want.lstrip("0") and got != want:
                wrong.append(why)
        ident, measure = self._fields(4, ("IMP", "VMP"))
        if ident != "IMP":
            wrong.append("the current source is active, not the voltage "
                         "source")
        if measure.get("Z", "0") != "0":
            wrong.append("suppression is on, so readings are offset by a "
                         "stored value")
        if measure.get("S") != str(self._nplc_option):
            wrong.append("the integration time is not the one sent")
        if wrong:
            raise RuntimeError(
                f"{self.DISPLAY_NAME} did not take its reset: "
                + "; ".join(wrong) + ". The instrument should not be used "
                "until this is understood.")

    # ---- source configuration ----------------------------------------
    def set_source_function(self, mode):
        """Change source - which also changes what is measured.

        The instrument goes to standby when the source changes (3.6.12,
        note 1), and brings back the other source's remembered setup, so
        this driver's settings are sent again straight after.
        """
        if mode not in _MODE_OPTION:
            raise ValueError(f"Unknown source function: {mode!r}")
        self._send(f"F{_MODE_OPTION[mode]},0")
        if mode != self._mode:
            self._operate = False
        self._mode = mode
        self._configure_source()

    def _range_full_scale(self, quantity, option):
        ladder = VOLTAGE_RANGES if quantity == "voltage" else CURRENT_RANGES
        return {o: fs for fs, o in ladder}.get(option)

    def _set_level(self, quantity, value, unit):
        if self._mode != quantity:
            raise ValueError(
                f"{self.DISPLAY_NAME} is sourcing {self._mode}; set the "
                f"source function to {quantity} before a {quantity} level.")
        value = float(value)
        self.guard_source_level(quantity, value, unit)
        option = self._source_range[quantity]
        full_scale = self._range_full_scale(quantity, option)
        if full_scale is not None and abs(value) > full_scale:
            raise RangeError(
                f"{value:g} {unit} is beyond the {full_scale:g} {unit} "
                f"source range in force. The 236 would put the range's "
                f"full scale on the sample instead, and say so only in a "
                f"warning word; the run's ranging plan should have chosen "
                f"a wider range.")
        self._send(f"B{_number(value)},{option},{self._delay_ms}")
        self._level = value
        if self.LEVEL_NEEDS_TRIGGER:
            self._apply_now()

    def set_voltage_level(self, volts):
        self._set_level("voltage", volts, "V")

    def set_current_level(self, amps):
        self._set_level("current", amps, "A")

    def _set_limit(self, quantity, value, unit):
        """The compliance on the quantity being measured.

        Refused where the instrument would change it in silence - beyond
        the fixed measurement range (it would hold the range's full
        scale), or below 100 counts of it (it would hold 100 counts).
        """
        sourced = "voltage" if quantity == "current" else "current"
        if self._mode != sourced:
            raise ValueError(
                f"{self.DISPLAY_NAME} is sourcing {self._mode}, so its "
                f"compliance is a {'current' if self._mode == 'voltage' else 'voltage'} "
                f"limit, not a {quantity} limit.")
        value = abs(float(value))
        if value <= 0:
            raise LimitError(f"A {quantity} compliance of 0 {unit} "
                             f"protects nothing; give a positive value.")
        option = self._measure_range[sourced]
        full_scale = self._range_full_scale(quantity, option)
        if full_scale is not None:
            if value > full_scale:
                raise LimitError(
                    f"A {value:g} {unit} compliance is beyond the "
                    f"{full_scale:g} {unit} measurement range in force; "
                    f"the 236 would hold {full_scale:g} {unit} instead.")
            if value < full_scale / 100.0:
                raise LimitError(
                    f"A {value:g} {unit} compliance is below 100 counts of "
                    f"the {full_scale:g} {unit} measurement range in force; "
                    f"the 236 would hold {full_scale / 100.0:g} {unit} "
                    f"instead - less protection than asked for.")
        self._send(f"L{_number(value)},{option}")
        self._compliance[sourced] = value
        self._check_value_in_range(f"L{_number(value)},{option}")
        self._apply_now()

    def set_current_limit(self, amps):
        self._set_limit("current", amps, "A")

    def set_voltage_limit(self, volts):
        self._set_limit("voltage", volts, "V")

    def _check_value_in_range(self, command):
        """Raise if the instrument changed a value it was just sent.

        The VALUE OUT OF RANGE warning (U9, third flag) means it put the
        range's full scale in place of what was asked. The driver's own
        refusals should make this unreachable; this is the instrument's
        word for it.
        """
        word, flags = self._flags(9)
        if len(flags) > 2 and flags[2] == "1":
            raise LimitError(
                f"{self.DISPLAY_NAME} reported VALUE OUT OF RANGE after "
                f"{command}X (U9 = {word}): it is holding its range's full "
                f"scale instead of the value sent.")

    # ---- ranging -----------------------------------------------------
    @staticmethod
    def _option_for(ladder, magnitude):
        """The range option for AUTO or the smallest range holding
        `magnitude`, or None when no range does."""
        if magnitude is AUTO or magnitude is NOT_SOURCED:
            return AUTO_RANGE
        fitting = [o for fs, o in ladder if fs >= abs(float(magnitude))]
        return fitting[0] if fitting else None

    def _apply_source_range(self, quantity, value, unit):
        ladder = VOLTAGE_RANGES if quantity == "voltage" else CURRENT_RANGES
        option = self._option_for(ladder, value)
        if option is None:
            raise RangeError(
                f"{float(value):g} {unit} is beyond the {self.DISPLAY_NAME}'s "
                f"{ladder[-1][0]:g} {unit} source range.")
        self._source_range[quantity] = option
        if quantity == self._mode:
            # At 0: a range change is configuration, done with the level
            # down (house rule 12), and a level carried over could be
            # beyond the new range - which this instrument would clamp.
            self._send(f"B0,{option},{self._delay_ms}")
            self._level = 0.0

    def _apply_source_voltage_range(self, volts):
        self._apply_source_range("voltage", volts, "V")

    def _apply_source_current_range(self, amps):
        self._apply_source_range("current", amps, "A")

    def _apply_measure_range(self, quantity, value, unit):
        sourced = "voltage" if quantity == "current" else "current"
        ladder = CURRENT_RANGES if quantity == "current" else VOLTAGE_RANGES
        option = self._option_for(ladder, value)
        if option is None:
            # Wider than anything here: the widest, so nothing is clamped.
            option = ladder[-1][1]
        self._measure_range[sourced] = option
        if self._mode != sourced:
            # Nothing measures this quantity while it is being sourced:
            # the range belongs to the other source's setup, which keeps
            # it and has it sent with its compliance on the next change
            # of source. (`for_sourcing()` puts AUTO here.)
            return
        # The compliance rides on the same command; the experiment sets
        # its own next.
        self._send_compliance(sourced)

    def _apply_measure_current_range(self, amps):
        self._apply_measure_range("current", amps, "A")

    def _apply_measure_voltage_range(self, volts):
        self._apply_measure_range("voltage", volts, "V")

    # ---- reading state back ------------------------------------------
    # Compliance from U5, measurement range from U4's L field. Neither
    # is trusted until a bench session has compared them with values set
    # at the front panel. There is no word reporting the bias range, so
    # the source ranges are not read back.
    COMPLIANCE_READBACK_TRUSTED = False
    RANGE_READBACK_TRUSTED = False

    def _read_compliance(self, letter):
        word = self._status(5).replace(" ", "")
        match = _U5.match(word)
        if not match:
            raise ValueError(f"unexpected U5 reply {word!r}")
        if match.group(1) != letter:
            raise ValueError(
                f"U5 reports a {'current' if match.group(1) == 'I' else 'voltage'} "
                f"compliance ({word!r}); the other source is active.")
        return float(match.group(2))

    def read_current_limit(self):
        """`U5X` while sourcing voltage: `ICP` and the value in amps."""
        return self._read_compliance("I")

    def read_voltage_limit(self):
        """`U5X` while sourcing current: `VCP` and the value in volts."""
        return self._read_compliance("V")

    def _read_measure_range(self, ident, quantity):
        got, fields = self._fields(4, ("IMP", "VMP"))
        if got != ident:
            raise ValueError(f"U4 reports {got}; the other source is active.")
        option = int(fields.get("L", ""))
        if option == AUTO_RANGE:
            raise ValueError("U4 reports autorange, not a fixed range.")
        full_scale = self._range_full_scale(quantity, option)
        if full_scale is None:
            raise ValueError(f"U4 reports range option {option}, which a "
                             f"236 does not have for {quantity}.")
        return full_scale

    def read_measure_current_range(self):
        """`U4X`, `IMP` word, `L` field: the current range option."""
        return self._read_measure_range("IMP", "current")

    def read_measure_voltage_range(self):
        """`U4X`, `VMP` word, `L` field: the voltage range option."""
        return self._read_measure_range("VMP", "voltage")

    def compliance_tripped(self):
        """Has a reading come back in compliance since this was asked?

        Read off the readings themselves, not a query: the source item's
        status letter is `O` when the source is in compliance (manual
        Figure 3-3). So this costs nothing on the wire.
        """
        tripped, self._clamped = self._clamped, False
        return tripped

    @classmethod
    def interlock_note(cls):
        """Not a voltage threshold: the interlock gates the whole output.

        With the interlock cable connected, an open interlock refuses
        operate, and opening it while in operate drops to standby.
        """
        return ("with the interlock cable connected, the output will not "
                "leave standby while the interlock is open - at any "
                "voltage. If a run refuses to energise, check the fixture "
                "lid before suspecting the driver.")

    # ---- sensing and timing ------------------------------------------
    def set_remote_sense(self, on=True):
        """`O1` remote, `O0` local - for the active source; remembered
        and sent again on a change of source.

        Connect the sense leads first: the manual warns that remote
        sense with nothing on SENSE drives OUTPUT HI and its guard to
        potentially lethal voltages.
        """
        self._sense = 1 if on else 0
        self._send(f"O{self._sense}")

    def set_source_delay(self, seconds):
        """The dc delay, in the B command's own field (0-65000 ms).

        Added to the default delay in every source-delay-measure cycle,
        so it sits between the source phase and the measurement.
        """
        self._delay_ms = int(round(max(0.0, min(float(seconds) * 1000.0,
                                                MAX_DELAY_MS))))
        self._send(f"B{_number(self._level)},"
                   f"{self._source_range[self._mode]},{self._delay_ms}")

    @classmethod
    def clamp_nplc(cls, nplc):
        """Snap onto one of the three integration times.

        Clamping into the window would let 0.5 through and record it
        while the instrument integrated for one of three fixed periods.
        Snapping (at the geometric midpoints) makes the recorded value
        the one used; `apply_nplc()` logs the difference.
        """
        value = float(nplc)
        options = [n for n, _ in NPLC_OPTIONS]
        for low, high in zip(options, options[1:]):
            if value < (low * high) ** 0.5:
                return low
        return options[-1]

    def set_nplc(self, nplc):
        snapped = self.clamp_nplc(nplc)
        self._nplc_option = dict(NPLC_OPTIONS)[snapped]
        self._send(f"S{self._nplc_option}")

    # ---- output ------------------------------------------------------
    def output_on(self):
        """Operate, check it took, then one cycle to apply the setup.

        An open interlock refuses operate and says so only in the status
        words, so the U3 machine status is asked rather than assumed.
        The cycle after operate puts the programmed level and compliance
        into effect (see the module docstring).
        """
        self._send("N1")
        _, machine = self._fields(3, ("MST",))
        if machine.get("N") != "1":
            self._send("N0")
            raise RuntimeError(
                f"{self.DISPLAY_NAME} stayed in standby after N1X - an "
                f"open interlock refuses operate. Close the fixture lid.")
        self._operate = True
        self._cycle()

    def output_off(self):
        """0, then standby.

        Writes only, so it still works on a link that has stopped
        answering (see Transport.write). Zero first, as the manual asks:
        a level left programmed through standby comes back for 10 ms at
        the next operate.
        """
        self._send(f"B0,{self._source_range[self._mode]},{self._delay_ms}")
        self._level = 0.0
        self._send("N0")
        self._operate = False

    # ---- measurement -------------------------------------------------
    def measure(self, timeout_s=3.0):
        """One reading from a cycle triggered now.

        Returns (volts, amps) with None for the quantity being sourced -
        the instrument does not measure it, and the source item in its
        reply is the programmed value.
        """
        reply = self._cycle(timeout_s=timeout_s)
        measured = self._parse_reading(reply)
        if self._mode == "voltage":
            return (None, measured)
        return (measured, None)

    def _parse_reading(self, reply):
        """The measured value out of a `G5,1,0` reply, or None.

        Two items: the source (`NSDCV+1.0000E+00`) and the measurement
        (`NMDCI+1.23456E-09`). The measurement's `O` means overlimit -
        either in compliance or an overflow - and the source's `O` means
        the source is in compliance. So:

        * source `O`: a reading at compliance, which is a real
          measurement (manual 3.6.6), returned and flagged for
          `compliance_tripped()`;
        * measure `O` with source `N`: an overflow - no reading;
        * a reply in any other shape raises: it means the instrument is
          not in the format `reset()` set.
        """
        text = str(reply or "").replace(" ", "").strip()
        items = _ITEM.findall(text)
        source = [i for i in items if i[1] == "S"]
        measure = [i for i in items if i[1] == "M"]
        if len(source) != 1 or len(measure) != 1:
            raise ValueError(
                f"{self.DISPLAY_NAME}: unexpected reading {text!r}")
        s_status, _, _, s_unit, _ = source[0]
        m_status, _, _, m_unit, number = measure[0]
        want_source = "V" if self._mode == "voltage" else "I"
        if s_unit != want_source or m_unit == s_unit:
            raise ValueError(
                f"{self.DISPLAY_NAME} is sourcing "
                f"{'voltage' if s_unit == 'V' else 'current'} ({text!r}), "
                f"but this driver set it to source {self._mode}.")
        if m_status == "Z":
            raise ValueError(
                f"{self.DISPLAY_NAME} is reporting a suppressed reading "
                f"({text!r}): it is offset by a stored value, and "
                f"suppression should be off.")
        if s_status == "O":
            self._clamped = True
        elif m_status == "O":
            return None
        return self.drop_sentinel(float(number))

    # ---- errors ------------------------------------------------------
    #: The U1 flags, most significant first (manual Figure 3-15).
    U1_FLAGS: tuple[str, ...] = (
        "trigger overrun", "IDDC (illegal command)",
        "IDDCO (illegal command option)", "interlock present",
        "illegal measure range", "illegal source range",
        "invalid sweep mix", "log cannot cross zero",
        "autoranging source with pulse sweep", "in calibration",
        "in standby", "unit is a 236", "IOU DPRAM failed",
        "IOU EEROM failed", "IOU cal checksum error", "DPRAM lockup",
        "DPRAM link error", "cal ADC zero error", "cal ADC gain error",
        "cal SRC zero error", "cal SRC gain error",
        "cal common mode error", "cal compliance error",
        "cal value error", "cal constants error", "cal invalid error")

    #: The U9 flags, most significant first (manual Figure 3-23).
    U9_FLAGS: tuple[str, ...] = (
        "uncalibrated", "temporary cal", "value out of range",
        "sweep buffer filled", "no sweep points", "pulse times not met",
        "not in remote", "measure range changed",
        "measurement overflow / sweep aborted", "pending trigger")

    #: U9 positions that a reset need not fail on: an overflow is a
    #: reading's business, and a pending trigger is acted on in time.
    U9_HARMLESS = frozenset({8, 9})

    @staticmethod
    def _describe(flags, names):
        positions = [i for i, f in enumerate(flags) if f == "1"]
        if len(names) == len(flags):
            return "Set: " + ", ".join(names[i] for i in positions)
        return ("Set at position(s) "
                + ", ".join(str(i + 1) for i in positions)
                + " of the word - see the manual's figure for it.")

    def read_error(self):
        """The `U1` error word, which latches and clears when read.

        Not a queue: one read returns every flag set since the last, and
        the next read returns none. So the code is the position of the
        first set flag and the message lists them all; a second call
        then returns (0, ""), which is what "the queue is empty" means
        to every caller.

        `U9`, the warnings, is not read here: an overflow during a run
        would then read as a failed shutdown. The driver checks the
        warnings that matter where they arise.

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
                f"U1 = {word}. {self._describe(flags, self.U1_FLAGS)}")

    def read_warnings(self):
        """The `U9` warning word, as (word, [names of the set flags]).

        Latches and clears when read. For the checkup and the bench: no
        experiment calls it.
        """
        word, flags = self._flags(9)
        return word, [self.U9_FLAGS[i] for i, f in enumerate(flags)
                      if f == "1" and i < len(self.U9_FLAGS)]

