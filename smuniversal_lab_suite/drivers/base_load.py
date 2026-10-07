"""
The electronic load contract - `BaseSMU`'s sibling.

A load carries the measurement: it sets the operating point and reads V
and I back. By the test in `docs/architecture/devices.md` - *does it
carry the measurement?* - that makes it a driver rather than a device.
But it is not a source-measure unit, and the differences are not
features it happens to lack:

  * **It cannot source.** Something else must push power into it. An SMU
    energises a passive sample; a load is energised *by* the sample, so
    every safety intuition inherited from `BaseSMU` has to be re-read
    rather than reused. See `output_off` below.
  * **It has no compliance.** Its OCP and OPP are *trips* that shut the
    input down, not ceilings it regulates at. Mapping a compliance
    setter onto one would be fault 11 written on purpose.
  * **It is one quadrant.** Positive terminal voltage, current inward,
    and nothing else - ever.
  * **It has a floor made of headroom.** The pass element needs volts
    across it to regulate, so below some terminal voltage the load stops
    controlling anything. The floor rises with current, and it is
    usually undocumented.

Why it is not a `BaseSMU` subclass
----------------------------------
It would inherit a contract half of whose questions are meaningless for
it, and answer them `False` in a ledger where every other `False` means
"this model lacks this feature". Worse, `issubclass(load, BaseSMU)`
would be true, so every guard written against that would wave it
through in the dangerous direction. Both fleets sit on `BaseInstrument`
instead; `drivers/registry.py` keeps them in separate lists and
identifies from the union.

The sign convention, which is this file's sharpest edge
-------------------------------------------------------
A load's own ammeter reads a sink as **positive**. An SMU measuring the
same illuminated solar cell reads **negative**, because the current
flows into its HI terminal. Same cell, same operating point, opposite
numbers in a column with the same name - and `iv_math.fit_sweep` turns
that into a resistance whose sign flips with it.

So a load driver negates at the boundary, and this class does it rather
than leaving it to each driver to remember: `measure()` is implemented
here and calls the abstract `measure_sinking()`. A concrete driver
reports what its instrument said, in the instrument's own convention,
and physically cannot forget the flip. The same applies in reverse to
`set_current_level()`.

The consequence worth stating plainly: **in this suite a sinking current
is negative.** A solar cell under illumination sits in the fourth
quadrant - voltage positive, current negative - whether it was measured
by a load or by an SMU, which is the entire point.
"""
from smuniversal_lab_suite.core.limits import LimitError

from .base_instrument import BaseInstrument


class BaseLoad(BaseInstrument):
    """What every electronic load in this suite implements."""

    # ---- what a load has instead of a compliance ----
    #
    # `False` is read by the experiments, which ask
    # `supports_compliance()` the same way they already ask
    # `supports_ovp()`. They never ask what kind of instrument this is.
    HAS_COMPLIANCE = False

    #: A load sinks. Nothing it can do puts power into a sample, so the
    #: experiments built on sourcing one refuse it at connect rather
    #: than at Run - see `Experiment.ROLE_REQUIRES`.
    CAN_SOURCE = False

    #: True where the model's protections stop the input rather than
    #: regulating at a ceiling. Declared rather than assumed because the
    #: difference decides what a run does when one fires: a compliance
    #: clamps and the sweep continues with clamped data, a trip ends the
    #: measurement. Recorded in run metadata so the distinction survives
    #: into the file.
    PROTECTION_IS_TRIP = True

    def set_current_limit(self, amps):
        """There is no current compliance on a load.

        Raises rather than doing nothing. A silent no-op here is exactly
        fault 11 - the caller believes a ceiling is in force, the
        instrument was never told, and the first evidence is a sample
        that took more than anyone intended.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} is an electronic load and has no current "
            f"compliance. Its over-current protection is a trip that stops "
            f"the input, not a ceiling it regulates at. Check "
            f"supports_compliance() before calling this.")

    def set_voltage_limit(self, volts):
        """There is no voltage compliance on a load. See above."""
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} is an electronic load and has no voltage "
            f"compliance. Check supports_compliance() before calling this.")

    # ---- the measurement, and the flip ----
    def measure(self, timeout_s=3.0):
        """One reading, in **this suite's** sign convention.

        Returns `(volts, amps)` with a sinking current **negative**.

        Implemented here and final in practice: a driver supplies
        `measure_sinking()` in its instrument's own convention and this
        does the flip. Leaving the negation to each driver would make it
        a thing to remember, and the failure mode of forgetting is a
        complete, plausible, sign-inverted IV curve - which no test that
        checks shape rather than sign would catch, and which fits to a
        resistance of the wrong sign.
        """
        volts, amps = self.measure_sinking(timeout_s=timeout_s)
        # `+ 0.0` normalises the negative zero that -float(0.0)
        # produces. A "-0" in a current column is not wrong, but
        # it reads as a measurement someone should look at.
        return volts, (None if amps is None else -float(amps) + 0.0)

    def measure_sinking(self, timeout_s=3.0):
        """One reading in the **instrument's** convention: sink positive.

        Abstract in effect - `measure()` above is the contract method
        and this is what it is built from. A driver implements this one
        and never touches `measure()`.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} must implement measure_sinking().")

    #: A positive level this small is a rounding error on zero, not a
    #: request to source. A picoamp: nine orders below anything a load
    #: here resolves, and far above what float arithmetic on a sweep's
    #: levels leaves behind (1e-17 A, seen 2026-10-07).
    ZERO_CURRENT_SLACK_A = 1e-12

    def set_current_level(self, amps):
        """Set the CC setpoint, given a level in the suite's convention.

        So `amps` is **negative** to sink. Refuses a positive request
        rather than taking its magnitude: a positive current means
        sourcing, this instrument cannot source, and quietly sinking
        instead would be the one error that looks exactly like success.
        """
        amps = float(amps)
        if 0 < amps <= self.ZERO_CURRENT_SLACK_A:
            # A sweep that ends at zero computes its last level as
            # start + step * (n - 1), and from -0.026 A that came out as
            # +3.5e-18 A - refused below as a request to source. It is
            # zero, and is sent as zero.
            amps = 0.0
        if amps > 0:
            raise LimitError(
                f"{self.DISPLAY_NAME}: a current level of +{amps:.6g} A "
                f"means current out of the instrument, and an electronic "
                f"load can only sink. Ask for {-amps:.6g} A to sink that "
                f"much.")
        self.set_sink_current(abs(amps))

    def set_sink_current(self, amps):
        """Set the CC setpoint as a positive magnitude, the way the
        instrument's own command spells it."""
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} must implement set_sink_current().")

    # ---- the gate: a level, and a range beside it ----
    def validate_source_point(self, current=None, voltage=None,
                              sourcing=None):
        """Check the commanded level and the range beside it, separately.

        Every experiment hands this gate the swept level for one
        quantity and its "compliance" for the other. On an SMU that
        second number is a limit the instrument will regulate at, so
        level x compliance is the most power the run can reach and
        checking the product against a power ceiling is right.

        **On a load it is the measurement range**, 18 V or 120 V on the
        72-13200, and nothing regulates there. Multiplying by it
        refused every current sweep above 150 W / 18 V = 8.33 A - on a
        solar cell sitting at 0.6 V and under 5 W (seen 2026-10-07) -
        and above 1.25 A on the 120 V range.

        So with `sourcing` given, the two are checked one at a time:
        the level against its maximum and its polarity, the range
        against its own maximum, and no product. What a load's power
        actually is depends on the source attached, which this gate
        cannot know; the instrument's own over-power protection stops
        the input if it is exceeded (`PROTECTION_IS_TRIP`), and that is
        the protection relied on.

        With `sourcing` None both values are a real operating point,
        and the product is checked as before.
        """
        if self.LIMITS is None:
            return
        if sourcing not in ("current", "voltage"):
            self.LIMITS.validate_source_point(
                current=current, voltage=voltage, sourcing=sourcing)
            return
        if current is not None:
            self.LIMITS.validate_source_point(current=current,
                                              sourcing=sourcing)
        if voltage is not None:
            self.LIMITS.validate_source_point(voltage=voltage,
                                              sourcing=sourcing)

    # ---- how long a point takes ----
    #: Seconds this model needs between a new setpoint and a reading
    #: that describes it. Zero means "not known to need any".
    SETTLING_S = 0.0

    def minimum_point_delay(self, mode):
        """The shortest per-point delay a sweep in `mode` may use, in s.

        Asked by the experiments before a run. A sweep stepped faster
        than this records the instrument on its way to each level
        rather than at it, in a file that looks like any other.
        """
        return float(self.SETTLING_S or 0.0)

    # ---- did it do what it was asked? ----
    #: A CV point within this of its setpoint, or within 1% of it, was
    #: followed. The 72-13200 holds a reachable setpoint to 0.3 mV.
    REGULATION_TOLERANCE_V = 0.005
    #: The same for a CC point, in amps.
    REGULATION_TOLERANCE_A = 0.005

    def regulation_report(self, mode, asked, volts, amps):
        """Say where a finished sweep did not reach what it asked for.

        `asked` is the commanded levels, `volts` and `amps` the readings
        at each, in the suite's convention. Returns one sentence per
        kind of shortfall, joined, or "" when every point was followed.

        A load does not refuse a level it cannot hold. It reports
        whatever is across its terminals and the sweep completes, so
        the only evidence is the gap between the two columns. Three
        gaps in a voltage sweep, with different causes and remedies:

        * **Fully on.** The source stayed above the setpoint with
          current flowing: the load is at its minimum resistance and
          the source can push that current through the loop without
          dropping further. Not a fault - the bottom of what this load
          can reach on this source.
        * **Held below the setpoint, still sinking.** The CV loop has
          stopped responding. Measured on the 72-13200 with a weak
          source (2026-10-07): once pulled onto the flat part of a
          solar cell's curve it never let go, 45 s and a setpoint above
          open circuit included.
        * **Not sinking with the source above the setpoint.** The input
          is off or a protection has tripped.

        A point below its setpoint with no current is none of these:
        the source's open-circuit voltage is simply lower than what was
        asked, and nothing is wrong.

        In a current sweep there is one: the source could not supply
        the current, so every point past its limit is the same point.
        """
        n = min(len(asked), len(volts), len(amps))
        if n == 0:
            return ""
        asked, volts, amps = asked[:n], volts[:n], amps[:n]
        flowing = max(0.002, 0.02 * max(abs(i) for i in amps))
        notes = []

        if mode == "voltage":
            fully_on, stuck, idle = [], [], []
            for want, v, i in zip(asked, volts, amps):
                slack = max(self.REGULATION_TOLERANCE_V, 0.01 * abs(want))
                if abs(v - want) <= slack:
                    continue
                sinking = abs(i) > flowing
                if v > want:
                    (fully_on if sinking else idle).append((want, v, i))
                elif sinking:
                    stuck.append((want, v, i))
            if fully_on:
                _, v, i = min(fully_on, key=lambda p: p[1])
                notes.append(
                    f"{len(fully_on)} of {n} points were below what this "
                    f"load can reach on this source: fully on, it held "
                    f"{v:.4g} V at {abs(i):.4g} A "
                    f"({v / abs(i) * 1000:.3g} mOhm around the loop) and "
                    f"could pull no lower. Those points repeat one "
                    f"operating point; start the sweep at {v:.3g} V")
            if stuck:
                want, v, i = max(stuck, key=lambda p: p[0] - p[1])
                notes.append(
                    f"{len(stuck)} of {n} points were held BELOW the "
                    f"setpoint while still sinking - asked {want:.4g} V, "
                    f"measured {v:.4g} V at {abs(i):.4g} A. The load's "
                    f"voltage loop stopped responding, which it does once "
                    f"a weak source is pulled onto the flat part of its "
                    f"curve, and it stays that way until the input is "
                    f"switched off. These points are not the source's "
                    f"curve. Sweep current instead, or use an SMU for a "
                    f"source this small")
            if idle:
                want, v, _ = idle[0]
                notes.append(
                    f"{len(idle)} of {n} points sank nothing with the "
                    f"source above the setpoint (asked {want:.4g} V, "
                    f"measured {v:.4g} V). The input is off or a "
                    f"protection has tripped")
        else:
            short = [(want, v, i) for want, v, i in zip(asked, volts, amps)
                     if abs(want) - abs(i) > max(self.REGULATION_TOLERANCE_A,
                                                 0.01 * abs(want))]
            if short:
                _, v, i = max(short, key=lambda p: abs(p[2]))
                notes.append(
                    f"{len(short)} of {n} points asked for more current "
                    f"than the source and wiring deliver: at most "
                    f"{abs(i):.4g} A flowed, with {v:.4g} V left across "
                    f"the source. Those points repeat one operating "
                    f"point; end the sweep near {abs(i):.3g} A")
        return ". ".join(notes)

    # ---- the floor: headroom, not counts ----
    #
    # The same shape of problem as an SMU's sub-count floor, from a
    # completely different cause, and declared the same way so that
    # "nobody has measured this" cannot be mistaken for "fine".
    #
    # A load regulates by dropping voltage across a pass element. Below
    # some terminal voltage there is not enough across it to control
    # anything, and the load stops being a load - it does not error, it
    # simply stops following the setpoint while continuing to return
    # readings of exactly the right shape. The floor RISES WITH CURRENT,
    # which is why this is a function and not a constant.
    #
    # It is the boundary that decides where an IV curve stops being a
    # measurement, and on a solar cell it sits at the end of the sweep
    # that matters most: short-circuit current is at V = 0, which no
    # load can reach.

    #: Measured on this model, at known currents.
    HEADROOM_MEASURED = "measured"
    #: This model has a pass element and therefore a floor, and nobody
    #: has measured where it is. The default, and the honest answer for
    #: a driver written from a manual - no datasheet in this project's
    #: collection states one.
    HEADROOM_UNMEASURED = "unmeasured"

    HEADROOM_STATES = (HEADROOM_MEASURED, HEADROOM_UNMEASURED)

    HEADROOM_STATE = HEADROOM_UNMEASURED

    def minimum_operating_voltage(self, amps):
        """Lowest terminal voltage this model can still regulate at
        `amps`, in volts, or `None` where it has never been measured.

        `None` is not "there is no floor" - every load has one. It is
        "this model has not declared one", and the difference matters:
        the first would justify sweeping to zero, the second is a gap
        that a bench session closes. Callers say which they got rather
        than treating silence as permission.
        """
        return None

    @classmethod
    def declares_headroom(cls):
        """True when this driver can put a floor under an operating
        point.

        Keyed on `HEADROOM_STATE`, **not** on whether the method is
        overridden - and that distinction was found by this project's
        own first load driver. `BaseSMU.declares_source_level_floor()`
        treats an override as a declaration, which works there because
        overriding it means computing a floor a different way.

        Here it does not. A driver overriding
        `minimum_operating_voltage()` to return `None` with a paragraph
        saying *why nobody has measured this* is doing the most useful
        thing available, and reading that as "a floor is declared" would
        turn documentation into a false claim. The state says what is
        known; the method says what the number is.
        """
        return cls.HEADROOM_STATE == cls.HEADROOM_MEASURED

    def guard_operating_point(self, volts, amps):
        """Refuse an operating point below the headroom floor.

        Called before energising, like `BaseSMU.guard_source_level()`,
        and for the same reason: past this boundary the instrument stops
        doing what it was told without saying so, and a refusal before
        the input comes up is the only thing that distinguishes "could
        not" from "did, badly".
        """
        floor = self.minimum_operating_voltage(abs(float(amps)))
        if floor is None or abs(float(volts)) >= floor:
            return
        raise LimitError(
            f"{self.DISPLAY_NAME}: at {abs(float(amps)):.6g} A this load "
            f"needs at least {floor:.6g} V across its terminals to "
            f"regulate, and {abs(float(volts)):.6g} V was requested. Below "
            f"that the pass element has nothing to control with: the "
            f"setpoint stops being followed, no error is raised, and the "
            f"readings keep their usual shape. Refusing before the input "
            f"is enabled.")

    # ---- ranging: read, never written ----
    #: A load's per-quantity ceilings are entered at the front panel.
    #: `False` says the bus cannot set them, which is different from
    #: having none - and the difference is what the operator needs,
    #: because the ceiling sets the measurement floor through the
    #: full-scale term in the accuracy spec.
    RANGES_ARE_OPERATOR_SET = True

    def apply_ranges(self, plan, log=None):
        """Carry out what can be carried out of a ranging plan, and say
        what the rest was.

        Sends nothing. On a load there is no source range and no
        independent measurement range, and on the models here the
        per-quantity ceilings cannot be written over the bus at all - so
        the honest implementation is to *read back* what the operator
        set and record it beside the data, rather than report ranges
        that were never applied.

        That is the U2722A's lesson generalised: the driver absorbs the
        mismatch so no experiment has to know, and `apply_ranges()`
        keeps its promise to describe what is actually in force rather
        than what was asked for.
        """
        ceilings = self.read_ceilings()
        described = ", ".join(
            f"{q} {v:.6g} {u}" if v is not None else f"{q} unknown"
            for q, v, u in (("current", ceilings.get("current"), "A"),
                            ("voltage", ceilings.get("voltage"), "V")))
        message = (
            f"{self.DISPLAY_NAME}: ranges are set at the front panel and "
            f"cannot be written over the bus. Requested {plan.describe()}; "
            f"the instrument reports {described}. The ceiling sets the "
            f"full-scale term in the accuracy spec, so it decides the "
            f"measurement floor - it is recorded, not chosen.")
        if log:
            log(message)
        return f"operator-set ceilings: {described}"

    def read_ceilings(self):
        """`{"current": amps|None, "voltage": volts|None}` as the
        instrument reports them.

        `None` per axis where this driver has no confirmed query
        spelling - the same rule as every readback in this suite, and
        for the same reason: an unrecognised *command* is logged and
        ignored, an unrecognised *query* is never answered, times out
        and latches the transport. A guess costs a run rather than a
        line in a report.
        """
        return {"current": None, "voltage": None}

    # ---- what "off" means here ----
    def output_off(self):
        """Disable the input.

        Named for the contract rather than for the instrument, which
        calls it an input - the word an experiment uses must not depend
        on which fleet answered.

        **Read the safety story backwards from an SMU's.** Turning an
        SMU's output off de-energises the sample. Turning a load's input
        off stops it drawing, which leaves whatever is attached at *open
        circuit* - for an illuminated solar cell, its highest voltage,
        not its lowest. Off is safe for the instrument and is not
        automatically the safe state for what is wired to it.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} must implement output_off().")
