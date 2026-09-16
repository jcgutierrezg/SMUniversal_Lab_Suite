"""Tier 2 - configuration: does each setting take, and read back?

A mixin on `Checkup`; the state it uses is set up by
`CheckupBase`.
"""

from smuniversal_lab_suite.core import readback as readback_states
from smuniversal_lab_suite.core.ranges import (
    AUTO,
    NOT_SOURCED,
    RangeError,
    RangePlan,
)
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised


class Tier2Checks:
    """Tier 2 - configuration: does each setting take, and read back?"""


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
        # Ranges before limits, which is fault 15 and which this tool had
        # backwards until 2026-08-20.
        #
        # On the GSM-20H10 the wrong order cost three of six checkup
        # failures and took tier 3 with them: the instrument would not
        # energise afterwards, so `measure()` returned `(None, None)`
        # and every reading, the sweep and the timing figure went with
        # it. Reordering took that instrument from six failures to
        # three, with tier 3 green.
        #
        # Every experiment already orders it correctly - that is what
        # `tests/test_range_before_limit.py` holds - so this tool was
        # producing a failure the application cannot produce, and then a
        # cascade of failures behind it. A commissioning tool that
        # invents faults teaches people to ignore it, which is the one
        # thing it cannot afford.
        by_mode = {
            "voltage": [
                ("apply_ranges", lambda: driver.apply_ranges(
                    RangePlan.for_sourcing(
                        "voltage", source_range=self.probe.voltage,
                        measure_range=self.probe.compliance_i))),
                ("set_current_limit", lambda: driver.set_current_limit(
                    self.probe.compliance_i)),
                ("set_voltage_level(0)",
                 lambda: driver.set_voltage_level(0.0)),
            ],
            "current": [
                ("apply_ranges", lambda: driver.apply_ranges(
                    RangePlan.for_sourcing(
                        "current", source_range=self.probe.current,
                        measure_range=self.probe.compliance_v))),
                ("set_voltage_limit", lambda: driver.set_voltage_limit(
                    self.probe.compliance_v)),
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
        # others; a refusal here is information, not a fault. The
        # U2722A has no autorange at all and says so - which is why the
        # plan carries AUTO on every axis rather than a value that
        # would quietly succeed.
        self.attempt(2, "apply_ranges(all AUTO)",
                     lambda: driver.apply_ranges(RangePlan(
                         source_current=AUTO, source_voltage=AUTO,
                         measure_current=AUTO, measure_voltage=AUTO)))
        self.check_queue(2, "apply_ranges(all AUTO)")

        self._tier2_compliance_survives_ranging()
        self._tier2_range_readback()
        self._tier2_range_wider_than_the_old_compliance()
        self._tier2_power_limit()
        self._tier2_sub_count_refusal()
        self._tier2_capabilities()

    def burst_configuration(self):
        """An SMU's configuration block, as the first run after a connect.

        `reset()` - which the app sends on every connect, so it is safe
        on every driver by construction - then ranges, the limit and a
        level, output off: the calls `_prepare()` makes. Without the
        reset the GSM-20H10's burst was 12 writes against the 25 that
        lost 7 queries in 10 on the bench, and a shorter burst than the
        real one can pass an instrument for free.
        """
        driver = self.driver
        driver.reset()
        driver.set_source_function("voltage")
        driver.apply_ranges(RangePlan.for_sourcing(
            "voltage", source_range=self.probe.voltage,
            measure_range=self.probe.compliance_i), log=self._log)
        driver.set_current_limit(self.probe.compliance_i)
        driver.set_voltage_level(0.0)

    def _tier2_range_readback(self):
        """Is the instrument on the ranges it was just told to be on?

        `apply_ranges()` reports what it *sent*. That is the half of the
        problem the compliance readback did not cover, and it is not the
        lesser half: on the GSM-20H10, asking for a 100 uA measurement
        range with a 10 uA compliance in force gives `+824` and leaves
        `SENS:CURR:DC:RANG?` reading `1.050000E-05`. No exception, a
        range the operator did not choose, and every reading afterwards
        taken on it - overranging into a sentinel rather than reading.

        Runs immediately after `_tier2_compliance_survives_ranging()`
        restored the correct order, so the ranges in force are known
        exactly: this is the voltage-sourcing plan, with the source
        current axis carrying nothing and the measured voltage read back
        from the source.

        Every axis is reported, including the ones with nothing to
        compare against and the ones this driver cannot query. An axis
        that is silently absent from a report reads as an axis that was
        checked.
        """
        driver = self.driver
        requested = {
            "source_voltage": self.probe.voltage,
            "source_current": NOT_SOURCED,
            "measure_current": self.probe.compliance_i,
            "measure_voltage": AUTO,
        }
        for axis in type(driver).RANGE_AXES:
            self._record_readback(
                2, f"range readback: {axis.replace('_', ' ')}",
                lambda a=axis: driver.verify_range(a, requested[a]))

    #: How far above the old compliance the wider range sits. A decade
    #: is enough to be refused outright by an instrument that refuses,
    #: and small enough that the new compliance stays modest: 1 mA and
    #: 10 V on the probe's usual levels, with the output off.
    WIDER_RANGE_FACTOR = 10.0

    def _tier2_range_wider_than_the_old_compliance(self):
        """Does a range wider than the compliance in force survive the new one?

        The case the other two range checks cannot reach, and the one
        that cost IV sweeps on the GSM-20H10. Every experiment ranges
        first and limits second (fault 15). On that instrument a range
        wider than the compliance *already* in force is refused with
        `+824` and the narrower range stays - so after `*RST`, with the
        compliance at 105 uA, an IV sweep asking for a 100 mA range
        measured on 105 uA instead. The range readback above never saw
        it, because the probe's range fits inside its own compliance.

        Asked in the experiments' order, with the old compliance made
        narrow on purpose: limit low, range a decade wider, limit up to
        the range, then read the range back. An instrument that refuses
        and does nothing about it fails SAFETY here; one that never
        refuses, or re-sends the range once the limit arrives, passes.
        The output is off throughout, and the probe's own ranges and
        limits are restored afterwards so the checks below see what they
        expect.

        Both axes, each in the source function that measures it. The
        voltage axis on the GSM-20H10 is the open question from
        2026-09-11, when a 200 V measure range did not take with the
        21 V reset compliance in force and nobody read the queue.
        """
        driver = self.driver
        limits = type(driver).LIMITS
        cases = (
            ("current", "voltage", "measure_current", "A",
             self.probe.compliance_i, self.probe.voltage,
             driver.set_current_limit,
             limits.current_ranges if limits is not None else []),
            ("voltage", "current", "measure_voltage", "V",
             self.probe.compliance_v, self.probe.current,
             driver.set_voltage_limit,
             limits.voltage_ranges if limits is not None else []),
        )
        touched = False
        for quantity, mode, axis, unit, old, level, set_limit, ranges in cases:
            name = (f"a {quantity} range wider than the old compliance "
                    f"survives the new one")
            if not self._output_is_off:
                self.record(2, name, "skip",
                            "the output could not be confirmed off, and "
                            "this raises a compliance")
                continue
            if not type(driver).supports_range_readback(axis):
                self.record(2, name, "skip",
                            f"{driver.DISPLAY_NAME} has no confirmed query "
                            f"for the {axis.replace('_', ' ')} range, so "
                            f"whether a refused range stayed narrow cannot "
                            f"be seen")
                continue
            wider = [r for r in sorted(ranges)
                     if r >= old * self.WIDER_RANGE_FACTOR]
            if not wider:
                self.record(2, name, "skip",
                            f"this model declares no {quantity} range a "
                            f"decade above the probe's {old:g} {unit} "
                            f"compliance")
                continue
            wide = wider[0]

            touched = True
            try:
                driver.set_source_function(mode)
                set_limit(old)
                self._drain_quietly()
                # The experiments' order: ranges, then the limit.
                driver.apply_ranges(RangePlan.for_sourcing(
                    mode, source_range=level, measure_range=wide),
                    log=self._log)
                set_limit(wide)
            except TransportDesynchronised:
                raise
            except Exception as exc:
                self.record(2, name, "fail", f"{type(exc).__name__}: {exc}")
                continue
            answer = self._record_readback(
                2, name, lambda a=axis, w=wide: driver.verify_range(a, w))
            if answer is not None and answer.is_safety_event:
                self.results[-1].detail += (
                    f" - asked for {wide:g} {unit} while the compliance "
                    f"was {old:g} {unit}, then raised the compliance to "
                    f"{wide:g} {unit}. An instrument that refuses a range "
                    f"wider than its compliance has to be sent the range "
                    f"again once the limit arrives")
            # This axis's compliance back to the probe's, while still in
            # the source function it belongs to: several models refuse a
            # voltage limit while sourcing voltage, and tier 2 does not
            # manufacture failures the experiments cannot produce.
            set_limit(old)
            # Refusals on the first send are expected on some models and
            # are not what is being graded; the range in force is.
            self._drain_quietly()

        if touched:
            # Back to exactly what the checks below expect.
            driver.set_source_function("voltage")
            driver.apply_ranges(RangePlan.for_sourcing(
                "voltage", source_range=self.probe.voltage,
                measure_range=self.probe.compliance_i), log=self._log)
            driver.set_current_limit(self.probe.compliance_i)
            self._drain_quietly()

    def _tier2_power_limit(self):
        """The ceiling nothing watched.

        Power compliance applies whichever of the three limits is lower,
        so a nonzero one silently overrides the compliance the
        experiment set - and reading the voltage or current limit back
        reports the *programmed* value rather than the effective one, so
        the readback that already exists cannot see it. It resets to
        disabled on every model that has it, which is exactly why
        nothing looked: `Recall setup` can carry a nonzero one into a
        session and no other check in this tool would notice.

        One query answers it, and this is that query.
        """
        self._record_readback(2, "power limit is where the driver put it",
                              self.driver.verify_power_limit)

    def _tier2_sub_count_refusal(self):
        """Where a floor is declared, prove it actually refuses.

        Asked with the output off, and asked in the direction where the
        interesting answer is the correct one: the level offered is a
        tenth of the driver's own declared floor, so a driver whose
        guard works must decline it. A guard that has stopped guarding
        passes every other check in this file - the level is written,
        the instrument accepts it, the error queue is clean - which is
        exactly the shape of fault 19.

        Skipped where no floor is declared. That is not silence: the
        tier 1 entry has already said, per axis, whether the floor is
        unmeasured or does not apply.

        Each axis is exercised in the source mode that axis belongs to,
        for the same reason the rest of tier 2 is: setting a current
        level while sourcing voltage is a settings conflict, and a
        commissioning tool that produces failures the application cannot
        produce trains people to ignore it.
        """
        driver = self.driver
        probed = False
        for quantity, unit in (("current", "A"), ("voltage", "V")):
            name = f"a sub-count {quantity} level is refused"
            try:
                floor = driver.source_level_floor(quantity)
            except TransportDesynchronised:
                raise
            except Exception as exc:
                self.record(2, name, "warn",
                            f"the driver could not say what its floor is: "
                            f"{type(exc).__name__}: {exc}")
                continue
            if floor is None:
                self.record(2, name, "skip",
                            f"this model declares no source {quantity} floor "
                            f"- see the tier 1 entry for what that means "
                            f"here")
                continue

            # Only now, and only for an axis that is actually going to
            # be written. A mode change is real traffic on most models,
            # and sending it to prove nothing would put commands in
            # every instrument's trace for the sake of the one that has
            # a floor.
            driver.set_source_function(quantity)
            self._drain_quietly()
            probed = True

            setter = (driver.set_current_level if quantity == "current"
                      else driver.set_voltage_level)
            offered = floor / 10.0
            try:
                setter(offered)
            except TransportDesynchronised:
                raise
            except RangeError as exc:
                self.record(2, name, "pass",
                            f"{offered:.6g} {unit} against a {floor:.6g} "
                            f"{unit} floor: {exc}")
                self._drain_quietly()
                continue
            except Exception as exc:
                self.record(2, name, "fail",
                            f"refused with {type(exc).__name__} rather than "
                            f"RangeError, so callers cannot tell an "
                            f"unreachable level from a broken link: {exc}")
                self._drain_quietly()
                continue
            self.record(
                2, name, "fail",
                f"{offered:.6g} {unit} is a tenth of this model's own "
                f"{floor:.6g} {unit} floor and it was accepted. Below the "
                f"floor the output is offset residue whose sign is not "
                f"commanded, so the guard is what stops an operator "
                f"getting a bias at the opposite polarity from the one "
                f"their sample is wired for")
            self._drain_quietly()
            # Put the axis back where the rest of tier 2 expects it.
            setter(0.0)

        if probed:
            driver.set_source_function("voltage")
            self._drain_quietly()

    def _record_readback(self, tier, name, ask):
        """Run one readback and record it, loudly where it disagrees.

        The whole reason `core.readback` has five states rather than two
        is that four of them are not a pass, and this is the one place
        that decides how each renders. A mismatch is a fail with the
        word SAFETY in it, because a range or a compliance that is not
        the one the software asked for is the bound on what reaches the
        sample, and the operator reading a wall of green needs it to
        stop being a wall.
        """
        try:
            answer = ask()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(tier, name, "fail",
                        f"the readback itself raised "
                        f"{type(exc).__name__}: {exc}")
            return None
        detail = answer.detail
        if answer.is_safety_event:
            detail = ("SAFETY: the instrument is not in the state it was "
                      "asked for. " + detail)
        self.record(tier, name, answer.severity, detail)
        return answer

    def _compliance_blindness(self):
        """What "cannot read the compliance back" costs on *this* driver.

        There are two different gaps behind that one sentence, and until
        2026-09-04 the report gave both the same words - "a collapse
        here would be invisible" - on five instruments. On three of
        them it was wrong. The 2611A, the 2635B and the B2901A all
        report the compliance **flag** correctly: `compliance_tripped()`
        returns True while they are clamping, and that was watched on
        the bench. What they do not read back is the compliance
        **limit value**. Only the 2401 and the miniSMU are blind to
        both.

        The difference is the difference between two failures:

          * a limit that moved to a value nobody chose, where the
            instrument is not clamping and nothing anywhere trips. No
            driver here can see that without the limit readback, and
            that is what the skip is about.
          * an output riding a limit during a run. An instrument that
            reports the flag still shows this, at the moment it
            matters, which is not nothing and must not be described as
            blindness.

        Asked of the driver rather than read from a model list, so this
        stays true as the limit readbacks land: a driver that grows one
        stops reaching this branch at all, and a driver that grows only
        the flag gets the milder sentence without anything here being
        edited.

        Output is off in tier 2, so False is the expected answer and
        only "did it answer at all" is being read.
        """
        try:
            answered = self.driver.compliance_tripped() is not None
        except TransportDesynchronised:
            raise
        except Exception:
            # It raised, so it cannot be relied on to report a trip
            # either. The tier 2 `compliance_tripped()` row records the
            # exception itself; here it only decides the wording.
            answered = False
        name = type(self.driver).DISPLAY_NAME
        if answered:
            return (f"the {name} does not report its compliance *limit "
                    f"value*, so this check cannot be run. It does report "
                    f"the compliance *flag*, and that part works - an "
                    f"output riding its limit during a run is still "
                    f"visible. What is unseen is narrower: a limit that "
                    f"moved to a value nobody chose, which clamps nothing "
                    f"and trips nothing")
        return (f"the {name} reports neither its compliance limit value "
                f"nor a compliance flag, so a collapse here would be "
                f"invisible")

    def _tier2_compliance_survives_ranging(self):
        """Does the compliance still hold after the ranges are applied?

        The check that would have caught the GSM-20H10 in one run
        instead of a week. On that instrument
        `SOUR:CURR:RANG:AUTO ON` - a command sent only to express
        indifference about an axis carrying nothing - silently reset the
        current compliance from 105 uA to 1 nA, with a clean error queue
        and nothing raised. It surfaced only because a later, innocent
        command tripped over the collapsed value and complained about
        something else entirely.

        Nothing in this suite read a compliance back, so on an
        instrument where nothing downstream trips, that collapse is
        invisible. Five of the seven checkups on 2026-08-18 came back
        clean, and "clean" there means *none observed*, not *none*.

        **Deliberately sends the limit before the ranges**, which is the
        order fault 15 exists to prevent and which this tool was fixed
        to stop using. That is the point: the question is what ranging
        does to a compliance already in force, and asking it the safe
        way round - where the experiment's own limit arrives afterwards
        and papers over any damage - is a probe whose interesting answer
        is not the correct one. The correct order is restored
        immediately afterwards, and the output is off throughout tier 2.
        """
        driver = self.driver
        mode = "voltage"
        limit = self.probe.compliance_i

        before = driver.verify_compliance(mode, limit)
        if before.state == readback_states.UNSUPPORTED:
            # `before.detail` is deliberately not quoted here. It says
            # "<model> does not report its compliance", which is the
            # sentence this branch exists to stop repeating: on three of
            # the five drivers it reaches, the compliance flag is
            # reported and only the limit value is not.
            self.record(2, "compliance survives ranging", "skip",
                        self._compliance_blindness())
            return

        # limit first, on purpose; see the docstring
        try:
            driver.set_current_limit(limit)
            driver.apply_ranges(RangePlan.for_sourcing(
                mode, source_range=self.probe.voltage, measure_range=limit),
                log=self._log)
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(2, "compliance survives ranging", "fail",
                        f"{type(exc).__name__}: {exc}")
            return

        after = driver.verify_compliance(mode, limit)
        detail = after.detail
        if after.is_safety_event:
            detail += (" - a ranging command moved the compliance. "
                       "See docs/faults/23-autorange-resets-compliance.md")
        self.record(2, "compliance survives ranging", after.severity, detail)

        # Put the correct order back before anything else runs.
        driver.apply_ranges(RangePlan.for_sourcing(
            mode, source_range=self.probe.voltage, measure_range=limit),
            log=self._log)
        driver.set_current_limit(limit)
        self.check_queue(2, "compliance survives ranging")

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

        # Not through `attempt()`. With no expectation attached, a
        # driver returning None passed indistinguishably from one
        # returning a real answer, and the detail column came out empty
        # - which reads as "checked, fine" rather than "asked, and it
        # cannot say". That is the same non-discriminating shape the
        # tier 3 version's docstring warns about, one tier up.
        #
        # This one cannot be a verdict on correctness: the output is off
        # here, so False is the honest answer and True would be the
        # suspicious one. What it can do is say which of the three
        # things happened.
        try:
            state = driver.compliance_tripped()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(2, "compliance_tripped()", "fail",
                        f"raised {type(exc).__name__}: {exc} with the "
                        f"output off")
        else:
            if state is None:
                self.record(2, "compliance_tripped()", "skip",
                            "not implemented by this driver")
            elif state:
                self.record(2, "compliance_tripped()", "warn",
                            "reported True with the output off, which "
                            "should not be possible - the flag may be "
                            "latched from an earlier run, or read from "
                            "an axis that is not the active one")
            else:
                self.record(2, "compliance_tripped()", "pass",
                            "False with the output off")
