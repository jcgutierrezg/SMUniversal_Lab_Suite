"""
Keysight B2987A Electrometer / High Resistance Meter.

A femtoammeter with a +/-1000 V source beside it, on **separate
terminals**: the source comes out of banana posts, the current goes in
through a triax. It holds a voltage and measures the current that
results, which is the Keithley 487's shape, so it is declared the same
way - an SMU with half its modes missing: `SOURCE_FUNCTIONS =
("voltage",)`, current measured and nothing else, and the four-contact
experiments refuse it at Connect. See `docs/architecture/devices.md`,
"An SMU that sources one quantity".

Written from the B2980 SCPI Command Reference (the parts used are in
`docs/reference/manuals/b2987a-commands.md`) and a probe sitting,
`tools/bench_b2987a.py`, on 2026-11-18. Everything below marked
"measured" comes from that sitting.

Three source ranges, two of them one-sided
------------------------------------------
20 V (+/-21 V, 20 mA), +1000 V (-1 V to +1000 V, 1 mA) and -1000 V
(-1000 V to +1 V, 1 mA). Measured:

* a level the range in force cannot hold is refused (-222), the previous
  level stays on the sample, and the range does not move;
* the range cannot be changed with the output on - not even at 0 V
  (+213, "Output relay must be off").

So the 20 V range takes any run that stays inside 21 V, and a run that
goes further uses the 1000 V pair. The ranging plan hands a driver a
magnitude, never a sign, so which of the pair is in force is decided
here, level by level: a level above +1 V needs the +1000 V range, one
below -1 V the -1000 V range, and anything between is reachable on
either. When a sweep crosses from one side to the other with the output
on, `set_voltage_level()` takes the source to 0 V, opens the output
(0 V, then the relay), changes range, closes it again at 0 V, and only
then sets the new level - the two-step sweep, switched at 0 V. The
sample sees 0 V on both sides of the switch and floats for the length
of the relay operation.

The interlock
-------------
Open, the instrument holds the source to 21 V: a higher level is refused
with -222 "Interlock open" (measured). Applying a 1000 V range asks
`:SYST:INT:TRIP?` first and refuses with the remedy, before anything is
energised. Opened during a run, the instrument switches the source off
on its own; on the 1000 V ranges every reading asks the interlock again,
so the run stops rather than recording a sample with no voltage on it.

The compliance is the range's
-----------------------------
No command sets a current limit. The source holds a fixed one - 20 mA
on the 20 V range, 1 mA on the 1000 V pair - and regulates there rather
than tripping: asked for 31 mA it stayed on and set status bit 8,
"voltage force over current", with no error (measured, holding about
25.5 mA, above the nominal 20). So the compliance is a menu of those
two, each true only on its own range: 20 mA above 21 V, or 1 mA inside
it, would record a protection the run did not have, and both are
refused. `compliance_tripped()` is bit 8 of the last reading's status
word, so it costs no query.

Reset leaves the ammeter input off, and off it reads a number
-------------------------------------------------------------
`*RST` leaves `:INP` OFF, and a reading with the input off is not "not a
number": it returned +2.6E-11 A and left the input off (measured). A
driver that never switched the input on would record tens of picoamps of
nothing, plausibly. So `reset()` switches it on and reads it back.

Four more reset values are overridden: auto aperture (on, and 1.4 s a
reading where 1 PLC is 34 ms, measured), the function list (voltage too,
from a separate input this suite does not wire), the reply's element
list (`*RST` does not touch it at all - eight elements on this unit),
and the low terminal, which `*RST` does leave common but which is stated
anyway: floating, no current returns through the ammeter (measured).

Off is disconnected
-------------------
`:OUTP:OFF:MODE NORM`: 0 V, then the output relay opens. There is no
off that leaves the relay closed and still allows a range change, so
there is no high-Z choice to offer - `OUTPUT_OFF_DISCONNECTS`.

The ammeter input is switched on again at every output-on, since the
front panel's Ammeter switch turns it off even under remote, and off at
the end of a session - disconnect, or the end of a checkup - where it
used to stay on (2026-11-18): off, its centre conductor is tied to
circuit common.

Never sent: `SYST:BATT?` (with no battery fitted it queues -241
"Cannot detect battery"), `*SAV`/`*RCL`, the sweep, list and square-wave
modes, the 20 MOhm limiting resistor, `CALC`, and anything that changes
the communication settings.
"""
import time

from smuniversal_lab_suite.core.limits import LimitError, SMULimits
from smuniversal_lab_suite.core.ranges import AUTO, NOT_SOURCED, RangeError
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

from .base_smu import BaseSMU

#: Source ranges: the value `:SOUR:VOLT:RANG` takes -> (lowest level,
#: highest level, the current the source holds on it).
SOURCE_RANGES = {
    20.0: (-21.0, 21.0, 20e-3),
    1000.0: (-1.0, 1000.0, 1e-3),
    -1000.0: (-1000.0, 1.0, 1e-3),
}

#: The highest magnitude the 20 V range holds, and so the line between
#: the two families of range.
LOW_RANGE_SPAN_V = 21.0

#: The compliance each family of range holds, in amps.
LOW_RANGE_LIMIT_A = 20e-3
HIGH_RANGE_LIMIT_A = 1e-3

#: Current measurement ranges, full scale in amps. A request snaps up to
#: the next (measured: 3E-9 landed on 20 nA).
CURRENT_RANGES = (2e-12, 20e-12, 200e-12, 2e-9, 20e-9, 200e-9, 2e-6,
                  20e-6, 200e-6, 2e-3, 20e-3)

#: Status word bits (reference Table 1-2): a current overflow, and the
#: source at its current limit.
STATUS_CURRENT_OVERFLOW = 1 << 0
STATUS_SOURCE_OVER_CURRENT = 1 << 8

#: How long the source is held at 0 V before the relay opens for a range
#: switch inside a sweep. NORM mode already sets 0 V before it opens the
#: relay; this is the time for a 1000 V output to come down to it first.
#: A guess on the long side, and a bench item.
ZERO_HOLD_S = 0.05

#: The shortest timeout a reading is given. Autoranging down to the
#: 2 pA range with the instrument's own measurement wait is not quick.
READ_TIMEOUT_S = 10.0

#: Settings `reset()` reads back, and what each must say.
_RESET_STATE = {
    "INP?": ("1", "the ammeter input is off, and off it reads a "
                  "plausible current rather than nothing"),
    "OUTP?": ("0", "the source is on"),
    "OUTP:LOW?": ("COMM", "the source's low terminal is floating, so no "
                          "current returns through the ammeter"),
    "SENS:CURR:NPLC:AUTO?": ("0", "auto aperture is on, and a reading "
                                  "takes over a second"),
    "FORM:ELEM:SENS?": ("CURR,STAT", "readings are not in the shape "
                                     "this driver parses"),
}


class KeysightB2987A(BaseSMU):
    # Measured *IDN?: "Keysight Technologies,B2987A,MY54320335,
    # 2.0.1608.8800". Only the B2987A: the B2985A is the same instrument
    # without the battery and would work, but nobody has run it, and the
    # B2981A/B2983A have no source at all.
    MODEL_IDS = ["B2987A"]
    DISPLAY_NAME = "Keysight B2987A"

    LIMITS = SMULimits(
        max_voltage=1000.0,
        max_current=LOW_RANGE_LIMIT_A,
        # Full scale of the 20 V range is 21 V, and that is what a span
        # is compared with; the 1000 V pair share a magnitude.
        voltage_ranges=[LOW_RANGE_SPAN_V, 1000.0],
        current_ranges=list(CURRENT_RANGES),
        power_envelope=[],
    )

    # ---- what kind of instrument this is ----
    SOURCE_FUNCTIONS = ("voltage",)
    #: Current only: `measure()` always gives None for the voltage. The
    #: voltmeter is a separate +/-21 V input, not the source terminals.
    MEASURE_FUNCTIONS = ("current",)
    # The common case first, so a fresh form defaults to it: a run inside
    # 21 V is what this instrument is mostly used for, and the 1 mA a run
    # beyond it needs is asked for at Run with the reason.
    COMPLIANCE_CHOICES = {"current": (LOW_RANGE_LIMIT_A, HIGH_RANGE_LIMIT_A)}
    # A protection only. Deriving the measurement range from 20 mA would
    # put a femtoammeter on its 20 mA range.
    COMPLIANCE_SETS_MEASURE_RANGE = False

    INDEPENDENT_SOURCE_RANGE = True
    HAS_MEASURE_RANGE = True

    REMOTE_SENSE_CONTROL = False
    FIXED_SENSE = ("2-wire (no sense terminals - the source and the "
                   "ammeter are separate circuits)")

    # 5E-4 to 100 PLC at 50 Hz, 6E-4 to 120 at 60 Hz; the overlap, so a
    # clamped value is valid on either mains. Any value inside is taken
    # as it is (measured: 0.5 read back 0.5).
    NPLC_RANGE = (6e-4, 100.0)

    HIGH_Z_OFF = False
    OUTPUT_OFF_DISCONNECTS = True

    # Above 21 V the source needs the interlock closed - the fixture's
    # lid shut. Above 50 V a run is also confirmed through the warning,
    # as on every SMU here that can reach it (2026-10-15): an interlock
    # guards the fixture, not the leads on the way to it.
    INTERLOCK_ABOVE_V = LOW_RANGE_SPAN_V
    HAZARDOUS_ABOVE_V = 50.0

    SUB_COUNT_LEVELS = {"current": BaseSMU.SUB_COUNT_NOT_APPLICABLE,
                        "voltage": BaseSMU.SUB_COUNT_UNMEASURED}

    def __init__(self, transport):
        super().__init__(transport)
        #: The `:SOUR:VOLT:RANG` value in force, as last sent.
        self._range = 20.0
        #: Whether the run is on the 1000 V pair, as `apply_ranges()` left it.
        self._high = False
        self._limit = LOW_RANGE_LIMIT_A
        self._output = False
        self._settle_s = 0.0
        #: The status word of the last reading, for `compliance_tripped()`.
        self._last_status = None
        #: Range switches made inside a run, for the console.
        self.crossings = 0

    # ---- the wire ----------------------------------------------------
    def _send(self, command):
        self.transport.write(command)

    def _ask(self, command, timeout_s=3.0):
        return str(self.transport.query(command, timeout_s=timeout_s)).strip()

    def _drain_errors(self):
        """Every entry in the error queue, oldest first."""
        seen = []
        for _ in range(12):
            code, message = self.read_error()
            if code == 0:
                break
            seen.append(f"{code},{message}")
        return seen

    # ---- reset -------------------------------------------------------
    def reset(self):
        """`*RST`, then every setting this driver depends on, stated.

        Then read back the five that a reading's meaning hangs on, and
        the error queue: a setting the instrument refused is a failure
        here, not a silent default at the first run.
        """
        self._send("*RST")
        self._send("*CLS")
        for command in (
                "OUTP:LOW COMM",       # the current returns through the ammeter
                "OUTP:OFF:MODE NORM",  # off: 0 V, then the relay opens
                "SOUR:VOLT:RANG 20",
                "SOUR:VOLT 0",
                'SENS:FUNC "CURR"',    # not the separate voltmeter input
                "SENS:CURR:NPLC:AUTO OFF",
                "SENS:CURR:NPLC 1",
                "SENS:CURR:RANG:AUTO ON",
                "SENS:CURR:AVER:MOV OFF",
                "SENS:CURR:MED OFF",
                "SENS:CURR:REF:STAT OFF",
                "INP:ZCOR OFF",
                # The instrument's own settling waits, range-dependent,
                # kept on and stated (2026-11-18). The run's source delay
                # is added on top, in `measure()`.
                "SOUR:WAIT ON", "SOUR:WAIT:AUTO ON",
                "SENS:WAIT ON", "SENS:WAIT:AUTO ON",
                "FORM ASC",
                "FORM:ELEM:SENS CURR,STAT",
                "INP 1"):              # last, after everything it measures with
            self._send(command)
        self._range, self._high = 20.0, False
        self._limit = LOW_RANGE_LIMIT_A
        self._output = False
        self._settle_s = 0.0
        self._last_status = None
        self.crossings = 0

        errors = self._drain_errors()
        if errors:
            raise RuntimeError(
                f"{self.DISPLAY_NAME} refused part of its reset: "
                f"{'; '.join(errors)}. The instrument should not be used "
                f"until this is understood.")
        wrong = []
        for query, (want, why) in _RESET_STATE.items():
            reply = self._ask(query).replace('"', "").upper()
            if reply != want:
                wrong.append(f"{why} ({query} {reply})")
        if wrong:
            raise RuntimeError(
                f"{self.DISPLAY_NAME} did not take its reset: "
                + "; ".join(wrong) + ".")

    # ---- source configuration ----------------------------------------
    def set_source_function(self, mode):
        """Voltage, always. There is nothing to send."""
        if mode not in self.SOURCE_FUNCTIONS:
            raise ValueError(
                f"{self.DISPLAY_NAME} can only source voltage, got "
                f"{mode!r}. It has no current source.")

    def set_current_level(self, amps):
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no current source.")

    def _side_for(self, volts):
        """The 1000 V range a level needs, or the one in force when
        either would do."""
        if volts > SOURCE_RANGES[-1000.0][1]:
            return 1000.0
        if volts < SOURCE_RANGES[1000.0][0]:
            return -1000.0
        return self._range

    def set_voltage_level(self, volts):
        """Program the level, switching the 1000 V side at 0 V if the
        level is on the other one, and refusing any the instrument would
        drop.

        A refused level costs the sample nothing visible - the previous
        one stays and the run records the level it asked for - so it is
        refused here, loudly, before it reaches the wire.
        """
        volts = float(volts)
        if self._high:
            side = self._side_for(volts)
            if side != self._range:
                self._switch_side(side)
        low, high, _ = SOURCE_RANGES[self._range]
        if not low <= volts <= high:
            raise RangeError(
                f"{volts:g} V is outside the {self._range:g} V range in "
                f"force ({low:g} V to {high:g} V). The B2987A would refuse "
                f"it and stay where it is; the run's ranging plan should "
                f"have chosen the 1000 V ranges for it.")
        self._send(f"SOUR:VOLT {volts:.6e}")

    def _switch_side(self, side):
        """From one 1000 V range to the other, through 0 V.

        The range cannot change with the output on, so with it on the
        output is opened at 0 V and closed again at 0 V around the
        change. With it off, the change is just the change.
        """
        self._send("SOUR:VOLT 0")
        if self._output:
            time.sleep(ZERO_HOLD_S)
            self._send("OUTP 0")
            self._send(f"SOUR:VOLT:RANG {side:g}")
            self._send("OUTP 1")
            self.crossings += 1
        else:
            self._send(f"SOUR:VOLT:RANG {side:g}")
        self._range = side

    def set_current_limit(self, amps):
        """One of two values, each the one its range holds.

        Nothing is sent: no command sets it. What this checks is that the
        value the run records is the protection the sample has.
        """
        amps = self._limit_for(amps)
        holds = HIGH_RANGE_LIMIT_A if self._high else LOW_RANGE_LIMIT_A
        if amps != holds:
            where = ("the 1000 V ranges this run is on"
                     if self._high else "the 20 V range this run is on")
            raise LimitError(
                f"{self.DISPLAY_NAME}: {where} hold the current at "
                f"{holds * 1e3:g} mA, and no command changes it. A "
                f"{amps * 1e3:g} mA compliance would be a protection the "
                f"sample does not have; choose {holds * 1e3:g} mA.")
        self._limit = amps

    def set_voltage_limit(self, volts):
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no current source, so there is "
            f"never a voltage limit to set.")

    @classmethod
    def _limit_for(cls, amps):
        for value in (LOW_RANGE_LIMIT_A, HIGH_RANGE_LIMIT_A):
            if abs(float(amps) - value) <= value * 1e-6:
                return value
        raise LimitError(
            f"The {cls.DISPLAY_NAME}'s current limit is 20 mA on its 20 V "
            f"range and 1 mA on its 1000 V ranges, and nothing else; "
            f"{float(amps):g} A is neither.")

    def validate_source_point(self, current=None, voltage=None,
                              sourcing=None):
        """The limits, the menu, and the one pairing a single point can
        show: a level beyond 21 V runs on the 1000 V ranges, which hold
        1 mA, so a 20 mA compliance with it is refused at Run.
        """
        super().validate_source_point(current=current, voltage=voltage,
                                      sourcing=sourcing)
        if sourcing == "current":
            raise LimitError(f"{self.DISPLAY_NAME} cannot source current.")
        if current is None or sourcing != "voltage":
            return
        amps = self._limit_for(current)
        if (voltage is not None and abs(float(voltage)) > LOW_RANGE_SPAN_V
                and amps != HIGH_RANGE_LIMIT_A):
            raise LimitError(
                f"{float(voltage):g} V is beyond the 20 V range, so the "
                f"{self.DISPLAY_NAME} runs it on its 1000 V ranges, which "
                f"hold the current at 1 mA. Choose the 1 mA compliance.")

    # ---- ranging -----------------------------------------------------
    def interlock_open(self):
        """`:SYST:INT:TRIP?`: True open, False closed, None unanswerable."""
        try:
            reply = self._ask("SYST:INT:TRIP?")
        except TransportDesynchronised:
            raise
        except Exception:
            return None
        try:
            return int(float(reply)) == 1
        except ValueError:
            return None

    @classmethod
    def interlock_note(cls):
        return ("above 21 V the source needs the interlock closed - the "
                "fixture lid shut. Open, the instrument refuses the level "
                "and this driver refuses the run before anything is "
                "energised.")

    def _apply_source_voltage_range(self, volts):
        """The 20 V range for a span inside 21 V, the 1000 V pair beyond.

        `AUTO` takes the 1000 V pair when the interlock is closed - the
        widest, which never refuses a level, the U2722A's reasoning -
        and the 20 V range when it is open, since that is then all the
        instrument will source.

        At 0 V, and refused with the output on: the instrument would
        refuse it too (+213), and the run would go on with the range it
        had.
        """
        if self._output:
            raise RangeError(
                f"{self.DISPLAY_NAME}: the source range cannot change with "
                f"the output on.")
        if volts is AUTO or volts is NOT_SOURCED:
            high = self.interlock_open() is False
        else:
            span = abs(float(volts))
            if span > SOURCE_RANGES[1000.0][1]:
                raise RangeError(
                    f"{span:g} V is beyond the {self.DISPLAY_NAME}'s "
                    f"1000 V.")
            high = span > LOW_RANGE_SPAN_V
            if high:
                state = self.interlock_open()
                if state is not False:
                    raise RangeError(
                        f"{span:g} V needs the {self.DISPLAY_NAME}'s 1000 V "
                        f"ranges, and the interlock is "
                        + ("open" if state else "not answering")
                        + ". Close the fixture lid, or keep the run inside "
                          "21 V.")
        side = 1000.0 if high else 20.0
        self._send("SOUR:VOLT 0")
        self._send(f"SOUR:VOLT:RANG {side:g}")
        self._range, self._high = side, high

    def _apply_source_current_range(self, amps):
        if amps is AUTO or amps is NOT_SOURCED:
            return
        raise RangeError(f"{self.DISPLAY_NAME} has no current source.")

    def _apply_measure_current_range(self, amps):
        """Autorange, or the smallest range that holds `amps`. Setting a
        range does not turn autorange off on its own, so it is said."""
        if amps is AUTO:
            self._send("SENS:CURR:RANG:AUTO ON")
            return
        fitting = [r for r in CURRENT_RANGES if r >= float(amps)]
        self._send("SENS:CURR:RANG:AUTO OFF")
        self._send(f"SENS:CURR:RANG {(fitting or CURRENT_RANGES[-1:])[0]:g}")

    def _apply_measure_voltage_range(self, volts):
        if volts is AUTO:
            return
        raise RangeError(f"{self.DISPLAY_NAME} does not measure voltage.")

    # ---- reading state back ------------------------------------------
    # Query forms of the headers above. Not yet checked against a value
    # set at the front panel, so neither is trusted. There is no
    # compliance to read back: nothing sets one.
    RANGE_READBACK_TRUSTED = False

    def read_source_voltage_range(self):
        """The span of the range in force: 21 V for the 20 V range, 1000
        for either of the pair - the magnitude the plan asked for."""
        value = self._read_setting("SOUR:VOLT:RANG?")
        if value is None:
            return None
        return LOW_RANGE_SPAN_V if abs(value) < 100 else abs(value)

    def read_measure_current_range(self):
        return self._read_setting("SENS:CURR:RANG?")

    def _read_setting(self, query):
        try:
            return float(self._ask(query).split(",")[0])
        except TransportDesynchronised:
            raise
        except Exception:
            return None

    def compliance_tripped(self):
        """Bit 8 of the last reading's status word: the source at its
        current limit.

        Free after a reading, which is when a run asks. Asked before
        any, it takes one: the status word only arrives with a reading,
        and returning None there - "cannot say" - told the 2026-11-18
        checkup this driver had no flag at all. None only when the
        reading cannot be had.
        """
        if self._last_status is None:
            try:
                self.measure()
            except TransportDesynchronised:
                raise
            except Exception:
                return None
            if self._last_status is None:
                return None
        return bool(self._last_status & STATUS_SOURCE_OVER_CURRENT)

    # ---- sensing and timing ------------------------------------------
    def set_remote_sense(self, on=True):
        if on:
            raise NotImplementedError(
                f"{self.DISPLAY_NAME} has no sense terminals. Sensing is "
                f"{self.FIXED_SENSE}.")

    def set_source_delay(self, seconds):
        """The settle between a source step and its reading, kept here
        and waited before each `:MEAS?`. The instrument's own trigger
        delays belong to its trigger system, which `:MEAS?` does not go
        through on the reference's account, so this does not lean on
        them."""
        self._settle_s = max(0.0, float(seconds))

    def set_nplc(self, nplc):
        self._send(f"SENS:CURR:NPLC {self.clamp_nplc(nplc):.6g}")

    # ---- output ------------------------------------------------------
    def output_on(self):
        """The ammeter input on, then the output, each confirmed.

        The input first, and refused before anything is energised if it
        does not come on. The front panel's Ammeter switch turns the
        input off even under remote control - the natural thing to press
        before rewiring - and with it off a reading is a plausible
        current, not nothing (2026-11-18). So every run starts by
        putting it back, rather than trusting it to be as reset left it.
        """
        self._send("INP 1")
        state = self._ask("INP?")
        if state != "1":
            raise RuntimeError(
                f"{self.DISPLAY_NAME}: the ammeter input did not switch on "
                f"(INP? {state}), and with it off a reading is a plausible "
                f"current rather than the sample's. Nothing was sourced.")
        self._send("OUTP 1")
        self._output = True
        state = self._ask("OUTP?")
        if state != "1":
            self._output = False
            raise RuntimeError(
                f"{self.DISPLAY_NAME} did not switch on (OUTP? {state}). "
                + ("The interlock is open. " if self.interlock_open() else "")
                + "Nothing was sourced.")

    def output_off(self):
        """0 V, then off - writes only, so it still works on a link that
        has stopped answering. In NORM mode off is 0 V and the relay
        open."""
        self._send("SOUR:VOLT 0")
        self._send("OUTP 0")
        self._output = False

    def release_front_panel(self):
        """The ammeter input off, as the instrument is left at the end of
        a session: called by the app at disconnect, after the output is
        off, and by the checkup when it finishes.

        Off, the input's centre conductor is tied to circuit common - the
        protected state, and the one `*RST` leaves - rather than holding
        the sample on the ammeter's amplifier while it is rewired. The
        hook's name is the Z+'s, which hands its front panel back here; on
        this instrument it hands back the front panel's Ammeter switch
        off. A write only, so it goes out on a link that has stopped
        answering.
        """
        self._send("INP 0")

    # ---- measurement -------------------------------------------------
    def measure(self, timeout_s=3.0):
        """One reading: `(None, amps)`.

        No voltage, ever: the voltmeter is another input, and the
        programmed level is not a measurement. An overflowed reading is
        no reading. On the 1000 V ranges the interlock is asked as well:
        opened mid-run, the instrument switches the source off itself,
        and every reading after that is of a sample with no voltage on.
        """
        if self._settle_s:
            time.sleep(self._settle_s)
        reply = self._ask("MEAS?", timeout_s=max(timeout_s, READ_TIMEOUT_S))
        amps, status = self._parse_reading(reply)
        self._last_status = status
        if self._high and self._output and self.interlock_open():
            self._output = False
            raise RuntimeError(
                f"{self.DISPLAY_NAME}: the interlock opened, so the "
                f"instrument switched the source off. Readings from here "
                f"would be of a sample with no voltage on it.")
        return (None, amps)

    @classmethod
    def _parse_reading(cls, reply):
        """`(amps, status)` from a `CURR,STAT` reply. Raises on any other
        shape: it means the element list is not the one reset set, and a
        number pulled out of it would be a guess."""
        fields = str(reply or "").strip().split(",")
        if len(fields) != 2:
            raise ValueError(
                f"{cls.DISPLAY_NAME}: unexpected reading {reply!r} - "
                f"expected the current and its status word.")
        try:
            amps = float(fields[0])
            status = int(float(fields[1]))
        except ValueError:
            raise ValueError(
                f"{cls.DISPLAY_NAME}: unexpected reading {reply!r}") from None
        if status & STATUS_CURRENT_OVERFLOW:
            return None, status
        return cls.drop_sentinel(amps), status

    # ---- errors ------------------------------------------------------
    def read_error(self):
        """Pop one entry off the error queue. A failure to ask reports 0,
        per the contract."""
        try:
            reply = self._ask("SYST:ERR?")
        except TransportDesynchronised:
            raise
        except Exception:
            return (0, "")
        head, _, tail = reply.partition(",")
        try:
            return (int(float(head)), tail.strip().strip('"'))
        except ValueError:
            return (0, reply)

    # ---- console note ------------------------------------------------
    def sweep_note(self):
        """What the console says at connect."""
        return ("B2987A: source +/-21 V at 20 mA, or to +/-1000 V at 1 mA "
                "with the interlock closed. A sweep through zero beyond "
                "21 V switches range at 0 V, opening the output for the "
                "change. Software sweep, stepped from the PC.")
