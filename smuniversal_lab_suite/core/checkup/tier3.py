"""Tier 3 - measurement: does the instrument measure what it is
asked to, in the time it should?

A mixin on `Checkup`; the state it uses is set up by
`CheckupBase`.
"""
import time

from smuniversal_lab_suite.core.checkup.probes import (
    COMPLIANCE_CEILING,
    COMPLIANCE_FLOOR,
    OPEN_CIRCUIT_MAX_A,
    SETTLE_TOLERANCE_FRACTION,
    SWEEP_POINTS,
    TIMED_READINGS,
    ProbeLevels,
)
from smuniversal_lab_suite.core.ranges import (
    RangePlan,
)
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised


class Tier3Checks:
    """Tier 3 - measurement: does the instrument measure what it is"""


    # ---- choosing a level the instrument can actually express ----
    def _resolve_source_level(self, quantity, unit):
        """Raise the probe level to this instrument's floor, if it has one.

        Called **after** the ranging plan has been carried out and
        **before** anything is sourced, because the floor is a property
        of the range that is now active and of nothing else. On the
        U2722A the checkup's current-mode plan puts the shared knob on
        R120mA, where one count is 7.32 uA; the nominal 1 uA probe is a
        seventh of a count there and comes out as offset residue whose
        sign is not the one that was asked for. On the same instrument's
        R1uA range the same 1 uA is eleven counts and perfectly good.
        There is no single number that is right on both.

        The resolved level is written back into `self.probe`, so every
        message after this quotes what was actually sourced rather than
        what was nominally asked for. A report that says "sourcing 1e-06
        A" while the instrument was handed 73 uA is a report that will
        be quoted later.

        Returns the level to use. Never lowers one: a floor says what is
        too small, and nothing here knows what would be too large beyond
        the envelope clamp that has already been applied.
        """
        wanted = (self.probe.current if quantity == "current"
                  else self.probe.voltage)
        name = f"{quantity} probe level is expressible on the active range"
        state = type(self.driver).sub_count_state(quantity)

        try:
            floor = self.driver.source_level_floor(quantity)
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, name, "warn",
                        f"the driver could not say what its floor is: "
                        f"{type(exc).__name__}: {exc}. Probing at "
                        f"{wanted:.6g} {unit} anyway")
            return wanted

        if floor is None:
            # No declared floor. Whether that is safe depends entirely
            # on which of the three sub-count states this model is in,
            # and the difference is the whole point: "there is no
            # converter to fall below" and "nobody has measured this
            # converter" must not read the same in a report.
            if state == type(self.driver).SUB_COUNT_NOT_APPLICABLE:
                self.record(3, name, "skip",
                            f"{wanted:.6g} {unit}; this model has no source "
                            f"{quantity} range for a level to fall below, so "
                            f"the question does not arise in this form")
            else:
                self.record(3, name, "warn",
                            f"probing at {wanted:.6g} {unit}, and this model "
                            f"declares no floor: what a source level below "
                            f"one count of the active range does here is "
                            f"UNMEASURED. On the one instrument where it has "
                            f"been measured the output was offset residue "
                            f"whose sign was not the one commanded. Nothing "
                            f"here says this level is in that regime - it "
                            f"says nobody can tell")
            return wanted

        if abs(wanted) >= floor:
            self.record(3, name, "pass",
                        f"{wanted:.6g} {unit} is at or above the "
                        f"{floor:.6g} {unit} this instrument can express on "
                        f"the range the plan landed on")
            return wanted

        raised = floor
        what, _ = ProbeLevels.UNITS[quantity]
        reason = (f"the {what} was substituted: the nominal {wanted:.6g} "
                  f"{unit} is below the {floor:.6g} {unit} this instrument "
                  f"can express on the range the plan landed on, so it was "
                  f"probed at {raised:.6g} {unit} instead")
        self.probe.substitute(quantity, raised, reason)
        self.record(
            3, name, "pass",
            f"the nominal {wanted:.6g} {unit} is below the {floor:.6g} "
            f"{unit} this instrument can express on the range the plan "
            f"landed on, so it is probed at {raised:.6g} {unit} instead. "
            f"Below the floor the output is offset residue whose sign is "
            f"not commanded, so a smaller probe would be testing the "
            f"instrument's offset rather than its source")
        return raised

    def _settle_tolerance(self):
        """Two readings closer than this count as the same reading.

        Derived from the compliance this run is actually using rather
        than from a module constant, for the same reason the probe is:
        the number has to mean the same fraction of the limit on every
        instrument. See SETTLE_TOLERANCE_V for what it has to
        distinguish.
        """
        return self.probe.compliance_v * SETTLE_TOLERANCE_FRACTION

    # ---- tier 3 ----
    def tier3_measurement(self):
        driver = self.driver
        self._log("\nTier 3 - live measurement (open circuit expected)")

        if not self._output_is_off:
            self.record(3, "live measurement", "skip",
                        "output_off() did not succeed, so enabling the "
                        "output is not safe")
            return

        driver.set_source_function("voltage")
        # Ranges before the limit, all four axes: sourcing volts and
        # measuring the current that flows.
        driver.apply_ranges(RangePlan.for_sourcing(
            "voltage", source_range=self.probe.voltage,
            measure_range=self.probe.compliance_i))
        driver.set_current_limit(self.probe.compliance_i)
        # Asked here, with the output still off and the ranges just
        # applied, so that a level the instrument cannot express is
        # found before anything is energised rather than after.
        self._resolve_source_level("voltage", "V")
        driver.set_voltage_level(0.0)

        self.attempt(3, "output_on()", driver.output_on)
        self.check_queue(3, "output_on()")

        try:
            self._tier3_body()
        finally:
            # Whatever happened above, the output comes off. A checkup
            # that aborts with the terminals live is worse than no
            # checkup.
            self.attempt(3, "output_off()  [cleanup]", driver.output_off)

    def _tier3_body(self):
        driver = self.driver

        # Generous, and derived from the integration time rather than
        # left at measure()'s 3 s default. At NPLC 10 a 2401 that has
        # to autorange on the way takes longer than that, and the
        # timeout it produces looks like a broken instrument rather
        # than a slow one.
        self.attempt(3, "measure() at 0 V",
                     lambda: driver.measure(timeout_s=self._read_timeout()),
                     expect=self._expect_reading)

        driver.set_voltage_level(self.probe.voltage)
        time.sleep(0.05)
        result = self.attempt(
            3, f"measure() at {self.probe.voltage} V",
            lambda: driver.measure(timeout_s=self._read_timeout()),
            expect=self._expect_reading)
        if result.severity == "pass":
            self._check_open_circuit(result)

        self.check_queue(3, "measure()")
        driver.set_voltage_level(0.0)

        # Sourcing current into an open circuit is the one place a
        # compliance limit is genuinely exercised: the instrument cannot
        # push the current anywhere, so it must ride into the voltage
        # limit. An instrument that reports something else here has a
        # compliance setting that is not doing what it says.
        # House rule 12: the output comes down before the
        # source function changes, and everything is configured before
        # it goes back up.
        #
        # This block used to change function with the output still on
        # and rely on the instrument dropping it - which the 2400 family
        # does, and which no manual in the suite states for the 2450,
        # the B2901A or the 2611A. Doing it explicitly makes the
        # sequence identical on every model instead of depending on an
        # answer nobody has, and it turns the gap into something that
        # can be measured rather than assumed.
        gap_start = time.monotonic()
        driver.safe_output_off()

        # Every one of these is graded rather than called bare, because
        # a driver is allowed to REFUSE a configuration and that is not
        # a crash.
        #
        # The U2722A did exactly that until the probe became
        # instrument-aware: the tool asked for a module-wide 1 uA, the
        # shared-knob reconciliation put the current axis on R120mA
        # where one count is 7.32 uA, and the driver declined rather
        # than emitting offset residue of a sign nobody commanded.
        # Called bare, that RangeError escaped and took tier 3 with it -
        # the tool reporting nothing at all about an instrument that had
        # answered the question correctly.
        #
        # The refusal path stays, and stays graded. Choosing the level
        # from the instrument's own floor removes the case where the
        # *tool* provoked it; a driver may still decline for a reason
        # nobody has thought of, and that belongs in the report next to
        # everything else the instrument said, with the driver's own
        # message, while the run continues to whatever can still be
        # checked.
        #
        # The level is settled in two stages for the same reason the
        # floor is an instance method on the driver: it depends on the
        # range `apply_ranges()` just landed on, so it cannot be known
        # until those three steps have run.
        configured = self.setup(3, "configure for current sourcing", [
            ("set_source_function('current')",
             lambda: driver.set_source_function("current")),
            ("apply_ranges()  [current mode]",
             lambda: driver.apply_ranges(RangePlan.for_sourcing(
                 "current", source_range=self.probe.current,
                 measure_range=self.probe.compliance_v))),
            (f"set_voltage_limit({self.probe.compliance_v:g})",
             lambda: driver.set_voltage_limit(self.probe.compliance_v)),
        ])
        if configured:
            level = self._resolve_source_level("current", "A")
            configured = self.setup(3, "configure for current sourcing", [
                (f"set_current_level({level:g})",
                 lambda: driver.set_current_level(level)),
            ])
        if not configured:
            # The gap entry is recorded even here, as a skip, so every
            # driver's report has the same shape and a missing entry
            # always means a tool fault rather than an instrument that
            # declined. There is no duration to give: the output never
            # came back up, because there was nothing to bring it up
            # for.
            self.record(3, "output gap across a source-function change",
                        "skip",
                        "not measured - the instrument could not be "
                        "configured for current sourcing, so the output "
                        "was left off rather than restored",
                        elapsed_s=time.monotonic() - gap_start)
            self.record(3, "current-sourcing checks", "skip",
                        "the instrument could not be configured for "
                        "current sourcing - see the failure above; the "
                        "checks that depend on it were not attempted")
            driver.safe_output_off()
            return
        # The output has to be turned on AGAIN after a source-function
        # change. Changing function drops the output on the 2400 family,
        # and with auto output-off disabled - which this driver sets, so
        # that a sweep holds its level between points - the 2401's own
        # documentation is explicit that "the output must be turned on
        # before you can perform a :READ?".
        #
        # Miss it and `:READ?` simply never answers: the trigger model
        # is waiting for source-measure operations that cannot happen,
        # so the query blocks until the VISA timeout and reports a
        # comms failure for what is actually a configuration mistake.
        # Every experiment already calls output_on() after
        # set_source_function(); this checkup did not, and spent two
        # rounds looking like a driver fault.
        self.attempt(3, "output_on()  [after the mode change]",
                     driver.output_on)

        # How long the sample was not energised across a source-function
        # change, on this instrument, over this bus. Recorded because
        # the IV periodic run has to interrupt a bias to change function
        # (decision W6-3) and the operator needs a number to compare
        # against their device's relaxation time - not an assurance that
        # it was brief. On a slow GPIB link this is dominated by command
        # turnaround, not by the instrument.
        #
        # Informational: there is no threshold to pass or fail against,
        # because what counts as too long depends on the sample.
        gap_s = time.monotonic() - gap_start
        self.record(3, "output gap across a source-function change",
                    "pass", f"{gap_s * 1000:.0f} ms de-energised",
                    elapsed_s=gap_s)
        result = self.attempt(
            3,
            f"measure() sourcing {self.probe.current:g} A into open circuit",
            lambda: self._settle_to_compliance(),
            expect=self._expect_reading)
        if result.severity == "pass":
            volts, _ = self._last_reading
            ramping = getattr(self, "_ramping", False)
            if not self.open_circuit:
                self.record(3, "compliance on a sourced current", "skip",
                            f"{volts:.4g} V - not checked, something is "
                            f"connected")
            elif abs(volts) > self.probe.compliance_v * COMPLIANCE_CEILING:
                # The compliance is not being enforced at the value that
                # was requested. Checked BEFORE settling, because an
                # output above its own limit is a fault whether it has
                # come to rest there or is still on its way past.
                #
                # This is what the U2722A did on 2026-08-21: -2.0 V
                # against a 1 V limit, the limit having been refused as
                # below that range's floor, so the range rail bounded
                # the output instead. The check tested only the lower
                # edge and called it a pass.
                #
                # Loud, because of what a compliance is for. It is the
                # bound on what reaches the sample and the person at the
                # fixture, and an instrument holding a wider one than
                # the software asked for is exactly the case that must
                # not be discovered from the data afterwards.
                self.record(
                    3, "compliance reached on open circuit", "fail",
                    f"{volts:.4g} V against a "
                    f"{self.probe.compliance_v} V limit"
                    f" - beyond it by more than "
                    f"{(COMPLIANCE_CEILING - 1) * 100:.0f}%, so the limit "
                    f"that is holding the output is not the one that was "
                    f"set. Check whether the instrument accepted it: a "
                    f"limit can be refused for being small relative to "
                    f"the active range, and the range rail bounds the "
                    f"output instead")
            elif ramping:
                # Still climbing when the budget ran out. That is the
                # output capacitance charging at the probe current, not
                # a load - so it says so rather than sending someone to
                # check the terminals.
                self.record(
                    3, "compliance reached on open circuit", "skip",
                    f"reached {volts:.4g} V of a {self.probe.compliance_v} V "
                    f"limit and was still rising - the output is charging "
                    f"its own capacitance at {self.probe.current:g} A, "
                    f"which is open-circuit behaviour, just slow. "
                    f"Not a load")
            elif abs(volts) >= self.probe.compliance_v * COMPLIANCE_FLOOR:
                # Settled, and within the window. Only now is the
                # instrument known to be clamping, which is the one
                # moment `compliance_tripped()` can be asked where True
                # is the correct answer.
                #
                # Magnitude only. The SIGN carries no information here
                # and an earlier version of this check wrongly warned
                # about it.
                #
                # An instrument in compliance is not regulating: the
                # miniSMU reported -1.02 V while measuring -1.2e-10 A
                # against a requested +1 uA, so it was not delivering
                # the current at all. Which rail the loop saturates to
                # with nothing to push against is implementation-
                # defined, and a 10 kohm resistor later confirmed that
                # model's polarity is entirely conventional - positive
                # current, positive voltage, R = +9.95 kohm.
                #
                # Polarity can only be judged where the instrument is
                # actually delivering what was asked, which an open
                # circuit never is. The known-resistor test settles it;
                # this one cannot.
                self.record(
                    3, "compliance reached on open circuit", "pass",
                    f"{volts:.4g} V against a "
                    f"{self.probe.compliance_v} V limit,"
                    f" settled (sign not checked - a railed output saturates "
                    f"whichever way the loop happens to go)")
                self._check_compliance_reported()
            else:
                self.record(
                    3, "compliance reached on open circuit", "warn",
                    f"settled at {volts:.4g} V against a "
                    f"{self.probe.compliance_v} V limit and stopped rising - "
                    f"with nothing connected the output should ride up to "
                    f"compliance. Is something attached?")

        # Back to sourcing voltage for the timing and sweep checks.
        # Same house rule 12 sequence as the change on the way in: down,
        # reconfigure, up. This one also relied on the instrument
        # dropping its own output at the function change.
        driver.set_current_level(0.0)
        driver.safe_output_off()
        driver.set_source_function("voltage")
        driver.set_current_limit(self.probe.compliance_i)
        driver.output_on()
        # Timed before the sweep, because the sweep's deadline depends
        # on the answer.
        self._tier3_timing()
        self._tier3_sweep()

    def _tier3_sweep(self):
        """A short sweep through whichever path this driver uses.

        Deliberately runs the same three-method sequence the experiments
        use rather than a shortcut, because on the miniSMU and the GSM
        that sequence is where the hardware path lives, and a hardware
        sweep that never starts is invisible from a single measure().
        """
        driver = self.driver
        kind = driver.sweep_kind()
        try:
            driver.start_linear_sweep("voltage", 0.0, self.probe.voltage,
                                      SWEEP_POINTS, 0.01)
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, f"start_linear_sweep()  [{kind}]", "fail",
                        f"{type(exc).__name__}: {exc}")
            return
        self.record(3, f"start_linear_sweep()  [{kind}]", "pass")

        # The deadline is derived from what a reading has already been
        # observed to cost on THIS instrument, not from a fixed number.
        # Readings here span four orders of magnitude - sub-millisecond
        # on the simulated driver, over ten seconds on a U2722A at a
        # long aperture - so any constant is either uselessly long for
        # one instrument or a false failure on another.
        per_reading = self._seconds_per_reading or 1.0
        # The first-read cost is added rather than folded into
        # `per_reading`, because a sweep pays it once and not per point.
        # It used to be inside the average, which made the deadline
        # accidentally generous - and would have made it accidentally
        # tight on any instrument whose first read is quicker than its
        # steady state, arriving as "sweep completes: fail" with nothing
        # to say why.
        first_read = getattr(self, "_first_reading_s", None) or 0.0
        budget = max(30.0,
                     per_reading * SWEEP_POINTS * 3.0 + first_read + 10.0)
        started = time.perf_counter()
        deadline = started + budget
        ready = 0
        while ready < SWEEP_POINTS and time.perf_counter() < deadline:
            try:
                ready = driver.sweep_points_ready()
            except TransportDesynchronised:
                raise
            except Exception as exc:
                self.record(3, "sweep_points_ready()", "fail", str(exc))
                driver.abort_sweep()
                return
            time.sleep(0.02)
        elapsed = time.perf_counter() - started

        if ready < SWEEP_POINTS:
            self.record(3, "sweep completes", "fail",
                        f"only {ready} of {SWEEP_POINTS} points after "
                        f"{elapsed:.1f} s (allowed {budget:.0f} s for "
                        f"{SWEEP_POINTS} points at {per_reading:.3g} s per "
                        f"reading); aborting")
            driver.abort_sweep()
            return
        self.record(3, "sweep completes", "pass",
                    f"{SWEEP_POINTS} points in {elapsed:.2f} s", elapsed)

        try:
            sourced, measured = driver.read_sweep(SWEEP_POINTS)
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, "read_sweep()", "fail",
                        f"{type(exc).__name__}: {exc}")
            return

        if len(sourced) != SWEEP_POINTS or len(measured) != SWEEP_POINTS:
            self.record(3, "read_sweep() returns the right shape", "fail",
                        f"{len(sourced)} sourced, {len(measured)} measured, "
                        f"expected {SWEEP_POINTS} of each")
        else:
            self.record(3, "read_sweep() returns the right shape", "pass",
                        f"{SWEEP_POINTS} pairs")
            span = max(sourced) - min(sourced)
            # A short span has two very different causes, and calling
            # them both a fault would make this check cry wolf on every
            # low-resistance sample. Either the source never moved -
            # clamped by its range, or not stepping - or it moved
            # exactly as asked and the *compliance* limited it, which is
            # the instrument working correctly.
            peak = max((abs(i) for i in measured if i is not None),
                       default=0.0)
            clamped_by_compliance = peak >= self.probe.compliance_i * 0.9

            if span >= self.probe.voltage * 0.5:
                self.record(3, "the sweep actually moved", "pass",
                            f"{min(sourced):.4g} to {max(sourced):.4g} V")
            elif clamped_by_compliance and not self.open_circuit:
                self.record(
                    3, "the sweep actually moved", "skip",
                    f"span was only {span:.4g} V, but the current reached "
                    f"{peak:.3g} A against a {self.probe.compliance_i:g} A "
                    f"compliance - the limit stopped it, not the source. "
                    f"Expected with a low-resistance sample connected")
            elif clamped_by_compliance:
                self.record(
                    3, "the sweep actually moved", "warn",
                    f"span was only {span:.4g} V and the current reached "
                    f"{peak:.3g} A against a {self.probe.compliance_i:g} A "
                    f"compliance. The source is working, but an open "
                    f"circuit should not draw compliance current - "
                    f"something is probably connected")
            else:
                self.record(
                    3, "the sweep actually moved", "fail",
                    f"sourced values span only {span:.4g} V of a requested "
                    f"{self.probe.voltage} V, and the current stayed well "
                    f"below compliance at {peak:.3g} A - so the source is not "
                    f"stepping. It may be clamped, or clipped by its range")
        self.check_queue(3, "the sweep")

        # Drivers set their sweep note during read_sweep() when
        # something needed saying - the GSM records how many points came
        # back as NAN or over-range and were dropped. Tier 1 reads this
        # note too, but that is before any sweep has run, so the
        # interesting version only exists now. Without this, a short
        # sweep looks like an unexplained shortfall when the driver
        # already knows exactly why.
        note = getattr(driver, "sweep_note", None)
        if callable(note):
            try:
                text = note()
            except TransportDesynchronised:
                raise
            except Exception:
                text = None
            if text:
                self.record(3, "driver note after the sweep", "pass", text)

    def _check_compliance_reported(self):
        """Ask `compliance_tripped()` at the one moment the answer is
        known, and known to be True.

        Tier 2 already calls it, but with the output off - where the
        honest answer is False, and where a method that always returns
        False, or always returns None, passes just as well. That is the
        same shape as the B2901A's first sense-function probe, which
        counted enabled measurement functions after a reset that had
        already enabled them all: an observation that would have been
        identical whether or not the command worked.

        Here the instrument is demonstrably clamping - it is sourcing a
        current into an open circuit and the measured voltage has just
        been confirmed at the limit - so True is the only correct
        answer, and every wrong implementation is distinguishable:

          * `None`  - the driver does not implement it. Recorded as a
                      skip, because "cannot say" is a legitimate answer
                      and several drivers here give it.
          * `False` - implemented and wrong. This is the failure worth
                      catching: a sweep that clamps still draws a
                      convincing straight line with a high R-squared,
                      and the fit describes the limit rather than the
                      sample.
          * raises  - implemented and broken.

        Only meaningful on an open circuit; with something connected the
        instrument may legitimately not be in compliance at all, and the
        caller has already established that before getting here.
        """
        driver = self.driver
        try:
            state = driver.compliance_tripped()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(
                3, "compliance_tripped() while clamping", "fail",
                f"raised {type(exc).__name__}: {exc}")
            return

        if state is None:
            self.record(
                3, "compliance_tripped() while clamping", "skip",
                "this driver does not report compliance - a flat top on "
                "a curve may be the only warning you get")
        elif state:
            self.record(
                3, "compliance_tripped() while clamping", "pass",
                "reported True while riding the voltage limit")
        else:
            self.record(
                3, "compliance_tripped() while clamping", "fail",
                "reported False while the output was demonstrably at "
                "compliance. A clamped sweep still produces a neat "
                "straight line, so this is the check that would have "
                "told you the fit describes the limit and not the "
                "sample")

    def _time_readings(self, count=TIMED_READINGS):
        """Time `count` readings, discarding a warm-up read first.

        Returns `(steady_s, first_s)`, or `(None, None)` if a read
        raised.

        The warm-up is the whole point. **Every instrument in the
        registry pays a large one-off on the first reading after
        `output_on()`**, and averaging it in was distorting the headline
        figure on all of them - measured 2026-08-21:

            B2901A      173.2 ms then 4.8 ms      reported 38.6 (8x)
            2635B      1098.4 ms then 17.1 ms     reported 233.6 (14x)
            GSM-20H10   318.9 ms then 14.3 ms     reported 75.3 (5.2x)
            2611A        70.8 ms then 15.9 ms     reported 26.9 (1.7x)
            2401         91.7 ms then 37.0 ms     reported 48.0 (1.3x)

        That number is not cosmetic. It is published as the "Per
        reading" column in `bench/choosing-an-smu.md`, where somebody
        plans a run from it; it sets the sweep deadline; and it is the
        input to `_aperture_cost()`, whose slope answers whether an
        instrument's NPLC integrates at all. A first-read offset that
        differs between the two NPLC points corrupts both the slope and
        the intercept.

        It was not autoranging, which was the first hypothesis. The
        B2901A's ranges were fixed before its 173 ms read and it still
        paid 36x its steady state.

        Both numbers are real and the caller reports both. A user pays
        the first-read cost once per run, and on the 2635B that is over
        a second of dead time nobody had written down.
        """
        driver = self.driver
        try:
            first_started = time.perf_counter()
            driver.measure(timeout_s=self._read_timeout())
            first = time.perf_counter() - first_started

            started = time.perf_counter()
            for _ in range(count):
                driver.measure(timeout_s=self._read_timeout())
            steady = (time.perf_counter() - started) / float(count)
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self._timing_error = str(exc)
            return None, None
        return steady, first

    def _tier3_timing(self):
        """How long a reading takes, as information rather than a verdict.

        Worth recording because it is the number that decides whether a
        200-point sweep takes a minute or half an hour, it varies by two
        orders of magnitude across these instruments, and it is invisible
        until someone waits for it.
        """
        per_reading, first = self._time_readings()
        if per_reading is None:
            self.record(3, "reading timing", "warn",
                        getattr(self, "_timing_error", "read failed"))
            return
        self._seconds_per_reading = per_reading
        self._first_reading_s = first
        # Stated with the NPLC it was measured at. The number is
        # meaningless without it - the same instrument spans two orders
        # of magnitude across its own NPLC range - and an unqualified
        # figure in a report is one somebody will quote later.
        at = f" at NPLC {self._nplc:g}" if self._nplc else ""
        self.record(3, f"time per reading{at}", "pass",
                    f"{per_reading * 1000:.1f} ms "
                    f"({per_reading * 200:.1f} s for a 200-point sweep), "
                    f"steady state - the first reading is reported "
                    f"separately below",
                    per_reading)
        # Its own line rather than a parenthesis, because it is a cost
        # somebody plans around: it is paid once per run, it is not
        # predictable from the steady-state figure, and it spans a
        # factor of two hundred across this bench.
        ratio = (f", {first / per_reading:.0f}x the steady state"
                 if per_reading > 0 else "")
        self.record(3, "first reading after the output comes up", "pass",
                    f"{first * 1000:.1f} ms{ratio}", first)
        # After the headline figure, not before it: the aperture
        # calculation is a follow-up that only makes sense once the
        # reader has seen the number it is derived from.
        self._aperture_cost(per_reading)

    # ---- helpers ----
    def _aperture_cost(self, slow_reading_s):
        """How many apertures a single reading really costs.

        Only runs when --nplc asked for a specific integration time,
        because it needs two points on the same instrument: time a
        reading at the requested NPLC and again at the fast end, and the
        slope between them is the number of apertures per reading. The
        intercept is the fixed bus overhead.

        Worth automating rather than leaving as two manual runs. It
        answers a question that keeps coming up and that a single
        timing figure cannot: whether a driver's `measure()` costs one
        integration or two. The U2722A measured 2.04 apertures and
        34 ms of overhead, confirming that its separate `MEAS:VOLT?` and
        `MEAS:CURR?` each pay in full - which is why the driver says a
        point costs twice the aperture.

        Comparing across two separate runs is unreliable: per-reading
        overhead varies by machine and by port, by a factor of eight on
        one instrument here.
        """
        driver = self.driver
        cls = type(driver)
        if self.requested_nplc is None or not cls.supports_nplc():
            return
        fast = cls.NPLC_RANGE[0]
        slow = self._nplc
        if slow is None or abs(slow - fast) < 1e-9:
            return

        try:
            driver.set_nplc(fast)
            fast_clamped = cls.clamp_nplc(fast)
            # Through the same helper as the slow figure, so both points
            # on the fit are steady-state. They were not: each end
            # averaged in its own first read, and changing NPLC provokes
            # a fresh one. The two offsets do not cancel - on the 2635B
            # the first read is 65x the steady state at one end - so
            # they corrupted the slope and the intercept, which is the
            # whole output of this calculation.
            fast_reading, _ = self._time_readings()
            if fast_reading is None:
                raise RuntimeError(getattr(self, "_timing_error",
                                           "read failed"))
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, "apertures per reading", "warn", str(exc))
            return
        finally:
            try:
                driver.set_nplc(slow)     # leave it as asked
            except TransportDesynchronised:
                raise
            except Exception:
                pass

        span = (slow - fast_clamped) / 50.0
        if span <= 0:
            return
        apertures = (slow_reading_s - fast_reading) / span
        overhead = slow_reading_s - apertures * (slow / 50.0)
        detail = (f"{apertures:.2f} (fixed overhead {overhead * 1000:.0f} "
                  f"ms) - {fast_reading * 1000:.1f} ms at NPLC "
                  f"{fast_clamped:g} vs {slow_reading_s * 1000:.1f} ms at "
                  f"NPLC {slow:g}")

        # Well under one aperture is not a fast instrument - it is a
        # driver whose idea of an aperture is too big. The reading
        # cannot take less time than the integration it claims to be
        # doing, so a figure of 0.05 means the declared window is about
        # twenty times the real one, and the NPLC going into every CSV
        # is wrong by that factor. The miniSMU was out by eighteen.
        #
        # A slope of zero or below is a different thing again: it means
        # the two readings were not distinguishable, so there is no
        # measurement to report. It happens when the clock is too coarse
        # for the interval - time.monotonic() ticks every 15.6 ms on
        # Windows, which is why this code now uses perf_counter - or
        # when the instrument is quick enough that jitter swamps the
        # difference. Reporting "0.00 apertures" as if it were measured
        # would be worse than saying nothing, and dividing by it used to
        # raise ZeroDivisionError from inside a diagnostic tool.
        if apertures <= 0.0:
            self.record(
                3, "apertures per reading", "warn",
                f"{detail}. NOT MEASURABLE: the readings at NPLC "
                f"{fast_clamped:g} and {slow:g} were indistinguishable, so "
                f"the slope is zero or negative. Either the interval is "
                f"below the clock resolution or the difference is lost in "
                f"jitter; re-run with a larger NPLC separation",
                apertures)
            return

        if apertures < 0.5:
            self.record(
                3, "apertures per reading", "warn",
                f"{detail}. UNDER ONE APERTURE, which is impossible: a "
                f"reading cannot be quicker than the integration it "
                f"claims. The driver's declared aperture is about "
                f"{1 / apertures:.0f}x too long, so the NPLC it records "
                f"in the CSV is overstated by roughly that much",
                apertures)
            return

        # How much of the slow reading was actually integration. The
        # slope is only as good as this ratio: if the reading is mostly
        # overhead then the fit is measuring the link rather than the
        # instrument, and a few milliseconds of drift moves the answer
        # a long way.
        #
        # This is the difference between the two cross-session estimates
        # made by hand here. The U2722A's slow point was 500 ms of
        # integration against ~35 ms of overhead, so 3 ms of session
        # drift shifted it by 0.6% and the answer survived. The
        # miniSMU's was 5 ms of integration against overhead that varied
        # from 6 ms to 29 ms between sessions - the drift was four times
        # the signal, and the estimate was wrong by a factor of five.
        integration = apertures * (slow / 50.0)
        share = integration / slow_reading_s if slow_reading_s else 0.0
        if share < 0.5:
            detail += (f". Only {share * 100:.0f}% of that reading was "
                       f"integration, the rest overhead - so this slope is "
                       f"weakly determined. Use a slower NPLC for a firmer "
                       f"number")
        else:
            detail += (". About 1 means one integration per reading; about "
                       "2 means voltage and current are integrated "
                       "separately")

        self.record(3, "apertures per reading", "pass", detail, apertures)

    _last_reading = (None, None)

    def _read_timeout(self):
        """A read timeout that allows for the integration time in use,
        plus room for the instrument to autorange on the way."""
        aperture = (self._nplc or 1.0) / 50.0
        return max(10.0, aperture * 4.0 + 5.0)

    def _expect_reading(self, value):
        try:
            volts, amps = value
        except (TypeError, ValueError):
            return f"measure() returned {value!r}, expected a (volts, amps) pair"
        if volts is None or amps is None:
            return f"measure() returned {value!r} - a None means the reply " \
                   f"could not be parsed"
        try:
            float(volts), float(amps)
        except (TypeError, ValueError):
            return f"measure() returned non-numeric {value!r}"
        self._last_reading = (float(volts), float(amps))
        return True

    def _settle_to_compliance(self, budget_s=6.0):
        """Read while the output rides up, and stop when it stops rising.

        A fixed short wait is wrong here. Sourcing a small current into
        an open circuit charges the instrument's own output capacitance
        and nothing else, so the voltage *ramps* rather than jumping -
        and the ramp can be slow. A U2722A read 41 mV after 50 ms, which
        works out at about 1.2 uF being charged at 1 uA: a slew of
        roughly 1 V/s, needing well over a second to reach a 1 V limit.

        That produced a warning saying "expected the output to ride up
        to compliance - is something attached?", when nothing was
        attached and the output was simply still on its way. The
        earlier run passed the same check only because NPLC was left at
        255, making each reading take 10 s and hiding the ramp inside
        the measurement.

        **This loop used to exit the moment a reading passed 80% of the
        limit, without asking whether it was still climbing**, which is
        a different fault with the same cause. On the GSM-20H10 on
        2026-08-21 it stopped at 0.9151 V of a 1 V limit while still
        rising 0.23 V per poll, having spent 1.294 s of a 6 s budget -
        then asked `compliance_tripped()`, got the correct answer
        `False`, and recorded it as a failure. Invisible on a fast
        instrument: the 2401 and the 2611A reach the rail inside a
        single reading, so an 80% exit lands on an output that really
        is clamping and the check passes for the right reason. The
        threshold is a *verdict*, not a reason to stop looking.

        So the exit condition is now settling alone: two consecutive
        readings within `SETTLE_TOLERANCE_V` of each other, or the
        budget. `self._ramping` says which, and the caller decides what
        the settled value means.
        """
        deadline = time.perf_counter() + budget_s
        previous = None
        tolerance = self._settle_tolerance()
        reading = self.driver.measure(timeout_s=self._read_timeout())
        self._ramping = False

        while time.perf_counter() < deadline:
            volts = reading[0] if reading else None
            if volts is None:
                break
            if previous is not None and abs(volts - previous) < tolerance:
                break                      # stopped moving, wherever it is
            previous = volts
            time.sleep(0.25)
            reading = self.driver.measure(timeout_s=self._read_timeout())

        volts = reading[0] if reading else None
        # Still moving when the loop ended. Note this is decided by the
        # last pair of readings and not by where they landed: an output
        # sitting above the limit and still climbing is a fault, not a
        # settled clamp, and the old form could not express that.
        self._ramping = (volts is not None and previous is not None
                         and abs(volts - previous) >= tolerance)
        return reading

    def _check_open_circuit(self, result):
        volts, amps = self._last_reading
        if not self.open_circuit:
            self.record(3, "current at the probe voltage", "skip",
                        f"{amps:.3g} A at {volts:.4g} V - not checked, "
                        f"something is connected so the expected value is "
                        f"unknown")
            return
        if abs(amps) <= OPEN_CIRCUIT_MAX_A:
            self.record(3, "open-circuit current is near zero", "pass",
                        f"{amps:.3g} A at {volts:.4g} V")
        else:
            self.record(
                3, "open-circuit current is near zero", "warn",
                f"{amps:.3g} A at {volts:.4g} V, above the "
                f"{OPEN_CIRCUIT_MAX_A:g} A threshold. Either something is "
                f"connected to the output, or the reading is not in amps")
