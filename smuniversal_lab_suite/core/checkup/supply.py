"""The checkup for a power supply.

Closer to the SMU checkup than the load's is, because a supply sources:
with nothing attached, an open circuit is a known DUT again. Set a volt,
read back a volt and no current, and the reading can be graded rather
than merely recorded.

Three things are still its own.

**The error path is asked for a complaint before its silence is
believed.** A supply here has no error queue, only event registers its
driver decodes into one. A decoder reading the wrong register reports
"no error" just as convincingly as an instrument with nothing to say -
so tier 2 sends one command the instrument must reject, past the
driver's own guards, and requires the rejection. Every "error queue
after ..." row in the report rests on that one.

**Settings are graded by reading them back, on a grid.** Voltage and
current land in whole steps of the instrument's resolution, so a
fractional tolerance alone is wrong at the bottom of the range; the
driver's `verify_setpoint()` allows one step.

**The check that matters most cannot be run open-circuit, and says so.**
Whether the current setting actually clamps, and whether the driver
notices, needs a load drawing more than the setting. With nothing
attached the supply sits in constant voltage whatever the driver does,
so that row is a skip with the reason - not a pass earned by asking a
question with one possible answer.
"""
import time

from smuniversal_lab_suite.core.checkup.base import CheckupBase
from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.core.ranges import RangePlan
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

#: What tier 3 sets, in volts. Low enough to be safe into whatever turns
#: out to be on the terminals, and a hundred steps of a 10 mV grid, so a
#: reading one step out is still plainly this level and not another.
PROBE_VOLTAGE = 1.0

#: The current setting tier 3 energises with, in amps. Small, and above
#: the floor of every supply here.
PROBE_CURRENT_LIMIT = 0.05

#: How far the voltmeter may be from the commanded level, in volts. The
#: TSX-P allows 0.1% + 10 mV on the setting and 0.2% + one digit on the
#: readback, about 25 mV together at this level - so this does not fail
#: a correct instrument, and a driver returning zero, the current, or
#: the wrong setting cannot pass.
VOLTMETER_TOLERANCE_V = 0.05

#: Above this, something is drawing current, in amps. Three steps of the
#: coarsest readback here.
OPEN_CIRCUIT_MAX_A = 0.03

#: Readings timed for the per-reading figure.
TIMED_READINGS = 5


class SupplyCheckup(CheckupBase):
    """Runs the supply checks and collects Results.

    Takes a live driver. Does not open or close the transport - the
    caller owns the connection, the same rule the experiments follow.
    """

    def __init__(self, driver, log=None, open_circuit=True,
                 command_log=None):
        super().__init__(driver, log=log, open_circuit=open_circuit,
                         command_log=command_log)

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
                # The check that earns its place on a two-model driver:
                # a 3510 resolving to the 1820's class would be driven
                # against the wrong envelope, and nothing else would say.
                self.record(1, "identity resolves to this driver", "fail",
                            f"resolves to {resolved.__name__}, not "
                            f"{type(driver).__name__}")
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(1, "identity resolves to this driver", "fail",
                        str(exc))

        self.attempt(1, "reset()", driver.reset)
        self.check_queue(1, "reset()")

        limits = driver.LIMITS
        if limits is None:
            self.record(1, "LIMITS declared", "fail", "no envelope declared")
        else:
            self.record(1, "LIMITS declared", "pass",
                        f"{limits.max_voltage:g} V, {limits.max_current:g} A")
            one_way = (limits.voltage_polarity == "positive"
                       and limits.current_polarity == "positive")
            self.record(
                1, "quadrant declared", "pass" if one_way else "fail",
                f"voltage {limits.voltage_polarity}, "
                f"current {limits.current_polarity}"
                + ("" if one_way else " - a supply sources in one "
                   "quadrant; declared otherwise it will accept a sweep "
                   "through zero and sit at its floor for half of it"))

        self.record(1, "compliance", "pass" if driver.supports_compliance()
                    else "fail",
                    "regulates at the ceiling, as a supply should declare"
                    if driver.supports_compliance()
                    else "declares none - a supply in current limit goes "
                         "on regulating, which is what a compliance is")

        floor = driver.MIN_CURRENT_A
        self.record(1, "current floor", "pass" if floor else "warn",
                    f"{floor:g} A" if floor else
                    "none declared - a current setting below what the "
                    "instrument accepts is then refused by the instrument, "
                    "mid-run, instead of at the gate")

        steps = driver.RESOLUTION
        declared = steps.get("voltage") and steps.get("current")
        self.record(1, "resolution", "pass" if declared else "warn",
                    f"{steps.get('voltage'):g} V, {steps.get('current'):g} A"
                    if declared else
                    "not declared for both quantities, so a setting cannot "
                    "be graded to within a step")

        window = driver.OVP_RANGE_V
        self.record(1, "over-voltage trip", "pass" if window else "skip",
                    f"{window[0]:g} V to {window[1]:g} V" if window
                    else "no settable trip on this model")

        caveats = getattr(driver, "ROLE_CAVEATS", None) or {}
        self.record(1, "offered to experiments by invitation",
                    "pass" if caveats else "warn",
                    ", ".join(sorted(caveats)) if caveats else
                    "no caveat declared - every experiment will accept "
                    "this instrument on its capabilities alone, including "
                    "the ones that work far below its resolution")

        for label, value in (("sweep kind", driver.sweep_kind),
                             ("fixed sensing", driver.fixed_sense)):
            self.attempt(1, label, value)

    # ---- tier 2 ----
    def tier2_configuration(self):
        """Every configuration method, output off, each setting read
        back and the error registers asked after each group."""
        driver = self.driver
        self._log("\nTier 2 - configuration, output off")

        result = self.attempt(2, "output_off()", driver.output_off)
        self._output_is_off = result.severity == "pass"
        self.check_queue(2, "output_off()")

        self._check_the_error_path()

        for mode in ("current", "voltage"):
            self.attempt(2, f"set_source_function({mode!r})",
                         lambda m=mode: driver.set_source_function(m))

        plan = RangePlan.for_sourcing("voltage", source_range=PROBE_VOLTAGE,
                                      measure_range=PROBE_CURRENT_LIMIT)
        self.attempt(2, "apply_ranges()",
                     lambda: driver.apply_ranges(plan, log=None),
                     expect=lambda v: True if v
                     else "nothing was reported for the run to record")

        self.attempt(2, "set_current_limit()",
                     lambda: driver.set_current_limit(PROBE_CURRENT_LIMIT))
        self._readback(2, driver.verify_setpoint("current",
                                                 PROBE_CURRENT_LIMIT))
        self.attempt(2, "set_voltage_level()",
                     lambda: driver.set_voltage_level(PROBE_VOLTAGE))
        self._readback(2, driver.verify_setpoint("voltage", PROBE_VOLTAGE))
        self.attempt(2, "set_source_delay()",
                     lambda: driver.set_source_delay(0.0))
        self.check_queue(2, "the two settings")

        self._check_the_trip()
        self._check_the_refusals()

        # Leave the voltage setting at zero. The output is off, but the
        # setting is what the next press of the output key energises.
        self.attempt(2, "set_voltage_level(0) [left safe]",
                     lambda: driver.set_voltage_level(0.0))
        self.check_queue(2, "configuration")

    def _readback(self, tier, readback):
        """Record a `core.readback.Readback` under its own severity."""
        return self.record(tier, f"{readback.subject} read back",
                           readback.severity, readback.detail)

    def _check_the_error_path(self):
        """Send one thing the instrument must reject, and require the
        rejection.

        Run before anything else in this tier leans on a clean register.
        It goes straight to the transport on purpose: through the driver
        the command would be refused by the driver's guard, and what is
        being graded here is the instrument's answer and the decoding of
        it.
        """
        name = "the error path reports a rejected command"
        probe = getattr(self.driver, "ERROR_PROBE", None)
        if not probe:
            return self.record(
                2, name, "skip",
                "this driver declares no command the instrument must "
                "reject, so a clean error register below has not been "
                "shown to mean anything")
        command, expected = probe
        self._drain_quietly()
        try:
            self.driver.transport.write(command)
            code, message = self.driver.read_error()
        except TransportDesynchronised as exc:
            self._on_desynchronised(2, name, exc, 0.0)
            raise
        except Exception as exc:
            return self.record(2, name, "fail",
                               f"{type(exc).__name__}: {exc}")
        finally:
            self._mark_commands()

        if code == expected:
            result = self.record(2, name, "pass",
                                 f"{command!r} -> {code}: {message}")
        elif code == 0:
            result = self.record(
                2, name, "fail",
                f"{command!r} should be rejected with error {expected} and "
                f"nothing was reported ({message}). Either the instrument "
                f"accepted it or this driver is not reading its errors - "
                f"and until that is known, no clean error register in "
                f"this report is evidence of anything")
        else:
            result = self.record(
                2, name, "warn",
                f"{command!r} was rejected, as it should be, but with "
                f"{code} ({message}) where {expected} was expected. The "
                f"error path works; the manual's numbering and this "
                f"instrument's disagree")
        self._drain_quietly()
        return result

    def _check_the_trip(self):
        """Move the over-voltage trip, read it back, and put it back."""
        driver = self.driver
        window = driver.OVP_RANGE_V
        if not window:
            self.record(2, "set_overvoltage_trip()", "skip",
                        "no settable trip on this model")
            return
        low, high = window
        # Away from both ends, so a setter that did nothing cannot pass
        # against the reset value.
        probe = round(low + (high - low) / 2.0, 1)
        self.attempt(2, "set_overvoltage_trip()",
                     lambda: driver.set_overvoltage_trip(probe))
        self._readback(2, driver.verify_overvoltage_trip(probe))
        self.attempt(2, "set_overvoltage_trip() [restored]",
                     lambda: driver.set_overvoltage_trip(high))
        self._readback(2, driver.verify_overvoltage_trip(high))
        self.check_queue(2, "the over-voltage trip")

    def _check_the_refusals(self):
        """Each guard, graded by asking it for the thing it must refuse."""
        driver = self.driver
        limits = driver.LIMITS
        floor = driver.MIN_CURRENT_A

        self._expect_refusal(
            2, "refuses a negative voltage",
            lambda: driver.set_voltage_level(-1.0),
            "a supply cannot reverse its terminals; sending it would be "
            "rejected by the instrument mid-run instead")
        self._expect_refusal(
            2, "refuses to sink",
            lambda: driver.set_current_level(-0.1),
            "a negative current means current into the instrument, and "
            "taking its magnitude instead would source silently")
        if floor:
            self._expect_refusal(
                2, "refuses a current setting below the floor",
                lambda: driver.set_current_level(floor / 2.0),
                f"the instrument does not accept less than {floor:g} A")
            self._expect_refusal(
                2, "refuses a current setting of zero",
                lambda: driver.set_current_level(0.0),
                "the current setting does not reach zero; the way to stop "
                "driving is output_off()")
            self._expect_refusal(
                2, "the gate refuses a compliance below the floor",
                lambda: driver.validate_source_point(
                    voltage=PROBE_VOLTAGE, current=floor / 2.0,
                    sourcing="voltage"),
                "on a supply the compliance is the current setting, so the "
                "floor is under it too")
        if limits is not None:
            self._expect_refusal(
                2, "refuses a voltage above the maximum",
                lambda: driver.set_voltage_level(limits.max_voltage * 1.1),
                f"{limits.max_voltage:g} V is the top of the range")
        if driver.OVP_RANGE_V:
            self._expect_refusal(
                2, "refuses an over-voltage trip outside its range",
                lambda: driver.set_overvoltage_trip(
                    driver.OVP_RANGE_V[1] * 2.0),
                "the instrument would reject it and leave the old trip in "
                "force")
        if not driver.supports_remote_sense_control():
            self._expect_refusal(
                2, "refuses a remote-sense request it cannot honour",
                lambda: driver.set_remote_sense(True),
                "sensing is decided by wiring, and accepting the request "
                "would record a mode the measurement may not have used")
        # None of those should have reached the instrument. If one did,
        # this is where it shows.
        self.check_queue(2, "the refusals")

    def _expect_refusal(self, tier, name, action, why):
        """Grade a guard by asking it for the thing it must refuse.

        Accepting is the failure here, which is the opposite of every
        other check - hence a helper rather than an `expect=`.
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
        return self.record(tier, name, "fail", f"accepted it - {why}")

    # ---- tier 3 ----
    def tier3_measurement(self):
        """Energise at one small level and grade what comes back."""
        driver = self.driver
        self._log("\nTier 3 - live measurement")

        if not self._output_is_off:
            self.record(3, "live checks", "skip",
                        "the output could not be confirmed off, so nothing "
                        "here was run")
            return

        if not self.setup(3, "configure", [
                ("set_source_function('voltage')",
                 lambda: driver.set_source_function("voltage")),
                ("set_current_limit()",
                 lambda: driver.set_current_limit(PROBE_CURRENT_LIMIT)),
                ("set_voltage_level()",
                 lambda: driver.set_voltage_level(PROBE_VOLTAGE))]):
            return

        result = self.attempt(3, "output_on()", driver.output_on)
        if result.severity != "pass":
            driver.safe_output_off()
            return
        self._output_is_off = False

        try:
            time.sleep(getattr(driver, "READBACK_SETTLE_S", 1.0))
            self._check_the_reading()
            self._check_the_regulation()
            self._time_the_readings()
        finally:
            try:
                driver.set_voltage_level(0.0)
            except Exception:
                # Cleanup-only: the output switch below is what makes
                # the terminals safe, and it is tried regardless.
                pass
            driver.safe_output_off()
            self._output_is_off = True

        self.check_queue(3, "the live checks")
        self.attempt(3, "protection_tripped()", driver.protection_tripped,
                     expect=lambda v: True if v is not True
                     else "a protection shut the output down during a "
                          "1 V open-circuit check")

    def _check_the_reading(self):
        driver = self.driver
        try:
            volts, amps = driver.measure()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, "measure()", "fail",
                        f"{type(exc).__name__}: {exc}")
            return
        self.record(3, "measure()",
                    "pass" if volts is not None and amps is not None
                    else "fail",
                    f"{volts!r} V, {amps!r} A")
        if volts is None or amps is None:
            return

        drawing = abs(amps) > OPEN_CIRCUIT_MAX_A
        if not self.open_circuit:
            self.record(3, "voltmeter tracks the commanded voltage", "skip",
                        f"{volts:.4g} V at {amps:.4g} A - not checked, "
                        f"something is connected, and a load in current "
                        f"limit holds the voltage below the setting")
        else:
            off_by = abs(volts - PROBE_VOLTAGE)
            self.record(
                3, "voltmeter tracks the commanded voltage",
                "pass" if off_by <= VOLTMETER_TOLERANCE_V else "fail",
                f"asked {PROBE_VOLTAGE:g} V, measured {volts:.4g} V")
            self.record(
                3, "open-circuit current is near zero",
                "pass" if not drawing else "warn",
                f"{amps:.4g} A at {volts:.4g} V"
                + ("" if not drawing else " - something is drawing "
                   "current. If a load is attached, run again with "
                   "--sample-connected so this is not read as a fault"))

        # The sign, graded only where it can be wrong. At zero current
        # every sign convention reads the same.
        if drawing:
            self.record(
                3, "a sourced current reads positive",
                "pass" if amps > 0 else "fail",
                f"{amps:+.4g} A"
                + ("" if amps > 0 else " - current out of a source is "
                   "positive in this suite"))
        else:
            self.record(3, "a sourced current reads positive", "skip",
                        "no current is flowing, and zero has no sign - "
                        "needs a load attached")

        power = getattr(driver, "measure_power", None)
        if power is not None:
            self.attempt(3, "measure_power()", power)

    def _check_the_regulation(self):
        """What the driver says about which knob is in charge.

        Asked twice, and the first answer is not graded. Coming on, a
        supply charges its own output capacitor through the current
        setting, so it can pass through constant current on the way to
        constant voltage - and a driver that keeps limit *events* will
        say so. That is the instrument, not a fault. The second answer
        is the settled one.

        Open-circuit the true settled answer is constant voltage, so the
        only wrong ones available are "constant current" and "clamped",
        and those are graded. The discriminating case is the other way
        round, and it cannot be produced without a load.
        """
        driver = self.driver
        try:
            at_turn_on = driver.regulation()
            state = driver.regulation()
            tripped = driver.compliance_tripped()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, "regulation()", "fail",
                        f"{type(exc).__name__}: {exc}")
            return

        self.record(3, "regulation() at turn-on", "pass",
                    f"{at_turn_on!r} - recorded, not graded: charging the "
                    f"output capacitor can pass through current limit on "
                    f"the way up")

        if state is None:
            self.record(
                3, "regulation() once settled", "warn",
                "no mode is known. Either the instrument reports a limit "
                "only at the moment it is entered and none was entered "
                "cleanly, or the register is not being read. A run on "
                "this supply records a blank compliance column until that "
                "is understood")
        elif not self.open_circuit:
            self.record(3, "regulation() once settled", "pass",
                        f"{state} - recorded, not graded, because "
                        f"something is connected")
        elif state == "CV":
            self.record(3, "regulation() once settled", "pass", state)
        elif state == "CC":
            self.record(3, "regulation() once settled", "fail",
                        "CC - with nothing attached a supply is in "
                        "constant voltage")
        else:
            self.record(3, "regulation() once settled", "warn",
                        f"{state} - it changed mode between two polls a "
                        f"moment apart with nothing attached")

        if self.open_circuit:
            self.record(
                3, "compliance_tripped() open-circuit",
                "fail" if tripped is True else
                ("pass" if tripped is False else "warn"),
                f"{tripped!r}"
                + (" - nothing is drawing current, so nothing is clamped"
                   if tripped is True else
                   " - cannot say, which is honest and leaves the "
                   "compliance column blank" if tripped is None else ""))
        self.record(
            3, "the current setting clamps, and the driver notices", "skip",
            "needs a load that draws more than the setting. With nothing "
            "attached the supply is in constant voltage whatever this "
            "driver does, so the check that matters most here was not "
            "run - do it once by hand with a power resistor attached")

    def _time_the_readings(self):
        """How long one `measure()` takes, which on a supply is long
        enough to decide what sample rate a run can ask for."""
        driver = self.driver
        started = time.perf_counter()
        try:
            for _ in range(TIMED_READINGS):
                driver.measure()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, "seconds per reading", "warn",
                        f"could not be timed: {type(exc).__name__}: {exc}")
            return
        each = (time.perf_counter() - started) / TIMED_READINGS
        self._seconds_per_reading = each
        self.record(3, "seconds per reading", "pass",
                    f"{each * 1000:.0f} ms over {TIMED_READINGS} readings, "
                    f"two queries each")

    # ---- the burst check ----
    def burst_configuration(self):
        """A supply's configuration block, as the first run after a
        connect sends it."""
        driver = self.driver
        driver.reset()
        driver.set_source_function("voltage")
        driver.apply_ranges(RangePlan.for_sourcing(
            "voltage", source_range=PROBE_VOLTAGE,
            measure_range=PROBE_CURRENT_LIMIT), log=None)
        driver.set_current_limit(PROBE_CURRENT_LIMIT)
        driver.set_voltage_level(PROBE_VOLTAGE)
        driver.set_source_delay(0.0)

    def after_burst(self):
        """Voltage setting back to zero.

        Each burst ends by setting the probe voltage. The output is off,
        but the setting is what the front-panel output key would
        energise next - the lesson of the load's first fleet round.
        """
        self.driver.set_voltage_level(0.0)
