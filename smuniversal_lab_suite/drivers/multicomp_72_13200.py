"""
Multicomp Pro 72-13200 DC electronic load - the first non-SMU driver.

150 W, 0-120 V, 0-30 A, four regulation modes (CV, CC, CR, CW), SCPI
over a USB virtual COM port. Written from *Communication Commands with
Computer V2.10* and the 72-13200 user manual; neither PDF is committed
(see `manuals/README.md`), and the command table is transcribed in
`docs/reference/manuals/72-13200-commands.md`.

Bought for one measurement this lab could not otherwise take: the
illuminated IV curve of a large silicon solar cell, whose short-circuit
current is around 10 A. The B2901A is the widest-range SMU here and
stops at 3 A, so the current was clamped from the first point.

What this instrument is not
---------------------------
It sinks. It cannot source, and that is not a missing feature - it is
what a load is. Three consequences run through everything below, and
each of them is a way to record a wrong number rather than an error:

  * **One quadrant.** Terminal voltage positive, current inward. A
    solar sweep from -0.2 V to 0.8 V asks this instrument for the first
    quarter of a span it physically cannot enter. `LIMITS` declares the
    polarity so the request is refused at the gate rather than absorbed.
  * **Above Voc it is equally helpless.** Past the open-circuit voltage
    the cell must be *driven*, so the usable window is 0 V to Voc and
    nothing either side. On a silicon cell that is about 0 to 0.65 V.
  * **It cannot reach V = 0.** The pass element needs volts across it to
    regulate, so short-circuit current - the one point every solar
    measurement wants - is below the floor. **Measured 2026-09-15 at
    two currents: it is a saturation resistance of 43.1 mOhm**, so the
    floor is 0.431 V at 10 A and 0.216 V at 5 A. For a silicon cell
    with Voc around 0.65 V that leaves a usable window of roughly
    0.43 V to Voc - which contains the knee and the maximum power
    point, and does not contain Isc.

Two things this dialect does that no other driver here has to handle
--------------------------------------------------------------------
**1. Replies carry their units.** `:MEAS:CURR?` answers `0.789A`, not
`0.789`. Every other SCPI driver in this suite does `float(reply)` and
would raise on the first reading. Worse than raising: `drop_sentinel()`
catches `ValueError` and returns `None`, so a raw reply handed to it
becomes a **silently discarded reading**. So `_number()` strips the unit
*before* anything else looks at the value, and the sentinel check runs
on the number.

**2. There is no error queue.** No `:SYST:ERR?`, no equivalent -
`:STATus?` returns the buzzer state and the baud rate and says the
remaining bytes are "to be determined". This removes the mechanism this
project verifies command spellings with: at the bench, a wrong header on
any other instrument is *logged* and can be read back. Here a wrong
header is simply ignored, invisibly.

What stands in for it is readback, and unusually this instrument has
plenty: every setpoint and every ceiling has a query form. So the
verification strategy inverts - `read_ceilings()` and the setpoint
queries are the way to find out whether a command landed, rather than a
convenience on top of an error queue.

**And there is no `*RST`.** Nothing in the command list resets
anything. Fault 6 - inherited state - is therefore structural on this
instrument rather than avoidable, and `reset()` below does the only
honest thing available: put the input into the safe state it *can*
command, then read back and log what it found, so the session starts
with the instrument's actual state written down rather than assumed.

Never sent
----------
`:FUNC SHORT` is in the command table and is not reachable from this
driver. The user manual describes it as making "the tested equipment
output the max current" - a deliberate short circuit across whatever is
attached. It is not a measurement mode, and a driver that can express it
is a driver that can be asked for it by mistake.

The `:LIST` sequencer is also declined, and that one is a judgement
rather than a hazard. It is a genuine hardware stepper, but it steps
*current* in whole-second dwells with no measurement buffer behind it -
so the host still has to poll for readings, and would no longer know
which step a reading belonged to. `SWEEP_KIND` stays "software", where
the level of each point is known exactly.

Numbers that are not from this model's own document
----------------------------------------------------
The command PDF is written for a product family: its examples answer
`>150V` and `>300W` where this unit is 120 V and 150 W. **No envelope
figure here comes from it** - `LIMITS` is transcribed from the
72-13200's own specification table.
"""
from smuniversal_lab_suite.core.limits import (
    NEGATIVE,
    POSITIVE,
    LimitError,
    SMULimits,
)
from smuniversal_lab_suite.core.ranges import AUTO, NOT_SOURCED
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

from .base_load import BaseLoad

#: Regulation mode -> the argument `:FUNCtion` takes.
#:
#: **`CV` and `CC`, not `VOLT` and `CURR`. The manual is wrong.**
#: Measured on the bench 2026-09-15, firmware V3.30. The command table
#: gives the parameter as `VOLT|CURR|RES|POW|SHORT` and its worked
#: example is `:FUNCtion VOLT`; neither works. `:FUNCtion VOLT` sent to
#: an instrument in CC leaves it in CC, and says nothing - there is no
#: error queue for it to say anything with.
#:
#: This is the whole reason this project asserts command spellings
#: rather than results. The driver as first written would have put
#: every "voltage sweep" through a constant-CURRENT sink, returning a
#: full set of plausible readings from an experiment the operator did
#: not ask for, with nothing anywhere reporting a fault.
#:
#: The set and query vocabularies agree, which is the clue the manual's
#: own example contradicts: `:FUNCtion?` answers `CC` or `CV`.
#:
#: CR and CW are real modes and are deliberately absent: an experiment
#: asks for "voltage" or "current" because those are the two an IV
#: sweep can be, and a mode nothing can request is a mode nothing can
#: request by accident.
FUNCTIONS = {"voltage": "CV", "current": "CC"}
#: Unit suffixes the instrument appends to its replies, longest first so
#: that "OHM" is stripped before "M" would be.
REPLY_UNITS = ("OHM", "AH", "A", "V", "W", "S", "M", "%")


class MulticompPro7213200(BaseLoad):
    MODEL_IDS = ["72-13200"]
    DISPLAY_NAME = "Multicomp Pro 72-13200"

    #: Transcribed from the 72-13200 specification table, not from the
    #: family command PDF.
    #:
    #: The two ranges per quantity are the ceilings the specification
    #: documents and states an accuracy against. They matter more here
    #: than a range usually does: the accuracy spec carries a full-scale
    #: term, so the ceiling sets the noise floor directly. Current:
    #: 1.35 mA on the 3 A ceiling, 13.5 mA on the 30 A one. Voltage:
    #: 4.5 mV on 18 V against 30 mV on 120 V, which for a cell sitting
    #: below 0.7 V is the difference between resolving Voc and not.
    #:
    #: A cell whose short-circuit current is a few milliamps cannot be
    #: measured on this instrument at all, on either ceiling. Use an SMU.
    #:
    #: The instrument also accepts ceilings between these - 5 A and 15 A
    #: both land exactly - but `apply_ranges()` snaps to the two
    #: documented ones on purpose. See there.
    LIMITS = SMULimits(
        max_voltage=120.0,
        max_current=30.0,
        voltage_ranges=[18.0, 120.0],
        current_ranges=[3.0, 30.0],
        # A continuous 150 W hyperbola, not a set of corners. The OPP
        # trip sits just above it at 165 W, so a sweep that crosses this
        # does not clamp - it ends.
        max_power=150.0,
        # The quadrant, in this suite's convention. See BaseLoad.
        voltage_polarity=POSITIVE,
        current_polarity=NEGATIVE,
    )

    #: The smallest CV setpoint this instrument will actually hold, in
    #: volts. **Measured 2026-09-15**: asking for 0.05 V, 0.01 V or 0 V all
    #: leave `:VOLTage?` reading 0.1000 V. Silently - the level is clamped,
    #: nothing is raised, and the reply looks like any other.
    #:
    #: `:VOLTage:LOWer?` reports the same 0.1 V and is therefore honest,
    #: but it is not consulted per point: this is a fixed property of the
    #: model and a query per sweep point would triple the traffic to learn
    #: a constant.
    #:
    #: It is a **commanding** floor and is not the headroom floor - they
    #: are different mechanisms and the headroom one is still unmeasured.
    #: Whichever is higher decides where a sweep can start. On a silicon
    #: solar cell with Voc around 0.65 V, this floor alone removes the
    #: bottom 15% of the usable window before headroom is considered.
    MIN_CV_SETPOINT_V = 0.1

    # ---- what this model does not have ----
    #: No error queue of any kind. See `read_error()` - and note that
    #: this is what makes `tools/scpi_console.py` say so out loud
    #: instead of silently not checking.
    HAS_ERROR_QUEUE = False
    #: No integration-time control of any kind in the command set.
    NPLC_RANGE = None
    #: No overvoltage-protection menu. The OVP figure in the
    #: specification table is a fixed trip, not a settable ceiling.
    OVP_CHOICES = []
    #: `:INPut` is on/off only. And "off" is not a disconnection: the
    #: specification gives the input impedance as 150 kOhm, so an
    #: illuminated cell left on a switched-off load sits near its
    #: open-circuit voltage rather than at zero.
    HIGH_Z_OFF = False
    #: There is no remote-sense command. The user manual describes
    #: 4-wire as the "remote compensation function", entered with
    #: SHIFT+CW at the front panel - so it is real, and software gets no
    #: say. Same shape as the U2722A's strapped SENSE terminals.
    REMOTE_SENSE_CONTROL = False
    FIXED_SENSE = "as set at the front panel (SHIFT+CW remote compensation)"

    def __init__(self, transport, channel=None):
        super().__init__(transport)
        #: What `reset()` found, for the run record. This instrument has
        #: no reset command, so the state a session starts in is
        #: inherited - and the only defence against fault 6 is to write
        #: down what was inherited.
        self.state_at_connect = {}

    # ---- parsing, which is where a reading is won or lost ----
    @staticmethod
    def _number(reply):
        """Strip the unit suffix and return a float, or None.

        Runs before `drop_sentinel()` and never after. Handing a raw
        `'0.789A'` to the sentinel check would parse-fail inside its
        `except (TypeError, ValueError)` and come back `None` - a
        reading that exists, thrown away, with nothing raised and
        nothing logged.
        """
        if reply is None:
            return None
        text = str(reply).strip().upper()
        if not text:
            return None
        for unit in REPLY_UNITS:
            if text.endswith(unit):
                text = text[:-len(unit)].strip()
                break
        try:
            return float(text)
        except ValueError:
            return None

    def _query_number(self, command):
        value = self._number(self.transport.query(command))
        return self.drop_sentinel(value)

    # ---- identification and the reset that is not one ----
    def reset(self):
        """Put the input into the one safe state this model can command,
        and record what it was already set to.

        **There is no `*RST` on this instrument**, so this is not a
        return to known defaults - nothing here can do that. What it can
        do is disable the input, which is the state a session should
        start from, and then ask the instrument what mode and ceilings
        it is holding so the session's starting point is a recorded fact
        rather than an assumption.

        `*CLS` is not sent either: there is no status structure
        documented for it to clear, and an unrecognised command on this
        instrument is ignored in silence, so sending one would be a
        gesture rather than an action.
        """
        self.transport.write(":INPut OFF")
        self.state_at_connect = {
            "mode": self._mode_at_connect(),
            "ceilings": self.read_ceilings(),
        }

    def _mode_at_connect(self):
        """The regulation mode the front panel was left in, or None.

        `:FUNCtion?` can answer with modes this driver never sets - the
        command table says it reports CV, CC, CR and CW "in continuous
        mode, pulse, flip, battery and all the other modes". That is a
        readback that can legitimately disagree with anything this
        driver could have written, so it is recorded rather than
        checked.
        """
        try:
            reply = str(self.transport.query(":FUNCtion?")).strip()
            return reply or None
        except TransportDesynchronised:
            # Never swallowed. A desync says the replies themselves can
            # no longer be trusted, which is a different thing from one
            # query going unanswered - and on this instrument, with no
            # error queue to cross-check against, it is the only signal
            # there is that the stream has gone out of step.
            raise
        except Exception:
            return None

    # ---- regulation ----
    def set_source_function(self, mode):
        """Select CV or CC.

        Named for the contract rather than for the instrument, which
        calls this a function and means a regulation mode. An experiment
        asking for "voltage" means the same thing to a load and to an
        SMU: hold this quantity, measure the other.
        """
        if mode not in FUNCTIONS:
            raise ValueError(
                f"{self.DISPLAY_NAME}: mode must be one of "
                f"{sorted(FUNCTIONS)}, got {mode!r}. The CR and CW modes "
                f"exist on this instrument and are deliberately not "
                f"reachable from here.")
        wanted = FUNCTIONS[mode]
        self.transport.write(f":FUNCtion {wanted}")

        # Read it back, and refuse to continue if it did not take.
        #
        # Every other driver here can let a mode change stand on the
        # error queue: a header the instrument did not understand is
        # logged, and the checkup finds it. This model has no queue, so
        # a rejected `:FUNCtion` is indistinguishable from an accepted
        # one - which is exactly how the first version of this driver
        # came to send `VOLT` for months of imagined runs.
        #
        # One query, about 5 ms, once per run rather than once per
        # point. That is the cheapest insurance in this file: the state
        # it confirms decides whether the sweep measures the quantity
        # the operator asked for or the other one.
        got = str(self.transport.query(":FUNCtion?")).strip().upper()
        if got != wanted:
            raise RuntimeError(
                f"{self.DISPLAY_NAME}: asked for {wanted} and the "
                f"instrument reports {got or '(no reply)'}. The mode did "
                f"not change and this model has no error queue to say "
                f"why. Refusing rather than sweeping in the wrong mode - "
                f"a CV sweep run in CC returns a full set of plausible "
                f"readings of an experiment nobody asked for.")

    def set_voltage_level(self, volts):
        """Set the CV setpoint, in volts.

        Refuses a negative level rather than sending it. The gate in
        `LIMITS` catches a sweep's endpoints before the run, but a
        software sweep calls this once per point and computes its own
        levels, so the refusal belongs here too - this is the last place
        before the wire.
        """
        volts = float(volts)
        if volts < 0:
            raise ValueError(
                f"{self.DISPLAY_NAME}: a CV setpoint of {volts:.6g} V is "
                f"negative, and an electronic load cannot reverse its "
                f"terminals. There is nothing for it to sink below zero.")
        if volts < self.MIN_CV_SETPOINT_V:
            # Refused rather than sent, because sending it produces a
            # number: the instrument clamps to 0.1 V, reports 0.1 V, and
            # raises nothing. A sweep stepping down through this region
            # would record several distinct requested levels that were
            # all the same physical point, and the curve would flatten
            # exactly where the interesting part of a solar IV curve is.
            raise ValueError(
                f"{self.DISPLAY_NAME}: a CV setpoint of {volts:.6g} V is "
                f"below the smallest this model will hold "
                f"({self.MIN_CV_SETPOINT_V:g} V, measured). It would be "
                f"clamped to {self.MIN_CV_SETPOINT_V:g} V silently, so "
                f"every level below the floor would record as a "
                f"different point at the same voltage. "
                f"Including zero, which was measured too: asking for "
                f"0 V leaves this instrument reporting 0.1 V. A CV "
                f"setpoint of zero is a short across the terminals and "
                f"this model will not hold one. To stop it sinking, "
                f"disable the input with output_off() - on a load that "
                f"is the real settle-to-zero path, and unlike an SMU's "
                f"output-off it genuinely stops current rather than "
                f"driving zero volts.")
        self.transport.write(f":VOLTage {volts:g}V")

    def set_sink_current(self, amps):
        """Set the CC setpoint as a positive magnitude.

        `BaseLoad.set_current_level()` is what experiments call; it
        applies the suite's sign convention and hands the magnitude
        here, which is the way this instrument's own command spells it.
        """
        self.transport.write(f":CURRent {float(amps):g}A")

    # ---- reading back ----
    #: The ceilings are settable over the bus after all - see
    #: `apply_ranges()`. The manual's command table marks both `UPPer`
    #: entries "Setup: no", i.e. query-only. Measured 2026-09-15: they
    #: are writable, and the write takes effect immediately.
    RANGES_ARE_OPERATOR_SET = False

    def apply_ranges(self, plan, log=None):
        """Set both ceilings from the plan, then read them back.

        **This model can be ranged over the bus**, which the manual
        denies: its command table marks `:CURRent:UPPer` and
        `:VOLTage:UPPer` as query-only. They are not. Confirmed from two
        directions rather than one, because a query nobody has checked
        is not evidence: `:CURRent:UPPer?` reports the new value, *and*
        an over-large setpoint then clamps to it - asking for 10 A with
        a 3 A ceiling comes back 3 A.

        Why it matters more than ranging usually does
        ---------------------------------------------
        The accuracy spec carries a full-scale term - 0.045% of it for
        current, 0.025% for voltage - so the ceiling sets the noise
        floor directly. On the 30 A ceiling the current floor is
        13.5 mA; on 3 A it is 1.35 mA. For a solar cell sitting at
        0-0.65 V the *voltage* ceiling matters just as much: 18 V gives
        a 4.5 mV floor against 30 mV on 120 V.

        Snapped to the declared ranges, not passed through
        --------------------------------------------------
        Arbitrary ceilings are accepted - 5 A and 15 A both land exactly
        - but the specification documents **two** ranges per quantity
        and states accuracy per range. What an intermediate ceiling
        means for the full-scale term is therefore unknown: it may pick
        the hardware range, or it may only limit the setpoint while the
        converter stays where it was. Until that is measured against a
        known signal, this snaps to a documented range, which is the
        direction that cannot quietly claim resolution nobody has
        confirmed.

        `AUTO` resolves to the widest. There is no autorange on this
        instrument, so something concrete has to be chosen, and the
        widest never clamps a level - the U2722A's reasoning exactly.
        """
        chosen = {}
        for quantity, first, second, unit in (
                ("current", "source_current", "measure_current", "A"),
                ("voltage", "source_voltage", "measure_voltage", "V")):
            wanted = plan.widest(first, second)
            if quantity == "voltage" and wanted is AUTO                     and isinstance(plan.source_voltage, (int, float)):
                # `for_sourcing()` marks the measurement range of the
                # SOURCED quantity AUTO, because on a source-measure
                # unit that value is read back through the source and
                # has no independent range - asking for one is error
                # 823 on two of the instruments here.
                #
                # That is an SMU fact and it is false on a load. This
                # instrument measures its terminal voltage with its own
                # converter, whose range is the ceiling, so letting
                # AUTO win the shared knob does not avoid setting a
                # range nobody may set - it picks the widest one there
                # is and gives away resolution on the very quantity the
                # run is commanding. On a 0.8 V sweep that is a 30 mV
                # accuracy floor where 18 V full scale would give
                # 4.5 mV: 4.6% of a silicon cell's Voc against 0.7%.
                #
                # So the span the operator typed decides it. The safety
                # this gives up - a ceiling too low for whatever is
                # actually attached - is taken back in `output_on()`,
                # which reads the terminals before energising.
                #
                # Deliberately local to this driver. `for_sourcing()`
                # and `widest()` are unchanged, and the widest-range
                # landing they produce elsewhere is a decided design.
                wanted = plan.source_voltage
            ladder = (self.LIMITS.current_ranges if quantity == "current"
                      else self.LIMITS.voltage_ranges)
            if wanted is AUTO or wanted is NOT_SOURCED:
                ceiling = max(ladder)
            else:
                nearest = (self.LIMITS.nearest_current_range(wanted)
                           if quantity == "current"
                           else self.LIMITS.nearest_voltage_range(wanted))
                ceiling = nearest if nearest is not None else max(ladder)
            header = ":CURRent:UPPer" if quantity == "current"                 else ":VOLTage:UPPer"
            # The unit suffix is mandatory here too: `:CURRent:UPPer 3`
            # is accepted and ignored, exactly as the setpoints are.
            self.transport.write(f"{header} {ceiling:g}{unit}")
            chosen[quantity] = ceiling

        reported = self.read_ceilings()
        parts = []
        for quantity, unit in (("current", "A"), ("voltage", "V")):
            asked = chosen[quantity]
            got = reported.get(quantity)
            if got is None:
                parts.append(f"{quantity} {asked:g}{unit} (unconfirmed)")
            elif abs(got - asked) > max(abs(asked) * 1e-3, 1e-9):
                # Reported rather than raised. A ceiling wider than
                # asked for costs resolution; one narrower would clamp a
                # level. Either way the run records what the instrument
                # said it was on, not what this method sent.
                parts.append(f"{quantity} asked {asked:g}{unit}, "
                             f"reports {got:g}{unit} - MISMATCH")
            else:
                parts.append(f"{quantity} {got:g}{unit}")
        described = ", ".join(parts)
        if log:
            log(f"{self.DISPLAY_NAME}: ceilings set over the bus and read "
                f"back - {described}. The ceiling sets the full-scale term "
                f"in the accuracy spec, so it decides the measurement "
                f"floor.")
        return f"ceilings: {described}"

    def read_ceilings(self):
        """The per-quantity ceilings the instrument reports.

        Verified against a second fact rather than trusted on its own:
        with the ceiling at 3 A, a requested 10 A setpoint comes back
        3 A. A query that agrees with an independent consequence of the
        same setting is a query that has been checked.
        """
        ceilings = {"current": None, "voltage": None}
        for axis, command in (("current", ":CURRent:UPPer?"),
                              ("voltage", ":VOLTage:UPPer?")):
            try:
                ceilings[axis] = self._query_number(command)
            except TransportDesynchronised:
                raise
            except Exception:
                # A ceiling that cannot be read is a gap in the record,
                # not a failed run. `None` is what the caller renders.
                ceilings[axis] = None
        return ceilings

    #: The load's saturation resistance, in ohms - and therefore its
    #: headroom floor, which is `R x I`.
    #:
    #: **MEASURED at two currents a factor of two apart, 2026-09-15**,
    #: and that is what makes it a resistance rather than a number:
    #:
    #:     9.998 A   floor 0.4310 V   43.11 mOhm
    #:     5.023 A   floor 0.2164 V   43.08 mOhm
    #:
    #: The two agree to 0.03 mOhm. Predicting the 5 A floor from the
    #: 10 A one gave 0.2165 V against 0.2164 V measured, so there is no
    #: measurable fixed term: the pass element is simply a resistance
    #: once it saturates.
    #:
    #: Both floors were sharp - 0.0 mV of spread across every setpoint
    #: below them, four points at 10 A and five at 5 A.
    #:
    #: **Held as a resistance for the same reason the B2901A's
    #: sub-count floor is held as counts.** An absolute figure would be
    #: right at one current and wrong at every other, and this
    #: instrument is used across a 6:1 range of them. That driver's
    #: lesson was learned from two measurements on two ranges; this is
    #: the same experiment on the other side of the fleet.
    SATURATION_RESISTANCE_OHM = 0.04310

    #: How long the CV loop takes to settle a step down at 10 A, in
    #: seconds. Measured in the same session: a 1.0 -> 0.5 V step was
    #: still at 0.624 V after 220 ms and had reached its final value by
    #: 430 ms.
    #:
    #: This is the floor under an IV sweep's per-point delay, and it is
    #: long: a 100-point CV sweep cannot run faster than about a minute
    #: without recording the loop rather than the cell. It is a property
    #: of the instrument and the operating point, not of the bus - the
    #: queries themselves take 4-6 ms.
    SETTLING_S = 0.45

    HEADROOM_STATE = BaseLoad.HEADROOM_MEASURED

    def minimum_operating_voltage(self, amps):
        """Lowest terminal voltage this model holds at `amps`, in volts.

        `R x I`, with R measured at two currents - see
        `SATURATION_RESISTANCE_OHM`. Below this the pass element has
        nothing to regulate with: the setpoint stops being followed, no
        error is raised, and the readings keep their usual shape.

        **This is not the only floor**, and the other one wins at low
        current. `MIN_CV_SETPOINT_V` is 0.1 V and is absolute - the
        instrument will not accept a smaller CV setpoint at any current
        - so the effective floor is the larger of the two, and they
        cross at 2.32 A. Below that the commanding floor decides;
        above it, the headroom does.

        They are kept separate rather than collapsed into one number
        because they are different mechanisms with different remedies:
        one is a limit on what can be *asked for*, the other on what can
        be *held*, and an operator looking at a truncated curve needs to
        know which stopped them.
        """
        return self.SATURATION_RESISTANCE_OHM * abs(float(amps))

    # ---- output ----
    def output_on(self):
        """Enable the input, after checking what is across the terminals.

        With the input off the terminals are loaded only by the
        specified 150 kOhm, so `:MEAS:VOLT?` reads the attached source
        almost unloaded - which makes this the one moment the driver can
        find out what it is about to connect to, for free.

        It is checked because `apply_ranges()` narrows the voltage
        ceiling to the sweep span. That is the right call for a solar
        cell and the wrong one for a supply somebody left at 48 V, and
        the difference is knowable here and nowhere later: past this
        point the reading would simply overrange.
        """
        ceiling = self.read_ceilings().get("voltage")
        if ceiling is not None:
            present, _ = self.measure()
            if present is not None and abs(present) > ceiling:
                raise LimitError(
                    f"{self.DISPLAY_NAME}: {abs(present):.3g} V is across "
                    f"the terminals and the voltage ceiling is "
                    f"{ceiling:g} V, so a reading would overrange. The "
                    f"ceiling is chosen from the sweep span - either the "
                    f"run is set up for a different source than the one "
                    f"attached, or the span needs to cover it.")
        self.transport.write(":INPut ON")

    def output_off(self):
        self.transport.write(":INPut OFF")

    # ---- timing ----
    def set_source_delay(self, seconds):
        """Accepted, and applied by the host rather than the instrument.

        There is no settle-time command in this instrument's command
        set. That is not a silent no-op: the software sweep this driver
        inherits waits `delay_s` between setting a level and measuring,
        on the host, so the delay an experiment asks for is honoured -
        it is simply honoured one layer up. Recorded here so that a
        reader looking for the missing `:SOUR:DEL` finds the answer.
        """

    def set_remote_sense(self, on=True):
        """Refused, because software cannot honour it.

        There is no remote-sense command. 4-wire is entered at the front
        panel, so accepting a request here would write a sensing mode
        into the CSV that the measurement did not use - the U2722A's
        reasoning exactly.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no remote-sense command. Sensing is "
            f"set at the front panel with SHIFT+CW (remote compensation), "
            f"and this driver records it as {self.FIXED_SENSE!r} rather "
            f"than claiming a control it does not have.")

    # ---- measurement ----
    def measure_sinking(self, timeout_s=3.0):
        """One reading, in the **instrument's** convention: sink positive.

        `BaseLoad.measure()` applies this suite's sign convention on top,
        so nothing above the driver ever sees a positive sink current.

        Two queries, because there is no combined read - so a point
        costs two round trips, and a software sweep's per-point cost is
        two bus turnarounds rather than one.
        """
        volts = self._query_number(":MEASure:VOLTage?")
        amps = self._query_number(":MEASure:CURRent?")
        return volts, amps

    def measure_power(self, timeout_s=3.0):
        """The instrument's own power reading, in watts.

        Not part of any contract and not used by an experiment. It is
        here because this instrument measures power directly rather than
        by multiplication, and on a solar cell the quantity of interest
        at the maximum power point is exactly this one - so a future
        experiment has it without needing to know the command.
        """
        return self._query_number(":MEASure:POWer?")

    def read_error(self):
        """Always `(0, ...)`, because this instrument has no error queue.

        Not a failure to read one - there is not one to read. The
        command set has no `:SYST:ERR?` or equivalent, and `:STATus?`
        reports the buzzer and the baud rate.

        `BaseInstrument.read_error()` requires that a failure to *ask*
        reports code 0 rather than an error, on the grounds that being
        unable to ask is not evidence a command failed. That rule
        applies here in its strongest form, and the message says which
        of the two states this is: a caller that logs the text gets
        "this instrument cannot be asked", not a clean bill of health.
        """
        return 0, ("no error queue on this model - a rejected command is "
                   "ignored in silence, so nothing here is evidence that "
                   "anything was understood. Verify by reading the "
                   "setting back.")
