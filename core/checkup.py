"""
Instrument checkup - what the offline test suite cannot prove.

`tests/` proves every driver has the right *shape* and sends the right
strings to a fake. It cannot prove a real instrument agrees. Every
command spelling in the U2722A and miniSMU drivers was written from a
manual and has never been answered by hardware; the ones in the older
drivers were read off working scripts but have since been reordered,
retimed and re-ranged.

This module is the other half: it drives a connected instrument through
the whole BaseSMU contract and asks, at every step, whether the
instrument understood. `tools/smu_checkup.py` is the front end.

---------------------------------------------------------------------
IT ASSUMES NOTHING IS CONNECTED TO THE OUTPUT
---------------------------------------------------------------------
Every level it sources is chosen to be safe into an open circuit, and
the expected results are the open-circuit ones: source a small voltage,
measure approximately no current. That is not a limitation, it is the
point - an open circuit is a *known* DUT, so the readings can be checked
rather than merely recorded. With a sample connected, "0.1 V produced
2 uA" proves nothing without knowing the sample.

Connect a sample and the measurement checks will report failures that
are not faults. The report says so at the top.

**Sensing is forced to 2-wire wherever the driver allows it.** With
nothing connected, an SMU in 4-wire mode has open sense leads and many
will slew the output to compliance trying to servo a voltage they cannot
see. Two instruments cannot be forced: the U2722A is hardwired 4-wire,
and the miniSMU's 4-wire mode is system-wide. Both are noted in the
report rather than silently skipped.

---------------------------------------------------------------------
Three tiers
---------------------------------------------------------------------
1. Identity and declarations - output off, nothing sourced.
2. Configuration syntax     - output off, every contract method called
                              and the error queue checked after each.
3. Live measurement         - sources at small levels into open circuit.

Tier 3 stops at the first failure in tiers 1-2 severe enough to make
sourcing unwise, and never runs if the output could not be turned off.
"""
import time
import traceback

# Levels used in tier 3. Small enough to be harmless into an open
# circuit on every instrument in the registry, and large enough to be
# well clear of the noise floor on all of them.
PROBE_VOLTAGE = 0.1          # V
PROBE_CURRENT = 1e-6         # A
PROBE_COMPLIANCE_I = 1e-4    # A
PROBE_COMPLIANCE_V = 1.0     # V

# Sourcing 0.1 V into an open circuit should draw essentially nothing.
# The threshold is loose because the 2611A's low ranges and the
# miniSMU's autoranging both have offsets at this level; what it is
# really catching is a reading that came back in the wrong units, from
# the wrong quantity, or as a compliance-clamped value.
OPEN_CIRCUIT_MAX_A = 1e-5

SWEEP_POINTS = 5


class Result:
    """One check: what was tried, what happened, and how bad it is.

    `severity` is one of "pass", "warn", "fail", "skip". A warn is
    something worth a human's attention that does not mean the driver
    is wrong - an unverifiable capability, a slow reading, an instrument
    that cannot be asked about errors.
    """

    def __init__(self, tier, name, severity, detail="", elapsed_s=None):
        self.tier = tier
        self.name = name
        self.severity = severity
        self.detail = detail
        self.elapsed_s = elapsed_s

    def as_dict(self):
        return {"tier": self.tier, "name": self.name,
                "severity": self.severity, "detail": self.detail,
                "elapsed_s": self.elapsed_s}


class Checkup:
    """Runs the checks and collects Results.

    Takes a live driver. Does not open or close the transport - the
    caller owns the connection, same rule the experiments follow.
    """

    def __init__(self, driver, log=None, open_circuit=True, nplc=None):
        self.driver = driver
        self.results = []
        self._log = log or (lambda text: None)
        self._output_is_off = False
        self._sensing_note = None
        self._nplc = None
        self._seconds_per_reading = None
        self._timeouts = 0
        self._comms_suspect = False
        self._ramping = False
        # False when something IS attached - the simulated instrument
        # models a resistor, and a bench operator may be checking a rig
        # they cannot easily unplug. The measurement checks then record
        # what they saw without judging it, because the expected answer
        # is unknown. Everything else runs unchanged.
        self.open_circuit = bool(open_circuit)
        # Integration time to measure at. None means the fast end of
        # the declared range, which is what a commissioning run wants.
        # Setting it deliberately turns Tier 3's timing figure into an
        # experiment: read at two NPLCs and the difference is the
        # instrument's actual per-reading cost, which is how many
        # apertures a "reading" really costs.
        self.requested_nplc = nplc

    # ---- bookkeeping ----
    def record(self, tier, name, severity, detail="", elapsed_s=None):
        result = Result(tier, name, severity, detail, elapsed_s)
        self.results.append(result)
        mark = {"pass": "ok  ", "warn": "warn", "fail": "FAIL",
                "skip": "skip"}[severity]
        self._log(f"  [{mark}] {name}" + (f"  -- {detail}" if detail else ""))
        return result

    def attempt(self, tier, name, action, expect=None, allow_unsupported=True):
        """Call `action`, time it, and record what happened.

        `expect`, if given, is called with the return value and returns
        either True or a string explaining the problem. A
        NotImplementedError is recorded as a skip rather than a failure
        when `allow_unsupported` - declining a capability the driver
        never claimed is correct behaviour, not a fault.
        """
        started = time.perf_counter()
        try:
            value = action()
        except NotImplementedError as exc:
            elapsed = time.perf_counter() - started
            if allow_unsupported:
                return self.record(tier, name, "skip", str(exc) or
                                   "not supported by this model", elapsed)
            return self.record(tier, name, "fail",
                               f"unexpectedly unsupported: {exc}", elapsed)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            detail = f"{type(exc).__name__}: {exc}"
            if self._looks_like_timeout(exc):
                detail += self._recover_from_timeout()
            return self.record(tier, name, "fail", detail, elapsed)

        elapsed = time.perf_counter() - started
        if expect is not None:
            verdict = expect(value)
            if verdict is not True:
                return self.record(tier, name, "fail", str(verdict), elapsed)
        return self.record(tier, name, "pass",
                           "" if value is None else str(value)[:120], elapsed)

    def check_queue(self, tier, after):
        """Ask the instrument whether it understood the last command.

        This is the check that makes the whole tool worth running: it is
        the difference between "the method did not raise" - which the
        offline tests already prove against a fake - and "the instrument
        confirmed it parsed that".
        """
        try:
            errors = []
            for _ in range(21):
                code, message = self.driver.read_error()
                if code == 0:
                    break
                errors.append(f"{code}: {message}")
        except Exception as exc:
            return self.record(tier, f"error queue after {after}", "warn",
                               f"could not read the queue: {exc}")
        if errors:
            return self.record(tier, f"error queue after {after}", "fail",
                               "; ".join(errors))
        return self.record(tier, f"error queue after {after}", "pass")

    @staticmethod
    def _looks_like_timeout(exc):
        """Whether a failure was the instrument not answering in time."""
        text = f"{type(exc).__name__} {exc}".upper()
        return any(token in text for token in
                   ("TIMEOUT", "VI_ERROR_TMO", "TIMED OUT"))

    def _recover_from_timeout(self):
        """Resynchronise after a timed-out query, and say whether it
        worked.

        Without this, one slow reading poisons everything after it. The
        instrument finishes the measurement late, the reply lands in the
        output buffer, and the next query collects it instead of its
        own - so the session runs one command out of step and every
        later check fails for a reason that has nothing to do with what
        it was testing. A 2401 on the bench produced three consecutive
        failures from one slow reading, which read as three faults.

        The recovery note is appended to the failure that caused it, so
        the report says which failure was the real one.
        """
        transport = getattr(self.driver, "transport", None)
        cleared = False
        if transport is not None:
            try:
                cleared = bool(transport.clear())
            except Exception:
                cleared = False
        self._timeouts += 1
        if cleared:
            return (" [the instrument was not answering; a device clear "
                    "was sent to resynchronise, so later checks should "
                    "be independent of this one]")
        self._comms_suspect = True
        return (" [the instrument was not answering and could not be "
                "resynchronised, so FAILURES BELOW THIS POINT MAY BE "
                "CONSEQUENCES OF IT rather than separate faults]")

    def _drain_quietly(self):
        """Empty the error queue without recording anything.

        Used after a deliberate mode change, so that a complaint about
        the *previous* mode's configuration is not attributed to the
        first command of the next one.
        """
        try:
            for _ in range(21):
                code, _ = self.driver.read_error()
                if code == 0:
                    return
        except Exception:
            return

    def counts(self):
        out = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
        for result in self.results:
            out[result.severity] += 1
        return out

    # ---- tier 1 ----
    def tier1_identity(self):
        driver = self.driver
        self._log("\nTier 1 - identity and declarations")

        self.attempt(1, "identify()", driver.identify,
                     expect=lambda v: True if v and str(v).strip()
                     else "empty identity reply")

        # The registry is what picks the driver at connect. If the
        # identity no longer resolves to the class in use, auto-detection
        # is broken even though everything else may work.
        from drivers.registry import driver_for_idn
        try:
            idn = driver.identify()
            resolved = driver_for_idn(idn)
            if resolved is type(driver):
                self.record(1, "identity resolves to this driver", "pass",
                            type(driver).__name__)
            elif resolved is None:
                self.record(1, "identity resolves to this driver", "fail",
                            f"MODEL_IDS {type(driver).MODEL_IDS} does not "
                            f"match {idn!r} - auto-detect would fail")
            else:
                self.record(1, "identity resolves to this driver", "fail",
                            f"resolves to {resolved.__name__}, not "
                            f"{type(driver).__name__} - auto-detect would "
                            f"pick the wrong driver for this instrument")
        except Exception as exc:
            self.record(1, "identity resolves to this driver", "fail", str(exc))

        for label, value in (
                ("firmware", getattr(driver, "firmware", None)),
                ("sweep kind", getattr(driver, "sweep_kind", None))):
            if callable(value):
                self.attempt(1, label, value)

        self.attempt(1, "reset()", driver.reset)
        self.check_queue(1, "reset()")

        note = getattr(driver, "sweep_note", None)
        if callable(note):
            self.attempt(1, "sweep_note()", note)

        limits = driver.LIMITS
        self.record(1, "declared limits", "pass",
                    f"{limits.max_voltage} V, {limits.max_current} A, "
                    f"{len(limits.current_ranges)} current range(s)")

    # ---- tier 2 ----
    def tier2_configuration(self):
        driver = self.driver
        self._log("\nTier 2 - configuration syntax (output off)")

        # Off first and off throughout. Everything below is configuration
        # only; nothing should reach the terminals.
        result = self.attempt(2, "output_off()", driver.output_off)
        self._output_is_off = result.severity == "pass"
        self.check_queue(2, "output_off()")

        self._force_two_wire()

        for mode in ("voltage", "current"):
            self.attempt(2, f"set_source_function({mode!r})",
                         lambda m=mode: driver.set_source_function(m))
            self.check_queue(2, f"set_source_function({mode!r})")

        # Each setter is exercised in the source mode the experiments
        # actually use it in, and NOT in the other one.
        #
        # This is not fussiness. A real instrument rejects the wrong
        # combination and is right to: setting a current *level* while
        # sourcing voltage is a settings conflict, and on the GSM-20H10
        # setting the source range while source read-back is on is
        # error 823. An earlier version of this checkup called every
        # setter in one mode and reported both as driver faults, which
        # they are not - IVSweepExperiment._one_sweep never makes either
        # call. A commissioning tool that invents failures the
        # application cannot produce is worse than useless, because it
        # trains people to ignore it.
        #
        # So the shape below mirrors _one_sweep: sourcing voltage means
        # limiting and ranging the *current*, and vice versa.
        by_mode = {
            "voltage": [
                ("set_current_limit", lambda: driver.set_current_limit(
                    PROBE_COMPLIANCE_I)),
                ("set_current_range", lambda: driver.set_current_range(
                    PROBE_COMPLIANCE_I)),
                ("set_voltage_level(0)",
                 lambda: driver.set_voltage_level(0.0)),
            ],
            "current": [
                ("set_voltage_limit", lambda: driver.set_voltage_limit(
                    PROBE_COMPLIANCE_V)),
                ("set_voltage_range", lambda: driver.set_voltage_range(
                    PROBE_COMPLIANCE_V)),
                ("set_current_level(0)",
                 lambda: driver.set_current_level(0.0)),
            ],
        }
        for mode, checks in by_mode.items():
            driver.set_source_function(mode)
            self._drain_quietly()
            for name, action in checks:
                label = f"{name}()" if "(" not in name else name
                self.attempt(2, f"{label}  [sourcing {mode}]", action)
                self.check_queue(2, f"{name} while sourcing {mode}")

        driver.set_source_function("voltage")
        self._drain_quietly()
        self.attempt(2, "set_source_delay()",
                     lambda: driver.set_source_delay(0.01))
        self.check_queue(2, "set_source_delay")

        # Autoranging is a real capability on some models and absent on
        # others; a NotImplementedError here is information, not a fault.
        self.attempt(2, "set_current_range(None)  [auto]",
                     lambda: driver.set_current_range(None))
        self.check_queue(2, "set_current_range(None)")

        self._tier2_capabilities()

    def _force_two_wire(self):
        """2-wire for the checkup, where the driver allows it.

        With nothing connected, 4-wire leaves the sense leads open and
        many SMUs will slew to compliance trying to servo a voltage they
        cannot measure. Where sensing cannot be changed, that is recorded
        rather than worked around - the operator needs to know the
        readings below were taken 4-wire into an open circuit.
        """
        driver = self.driver
        supports = driver.supports_remote_sense_control()
        if not supports:
            self._sensing_note = (
                f"sensing is fixed at {driver.fixed_sense() or 'unknown'} on "
                f"this model, so the measurement checks below run 4-wire "
                f"into an open circuit and may read at compliance")
            self.record(2, "set_remote_sense(False)", "skip",
                        self._sensing_note)
            return
        result = self.attempt(2, "set_remote_sense(False)  [2-wire]",
                              lambda: driver.set_remote_sense(False))
        if result.severity != "pass":
            self._sensing_note = ("2-wire could not be selected; readings "
                                  "below may be affected")
        self.check_queue(2, "set_remote_sense(False)")

    def _tier2_capabilities(self):
        """Every declared optional capability, exercised once.

        A declaration that the instrument rejects is the most valuable
        thing this tool can find: the ledger says the model has the
        feature, the hardware disagrees, and until now nothing checked.
        """
        driver = self.driver
        cls = type(driver)

        if cls.supports_nplc():
            low, high = cls.NPLC_RANGE
            for value in (low, high):
                self.attempt(2, f"set_nplc({value:g})  [declared limit]",
                             lambda v=value: driver.set_nplc(v),
                             allow_unsupported=False)
                self.check_queue(2, f"set_nplc({value:g})")
            # And put it somewhere sensible before anything is
            # measured. Leaving it at the declared ceiling is a real
            # trap: the U2722A's ceiling is 255 PLC, which at 50 Hz is a
            # 5.1 s aperture, and with no combined read that is 10.5 s
            # per point. A 5-point sweep then takes nearly a minute and
            # times out, which reads as a broken sweep on an instrument
            # that was working exactly as configured.
            wanted = low if self.requested_nplc is None \
                else driver.clamp_nplc(self.requested_nplc)
            label = "restored for measuring" if self.requested_nplc is None \
                else "requested"
            self.attempt(2, f"set_nplc({wanted:g})  [{label}]",
                         lambda: driver.set_nplc(wanted),
                         allow_unsupported=False)
            self._nplc = driver.clamp_nplc(wanted)
        else:
            self.record(2, "NPLC", "skip", "not declared for this model")

        if cls.supports_ovp():
            choice = cls.OVP_CHOICES[0]
            self.attempt(2, f"set_voltage_protection({choice!r})",
                         lambda: driver.set_voltage_protection(choice),
                         allow_unsupported=False)
            self.check_queue(2, "set_voltage_protection()")
        else:
            self.record(2, "OVP", "skip", "not declared for this model")

        if cls.supports_high_z_off():
            self.attempt(2, "set_output_off_mode(high_z=True)",
                         lambda: driver.set_output_off_mode(True),
                         allow_unsupported=False)
            self.check_queue(2, "set_output_off_mode()")
            self.attempt(2, "set_output_off_mode(high_z=False)",
                         lambda: driver.set_output_off_mode(False),
                         allow_unsupported=False)
        else:
            self.record(2, "high-Z output off", "skip",
                        "not declared for this model")

        self.attempt(2, "compliance_tripped()", driver.compliance_tripped)

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
        driver.set_current_limit(PROBE_COMPLIANCE_I)
        try:
            driver.set_current_range(PROBE_COMPLIANCE_I)
        except NotImplementedError:
            pass
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

        driver.set_voltage_level(PROBE_VOLTAGE)
        time.sleep(0.05)
        result = self.attempt(
            3, f"measure() at {PROBE_VOLTAGE} V",
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
        driver.set_source_function("current")
        driver.set_voltage_limit(PROBE_COMPLIANCE_V)
        try:
            driver.set_voltage_range(PROBE_COMPLIANCE_V)
        except NotImplementedError:
            pass
        driver.set_current_level(PROBE_CURRENT)
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
        result = self.attempt(
            3, f"measure() sourcing {PROBE_CURRENT:g} A into open circuit",
            lambda: self._settle_to_compliance(),
            expect=self._expect_reading)
        if result.severity == "pass":
            volts, _ = self._last_reading
            if not self.open_circuit:
                self.record(3, "compliance on a sourced current", "skip",
                            f"{volts:.4g} V - not checked, something is "
                            f"connected")
            elif abs(volts) >= PROBE_COMPLIANCE_V * 0.8:
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
                    f"{volts:.4g} V against a {PROBE_COMPLIANCE_V} V limit "
                    f"(sign not checked - a railed output saturates "
                    f"whichever way the loop happens to go)")
                self._check_compliance_reported()
            elif getattr(self, "_ramping", False):
                # Still climbing when the budget ran out. That is the
                # output capacitance charging at the probe current, not
                # a load - so it says so rather than sending someone to
                # check the terminals.
                self.record(
                    3, "compliance reached on open circuit", "skip",
                    f"reached {volts:.4g} V of a {PROBE_COMPLIANCE_V} V "
                    f"limit and was still rising - the output is charging "
                    f"its own capacitance at {PROBE_CURRENT:g} A, which is "
                    f"open-circuit behaviour, just slow. Not a load")
            else:
                self.record(
                    3, "compliance reached on open circuit", "warn",
                    f"settled at {volts:.4g} V against a "
                    f"{PROBE_COMPLIANCE_V} V limit and stopped rising - "
                    f"with nothing connected the output should ride up to "
                    f"compliance. Is something attached?")

        driver.set_current_level(0.0)
        driver.set_source_function("voltage")
        driver.set_current_limit(PROBE_COMPLIANCE_I)
        driver.output_on()          # same reason as above
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
            driver.start_linear_sweep("voltage", 0.0, PROBE_VOLTAGE,
                                      SWEEP_POINTS, 0.01)
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
        budget = max(30.0, per_reading * SWEEP_POINTS * 3.0 + 10.0)
        started = time.perf_counter()
        deadline = started + budget
        ready = 0
        while ready < SWEEP_POINTS and time.perf_counter() < deadline:
            try:
                ready = driver.sweep_points_ready()
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
            clamped_by_compliance = peak >= PROBE_COMPLIANCE_I * 0.9

            if span >= PROBE_VOLTAGE * 0.5:
                self.record(3, "the sweep actually moved", "pass",
                            f"{min(sourced):.4g} to {max(sourced):.4g} V")
            elif clamped_by_compliance and not self.open_circuit:
                self.record(
                    3, "the sweep actually moved", "skip",
                    f"span was only {span:.4g} V, but the current reached "
                    f"{peak:.3g} A against a {PROBE_COMPLIANCE_I:g} A "
                    f"compliance - the limit stopped it, not the source. "
                    f"Expected with a low-resistance sample connected")
            elif clamped_by_compliance:
                self.record(
                    3, "the sweep actually moved", "warn",
                    f"span was only {span:.4g} V and the current reached "
                    f"{peak:.3g} A against a {PROBE_COMPLIANCE_I:g} A "
                    f"compliance. The source is working, but an open "
                    f"circuit should not draw compliance current - "
                    f"something is probably connected")
            else:
                self.record(
                    3, "the sweep actually moved", "fail",
                    f"sourced values span only {span:.4g} V of a requested "
                    f"{PROBE_VOLTAGE} V, and the current stayed well below "
                    f"compliance at {peak:.3g} A - so the source is not "
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

    def _tier3_timing(self):
        """How long a reading takes, as information rather than a verdict.

        Worth recording because it is the number that decides whether a
        200-point sweep takes a minute or half an hour, it varies by two
        orders of magnitude across these instruments, and it is invisible
        until someone waits for it.
        """
        driver = self.driver
        started = time.perf_counter()
        count = 0
        try:
            for _ in range(5):
                driver.measure(timeout_s=self._read_timeout())
                count += 1
        except Exception as exc:
            self.record(3, "reading timing", "warn", str(exc))
            return
        per_reading = (time.perf_counter() - started) / max(count, 1)
        self._seconds_per_reading = per_reading
        # Stated with the NPLC it was measured at. The number is
        # meaningless without it - the same instrument spans two orders
        # of magnitude across its own NPLC range - and an unqualified
        # figure in a report is one somebody will quote later.
        at = f" at NPLC {self._nplc:g}" if self._nplc else ""
        self.record(3, f"time per reading{at}", "pass",
                    f"{per_reading * 1000:.1f} ms "
                    f"({per_reading * 200:.1f} s for a 200-point sweep)",
                    per_reading)
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
            started = time.perf_counter()
            for _ in range(5):
                driver.measure(timeout_s=self._read_timeout())
            fast_reading = (time.perf_counter() - started) / 5.0
        except Exception as exc:
            self.record(3, "apertures per reading", "warn", str(exc))
            return
        finally:
            try:
                driver.set_nplc(slow)     # leave it as asked
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

        So: poll until the reading reaches compliance or stops changing,
        and record which it was. `self._ramping` is set when the output
        was still climbing at the end, so the caller can say so rather
        than blaming a phantom load.
        """
        deadline = time.perf_counter() + budget_s
        previous = None
        reading = self.driver.measure(timeout_s=self._read_timeout())
        self._ramping = False

        while time.perf_counter() < deadline:
            volts = reading[0] if reading else None
            if volts is None:
                break
            if abs(volts) >= PROBE_COMPLIANCE_V * 0.8:
                break
            if previous is not None and abs(volts - previous) < \
                    PROBE_COMPLIANCE_V * 0.005:
                break                      # settled below compliance
            previous = volts
            time.sleep(0.25)
            reading = self.driver.measure(timeout_s=self._read_timeout())

        volts = reading[0] if reading else None
        if volts is not None and previous is not None:
            self._ramping = (abs(volts) < PROBE_COMPLIANCE_V * 0.8
                             and abs(volts - previous)
                             >= PROBE_COMPLIANCE_V * 0.005)
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

    def run(self, tiers=(1, 2, 3)):
        if 1 in tiers:
            self.tier1_identity()
        if 2 in tiers:
            self.tier2_configuration()
        if 3 in tiers:
            self.tier3_measurement()
        return self.results


def build_report(driver, results, address="", sensing_note=None,
                 open_circuit=True):
    """Render the results as Markdown."""
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for result in results:
        counts[result.severity] += 1

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    verdict = "FAIL" if counts["fail"] else (
        "PASS WITH WARNINGS" if counts["warn"] else "PASS")

    lines = [
        f"# Instrument checkup - {type(driver).DISPLAY_NAME}",
        "",
        f"- **Result:** {verdict}",
        f"- **When:** {stamp}",
        f"- **Address:** {address or 'not recorded'}",
        f"- **Driver:** `{type(driver).__name__}`",
        f"- **Checks:** {counts['pass']} passed, {counts['warn']} warned, "
        f"{counts['fail']} failed, {counts['skip']} skipped",
        "",
        "> This checkup assumes **nothing is connected to the output**. "
        "The measurement checks expect open-circuit behaviour, so a "
        "connected sample will produce warnings that are not faults."
        if open_circuit else
        "> This checkup was told **something is connected** to the "
        "output. The open-circuit measurement checks were skipped, "
        "because the expected reading is unknown. Everything else ran "
        "normally.",
        "",
    ]
    if sensing_note:
        lines += [f"> {sensing_note}", ""]
    # Deliberately the built-in sum, not math.fsum: this counts
    # results, and fsum would return a float where an integer count is
    # meant. The 3.12 float-summation change that moved the maths
    # modules does not touch integer summation.
    timeouts = sum(1 for r in results
                   if r.severity == "fail" and "not answering" in r.detail)
    if timeouts:
        lines += [
            f"> **{timeouts} query timed out.** A timed-out read can leave "
            f"the instrument one command out of step, so check whether the "
            f"failures below are separate faults or consequences of the "
            f"first one.", ""]

    if counts["fail"]:
        lines += ["## Failures", ""]
        for result in results:
            if result.severity == "fail":
                lines.append(f"- **{result.name}** - {result.detail}")
        lines.append("")
    if counts["warn"]:
        lines += ["## Warnings", ""]
        for result in results:
            if result.severity == "warn":
                lines.append(f"- **{result.name}** - {result.detail}")
        lines.append("")

    titles = {1: "Tier 1 - identity and declarations",
              2: "Tier 2 - configuration syntax (output off)",
              3: "Tier 3 - live measurement"}
    for tier in (1, 2, 3):
        rows = [r for r in results if r.tier == tier]
        if not rows:
            continue
        lines += [f"## {titles[tier]}", "",
                  "| Check | Result | Detail |", "|---|---|---|"]
        for result in rows:
            detail = (result.detail or "").replace("|", "\\|")
            lines.append(f"| {result.name} | {result.severity} | {detail} |")
        lines.append("")

    return "\n".join(lines)
