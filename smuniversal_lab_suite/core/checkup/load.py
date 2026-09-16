"""The checkup for an electronic load, and why it is not the SMU one.

`Checkup` drives a source-measure unit and its whole premise is that
**nothing is connected**. That works because an open circuit is a known
DUT: source 0.1 V, measure approximately no current, and the reading can
be graded rather than merely recorded.

Invert the instrument and the premise inverts with it. A load with
nothing attached cannot sink anything, so **every reading is zero
whether the driver works or not** - which is
[fault 19](../../../docs/faults/19-non-discriminating-probe.md), the
one this project has repeated most, in its purest available form. An SMU
checkup pointed at a load would run to completion, report a clean sheet,
and have proved nothing at all.

So this file changes two things and keeps everything else.

**Tier 3 requires a source, and says so when there is not one.** It
looks first - with the input off the terminals are loaded only by the
input impedance, so the attached source can be read almost unloaded -
and if nothing is there every live check is `skip`, never `pass`. A
skip is a gap in a report; a pass earned against an open circuit is a
false statement about a driver.

**Readback replaces the error queue.** The SMU checkup leans on
`check_queue()` after every group of writes, and on the 72-13200 there
is no queue to ask: a rejected command is ignored in silence. What
stands in for it is that nearly every setting on that instrument has a
query, so each configuration step is graded on what the instrument says
it is holding rather than on nothing having raised. That inversion is
not a weaker check - it is the one that would have caught the
`:FUNCtion VOLT` bug on the day the driver was written, which the error
queue could never have caught because there is not one.

What is deliberately kept
-------------------------
Tier 1, almost unchanged. `identify()` resolving to *this* driver is
cheap and catches a `MODEL_IDS` mistake that would silently route the
next instrument to the wrong class - the check that pays off when there
is a second load.
"""
from smuniversal_lab_suite.core.checkup.base import CheckupBase
from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.core.ranges import RangePlan
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

#: How much current to ask the load to sink in tier 3, in amps, as a
#: fraction of whatever the attached source turns out to be able to
#: give. Small: this runs on somebody's bench with unknown wiring, and
#: the checks here are about whether the driver is right, not about how
#: much the instrument can take.
PROBE_SINK_A = 0.2

#: Below this the terminals count as having nothing attached, in volts.
#: Well above the noise on a floating input and far below anything a
#: bench supply would be set to.
SOURCE_PRESENT_V = 0.5

#: How far the ammeter may differ from the commanded current before it
#: counts as disagreeing. The 72-13200's own specification allows
#: 0.05% of setting plus 0.045% of full scale, which on the 3 A ceiling
#: is 1.4 mA at this probe level - so this is loose enough not to fail
#: a correct instrument and tight enough that a driver returning zero,
#: the wrong sign or the wrong quantity cannot pass.
AMMETER_TOLERANCE_A = 0.01


class LoadCheckup(CheckupBase):
    """Runs the load checks and collects Results.

    Takes a live driver. Does not open or close the transport - the
    caller owns the connection, the same rule the experiments follow.
    """

    def __init__(self, driver, log=None, source_present=None,
                 command_log=None):
        # `open_circuit` is the SMU checkup's word for "nothing is
        # attached" and it means the opposite thing here: there, it is
        # the condition that makes the readings gradeable; here it is
        # the condition that makes them meaningless. Passed as False so
        # nothing inherited assumes the SMU reading of it.
        super().__init__(driver, log=log, open_circuit=False,
                         command_log=command_log)
        #: None means "look and find out", which is the normal case.
        #: True or False force it, for a test or for an operator who
        #: knows better than the terminals do.
        self._source_present = source_present
        self._source_volts = None

    # ---- the error queue that is not there ----
    def check_queue(self, tier, after):
        """Say once that there is nothing to ask, then stop asking.

        `CheckupBase.check_queue()` is the SMU checkup's backbone. On an
        instrument that declares no error queue, calling it after every
        group would fill the report with rows that all say the same
        nothing - and a row reading "no errors" is exactly the false
        reassurance this whole file exists to avoid.
        """
        if self.driver.supports_error_queue():
            return super().check_queue(tier, after)
        if not getattr(self, "_said_no_queue", False):
            self._said_no_queue = True
            self.record(
                tier, "error queue", "warn",
                f"{self.driver.DISPLAY_NAME} has none. A rejected command "
                f"is ignored in silence, so nothing below is evidence that "
                f"anything was understood - every configuration check here "
                f"is graded on reading the setting back instead.")
        return None

    # ---- tier 1 ----
    def tier1_identity(self):
        driver = self.driver
        self._log("\nTier 1 - identity and declarations")

        self.attempt(1, "identify()", driver.identify,
                     expect=lambda v: True if v and str(v).strip()
                     else "empty identity reply")

        from smuniversal_lab_suite.drivers.registry import driver_for_idn
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
                            f"{type(driver).__name__}")
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(1, "identity resolves to this driver", "fail", str(exc))

        self.check_queue(1, "identity")
        self.attempt(1, "reset()", driver.reset)

        limits = driver.LIMITS
        if limits is None:
            self.record(1, "LIMITS declared", "fail", "no envelope declared")
        else:
            self.record(1, "LIMITS declared", "pass",
                        f"{limits.max_voltage:g} V, {limits.max_current:g} A"
                        + (f", {limits.max_power:g} W"
                           if limits.max_power else ""))
            # The quadrant is the declaration that stops a sweep asking
            # for the half of its span this instrument cannot enter.
            one_way = (limits.voltage_polarity != "either"
                       or limits.current_polarity != "either")
            self.record(
                1, "quadrant declared", "pass" if one_way else "fail",
                f"voltage {limits.voltage_polarity}, "
                f"current {limits.current_polarity}"
                + ("" if one_way else " - a load that declares itself "
                   "bipolar will accept a sweep into a region it cannot "
                   "reach and return readings from it"))

        self.record(1, "compliance", "pass" if not driver.supports_compliance()
                    else "fail",
                    "none, as a load should declare"
                    if not driver.supports_compliance()
                    else "declares a compliance - a load's protections are "
                         "trips, not ceilings it regulates at")

        state = getattr(driver, "HEADROOM_STATE", None)
        self.record(1, "headroom floor", "pass" if driver.declares_headroom()
                    else "warn",
                    f"{state}"
                    + ("" if driver.declares_headroom()
                       else " - nobody has measured where this load stops "
                            "regulating, so nothing refuses a setpoint "
                            "below it"))

        for label, value in (("sweep kind", driver.sweep_kind),
                             ("fixed sensing", driver.fixed_sense)):
            self.attempt(1, label, value)

    # ---- tier 2 ----
    def tier2_configuration(self):
        """Every configuration method, graded on the readback."""
        driver = self.driver
        self._log("\nTier 2 - configuration, verified by readback")

        result = self.attempt(2, "output_off()", driver.output_off)
        self._output_is_off = result.severity == "pass"
        self.check_queue(2, "output_off()")

        # Regulation mode, both ways, each confirmed. This is the check
        # that would have caught `:FUNCtion VOLT` doing nothing.
        for mode in ("current", "voltage"):
            self.attempt(2, f"set_source_function({mode!r}) [confirmed]",
                         lambda m=mode: driver.set_source_function(m))

        # Ranging. On a load the plan cannot be carried out as written -
        # there is no source range - so what is graded is that the
        # driver reports what the instrument says it is on.
        plan = RangePlan.for_sourcing("voltage", source_range=1.0,
                                      measure_range=PROBE_SINK_A)
        self.attempt(2, "apply_ranges()",
                     lambda: driver.apply_ranges(plan, log=None),
                     expect=lambda v: True if v and "MISMATCH" not in str(v)
                     else f"the instrument did not take the ranges: {v}")
        self.attempt(2, "read_ceilings()", driver.read_ceilings,
                     expect=lambda v: True
                     if v and any(x is not None for x in v.values())
                     else "no ceiling could be read back, so what this "
                          "instrument is ranged to is unknown")

        # Setpoints, each written then read back.
        self.attempt(2, "set_current_level() [sinking]",
                     lambda: driver.set_current_level(-PROBE_SINK_A))
        self.attempt(2, "set_source_delay()",
                     lambda: driver.set_source_delay(0.0))

        # The refusals. Each one is a guard that exists because the
        # instrument would otherwise do something plausible and wrong,
        # so each is checked by asking for the thing it must refuse.
        self._expect_refusal(
            2, "refuses to source",
            lambda: driver.set_current_level(+PROBE_SINK_A),
            "a positive current means current out of the instrument, and "
            "taking its magnitude instead would sink silently")

        limits = driver.LIMITS
        if limits is not None and limits.voltage_polarity == "positive":
            self._expect_refusal(
                2, "refuses a negative voltage",
                # `sourcing` is what turns the polarity rule on. Without
                # it this asked a question with no wrong answer, and
                # passed - fault 19 inside the check whose whole job is
                # to confirm a guard fires.
                lambda: limits.validate_source_point(voltage=-0.2,
                                                     sourcing="voltage"),
                "reverse bias needs a source; below zero there is nothing "
                "to sink")

        floor = getattr(driver, "MIN_CV_SETPOINT_V", None)
        if floor:
            self._expect_refusal(
                2, "refuses a CV setpoint below the commanding floor",
                lambda: driver.set_voltage_level(floor / 2.0),
                f"the instrument clamps below {floor:g} V without saying so")

        self.attempt(2, "set_current_level(0) [settle to zero]",
                     lambda: driver.set_current_level(0.0))

    def _expect_refusal(self, tier, name, action, why):
        """Grade a guard by asking it for the thing it must refuse.

        A guard is only worth having if it fires, and the way to find
        out is to ask - not to read the code. Accepting is the failure
        here, which is the opposite of every other check in this file
        and the reason this needs its own helper rather than an
        `expect=` on `attempt()`.
        """
        try:
            action()
        except (ValueError, LimitError, NotImplementedError) as exc:
            return self.record(tier, name, "pass", str(exc)[:110])
        except TransportDesynchronised:
            raise
        except Exception as exc:
            return self.record(tier, name, "fail",
                               f"raised the wrong thing: "
                               f"{type(exc).__name__}: {exc}")
        return self.record(tier, name, "fail",
                           f"accepted it - {why}")

    # ---- tier 3 ----
    def tier3_measurement(self):
        """Live checks, which need something pushing into the load.

        Every one of these is skipped rather than passed when there is
        no source, because with an open circuit they would all succeed
        against a driver that returned zeros.
        """
        driver = self.driver
        self._log("\nTier 3 - live measurement")

        if not self._output_is_off:
            self.record(3, "live checks", "skip",
                        "the input could not be confirmed off, so nothing "
                        "here was run")
            return

        volts, _ = driver.measure()
        self._source_volts = volts
        present = self._source_present
        if present is None:
            present = volts is not None and abs(volts) >= SOURCE_PRESENT_V

        if not present:
            self.record(
                3, "a source is attached", "skip",
                f"the terminals read "
                f"{'nothing' if volts is None else f'{volts:.4g} V'} with "
                f"the input off. A load with nothing attached sinks "
                f"nothing, so every live check below would read zero "
                f"whether this driver works or not - they are skipped "
                f"rather than passed. Attach a source (a bench supply at "
                f"a few volts, current-limited) and run again.")
            for name in ("ammeter tracks the commanded current",
                         "a sink reads negative",
                         "the headroom guard refuses below the floor"):
                self.record(3, name, "skip", "no source attached")
            return

        self.record(3, "a source is attached", "pass",
                    f"{volts:.4g} V across the terminals with the input off")

        ceilings = driver.read_ceilings()
        ceiling_v = ceilings.get("voltage")
        if ceiling_v is not None and abs(volts) > ceiling_v:
            self.record(3, "the source fits the voltage ceiling", "fail",
                        f"{abs(volts):.4g} V attached, ceiling {ceiling_v:g} V "
                        f"- a reading would overrange")
            return

        driver.set_source_function("current")
        driver.set_current_level(0.0)
        try:
            driver.output_on()
        except Exception as exc:
            self.record(3, "output_on()", "fail", f"{type(exc).__name__}: {exc}")
            return
        self.record(3, "output_on()", "pass")

        try:
            driver.set_current_level(-PROBE_SINK_A)
            import time
            time.sleep(getattr(driver, "SETTLING_S", 0.45))
            measured_v, measured_i = driver.measure()

            if measured_i is None:
                self.record(3, "ammeter tracks the commanded current", "fail",
                            "no current reading came back")
            else:
                off_by = abs(measured_i - (-PROBE_SINK_A))
                self.record(
                    3, "ammeter tracks the commanded current",
                    "pass" if off_by <= AMMETER_TOLERANCE_A else "fail",
                    f"asked {-PROBE_SINK_A:+.4g} A, measured "
                    f"{measured_i:+.4g} A")
                # Asked separately from the magnitude, because a driver
                # that forgot the flip would be out by exactly twice the
                # current and might still look close at small levels.
                self.record(
                    3, "a sink reads negative", "pass" if measured_i < 0
                    else "fail",
                    f"{measured_i:+.4g} A"
                    + ("" if measured_i < 0 else
                       " - this suite records a sink as negative so that a "
                       "sample measured here overlays the same sample on "
                       "an SMU. A positive reading is an inverted IV "
                       "curve that fits to a resistance of the wrong sign"))
            if measured_v is not None:
                self.record(3, "terminal voltage", "pass",
                            f"{measured_v:.4g} V while sinking "
                            f"{PROBE_SINK_A:g} A")
        finally:
            try:
                driver.set_current_level(0.0)
            except Exception:
                pass
            driver.safe_output_off()
            self._output_is_off = True

        # The headroom guard, asked where it must refuse. Cheap, and it
        # is the guard standing between a solar sweep and a region this
        # instrument silently stops regulating in.
        if driver.declares_headroom():
            floor = driver.minimum_operating_voltage(10.0)
            self._expect_refusal(
                3, "the headroom guard refuses below the floor",
                lambda: driver.guard_operating_point(volts=floor * 0.5,
                                                     amps=10.0),
                f"below {floor:.4g} V at 10 A the setpoint stops being "
                f"followed and nothing says so")
        else:
            self.record(3, "the headroom guard refuses below the floor",
                        "skip", "this driver declares no floor")

    def burst_configuration(self):
        """A load's configuration block, as the first sweep after a connect."""
        driver = self.driver
        driver.reset()
        driver.set_source_function("current")
        driver.apply_ranges(RangePlan.for_sourcing(
            "voltage", source_range=1.0, measure_range=PROBE_SINK_A),
            log=None)
        driver.set_current_level(-PROBE_SINK_A)
        driver.set_source_delay(0.0)

    def run(self, tiers=(1, 2, 3), burst=True):
        self._stopped_early = False
        try:
            if 1 in tiers:
                self.tier1_identity()
            if 2 in tiers:
                self.tier2_configuration()
            if 3 in tiers:
                self.tier3_measurement()
            if 2 in tiers:
                if burst:
                    self.burst_check()
                else:
                    self.record(2, self.BURST_NAME, "skip",
                                "skipped on request (--skip-burst), so "
                                "whether this instrument drops commands "
                                "sent in a burst was not tested")
        except TransportDesynchronised:
            self._stopped_early = True
        return self.results
