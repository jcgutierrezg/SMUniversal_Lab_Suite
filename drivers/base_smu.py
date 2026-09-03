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
"""
import threading as _threading
from abc import ABC, abstractmethod

from core import readback as _readback
from core.ranges import AUTO, NOT_SOURCED, RangeError
from core.transports.base import TransportDesynchronised


def _show(value):
    if value is AUTO:
        return "auto"
    if value is NOT_SOURCED:
        return "not sourced"
    return f"{value:.6g}"


class _SoftwareSweep:
    """One software sweep and everything that belongs to it.

    Review §20 asks that each sweep own a private thread, a private
    cancellation token, private result storage, an explicit terminal
    event and a non-reusable id. Putting all five in one object is what
    makes that true by construction rather than by discipline: the
    worker closes over *this* instance, so it physically cannot write
    into a later sweep's results, however the driver's attributes are
    rebound while it runs.
    """

    __slots__ = ("sweep_id", "sourced", "measured", "error",
                 "lock", "stop", "finished", "thread")

    def __init__(self, sweep_id):
        self.sweep_id = sweep_id
        self.sourced = []
        self.measured = []
        self.error = None
        self.lock = _threading.Lock()
        self.stop = _threading.Event()
        self.finished = _threading.Event()
        self.thread = None

    def can_drive(self):
        """True while the worker could still set a source level.

        Keyed on the terminal event, not on thread liveness. `finished`
        is set in the worker's finally block, after its last possible
        instrument interaction, so once it is set the sample is safe
        even though the thread object may not have been reaped yet.
        Using `thread.is_alive()` here instead makes the predicate true
        for a few microseconds *after* the worker is harmless, which is
        long enough to refuse a perfectly legal next sweep.
        """
        return not self.finished.is_set()

    def join(self, timeout):
        """Wait for the thread itself to exit. True if it did."""
        if self.thread is None:
            return True
        self.thread.join(timeout=timeout)
        return not self.thread.is_alive()


class BaseSMU(ABC):
    #: Source of software-sweep ids. Class-level and monotonic, so two
    #: drivers in one session never mint the same id and an id is never
    #: reused after an abort.
    _sweep_serial = 0

    # ---- identity, used by the registry to auto-detect ----
    MODEL_IDS: list[str] = []   # substrings matched against the *IDN? reply
    DISPLAY_NAME = "Unknown SMU"
    LIMITS = None       # an SMULimits instance, declared per model

    # ---- the "no reading" sentinel ----
    #
    # SCPI instruments report "there is no reading here" as a *number*:
    # +9.91e37 for not-a-number, +9.9e37 for over-range. TSP uses the
    # same values. Nothing raises, nothing is logged, and the value
    # parses as a perfectly ordinary float.
    #
    # These are the most dangerous numbers any driver handles. One of
    # them in a sweep is a point 37 orders of magnitude out, which drags
    # a least-squares fit to a meaningless slope while still returning a
    # respectable-looking R-squared. The fit describes the sentinel; the
    # R-squared describes how well it describes the sentinel.
    #
    # This lived on the GSM driver alone until the B2901A became the
    # second instrument to need it, at which point a diagnostic across
    # every registered driver found that the 2450, 2401, 2611A and
    # U2722A all returned both sentinels straight through as data. It is
    # a property of the protocols rather than of any one instrument, so
    # it belongs here - and a driver written next year gets it without
    # its author having to know the story.
    #
    # The threshold sits below both values so either is caught, and far
    # enough above any real reading that nothing legitimate approaches
    # it: the largest quantity any SMU in this suite sources is 210 V.
    NAN_THRESHOLD = 9.0e37

    @classmethod
    def drop_sentinel(cls, value):
        """None if `value` is a no-reading sentinel, else `value`.

        Returns None rather than omitting the value, and callers must
        keep it in place rather than filtering it out. Dropping a
        voltage by omission shifts every later column left, so the
        current is silently promoted into the voltage's position - a
        number of the right shape, wrong by a factor of the resistance,
        and indistinguishable from a real reading afterwards.
        """
        if value is None:
            return None
        try:
            return None if abs(float(value)) >= cls.NAN_THRESHOLD \
                else float(value)
        except (TypeError, ValueError):
            return None

    def __init__(self, transport):
        """`transport` is an already-connected Transport. The driver
        borrows it - it doesn't open or close it."""
        self.transport = transport

    # ---- identification ----
    def identify(self):
        """Return the instrument's *IDN? string. Standard across SCPI
        and TSP instruments alike, which is what makes auto-detection
        possible."""
        return self.transport.query("*IDN?").strip()

    def reset(self):
        """Return the instrument to a known state before configuring it."""
        self.transport.write("*RST")
        self.transport.write("*CLS")

    # ---- source configuration ----
    @abstractmethod
    def set_source_function(self, mode):
        """Select which quantity is sourced: "voltage" or "current".

        **The output state afterwards is undefined.** Several
        instruments drop the output when the source function changes -
        the 2400 family does, as a safety measure - so a caller that
        wants the output on must call `output_on()` after this, not
        before.

        Getting that wrong does not produce an error. On the 2401,
        `:READ?` with the output off and auto output-off disabled simply
        never answers: the trigger model waits for source-measure
        operations that cannot happen, and the query blocks until the
        VISA timeout. It looks exactly like a dead instrument.
        """
        """Set what the instrument sources: 'current' or 'voltage'."""

    @abstractmethod
    def set_current_level(self, amps):
        """Set the sourced current, in amps."""

    @abstractmethod
    def set_voltage_level(self, volts):
        """Set the sourced voltage, in volts."""

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
        answered, which times out and - since Wave 8a - latches the
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
                               f"compliance")

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
            return wanted <= abs(reported) <= ceiling

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

    def _read_and_compare(self, subject, expected, reader, *, supported,
                          trusted, unit, tolerance, unsupported_detail,
                          matcher=None, mismatch_note=None):
        """Call one reader, catch what it can legitimately throw, grade it.

        The broad handler is deliberate and narrow in effect: a query
        that fails is a failure to *ask*, which is information rather
        than evidence about the setting, and `UNREADABLE` is exactly
        that state. A desynchronised link is not that - it says the
        answers themselves can no longer be trusted - so it is named and
        re-raised, as everywhere else that wraps a query.
        """
        if not supported:
            return _readback.compare(
                subject, expected, None, supported=False, trusted=trusted,
                unit=unit, unsupported_detail=unsupported_detail)
        error = None
        reported = None
        try:
            reported = reader()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        return _readback.compare(subject, expected, reported,
                                 supported=True, trusted=trusted,
                                 unit=unit, tolerance=tolerance,
                                 error=error, matcher=matcher,
                                 mismatch_note=mismatch_note)

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
        declared one", which for six drivers here means the converter's
        bottom count has never been measured. The checkup says so rather
        than treating silence as safety.
        """
        return None

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
        raise RangeError(
            f"{self.DISPLAY_NAME}: a {quantity} level of {magnitude:.6g} "
            f"{unit} is below the smallest this instrument can express on "
            f"the range it is on ({floor:.6g} {unit}). Below that the "
            f"output is offset residue whose sign is not commanded. "
            f"Refusing before the output is energised.")

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
            self._apply_source_current_range(
                self._render_not_sourced(plan.source_current))
            self._apply_source_voltage_range(
                self._render_not_sourced(plan.source_voltage))
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

        self._apply_source_current_range(
            self._render_not_sourced(current))
        self._apply_source_voltage_range(
            self._render_not_sourced(voltage))
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

    # ---- sensing ----
    @abstractmethod
    def set_remote_sense(self, on=True):
        """Enable/disable 4-wire (Kelvin) sensing."""

    # ---- timing ----
    @abstractmethod
    def set_source_delay(self, seconds):
        """Settle time the instrument waits after a source step, before
        measuring. Takes seconds; each driver converts to whatever unit
        its dialect wants."""

    # ---- output ----
    @abstractmethod
    def output_on(self):
        """Enable the output terminals."""

    @abstractmethod
    def output_off(self):
        """Disable the output terminals."""

    # ---- measurement ----
    @abstractmethod
    def read_error(self):
        """Pop one entry off the instrument's error queue.

        Returns `(code, message)`. Code 0 means the queue was empty -
        everything sent so far was understood.

        Promoted from an informal habit to the contract because it is
        the only way anything above the driver can ask an instrument
        *"did you understand that?"* rather than merely observing that
        nothing crashed. `tools/smu_checkup.py` uses it to verify
        command spellings against real hardware, which is the one thing
        the offline test suite cannot do.

        Two rules every implementation follows:

        - **A failure to read the queue reports code 0, not an error.**
          Being unable to *ask* about errors is not evidence that a
          command failed, and treating it as one would abort runs over
          a dropped reply.
        - **Nothing else is inferred.** An unparseable reply is returned
          as code 0 with the raw text as the message, so a checkup can
          show it to a human rather than guessing.
        """
        raise NotImplementedError

    @abstractmethod
    def measure(self, timeout_s=3.0):
        """Take one reading. Returns (volts, amps); either may be None
        if this instrument/configuration doesn't report it.

        **Abstract since review A-09; it was not before.** It sat here
        with an empty body and no decorator, alone among the contract
        methods around it, which made the one method every experiment
        calls the one method a driver could omit. A driver that did
        would inherit this and return `None` from every reading, so a
        run would produce a full-length trace of `(None, None)` - the
        exact shape of a measurement, containing nothing - and the
        instrument would look like it was answering.

        `tests/test_driver_contract.py` already required every
        *registered* driver to define it, which is why nothing was
        broken. That check runs in the suite; this one runs at
        construction, and construction is where a driver written
        against this contract in a later wave will find out.

        The declared signature was also `measure(self)` while all nine
        implementations take `timeout_s`, so what was written here did
        not describe what was implemented.
        """
        raise NotImplementedError

    # ---- sweeps ----
    #
    # Two ways to run a sweep, behind one contract.
    #
    # A *hardware* sweep is run by the instrument off its own timebase:
    # one command starts it, the points land in the instrument's buffer,
    # and the point-to-point spacing is set by the SMU's clock rather
    # than by whatever the host was doing at the time. The 2611A does
    # this. It is the better measurement.
    #
    # A *software* sweep is the fallback for every instrument that
    # can't: step the source, wait, measure, repeat. It is built from
    # primitives every driver already implements, so it works on any
    # SMU in the suite - including ones not written yet.
    #
    # The contract is deliberately split into three: start it, ask how
    # far it has got, then collect. That is what lets the caller poll
    # for completion instead of sleeping a guessed duration (see
    # IVSweepExperiment._await_sweep), and it is also what lets these
    # two very different mechanisms look identical from outside. The
    # software sweep runs on its own thread precisely so that
    # start_linear_sweep() returns immediately, exactly as the hardware
    # one does.
    #
    # A driver gets the software sweep for free. A driver that can do
    # better overrides all three and sets SWEEP_KIND = "hardware".

    SWEEP_KIND = "software"

    # Guard against a host-side stall wedging a sweep thread forever.
    _SOFTWARE_SWEEP_READ_TIMEOUT_S = 30.0

    #: How long abort_sweep() waits for the worker to actually exit.
    #: Deliberately short: the worker's longest uninterruptible step is
    #: one measure(), and a worker still running after this is a fault
    #: to report rather than a delay to absorb.
    _SOFTWARE_SWEEP_ABORT_TIMEOUT_S = 10.0

    def start_linear_sweep(self, mode, start, stop, points, delay_s):
        """Begin a linear sweep and return immediately.

        `mode` is 'voltage' (source V, measure I) or 'current' (source
        I, measure V). `delay_s` is the per-point settle time.

        This base implementation steps the source from Python on a
        worker thread. Accuracy of the *levels* is unaffected - the
        instrument is told each one explicitly - but the *timing* is
        only as good as the host and the bus, which is why the run
        records which kind of sweep produced it.

        Sweep ownership (review §20)
        ----------------------------
        Each sweep owns its own storage, stop event and terminal event,
        and carries an id that is never reused. The worker writes into
        *its own* sweep object, captured when it was created, rather
        than into an attribute on the driver.

        That is not a tidiness point. Before this, `start_linear_sweep`
        rebound `self._sw_sourced` and friends without joining the
        previous worker, and the worker resolved those attributes at
        append time - so a sweep that was still running when the next
        one started appended its points into the *new* sweep's lists,
        and kept stepping the source underneath it. Two sweeps'
        readings in one buffer fit a perfectly convincing straight
        line.

        Starting a sweep while the previous worker is still alive is
        now refused outright, rather than papered over. The caller is
        expected to `abort_sweep()` and let it terminate first.
        """
        if mode not in ("voltage", "current"):
            raise ValueError(f"Unknown sweep mode: {mode!r}")
        points = int(points)
        if points < 2:
            raise ValueError("A sweep needs at least 2 points.")

        previous = getattr(self, "_sw", None)
        if previous is not None:
            if previous.can_drive():
                raise RuntimeError(
                    f"{self.DISPLAY_NAME}: sweep {previous.sweep_id} is "
                    f"still running. Abort it and wait for it to exit "
                    f"before starting another.")
            # It can no longer touch the instrument, but the thread may
            # not have been reaped yet. Join before letting go of the
            # reference, so no worker is ever silently orphaned.
            if not previous.join(self._SOFTWARE_SWEEP_ABORT_TIMEOUT_S):
                raise RuntimeError(
                    f"{self.DISPLAY_NAME}: sweep {previous.sweep_id} "
                    f"signalled completion but its thread has not exited.")

        start = float(start)
        stop = float(stop)
        delay_s = max(float(delay_s), 0.0)
        step = (stop - start) / (points - 1)
        levels = [start + step * i for i in range(points)]

        BaseSMU._sweep_serial += 1
        sweep = _SoftwareSweep(f"{self.DISPLAY_NAME}#{BaseSMU._sweep_serial}")
        self._sw = sweep

        set_level = (self.set_voltage_level if mode == "voltage"
                     else self.set_current_level)

        def worker():
            try:
                for level in levels:
                    if sweep.stop.is_set():
                        break
                    set_level(level)
                    if delay_s:
                        # Interruptible: an aborted sweep should stop
                        # promptly, not finish its remaining settles.
                        if sweep.stop.wait(delay_s):
                            break
                    volts, amps = self.measure()

                    # Source value: prefer what the instrument reports
                    # it actually sourced; fall back to what we asked
                    # for. Same principle as the hardware path.
                    if mode == "voltage":
                        sourced = volts if volts is not None else level
                        measured = amps
                    else:
                        sourced = amps if amps is not None else level
                        measured = volts
                    if measured is None:
                        raise RuntimeError(
                            "Instrument returned no reading for the "
                            "measured quantity.")

                    with sweep.lock:
                        sweep.sourced.append(float(sourced))
                        sweep.measured.append(float(measured))
            except Exception as exc:              # surfaced by read_sweep
                sweep.error = exc
            finally:
                # Set last and always. `finished` is what the caller
                # waits on to know the worker can no longer touch the
                # source, so it must be set even when the worker died.
                sweep.finished.set()

        sweep.thread = _threading.Thread(
            target=worker, daemon=True,
            name=f"{self.DISPLAY_NAME} software sweep {sweep.sweep_id}")
        sweep.thread.start()

    def sweep_points_ready(self):
        """How many sweep points have been recorded so far."""
        sweep = getattr(self, "_sw", None)
        if sweep is None:
            return 0
        if sweep.error is not None:
            raise sweep.error
        with sweep.lock:
            return len(sweep.measured)

    def read_sweep(self, points):
        """Collect a finished sweep.

        Returns (source_values, measured_values) as two equal-length
        lists of floats.

        Waits for the worker to terminate first, and raises if it does
        not. Returning data while the worker is still stepping the
        source would hand the caller a half-finished sweep *and* leave
        it free to energise the sample during the caller's cleanup -
        which §20 names explicitly.
        """
        sweep = getattr(self, "_sw", None)
        if sweep is None:
            return [], []
        if not sweep.finished.wait(self._SOFTWARE_SWEEP_READ_TIMEOUT_S):
            raise RuntimeError(
                f"{self.DISPLAY_NAME}: sweep {sweep.sweep_id} did not "
                f"finish within {self._SOFTWARE_SWEEP_READ_TIMEOUT_S:.0f} s "
                f"and is still able to drive the source.")
        if sweep.error is not None:
            raise sweep.error
        with sweep.lock:
            sourced = list(sweep.sourced)
            measured = list(sweep.measured)
        # Truncate rather than pad: a short sweep is missing points, and
        # inventing them would be worse than reporting fewer.
        if points and len(measured) > points:
            sourced, measured = sourced[:points], measured[:points]
        return sourced, measured

    def abort_sweep(self):
        """Stop a running sweep and wait for the worker to exit.

        Returns True if no worker is running when it returns. A False
        means a thread is still alive and may still set source levels -
        the caller must treat the instrument as live and say so, not
        proceed quietly.
        """
        sweep = getattr(self, "_sw", None)
        if sweep is None:
            return True
        sweep.stop.set()
        return sweep.finished.wait(self._SOFTWARE_SWEEP_ABORT_TIMEOUT_S)

    def sweep_running(self):
        """True while this driver's software sweep worker could still
        set a source level."""
        sweep = getattr(self, "_sw", None)
        return sweep is not None and sweep.can_drive()

    def sweep_id(self):
        """Identifier of the most recent software sweep, or None.

        Ids are never reused, so a caller holding one from before an
        abort can tell that the sweep it is looking at is not its own.
        """
        sweep = getattr(self, "_sw", None)
        return None if sweep is None else sweep.sweep_id

    @classmethod
    def supports_sweep(cls):
        """True when this model can sweep at all.

        Now true for every driver: the software fallback above is built
        from primitives each one already implements. Kept as a hook for
        an instrument that genuinely cannot (a fixed-output supply, say)
        and needs to say so up front rather than fail mid-run.
        """
        return True

    @classmethod
    def sweep_kind(cls):
        """'hardware' or 'software' - which mechanism this model uses.

        The experiment shows this and records it with the data. The two
        produce equally accurate *levels* but not equally trustworthy
        *timing*, so a saved run has to say which one made it.
        """
        return cls.SWEEP_KIND

    # ---- optional capabilities ----
    #
    # Not every SMU has every control, so rather than have experiments
    # guess, each driver *declares* what it has. Same idea as LIMITS:
    # the GUI reads the declaration to decide whether to offer the
    # control at all, and an instrument that lacks it simply shows the
    # field greyed out instead of erroring at Run.
    #
    # NPLC_RANGE   (min, max) integration time in power line cycles, or
    #              None if this model has no such setting.
    # OVP_CHOICES  the arguments this model's overvoltage protection
    #              accepts, in menu order, first entry being the safe
    #              default. Empty means no OVP control.

    NPLC_RANGE = None
    OVP_CHOICES: list[str] = []

    # HIGH_Z_OFF: True when this model can open its output relay on
    # output-off, disconnecting the sample entirely, rather than merely
    # sourcing 0 V into it.
    HIGH_Z_OFF = False

    # REMOTE_SENSE_CONTROL: True when 2-wire/4-wire is selectable over
    # the bus. False when it is decided by how the instrument is wired
    # and software gets no say - the Keysight U2722A has no remote-sense
    # command at all, and its SENSE terminals are strapped once and left.
    #
    # FIXED_SENSE names what the wiring actually is on such an
    # instrument ("4-wire (hardwired)"), so the value recorded in the
    # CSV describes the measurement rather than a checkbox that could
    # not affect it. None on any model where the control is real.
    #
    # Defaults to True because a selectable sense line is the normal
    # case; a model that cannot switch has to say so. The capability
    # ledger in tests/test_driver_contract.py still forces every driver
    # to record an answer either way.
    REMOTE_SENSE_CONTROL = True
    FIXED_SENSE = None

    # INTERLOCK_ABOVE_V: the source voltage above which this model
    # requires a hardware interlock line to be held high before the
    # output will energise. None on instruments with no such line.
    #
    # Declared rather than handled, because software cannot help here:
    # the interlock is a physical line on the instrument's Digital I/O
    # port and there is no command that overrides it. What the
    # declaration buys is that the operator is told, at the moment it
    # could matter, instead of watching a 200 V run refuse to source and
    # going looking for a driver fault.
    #
    # Common on TSP boxes and absent on the SCPI ones here, so it is
    # declared per model like every other capability rather than
    # assumed from the dialect.
    INTERLOCK_ABOVE_V = None

    @classmethod
    def interlock_note(cls):
        """One line for the console, or None when there is no interlock.

        Deliberately describes the condition rather than warning about
        the jumper. A bench that has the line shorted has made a
        decision; the console's job is to make sure that decision is
        visible in the same place as the measurement, not to argue with
        it every run.
        """
        if cls.INTERLOCK_ABOVE_V is None:
            return None
        return (f"the output will not energise above "
                f"{cls.INTERLOCK_ABOVE_V:g} V unless the interlock line "
                f"is held high. If a high-voltage run refuses to source, "
                f"check the interlock before suspecting the driver.")

    @classmethod
    def supports_remote_sense_control(cls):
        """True when 2-wire/4-wire can be selected from software."""
        return cls.REMOTE_SENSE_CONTROL

    @classmethod
    def fixed_sense(cls):
        """How this instrument is wired, when software cannot choose.

        Returns None on models where set_remote_sense() genuinely
        controls something.
        """
        return cls.FIXED_SENSE

    def set_output_off_mode(self, high_z=False):
        """Choose what "output off" physically means.

        Normal off still leaves the instrument connected, sourcing 0 V
        with a small compliance - a low-impedance path across the
        sample. High-Z opens the output relay instead, so the sample is
        genuinely disconnected.

        Like a light switch versus pulling the plug out of the wall.
        The switch is fine most of the time and doesn't wear anything
        out; pulling the plug is what you want when the appliance must
        be isolated, and it wears the socket.

        Off by default because the relay has a finite number of
        operations in it and a periodic run can cycle the output
        hundreds of times.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no output-off mode control.")

    @classmethod
    def supports_high_z_off(cls):
        """True when this model can open its output relay on off."""
        return cls.HIGH_Z_OFF

    def set_nplc(self, nplc):
        """Set integration time in power line cycles.

        This is the speed-versus-noise knob. One NPLC means the ADC
        integrates over exactly one mains period, so whatever 50 Hz hum
        the leads pick up averages to zero over the window. Ten NPLC is
        ten times quieter and ten times slower; 0.01 is fast and noisy.

        Think of it as shutter speed on a camera: longer exposure, less
        grain, but you can't photograph anything moving.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no NPLC setting.")

    def set_voltage_protection(self, choice):
        """Set the overvoltage protection ceiling.

        `choice` is one of OVP_CHOICES. This is a hardware clamp on how
        far the source can go, independent of the compliance setting -
        it is what stops a 4-wire sense lead falling off and the
        instrument winding the output up to compensate.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no overvoltage protection control.")

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

    @classmethod
    def supports_nplc(cls):
        """True when this model exposes an integration-time setting."""
        return cls.NPLC_RANGE is not None

    @classmethod
    def supports_ovp(cls):
        """True when this model exposes an overvoltage protection
        control."""
        return bool(cls.OVP_CHOICES)

    @classmethod
    def clamp_nplc(cls, nplc):
        """Pull a requested NPLC into this model's supported window.

        Clamping rather than raising: an out-of-range NPLC is a speed
        preference, not a safety matter, and losing a run over one
        would be disproportionate. Out-of-range *source points* still
        raise - see validate_source_point below.
        """
        if cls.NPLC_RANGE is None:
            return None
        low, high = cls.NPLC_RANGE
        return min(max(float(nplc), low), high)

    # ---- capability checks ----
    def validate_source_point(self, current=None, voltage=None):
        """Check a requested operating point against this model's limits.
        Raises LimitError if it's out of range.

        The default defers to LIMITS. Override in a driver whose real
        envelope is more complicated than a table of corners.
        """
        if self.LIMITS is None:
            return
        self.LIMITS.validate_source_point(current=current, voltage=voltage)

    # ---- convenience ----
    def safe_output_off(self):
        """Best-effort output shutdown, for error paths and app exit
        where an exception would be unhelpful.

        **Not the shutdown a run's data depends on.** That is
        `core.run_control.confirm_output_off()`, which asks the error
        queue whether the instrument agreed and returns a
        `ShutdownReport` the caller must branch on. The difference is
        stated there and is the reason both exist: at the end of a run,
        whether the output went off decides whether the readings may be
        kept, so a swallowed failure there would be a fail-open on a
        data-preservation path.
        """
        try:
            self.output_off()
        except Exception:
            # Cleanup-only, and the invariant is that every caller has
            # somewhere better to be. This runs on exit and error paths
            # where an exception would replace the real ending - a
            # disconnect that stops halfway, or a failure report never
            # printed - and where nothing downstream reads the result.
            # A caller that needs to *know* calls confirm_output_off().
            pass
