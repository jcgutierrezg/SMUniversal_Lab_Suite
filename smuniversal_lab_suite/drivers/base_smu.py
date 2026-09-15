"""
The SMU driver contract.

Every driver implements these methods in its own command dialect. A
Keithley 2450 speaks SCPI (":SOUR:CURR:LEV 1e-4"); a 2611A speaks TSP
("smu.source.leveli = 1e-4"). Measurement code calls
`smu.set_current_level(1e-4)` and never learns which.

This is the pin-compatible-part idea: a 2450 and a 2611A aren't the same
chip, but if they present the same footprint, the board around them
doesn't care.

Adding a new SMU = one file implementing this class + one line in
drivers/registry.py. Nothing in experiments/ changes.

If a model genuinely can't do something, leave that method raising
NotImplementedError - loud and obvious beats silently sending a command
the instrument ignores.

What is here and what is one level down
---------------------------------------
This file holds what makes an instrument a **source-measure unit**: a
source function, levels, a compliance, the four-axis `RangePlan`, and a
source converter whose bottom count a level can fall below.

Everything that is true of any bench instrument on a transport - the
identity, the no-reading sentinel, the readback grading, the software
sweep engine, the optional-capability declarations the GUI reads - lives
in `base_instrument.py`, which an electronic load sits on too. See there
for why the fork exists and where the line runs.
"""
from abc import abstractmethod

from smuniversal_lab_suite.core import readback as _readback
from smuniversal_lab_suite.core.ranges import AUTO, NOT_SOURCED, RangeError

from .base_instrument import BaseInstrument



def _show(value):
    if value is AUTO:
        return "auto"
    if value is NOT_SOURCED:
        return "not sourced"
    return f"{value:.6g}"


#: How far *below* a requested range a reply may land and still be that
#: range.
#:
#: Not a tolerance on the instrument's behaviour - a tolerance on its
#: arithmetic. A range held as a 32-bit float comes back a few parts in
#: 10^7 low, and the discrimination this check has to make is between
#: adjacent ranges a **factor of ten** apart. So this can be many orders
#: of magnitude larger than float32 epsilon (~1.19e-7) and still be
#: nowhere near able to hide a range that was silently narrowed.
_RANGE_FLOOR_SLACK = 1e-4


class BaseSMU(BaseInstrument):

    # ---- compliance ----
    #
    # Every source-measure unit has one, and it is the whole protection
    # for an output-on: the two setters below are mandatory here for
    # that reason. The declaration is what experiments read - see
    # `BaseInstrument.supports_compliance()`.
    HAS_COMPLIANCE = True

    @abstractmethod
    def set_current_limit(self, amps):
        """Set the current compliance limit, in amps."""

    @abstractmethod
    def set_voltage_limit(self, volts):
        """Set the voltage compliance limit, in volts."""

    # ---- reading state back: the contract -----------------------------
    #
    # Everything above this line is a *request*. Nothing so far proves
    # the instrument is in the state that was asked for, and a wrong
    # header does not raise - it is logged and ignored while the
    # previous setting stays in force (fault 11).
    #
    # Three subjects are read back, and they are the three whose
    # disagreement changes what a measurement means or what reaches the
    # sample: the **compliance**, the **range** and any applicable
    # **power limit**. Each answers in the vocabulary of
    # `core.readback`, whose five states are documented there. The rule
    # worth repeating here: a readback that DISAGREES is a mismatch
    # whether or not the readback itself has been verified, because
    # every reading of that observation needs a human.

    #: Has the compliance readback been checked at the bench against a
    #: value the instrument was known to hold?
    #:
    #: False by default, and False also covers "this driver cannot ask
    #: at all" - which is distinguished from an unverified answer by
    #: whether `read_current_limit` is overridden, not by this flag.
    #:
    #: The flag exists because of the GSM-20H10. Its `OUTP?` returns 0
    #: with the output demonstrably on and 10 V flowing, so at least one
    #: state query on that instrument lies - and five rounds of
    #: reasoning were built on believing it. A readback an instrument
    #: answers dishonestly is worse than none at all: it produces
    #: confident reassurance about the exact thing it exists to verify.
    COMPLIANCE_READBACK_TRUSTED = False

    #: The same question for the four ranging axes. Separate from the
    #: compliance flag because they are separate queries in separate
    #: subsystems, verified at separate bench sessions - the GSM's
    #: compliance readback was confirmed on 2026-08-20 and its range
    #: readback has never been checked against a value known
    #: independently.
    RANGE_READBACK_TRUSTED = False

    #: And for the power limit, on the models that have one.
    POWER_LIMIT_READBACK_TRUSTED = False

    #: How much wider than the smallest range that fits a reported range
    #: may be before it counts as a different range.
    #:
    #: Not a tolerance on a measurement: an instrument reports a range by
    #: its **full scale**, and the Keithley and GW Instek families set
    #: full scale 5% above the nominal decade - `1.050000E-04` is what
    #: the 100 uA range answers. So a fractional test at the 1% used for
    #: compliances would call every correct answer a mismatch. 10% sits
    #: clear of that convention and a factor of nine below the next
    #: range up, which is the thing this has to be able to tell apart.
    RANGE_READBACK_HEADROOM = 1.10

    #: The power ceiling this driver holds the instrument at, in watts,
    #: or None on a model with no such setting.
    #:
    #: 0.0 means *disabled*, which is the only value this suite ever
    #: wants: a power limit applies whichever of the three ceilings is
    #: lower, so a nonzero one silently overrides the compliance the
    #: experiment set, and reading the voltage or current limit back
    #: reports the programmed value rather than the effective one. It
    #: resets to disabled on every model that has it, but `Recall setup`
    #: can carry a nonzero one into a session and nothing else in the
    #: suite would notice.
    POWER_LIMIT_SETTING = None

    def read_current_limit(self):
        """The current compliance the instrument reports, in amps.

        `None` where the driver cannot ask. Not an exception: a driver
        that cannot read this back is not broken, it is a driver for an
        instrument that does not answer, and every caller here has
        something useful to do with that.
        """
        return None

    def read_voltage_limit(self):
        """The voltage compliance the instrument reports, in volts."""
        return None

    def read_source_current_range(self):
        """The source current range the instrument reports, in amps.

        `None` where this driver has no confirmed spelling for the
        query. That is a real state and not a placeholder: sending a
        header the instrument does not have means a query that is never
        answered, which times out and latches the
        transport. Guessing here would trade a gap in a report for a
        lost run, so a driver implements this only where the spelling
        came off a manual or a bench.
        """
        return None

    def read_source_voltage_range(self):
        """The source voltage range the instrument reports, in volts."""
        return None

    def read_measure_current_range(self):
        """The measurement current range the instrument reports, in amps."""
        return None

    def read_measure_voltage_range(self):
        """The measurement voltage range the instrument reports, in volts."""
        return None

    def read_power_limit(self):
        """The power ceiling the instrument reports, in watts."""
        return None

    #: The four ranging axes, mapped to the reader for each. Named once
    #: so the checkup, the contract ledger and `verify_range()` cannot
    #: drift apart on what an axis is called.
    RANGE_AXES = ("source_current", "source_voltage",
                  "measure_current", "measure_voltage")

    @classmethod
    def _range_reader_name(cls, axis):
        if axis not in cls.RANGE_AXES:
            raise ValueError(
                f"Unknown ranging axis: {axis!r}. One of {cls.RANGE_AXES}.")
        return f"read_{axis}_range"

    @classmethod
    def supports_compliance_readback(cls):
        """True when this driver implements a compliance query.

        Asked of the class rather than of a reply, because a `None` from
        a driver that never implemented the reader means something
        completely different from a `None` from one that did - the first
        is a model difference, the second is a query that has stopped
        answering. Collapsing them would hide the second behind the
        first.
        """
        return (cls.read_current_limit is not BaseSMU.read_current_limit
                or cls.read_voltage_limit is not BaseSMU.read_voltage_limit)

    @classmethod
    def supports_range_readback(cls, axis):
        """True when this driver implements the query for one axis."""
        name = cls._range_reader_name(axis)
        return getattr(cls, name) is not getattr(BaseSMU, name)

    @classmethod
    def supports_power_limit_readback(cls):
        """True when this driver implements the power-ceiling query."""
        return cls.read_power_limit is not BaseSMU.read_power_limit

    def verify_compliance(self, mode, expected,
                          tolerance=_readback.DEFAULT_TOLERANCE):
        """Did the compliance survive whatever just happened to it?

        Returns a `core.readback.Readback`.

        This exists because of what a ranging command did on the
        GSM-20H10: `SOUR:CURR:RANG:AUTO ON` took a 105 uA compliance to
        **1 nA**, with a clean error queue and nothing raised. It only
        ever surfaced because a later, innocent command tripped over the
        collapsed value and complained about something else. Nothing in
        this suite read a compliance back, so on an instrument where
        nothing downstream trips, the collapse is invisible - which is
        why five of seven instruments in the 2026-08-18 round are
        "none observed" rather than "none".

        `mode` is the quantity being *sourced*, so the compliance being
        checked is the other one.
        """
        reader = (self.read_current_limit if mode == "voltage"
                  else self.read_voltage_limit)
        unit = "A" if mode == "voltage" else "V"
        subject = f"{'current' if mode == 'voltage' else 'voltage'} compliance"
        return self._read_and_compare(
            subject, expected, reader,
            supported=self.supports_compliance_readback(),
            trusted=bool(self.COMPLIANCE_READBACK_TRUSTED),
            unit=unit, tolerance=tolerance,
            unsupported_detail=f"{self.DISPLAY_NAME} does not report its "
                               f"compliance limit - which is a different "
                               f"gap from the trip flag, and several "
                               f"models here report one and not the "
                               f"other")

    def verify_range(self, axis, expected,
                     tolerance=_readback.DEFAULT_TOLERANCE):
        """Is the instrument on the range that was applied to `axis`?

        Returns a `core.readback.Readback`. `expected` is a magnitude in
        amps or volts, or `AUTO` - for which there is nothing to compare
        and the answer is informational rather than a verdict.

        This is the half of "apply_ranges reports what it sent, not what
        was accepted" that stayed open after the compliance readback
        landed. It is not a lesser half: on the GSM-20H10, asking for a
        100 uA measurement range with a 10 uA compliance in force gives
        `+824` and leaves the instrument on 10.5 uA, so every reading
        afterwards is taken on a range the operator did not choose and
        overranges into a sentinel rather than reading.
        """
        unit = "A" if axis.endswith("current") else "V"
        reader = getattr(self, self._range_reader_name(axis))
        subject = f"{axis.replace('_', ' ')} range"

        if expected is AUTO or expected is NOT_SOURCED:
            # Nothing to compare against. `AUTO` is a request that the
            # instrument choose, so any range it names satisfies it, and
            # NOT_SOURCED means the axis was never given one. Reporting
            # either as CONFIRMED would be a pass earned by asking a
            # question with no wrong answer, which is fault 19.
            return _readback.Readback(
                subject, _readback.UNSUPPORTED,
                f"{_show(expected)} was requested, so there is no value "
                f"to confirm against",
                unit=unit)

        wanted = abs(float(expected))
        nearest = (self.LIMITS.nearest_current_range(wanted)
                   if unit == "A" else
                   self.LIMITS.nearest_voltage_range(wanted)) \
            if self.LIMITS is not None else None
        ceiling = (nearest or wanted) * self.RANGE_READBACK_HEADROOM

        def on_a_range_that_carries_it(_requested, reported):
            # The lower bound is relaxed, and house rule 9 is the whole
            # reason: an exact `wanted <= reported` compares a decimal
            # against whatever the instrument can represent, and the
            # 2600-series TSP layer stores a range as a **32-bit
            # float**. Both instruments answer a requested 1e-4 with
            # 9.999999747378752e-05 - that is float32(1e-4) widened, not
            # a narrower range - and an exact bound calls a correct
            # instrument a SAFETY failure by 2.5e-13 relative.
            #
            # Measured on 2026-09-04: the 2611A (firmware 2.2.2) and the
            # 2635B (firmware 3.2.2) returned byte-identical values, so
            # this is the representation and not one instrument.
            return (wanted * (1.0 - _RANGE_FLOOR_SLACK)
                    <= abs(reported) <= ceiling)

        return self._read_and_compare(
            subject, wanted, reader,
            supported=self.supports_range_readback(axis),
            trusted=bool(self.RANGE_READBACK_TRUSTED),
            unit=unit, tolerance=tolerance,
            matcher=on_a_range_that_carries_it,
            mismatch_note=(
                f"A range that carries {wanted:.6g} {unit} on this model "
                f"reports between {wanted:.6g} and {ceiling:.6g} {unit}. "
                f"Narrower than that clamps a source level and overranges "
                f"a reading into a sentinel; wider means resolution was "
                f"given away without anyone choosing to"),
            unsupported_detail=f"{self.DISPLAY_NAME} has no confirmed "
                               f"query for this range, so what it is "
                               f"actually on is unknown")

    def verify_power_limit(self, tolerance=_readback.DEFAULT_TOLERANCE):
        """Is the power ceiling where this driver put it?

        Returns a `core.readback.Readback`. On a model with no power
        limit the subject does not exist and the answer is
        ``UNSUPPORTED``; on a model that has one, the expected value is
        `POWER_LIMIT_SETTING` and a disagreement is a mismatch even
        where the readback is unverified - a ceiling nobody set that
        overrides the compliance the experiment chose is exactly the
        case that must not be discovered from the data.
        """
        expected = self.POWER_LIMIT_SETTING
        if expected is None:
            return _readback.Readback(
                "power limit", _readback.UNSUPPORTED,
                f"{self.DISPLAY_NAME} has no power-limit setting",
                unit="W")
        return self._read_and_compare(
            "power limit", expected, self.read_power_limit,
            supported=self.supports_power_limit_readback(),
            trusted=bool(self.POWER_LIMIT_READBACK_TRUSTED),
            unit="W", tolerance=tolerance,
            unsupported_detail=f"{self.DISPLAY_NAME} holds its power limit "
                               f"at {expected:g} W and cannot be asked "
                               f"what it is actually on")

    # ---- source levels below one count of the active range ------------
    #
    # Every fixed-range converter has a bottom count, and below it a
    # commanded level is not a small signal but offset residue. The
    # U2722A bench session on 2026-08-25 established what that means in
    # the only way that leaves nothing to interpret: on R120mA, where
    # one count is 7.32 uA, commanding `-1 uA` and `+1 uA` produced the
    # **same output**. The sign was ignored, and during the
    # commissioning round the residue pointed the wrong way and walked
    # the output to the range rail against a compliance that was working
    # correctly the whole time.
    #
    # Nothing about that mechanism is specific to the U2722A. What
    # differs between instruments is whether anyone has measured it - so
    # each driver declares which, and the declaration is checked against
    # the contract ledger rather than left to be discovered.

    #: Sub-count behaviour has been measured and the driver refuses.
    SUB_COUNT_REFUSED = "refused"
    #: The axis has a fixed source range with a bottom count, and what
    #: happens below it has never been measured on this model.
    SUB_COUNT_UNMEASURED = "unmeasured"
    #: The question does not arise in this form - there is no source
    #: range for this quantity, or there is no converter at all.
    SUB_COUNT_NOT_APPLICABLE = "not applicable"

    SUB_COUNT_STATES = (SUB_COUNT_REFUSED, SUB_COUNT_UNMEASURED,
                        SUB_COUNT_NOT_APPLICABLE)

    #: The smallest source level worth commanding, in counts of the
    #: active range. Below this the driver refuses rather than commanding
    #: a level the converter cannot express.
    #:
    #: One count is the floor where a request means *something* at all,
    #: and there the quantisation error is 100%. Ten caps it at 10%,
    #: which is the number this project chose - it is a decision, not a
    #: measurement, and it is one constant to change.
    #:
    #: It bounds quantisation error and **nothing more**. It is not a
    #: guarantee that the sign comes out right: probe G saw current
    #: readings excursing to twelve counts on the U2722A's R120mA, and
    #: separating source residue from measurement noise there needs a
    #: known load, which has not been done.
    #:
    #: Lived on the U2722A until 2026-09-04, when the 2026-09-01 bench
    #: round measured a floor on five more instruments and the constant
    #: stopped belonging to one driver.
    MIN_LEVEL_COUNTS = 10

    #: A level this far below the floor is the zero a sweep meant, not a
    #: level anyone asked for, and the floor lets it through.
    #:
    #: Sweeps compute their levels - `start + step * i`, `np.linspace` -
    #: and for many ordinary point counts the one that should be zero
    #: comes out as a few times 1e-20. A −100 uA to +100 uA current sweep
    #: in 201 points puts −1.36e-20 A at its midpoint, and so do 84 of the
    #: odd point counts from 3 to 1001 over that span. The floor exempted
    #: only an exact zero, so that point was refused and the run ended
    #: halfway: a current IV sweep on the 2401, 2635B and B2901A, and a
    #: 4PP triangular sweep - which always crosses zero - on every driver
    #: with a current floor. Found 2026-09-11, offline, a week after the
    #: floors landed; the checkup never sweeps through zero.
    #:
    #: The U2722A's own refusal had the same gap for longer, on voltage as
    #: well - 31 of the odd point counts for a −1 V to +1 V sweep.
    #:
    #: A millionth of the floor is below anything a source can express by
    #: many orders, and residue is about 1e-16 of the sweep's span, which
    #: every experiment makes the source range - so the two cannot be
    #: confused. With the range left on AUTO the floor falls back to the
    #: narrowest range's, and a wide sweep's residue could exceed this;
    #: no experiment does that.
    ZERO_RESIDUE_FRACTION = 1e-6

    #: How many counts the SOURCE converter has across one range, per
    #: axis. `None` means this model's converter has not been
    #: characterised on that axis, and then no floor is declared.
    #:
    #: **Counts, not amps.** This is the whole lesson of the 2026-09-01
    #: round and the reason a single measured number must not be written
    #: into a driver. The B2901A's floor was measured twice:
    #:
    #:     2026-08-27, source range pinned to 1 A     6.250e-06 A
    #:     2026-09-01, source range pinned to 100 uA  7.629e-10 A
    #:
    #: Four orders apart on one instrument, and the ratio is the ratio
    #: of the two ranges. The floor is a property of the RANGE. Held as
    #: counts it survives ranging; held as an absolute current it would
    #: be right on one range and wrong on every other.
    #:
    #: `tools/bench_envelope.py` pins `_apply_source_current_range(1e-4)`
    #: before sweeping, so every 2026-09-01 figure is a floor **on the
    #: 100 uA source range**, and each driver's count declaration is the
    #: one that reproduces its own measured floor as one count of that
    #: range. See the per-driver constants for the arithmetic.
    #:
    #: **A declared count is a refusal threshold, not a converter
    #: width.** Two things the 2026-09-11 round established:
    #:
    #: * the walk halves from full scale, so every level it tries is the
    #:   range over a power of two, and any crossing "matches" some
    #:   power-of-two count. That match is guaranteed, and is not
    #:   evidence about the converter.
    #: * where the legs stop straddling zero is mostly where the level
    #:   falls below the output's zero offset on that range, and the
    #:   offset drifts: the 2611A's halved in ten days and its crossing
    #:   moved with it. It is also only the part of the offset the
    #:   instrument's own readings can see.
    #:
    #: So the floor is carried by `MIN_LEVEL_COUNTS`, the factor between
    #: the crossing and the refusal, not by the count being exact.
    SOURCE_COUNTS_PER_RANGE = {"current": None, "voltage": None}

    #: Per quantity, what is known about levels below one count.
    #:
    #: The default is `unmeasured` on both axes, which is the honest
    #: answer for six of the eight drivers here and must stay the
    #: default: a driver that says nothing has to read as "nobody
    #: looked", never as "fine".
    SUB_COUNT_LEVELS = {"current": SUB_COUNT_UNMEASURED,
                        "voltage": SUB_COUNT_UNMEASURED}

    @classmethod
    def sub_count_state(cls, quantity):
        """What is known about sub-count levels of `quantity` here."""
        if quantity not in ("current", "voltage"):
            raise ValueError(f"Unknown quantity: {quantity!r}")
        return cls.SUB_COUNT_LEVELS.get(quantity, cls.SUB_COUNT_UNMEASURED)

    def source_level_floor(self, quantity):
        """Smallest magnitude of `quantity` worth commanding *right now*.

        In amps or volts, or `None` when this model declares no floor.

        Deliberately an instance method and deliberately about the range
        that is active at the moment of asking, not about the narrowest
        range the instrument owns. The floor is a property of the
        selected range: 1 uA is eleven counts on the U2722A's R1uA range
        and a seventh of one count on its R120mA range, and which of
        those a caller is in depends on the ranging plan that has
        already been carried out. A floor computed from the model alone
        would be right on one range and wrong on five.

        `None` is not "there is no floor" - it is "this model has not
        declared one", which means the converter's bottom count has
        never been measured on that axis. The checkup says so rather
        than treating silence as safety.

        The default implementation is the counts model, and it needs two
        things from the driver: `SOURCE_COUNTS_PER_RANGE[quantity]`, and
        a source range to apply it to. Which range that is has three
        cases, and they are deliberately not collapsed:

        * **A fixed range was applied.** `apply_ranges()` recorded it, so
          the floor is exact - `MIN_LEVEL_COUNTS` counts of that range.
        * **AUTO was applied**, or the range has never been set. The
          instrument is choosing, so the driver does not know which
          range is in force and cannot compute the exact floor. What it
          still knows is a bound that holds on *every* range: the
          narrowest source range this model has is the one with the
          smallest count in it, so a level below `MIN_LEVEL_COUNTS`
          counts of that is unresolvable whichever range the instrument
          picked. That bound is what gets returned.
        * **No ladder is declared** for the axis - `None`, as before.

        The autorange bound is weak on purpose. Under autoranging the
        instrument picks a range from the level it was handed, so the
        sub-count regime is one an autoranging instrument does not
        normally enter; the case the guard exists for is a range pinned
        wide by a plan, and there the exact figure is available.
        """
        counts = self.SOURCE_COUNTS_PER_RANGE.get(quantity)
        if not counts:
            return None
        ceiling = self.active_source_range(quantity)
        if ceiling is None:
            ceiling = self.narrowest_source_range(quantity)
        if ceiling is None:
            return None
        return float(ceiling) / counts * self.MIN_LEVEL_COUNTS

    @classmethod
    def declares_source_level_floor(cls):
        """True when this driver can put a floor under a source level.

        Two ways to qualify, because there are two mechanisms: declaring
        a converter count for an axis, or overriding
        `source_level_floor()` outright the way the U2722A does - its
        ranges are named tokens rather than numbers, so the ladder in
        `LIMITS` is not what its floor is computed from.

        Asked of the class because the contract ledger asks it of the
        class. A driver that neither declares counts nor overrides the
        method refuses nothing, and must not record `refused`.
        """
        if cls.source_level_floor is not BaseSMU.source_level_floor:
            return True
        return any(bool(cls.SOURCE_COUNTS_PER_RANGE.get(q))
                   for q in ("current", "voltage"))

    def _source_range_state(self):
        """The per-axis record of what `apply_ranges()` last applied.

        Lazily created rather than set in `__init__`, so a driver that
        does not chain to `BaseSMU.__init__` still gets it rather than
        raising `AttributeError` from inside a level setter - which is
        the one place in this file where an unexpected exception costs
        a run rather than a report.
        """
        state = getattr(self, "_active_source_range", None)
        if state is None:
            state = {"current": None, "voltage": None}
            self._active_source_range = state
        return state

    def active_source_range(self, quantity):
        """Full scale of the source range `apply_ranges()` last applied.

        `None` for AUTO, for an axis carrying nothing, and for an axis
        nothing has applied yet - all three of which mean the same thing
        to a floor: this driver does not know which range is in force.

        Deliberately recorded rather than queried. The range readback
        exists and would be the better answer, but on every driver that
        has one it is `UNVERIFIED`, and a level setter is called once
        per sweep point - a query there would triple the traffic of a
        sweep to consult a number the readback contract already says is
        not evidence.
        """
        return self._source_range_state().get(quantity)

    def _record_source_range(self, quantity, value):
        """Remember what a source range was set to, or that it is unknown.

        Called from `apply_ranges()`, which is the contract entry point
        for ranging. A driver hook invoked directly - as
        `tools/bench_envelope.py` does - bypasses this, and then
        `source_level_floor()` falls back to the narrowest-range bound
        rather than the exact one. That is the direction that under-
        refuses rather than over-refuses, which is the right way round
        for a bookkeeping miss: a false refusal stops a run that would
        have been fine.
        """
        self._source_range_state()[quantity] = (
            float(value) if isinstance(value, (int, float))
            and not isinstance(value, bool) else None)

    @classmethod
    def narrowest_source_range(cls, quantity):
        """The smallest range on this model's source ladder, or None.

        Read from `LIMITS`, which is where each driver already declares
        its ladder - and on the 2635B that list is documented as the
        SOURCE ranges specifically, with the measurement-only 100 pA
        range excluded. A second copy here would be a second thing to
        keep in step.
        """
        if cls.LIMITS is None:
            # A driver that declares no envelope has no ladder to read a
            # floor off. `None` is the honest answer and the caller
            # already treats it as "this model declares no floor".
            return None
        ladder = (cls.LIMITS.current_ranges if quantity == "current"
                  else cls.LIMITS.voltage_ranges)
        positive = [abs(float(r)) for r in (ladder or []) if r]
        return min(positive) if positive else None

    def guard_source_level(self, quantity, level, unit):
        """Refuse a level below this instrument's declared floor.

        Called by a driver's own level setter, before anything is
        written. Does nothing on a model with no declared floor, and
        nothing for a level of zero: "off" is exactly representable and
        is what every settle-to-zero path writes.

        Raises `RangeError` before the output is energised, which is the
        whole point - a level in this regime comes out with a polarity
        nobody commanded, so an operator asking for a 1 uA bias can get
        an output at the opposite polarity from the one their sample is
        wired for, with no error anywhere.
        """
        magnitude = abs(float(level))
        if magnitude == 0.0:
            return
        floor = self.source_level_floor(quantity)
        if floor is None or magnitude >= floor:
            return
        if magnitude < floor * self.ZERO_RESIDUE_FRACTION:
            # A zero that arithmetic did not quite reach, not a request.
            # See ZERO_RESIDUE_FRACTION.
            return

        # Which range the floor came from, so the message says what the
        # reader needs in order to act on it: a level refused on a wide
        # range is often perfectly expressible on a narrower one, and
        # the remedy is to change the plan, not the level.
        ceiling = self.active_source_range(quantity)
        counts = self.SOURCE_COUNTS_PER_RANGE.get(quantity)
        if ceiling is not None:
            where = f"the {ceiling:.6g} {unit} range it is on"
        else:
            narrowest = self.narrowest_source_range(quantity)
            where = (f"any range this model has - its narrowest is "
                     f"{narrowest:.6g} {unit}"
                     if narrowest is not None else "the range it is on")
        count = (f" One count of that range is "
                 f"{float(ceiling or self.narrowest_source_range(quantity) or 0) / counts:.6g} "
                 f"{unit} and this driver requires at least "
                 f"{self.MIN_LEVEL_COUNTS}." if counts else "")

        raise RangeError(
            f"{self.DISPLAY_NAME}: a {quantity} level of {magnitude:.6g} "
            f"{unit} is below the smallest this instrument can express on "
            f"{where} ({floor:.6g} {unit}).{count} Below a count the "
            f"output is offset residue whose sign is not commanded - the "
            f"instrument ignores the one you asked for. Refusing before "
            f"the output is energised.")

    # ---- ranging: the plan ----
    #: Does this instrument have a source range that can be set
    #: independently of its measurement range?
    #:
    #: False is not a failing grade. The U2722A genuinely has one knob
    #: serving both jobs; saying so is what lets `apply_ranges()` resolve
    #: a plan honestly instead of silently keeping whichever value
    #: happened to arrive last.
    INDEPENDENT_SOURCE_RANGE = True

    #: Can this instrument fix a measurement range at all, or does it
    #: only ever autorange?
    HAS_MEASURE_RANGE = True

    def apply_ranges(self, plan, log=None):
        """Carry out a ranging plan, and report what was actually done.

        Returns a short string describing the ranges applied, suitable
        for run metadata. It is not always what was asked for - see
        below - and the difference is the thing worth recording.

        Each axis goes to the command that axis actually names. That is
        the whole point of the exercise: before this, `set_current_range`
        sent a *source* command on two drivers and a *measure* command
        on five, and callers had no way to say which they meant.

        One-knob instruments
        --------------------
        Where source and measure share a range, the two requested values
        are reconciled by taking the **wider**, and saying so on the
        console. Wider always fails safe: a range broader than needed
        never clamps a source level and never overranges a reading. The
        only cost is resolution, which is a worse measurement rather
        than a wrong one - and this project would rather lose a digit
        than gain a plausible number that is wrong.

        `AUTO` beats any fixed value in that reconciliation, because
        autoranging covers everything a fixed range would. `NOT_SOURCED`
        loses to everything: an axis carrying nothing has no claim on a
        shared knob, and letting it win is what cost the U2722A its
        compliance - the knob went to the widest range and the
        requested limit was then too small a fraction of it to be
        settable at all.

        Axes that are not being sourced
        -------------------------------
        `NOT_SOURCED` on a source axis says the run puts nothing out of
        that quantity, so there is no range to pick. It is **not** the
        same as `AUTO`, which asks the instrument to pick one.

        The default here renders it as `AUTO`, which is what every
        driver did before the distinction existed - so the five
        instruments the 2026-08-18 commissioning round found unharmed
        keep exactly the behaviour they were commissioned with. The two
        that were harmed override `_render_not_sourced` and say what
        they need instead; see the contract ledger.

        Overriding is a per-instrument decision because the axis means
        different things on different instruments. On the 2611A and
        2635B the compliance lives on the source side, so the "unsourced"
        source range is the *compliance's own range* and must still be
        sent. On the GSM-20H10 the same command silently resets the
        compliance. A blanket rule would have broken one pair to fix the
        other.
        """
        applied = []

        if self.INDEPENDENT_SOURCE_RANGE:
            chosen_i = self._render_not_sourced(plan.source_current)
            chosen_v = self._render_not_sourced(plan.source_voltage)
            self._apply_source_current_range(chosen_i)
            self._record_source_range("current", chosen_i)
            self._apply_source_voltage_range(chosen_v)
            self._record_source_range("voltage", chosen_v)
            self._apply_measure_current_range(plan.measure_current)
            self._apply_measure_voltage_range(plan.measure_voltage)
            return plan.describe()

        # One knob per quantity. Reconcile, then apply once.
        current = plan.widest("source_current", "measure_current")
        voltage = plan.widest("source_voltage", "measure_voltage")

        for axis, chosen, asked in (
                ("current", current,
                 (plan.source_current, plan.measure_current)),
                ("voltage", voltage,
                 (plan.source_voltage, plan.measure_voltage))):
            if asked[0] != asked[1]:
                message = (
                    f"{self.DISPLAY_NAME}: source and measure share one "
                    f"{axis} range. Asked for source "
                    f"{_show(asked[0])} and measure {_show(asked[1])}; "
                    f"using the wider, {_show(chosen)}. The narrower "
                    f"axis loses resolution but nothing is clamped.")
                applied.append(message)
                if log:
                    log(message)
                else:
                    print(message)

        chosen_i = self._render_not_sourced(current)
        chosen_v = self._render_not_sourced(voltage)
        self._apply_source_current_range(chosen_i)
        self._record_source_range("current", chosen_i)
        self._apply_source_voltage_range(chosen_v)
        self._record_source_range("voltage", chosen_v)
        return plan.describe() + (
            f" (shared knob: I={_show(current)}, V={_show(voltage)})"
            if applied else " (shared knob, no conflict)")

    def _render_not_sourced(self, value):
        """What this instrument should do with an unsourced source axis.

        Called on source axes only, and only reaches a driver hook after
        this. The default keeps the pre-2026-08-20 behaviour - treat it
        as `AUTO` - so a driver that says nothing changes nothing.

        A driver overriding this is making a claim about its instrument
        that was checked at the bench, and the contract ledger records
        which. Two do: the GSM-20H10 and the U2722A.
        """
        return AUTO if value is NOT_SOURCED else value

    # Each hook takes AUTO or a magnitude. Drivers override the ones
    # their instrument has; the defaults refuse rather than pretend, so
    # a driver that forgets one is loud instead of quietly doing nothing.
    def _apply_source_current_range(self, amps):
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no source current range.")

    def _apply_source_voltage_range(self, volts):
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no source voltage range.")

    def _apply_measure_current_range(self, amps):
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no measure current range.")

    def _apply_measure_voltage_range(self, volts):
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no measure voltage range.")

    def compliance_tripped(self):
        """Whether the last reading hit the compliance limit.

        Returns True, False, or None for "this instrument can't say".
        None rather than False on purpose: an instrument that has no
        such query has not reported that everything was fine, and
        collapsing the two would turn a silence into a reassurance.

        Worth having because a sweep in compliance still produces a
        neat straight line and a convincing R-squared - the instrument
        was clamping, so the fit describes the limit rather than the
        sample.
        """
        return None

