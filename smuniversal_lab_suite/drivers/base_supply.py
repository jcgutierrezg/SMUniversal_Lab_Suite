"""
The power-supply contract - a sibling of `BaseSMU` and `BaseLoad`.

A bench supply sets a voltage and a current and reads both back, so by
the test in `docs/architecture/devices.md` - *does it carry the
measurement?* - it can be a driver rather than a device. But it is not a
source-measure unit, and the differences decide what it may be used for:

  * **Two knobs, and the load picks which one is in charge.** There is
    no source function to select. A supply holds its voltage until the
    load asks for more than the current setting, then holds the current
    instead - automatic crossover, constant voltage to constant current
    and back. So "source voltage with a current compliance" and "source
    current with a voltage compliance" are the *same two settings*, and
    which one is being regulated at any moment is a fact about the load,
    not about anything this driver sent.
  * **It has a compliance, and it is a real one.** That is the opposite
    of a load, whose protections are trips. A supply in current limit
    goes on regulating, at the ceiling, and the measurement continues
    with clamped data - exactly an SMU's compliance, so
    `supports_compliance()` is true and the setters below exist.
  * **It is one quadrant.** Positive voltage, current outward, and it
    cannot sink: a step down with little attached falls only as fast as
    the load discharges the output capacitor.
  * **It is coarse.** Setting and readback move in steps of the order of
    10 mV and 10 mA, and the current setting has a floor well above
    zero. Every four-contact measurement in this suite lives below that.

Why it is not a `BaseSMU` subclass
----------------------------------
For the reason a load is not: `issubclass(supply, BaseSMU)` would be
true, and the SMU contract suites would then grade it on a four-axis
`RangePlan`, a source converter's bottom count and a high-Z output-off -
questions that do not apply, answered in a ledger where every `False`
means "this model lacks this feature". All three fleets sit on
`BaseInstrument`; `drivers/registry.py` keeps three lists and identifies
from their union.

By invitation
-------------
Carrying *a* measurement is not carrying *every* measurement. A supply
connected to Van der Pauw would be accepted on its declarations alone -
it sources, it has a compliance - and then asked for 100 uA from a
converter whose smallest step is a hundred times that.

So a supply declares `ROLE_CAVEATS`: what an experiment has to have
accepted, by name, before this instrument may fill one of its roles. An
experiment that has thought about it lists the caveat in its
`ROLE_ACCEPTS`; every other experiment refuses at Connect, with the
caveat's own text as the reason. Nothing in `experiments/` learns what a
supply is - it accepts a named limitation or it does not, which is the
same shape as `ROLE_REQUIRES` and holds the same rule.

**The declaration lives here rather than on `BaseInstrument` on
purpose, and that is a debt.** Every commissioning record hashes the
bytes of `base_instrument.py`, so adding the default there would mark
the whole fleet stale for a change no SMU or load can observe. The app
shell reads it with a default instead. It moves down at the next fleet
round - `docs/open/technical-debt.md` carries it.
"""
from smuniversal_lab_suite.core import readback as _readback
from smuniversal_lab_suite.core.limits import LimitError

from .base_instrument import BaseInstrument

#: Regulating at the voltage setting. The current is whatever the load
#: draws, below the current setting.
CV = "CV"
#: Regulating at the current setting. The voltage has dropped to
#: whatever that current develops across the load.
CC = "CC"
#: Both, since the last time anyone asked - the supply went into one
#: mode and came back out between two polls. Which it is in *now* is not
#: known, and saying either would be a guess.
CROSSED = "crossed"

REGULATION_STATES = (CV, CC, CROSSED)


class BaseSupply(BaseInstrument):
    """What every power supply in this suite implements."""

    # ---- what a supply has that a load does not ----
    #
    # The ceiling is regulated at, not tripped on, so an experiment's
    # `apply_compliance()` has something real to set.
    HAS_COMPLIANCE = True

    # ---- by invitation ----
    #: Caveat name -> why an experiment has to have accepted it.
    #:
    #: A role is filled by this instrument only where the experiment
    #: lists every name here in its `ROLE_ACCEPTS` for that role. The
    #: text is what the operator reads when it does not, so it says what
    #: the instrument cannot do rather than what it is.
    ROLE_CAVEATS = {
        "power_supply_grade": (
            "It is a bench power supply, not a source-measure unit: it "
            "sets and reads in coarse steps, it cannot go below a minimum "
            "current, and it works in one quadrant only - positive "
            "voltage, current out, no sinking."),
    }

    # ---- the grid everything lands on ----
    #: The setting and readback step per quantity, in volts and amps, or
    #: `None` where a model has not declared one. A level between two
    #: steps is rounded **by the instrument**, not here - see fault 4:
    #: the full-precision level is what gets sent, and what the supply
    #: actually produced is read back rather than assumed.
    RESOLUTION = {"voltage": None, "current": None}

    #: The smallest current setting this model accepts, in amps. A
    #: supply's current knob does not reach zero, and that is the same
    #: knob whether it is being used as a level or as a compliance - so
    #: this is a floor under both.
    MIN_CURRENT_A = None

    #: `(low, high)` the over-voltage trip can be set to, in volts, or
    #: `None` on a model with no settable trip.
    #:
    #: Deliberately not `OVP_CHOICES`. That is a *menu* - the arguments
    #: a dropdown offers - and the experiments read it to decide whether
    #: to show one. A supply's trip is a continuous value, and inventing
    #: a ladder of them would put a default in a dropdown that trips the
    #: output the first time someone sets a level above it.
    OVP_RANGE_V = None

    #: Has the setpoint readback been checked at the bench against a
    #: value the instrument was known to hold? Same rule as
    #: `BaseSMU.COMPLIANCE_READBACK_TRUSTED`: a query answering the
    #: number it was just handed is not evidence until an independent
    #: consequence agrees with it.
    SETPOINT_READBACK_TRUSTED = False

    #: And for the over-voltage trip, which is a separate query.
    OVP_READBACK_TRUSTED = False

    #: `(command, code)`: something the instrument must reject, and the
    #: error it must reject it with. `None` where a model has nothing
    #: suitable.
    #:
    #: It exists for the checkup, and for one reason. Every "the error
    #: registers are clean" in a report is only worth something if those
    #: registers would have said otherwise - and a `read_error()` wired
    #: to the wrong query, or decoding the wrong bit, also reads clean,
    #: forever. So the checkup sends this once, past the driver's own
    #: guards, and requires the complaint (fault 19: ask where the
    #: interesting answer is the correct one).
    #:
    #: The command must be harmless if the instrument *accepted* it,
    #: because the point of the probe is that this driver might be
    #: wrong about what gets refused.
    ERROR_PROBE = None

    def __init__(self, transport):
        super().__init__(transport)
        #: Which of the two knobs the caller thinks of as the level.
        #: Nothing is sent for it - see `set_source_function`.
        self._source_function = None
        #: Whether this driver's own commands last left the output on.
        #: Not a readback: a front-panel press or a protection trip
        #: changes the truth without changing this.
        self._output_enabled = False

    # ---- the two knobs ----
    def set_source_function(self, mode):
        """Record which quantity the caller is treating as the level.

        **Sends nothing, because there is nothing to send.** A supply
        has no source-function command: it holds its voltage setting
        until the load draws the current setting, then holds that
        instead. "Voltage" here means the voltage setting is the level
        and the current setting is the compliance; "current" means the
        other way round. Both leave the same two numbers in the
        instrument.

        What the choice does change is how `compliance_tripped()` reads
        the regulation state: sourcing voltage, the supply clamping in
        constant current is the compliance; sourcing current, it is the
        supply sitting at its voltage setting because the load will not
        take the current asked for.
        """
        if mode not in ("voltage", "current"):
            raise ValueError(
                f"{self.DISPLAY_NAME}: mode must be 'voltage' or "
                f"'current', got {mode!r}.")
        self._source_function = mode

    def source_function(self):
        """'voltage', 'current', or None before anything has chosen."""
        return self._source_function

    def set_voltage_level(self, volts):
        """Set the voltage setting, in volts."""
        self.set_output_voltage(self._checked_voltage(volts))

    def set_voltage_limit(self, volts):
        """Set the voltage compliance - which is the voltage setting.

        The same knob as `set_voltage_level()`, named for the role it
        plays when the current setting is the level.
        """
        self.set_output_voltage(self._checked_voltage(volts))

    def set_current_level(self, amps):
        """Set the current setting, in amps."""
        self.set_output_current(self._checked_current(amps))

    def set_current_limit(self, amps):
        """Set the current compliance - which is the current setting."""
        self.set_output_current(self._checked_current(amps))

    def set_output_voltage(self, volts):
        """Write the voltage setting, the way the instrument spells it.

        Abstract in effect: the four contract setters above are built
        from this and `set_output_current()`, so a driver implements two
        commands and cannot give the level and the compliance different
        guards by accident.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} must implement set_output_voltage().")

    def set_output_current(self, amps):
        """Write the current setting, the way the instrument spells it."""
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} must implement set_output_current().")

    # ---- the last check before the wire ----
    def _checked_voltage(self, volts):
        """Refuse a voltage this instrument cannot produce.

        The gate in `validate_source_point()` catches a run's levels
        before anything is energised. A software sweep computes its own
        and calls the setter once per point, so the refusal belongs here
        too - this is the last place before the wire.
        """
        volts = float(volts)
        if volts < 0:
            raise LimitError(
                f"{self.DISPLAY_NAME}: {volts:.6g} V is negative, and a "
                f"power supply cannot reverse its terminals. Swap the "
                f"leads, or use an SMU for a sweep through zero.")
        limits = self.LIMITS
        if limits is not None and volts > limits.max_voltage:
            raise LimitError(
                f"{self.DISPLAY_NAME}: {volts:.6g} V is above this "
                f"model's maximum of {limits.max_voltage:.6g} V.")
        return volts

    def _checked_current(self, amps):
        """Refuse a current this instrument cannot be set to.

        Zero is refused along with everything else below the floor, and
        that is the one that surprises: every SMU settles to zero by
        writing a zero level. A supply's current setting does not reach
        zero, so the settle-to-zero path here is `output_off()`.
        """
        amps = float(amps)
        if amps < 0:
            raise LimitError(
                f"{self.DISPLAY_NAME}: {amps:.6g} A is negative, which "
                f"means current into the instrument, and a power supply "
                f"cannot sink. Use an electronic load or an SMU.")
        floor = self.MIN_CURRENT_A
        if floor is not None and amps < floor:
            raise LimitError(
                f"{self.DISPLAY_NAME}: a current setting of {amps:.6g} A "
                f"is below the smallest this model accepts "
                f"({floor:.6g} A). That holds for zero too - the current "
                f"setting does not reach it. To stop the output driving "
                f"anything, switch it off with output_off().")
        limits = self.LIMITS
        if limits is not None and amps > limits.max_current:
            raise LimitError(
                f"{self.DISPLAY_NAME}: {amps:.6g} A is above this model's "
                f"maximum of {limits.max_current:.6g} A.")
        return amps

    def validate_source_point(self, current=None, voltage=None,
                              sourcing=None):
        """The envelope, the quadrant and the current floor - checked
        before the run.

        The setters refuse the same things, on the worker thread, where
        a refusal reaches the console and nothing else. Here it is a
        dialog before anything is energised.

        The current floor applies to **both** arguments' roles. Every
        caller passes a level for one quantity and a compliance for the
        other, and on a supply the current compliance is the current
        setting - so a 1 mA compliance is as unsettable as a 1 mA level.
        The sign is only checked on the quantity being commanded, for
        the reason `SMULimits` gives: a compliance is a magnitude.
        """
        if sourcing == "voltage" and voltage is not None and voltage < 0:
            raise LimitError(
                f"Requested voltage {float(voltage):.6g} V is negative, "
                f"and {self.DISPLAY_NAME} is a power supply: it cannot "
                f"reverse its terminals. Swap the leads, or use an SMU "
                f"for a sweep through zero.")
        if sourcing == "current" and current is not None and current < 0:
            raise LimitError(
                f"Requested current {float(current):.6g} A is negative, "
                f"which means current into the instrument, and "
                f"{self.DISPLAY_NAME} is a power supply: it cannot sink. "
                f"Use an electronic load or an SMU.")
        floor = self.MIN_CURRENT_A
        if (floor is not None and current is not None
                and abs(float(current)) < floor):
            role = "level" if sourcing == "current" else "compliance"
            raise LimitError(
                f"Requested current {role} {abs(float(current)):.6g} A is "
                f"below the smallest current setting {self.DISPLAY_NAME} "
                f"accepts ({floor:.6g} A). On a supply the level and the "
                f"compliance are the same knob, so the floor is under "
                f"both.")
        if self.LIMITS is not None:
            self.LIMITS.validate_source_point(
                current=None if current is None else abs(float(current)),
                voltage=None if voltage is None else abs(float(voltage)),
                sourcing=sourcing)

    # ---- ranging: there is none ----
    def apply_ranges(self, plan, log=None):
        """Report that there is nothing to range, and what that costs.

        Sends nothing. A supply has one range per quantity, so the plan
        cannot change what the instrument does - but it must still be
        answered honestly, because the string returned here goes into
        run metadata as the ranges the data was taken on.

        The U2722A's lesson again: the driver absorbs the mismatch so no
        experiment has to know, and what is recorded is what is actually
        in force rather than what was asked for.
        """
        limits = self.LIMITS
        span = ("" if limits is None else
                f" ({limits.max_voltage:.6g} V, {limits.max_current:.6g} A)")
        steps = ", ".join(
            f"{step:g} {unit}" for step, unit in (
                (self.RESOLUTION.get("voltage"), "V"),
                (self.RESOLUTION.get("current"), "A"))
            if step)
        described = f"fixed - one range per quantity{span}" + (
            f", steps of {steps}" if steps else "")
        if log:
            log(f"{self.DISPLAY_NAME}: there is one range per quantity and "
                f"nothing to select. Requested {plan.describe()}; recorded "
                f"as {described}.")
        return described

    # ---- which knob is in charge ----
    def regulation(self):
        """`CV`, `CC`, `CROSSED`, or `None` for "this driver cannot say".

        `None` rather than a guess, and the default: a model whose
        driver has no confirmed way to ask is not reporting constant
        voltage by saying nothing.
        """
        return None

    def compliance_tripped(self):
        """Whether the supply is regulating at the compliance.

        True, False, or None for "cannot say" - the contract every
        instrument answers.

        Sourcing voltage, the compliance is the current setting, so this
        is true in constant current. Sourcing current it is the other
        way round: the supply sitting in constant voltage means the load
        would not take the current asked for, and the reading is of the
        voltage ceiling rather than of the sample.

        **False with the output off**, as far as this driver's own
        commands know: nothing is being regulated, so nothing is
        clamped. `None` when the output is on and the regulation state
        is unknown, which is not the same statement and must not render
        as one.
        """
        if not self._output_enabled:
            return False
        if self._source_function is None:
            return None
        state = self.regulation()
        if state is None:
            return None
        if state == CROSSED:
            # It reached the ceiling at some point since the last
            # question. That is a clamped interval whichever side of it
            # the supply is on now.
            return True
        clamped = CC if self._source_function == "voltage" else CV
        return state == clamped

    # ---- output ----
    def output_on(self):
        """Enable the output.

        Implemented here so the bookkeeping `compliance_tripped()`
        depends on cannot be forgotten; a driver supplies
        `_switch_output()`.
        """
        self._switch_output(True)
        self._output_enabled = True

    def output_off(self):
        """Disable the output.

        The flag is cleared **before** the write, not after. If the
        write fails the output may still be on - but the alternative is
        a driver that goes on describing itself as energised after its
        caller has been told the shutdown raised, and every path that
        handles that exception already treats the instrument as live.
        """
        self._output_enabled = False
        self._switch_output(False)

    def _switch_output(self, on):
        """Write the output switch, the way the instrument spells it."""
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} must implement _switch_output().")

    # ---- the over-voltage trip ----
    @classmethod
    def supports_overvoltage_trip(cls):
        """True when this model has an over-voltage trip the bus can
        set."""
        return cls.OVP_RANGE_V is not None

    def set_overvoltage_trip(self, volts):
        """Set the over-voltage trip, in volts.

        A trip, not a ceiling: when the output voltage exceeds it the
        output shuts down. It is what protects whatever is attached from
        a sense lead falling off and the supply winding its output up to
        compensate.
        """
        window = self.OVP_RANGE_V
        if window is None:
            raise NotImplementedError(
                f"{self.DISPLAY_NAME} has no settable over-voltage trip.")
        volts = float(volts)
        low, high = window
        if not low <= volts <= high:
            raise LimitError(
                f"{self.DISPLAY_NAME}: an over-voltage trip of "
                f"{volts:.6g} V is outside what this model accepts "
                f"({low:g} V to {high:g} V).")
        self._send_overvoltage_trip(volts)

    def _send_overvoltage_trip(self, volts):
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} must implement _send_overvoltage_trip().")

    def protection_tripped(self):
        """Whether a protection has shut the output down.

        True, False, or None for "cannot say". Separate from
        `compliance_tripped()` because it is the other kind of event: a
        compliance clamps and the run continues, a trip ends it.
        """
        return None

    # ---- reading settings back ----
    def read_voltage_setpoint(self):
        """The voltage setting the instrument reports, in volts.

        `None` where the driver has no confirmed spelling for the query
        - the rule every readback in this suite follows, because an
        unrecognised query is never answered and latches the transport.
        """
        return None

    def read_current_setpoint(self):
        """The current setting the instrument reports, in amps."""
        return None

    def read_overvoltage_trip(self):
        """The over-voltage trip the instrument reports, in volts."""
        return None

    @classmethod
    def supports_setpoint_readback(cls, quantity):
        """True when this driver implements the query for `quantity`."""
        name = cls._setpoint_reader_name(quantity)
        return getattr(cls, name) is not getattr(BaseSupply, name)

    @staticmethod
    def _setpoint_reader_name(quantity):
        if quantity not in ("voltage", "current"):
            raise ValueError(f"Unknown quantity: {quantity!r}")
        return f"read_{quantity}_setpoint"

    def _within_a_step(self, quantity, tolerance):
        """A matcher that allows one step of the setting grid.

        A fractional tolerance alone is wrong at the bottom of the
        range: one percent of a 50 mV setting is half a millivolt, and
        the instrument can only answer in whole steps of ten.
        """
        step = self.RESOLUTION.get(quantity) or 0.0

        def matcher(requested, reported):
            allowed = max(step, abs(requested) * tolerance)
            # A hair over, so a reply exactly one step out is not
            # refused by the last bit of a float subtraction.
            return abs(abs(reported) - abs(requested)) <= allowed * (1 + 1e-9)
        return matcher

    def verify_setpoint(self, quantity, expected,
                        tolerance=_readback.DEFAULT_TOLERANCE):
        """Is the instrument holding the setting that was sent?

        Returns a `core.readback.Readback`, graded by the same reader
        the SMU fleet's compliance and range checks go through.
        """
        unit = "V" if quantity == "voltage" else "A"
        reader = getattr(self, self._setpoint_reader_name(quantity))
        return self._read_and_compare(
            f"{quantity} setting", float(expected), reader,
            supported=self.supports_setpoint_readback(quantity),
            trusted=bool(self.SETPOINT_READBACK_TRUSTED),
            unit=unit, tolerance=tolerance,
            matcher=self._within_a_step(quantity, tolerance),
            unsupported_detail=f"{self.DISPLAY_NAME} has no confirmed "
                               f"query for its {quantity} setting")

    def verify_overvoltage_trip(self, expected,
                                tolerance=_readback.DEFAULT_TOLERANCE):
        """Is the over-voltage trip where it was put?"""
        supported = (type(self).read_overvoltage_trip
                     is not BaseSupply.read_overvoltage_trip)
        return self._read_and_compare(
            "over-voltage trip", float(expected),
            self.read_overvoltage_trip,
            supported=supported,
            trusted=bool(self.OVP_READBACK_TRUSTED),
            unit="V", tolerance=tolerance,
            matcher=self._within_a_step("voltage", tolerance),
            unsupported_detail=f"{self.DISPLAY_NAME} does not report its "
                               f"over-voltage trip")
