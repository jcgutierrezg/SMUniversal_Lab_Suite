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
from abc import ABC, abstractmethod
import threading as _threading

from core.ranges import AUTO, NOT_SOURCED, RangeError, RangePlan


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
    MODEL_IDS = []      # substrings matched against the *IDN? reply
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

    # ---- reading a compliance back ----
    #: Can this instrument be believed when asked what its compliance
    #: is?
    #:
    #: Three-valued on purpose, and the third value is the point.
    #:
    #:   True   - the readback was checked at the bench against a value
    #:            the instrument was known to hold, and it agreed.
    #:   False  - this driver cannot read a compliance back at all.
    #:   None   - it can, and nobody has checked whether it tells the
    #:            truth.
    #:
    #: `None` exists because of the GSM-20H10. Its `OUTP?` returns 0
    #: with the output demonstrably on and 10 V flowing, so at least one
    #: state query on that instrument lies - and five rounds of
    #: reasoning were built on believing it. A compliance readback that
    #: an instrument answers dishonestly is worse than none at all: it
    #: produces confident reassurance about the exact thing it exists to
    #: verify.
    #:
    #: So `verify_compliance()` reports "unverified" rather than "pass"
    #: for a `None`, and the checkup skips rather than claims. Skips are
    #: already a first-class outcome there.
    COMPLIANCE_READBACK_TRUSTED = False

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

    def verify_compliance(self, mode, expected, tolerance=0.01):
        """Did the compliance survive whatever just happened to it?

        Returns `(verdict, detail)` where verdict is one of `"ok"`,
        `"mismatch"`, `"unreadable"` or `"unverified"`.

        This exists because of what a ranging command did on the
        GSM-20H10: `SOUR:CURR:RANG:AUTO ON` took a 105 uA compliance to
        **1 nA**, with a clean error queue and nothing raised. It only
        ever surfaced because a later, innocent command tripped over the
        collapsed value and complained about something else. Nothing in
        this suite read a compliance back, so on an instrument where
        nothing downstream trips, the collapse is invisible - which is
        why five of seven instruments in the 2026-08-18 round are
        "none observed" rather than "none".

        The tolerance is fractional and generous by default. Instruments
        round: the GSM-20H10 returns `1.050000e-04` for a 100 uA range's
        full scale, and a check tight enough to call that a mismatch
        would cry wolf on every instrument that reports full scale
        rather than the requested value.
        """
        reader = (self.read_current_limit if mode == "voltage"
                  else self.read_voltage_limit)
        unit = "A" if mode == "voltage" else "V"

        try:
            actual = reader()
        except Exception as exc:
            return ("unreadable", f"{type(exc).__name__}: {exc}")

        if actual is None:
            return ("unreadable",
                    f"{self.DISPLAY_NAME} does not report its compliance")

        if not self.COMPLIANCE_READBACK_TRUSTED:
            return ("unverified",
                    f"reads {actual:.6g} {unit} against {expected:.6g} "
                    f"{unit}, but this readback has never been checked "
                    f"against a known value on this instrument")

        if expected == 0:
            agreed = actual == 0
        else:
            agreed = abs(actual - expected) / abs(expected) <= tolerance
        if agreed:
            return ("ok", f"{actual:.6g} {unit}")
        return ("mismatch",
                f"asked for {expected:.6g} {unit}, instrument reports "
                f"{actual:.6g} {unit}")

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

    def measure(self):
        """Take one reading. Returns (volts, amps); either may be None
        if this instrument/configuration doesn't report it."""

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
    OVP_CHOICES = []

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
        where an exception would be unhelpful."""
        try:
            self.output_off()
        except Exception:
            pass
