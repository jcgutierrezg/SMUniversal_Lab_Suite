"""The checkup for a meter - a multimeter or a picoammeter.

The shortest of the four, because a meter sets nothing: there is no
output to energise and no level to grade a reading against. What is
left to prove is that the instrument understands the configuration the
driver sends, that the settings read back as sent, that a reading comes
back as one number in the column of the quantity the meter reads, and
how long it takes.

It does not care which quantity that is. Every range, readback and
reading goes through `BaseMeter`'s neutral layer (`measured_quantity()`,
`measure_ranges()`, `set_measure_range()`), so the 34401A's volts and
the 6485's amps take the same rows.

Four things are its own.

**Nothing is energised, so nothing has to be confirmed off.** Tier 3
reads an open input; there is no fixture to make safe and the
"output-off" lines other fleets carry do not apply.

**The open-input reading is taken where it means something.** On a
voltmeter's high-impedance input an open pair of terminals floats
wherever pickup and the amplifier's bias current take it, so tier 3
uses the 10 MOhm divider, across which the bias current develops well
under a millivolt. An open ammeter input carries only the meter's own
offset and whatever the open connector picks up. Either reads close to
zero - something that can be graded, loosely.

**A shunted input is read back, not looked for in the data.** An
ammeter with zero check on answers every reading with its own offset -
which is also what an open input reads. Only the readback can tell them
apart, so a meter with a shunt has it graded after reset and toggled in
tier 2.

**The slowest integration is timed once.** At 100 power-line cycles
with autozero a 34401A reading takes about four seconds, longer than
the timeout every other driver here is called with. The driver scales
its timeout to the integration time, and one reading at the top of the
setting is the only way to show that the scaling holds on the
instrument.
"""
import time

from smuniversal_lab_suite.core.checkup.base import CheckupBase
from smuniversal_lab_suite.core.checkup.supply import SupplyCheckup
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised
from smuniversal_lab_suite.drivers.base_meter import BaseMeter

#: Above this an open input on the 10 MOhm divider is reading something
#: other than its own offset, in volts. Generous: mains pickup on an
#: unscreened open pair can reach millivolts, and this is a warning,
#: not a failure.
OPEN_INPUT_MAX_V = 0.01

#: The same for an open ammeter input, in amps. The 6485's offset is
#: hundreds of femtoamps on the 2 nA range; 100 pA is pickup or
#: something connected. A warning, not a failure.
OPEN_INPUT_MAX_A = 1e-10

#: The open-input bound per quantity.
OPEN_INPUT_MAX = {"voltage": OPEN_INPUT_MAX_V, "current": OPEN_INPUT_MAX_A}

#: The integration time the open-input reading is taken at, in PLC.
#: One cycle rejects mains pickup and keeps the check quick.
READING_NPLC = 1.0

#: Readings timed for the per-reading figure.
TIMED_READINGS = 5

#: How long the bus is left quiet after a reading before the errors are
#: asked for, in seconds - what a logging run does between samples.
QUIET_BUS_PAUSE_S = 1.5


class MeterCheckup(CheckupBase):
    """Runs the meter checks and collects Results.

    Takes a live driver. Does not open or close the transport - the
    caller owns the connection, as everywhere.
    """

    # Shared with the supply checkup rather than copied: the same probe
    # of the error path, the same guard-grading, the same readback row.
    # Taken by reference so a fix to one is a fix to both.
    _check_the_error_path = SupplyCheckup._check_the_error_path
    _expect_refusal = SupplyCheckup._expect_refusal
    _readback = SupplyCheckup._readback

    def __init__(self, driver, log=None, open_circuit=True,
                 command_log=None):
        super().__init__(driver, log=log, open_circuit=open_circuit,
                         command_log=command_log)
        # Nothing to switch off, so nothing that could have been left on.
        self._output_is_off = True

    def _on_desynchronised(self, tier, name, exc, elapsed):
        """As the base records it, without the output-off warning.

        The base appends "OUTPUT-OFF WAS COMMANDED BUT COULD NOT BE
        CONFIRMED - check the front panel before touching the fixture",
        which on a meter is an alarm about an output that does not
        exist. The stop itself is recorded the same way.
        """
        self._timeouts += 1
        self._comms_suspect = True
        self._desync_recorded = True
        self.record(tier, name, "fail",
                    f"{type(exc).__name__}: {exc}"
                    " [the link went out of step here; the checkup stopped "
                    "rather than report readings that would answer the "
                    "previous command. Reconnect the instrument and run it "
                    "again. A meter has no output, so nothing was left "
                    "energised]",
                    elapsed)

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
            self.record(1, "identity resolves to this driver", "fail",
                        str(exc))

        self.attempt(1, "reset()", driver.reset)
        self.check_queue(1, "reset()")

        self.record(1, "sets nothing",
                    "pass" if not driver.supports_sourcing()
                    and not driver.source_functions()
                    and not driver.supports_sweep() else "fail",
                    "no source, no source functions, no sweep"
                    if not driver.supports_sourcing() else
                    "declares that it can source - an experiment would "
                    "then try to set a level on it")
        self.record(1, "measures", "pass" if driver.measure_functions()
                    else "fail",
                    ", ".join(driver.measure_functions()) or
                    "declares nothing measure() reports")

        caveats = driver.ROLE_CAVEATS or {}
        self.record(1, "offered to experiments by invitation",
                    "pass" if caveats else "fail",
                    ", ".join(sorted(caveats)) if caveats else
                    "no caveat declared - IV sweep and Fixed Source would "
                    "accept a meter as their source")

        menu = driver.NPLC_CHOICES
        span = driver.NPLC_RANGE
        if menu:
            self.record(1, "integration menu", "pass",
                        ", ".join(f"{n:g}" for n in menu) + " PLC")
        elif span:
            self.record(1, "integration menu", "pass",
                        f"continuous, {span[0]:g} to {span[1]:g} PLC - "
                        f"clamped into that span, never rounded")
        else:
            self.record(1, "integration menu", "warn",
                        "none declared, so a requested integration time is "
                        "sent as typed and rounded by the instrument")

        if driver.has_terminal_switch():
            self.attempt(1, "read_terminals()", driver.read_terminals,
                         expect=lambda v: True if v in ("front", "rear")
                         else f"{v!r} - expected front or rear")
        else:
            self.record(1, "read_terminals()", "skip",
                        "one input connector, so no terminal switch")

    # ---- tier 2 ----
    def tier2_configuration(self):
        """Every setting, sent and read back, and every refusal."""
        driver = self.driver
        self._log("\nTier 2 - configuration")

        self.attempt(2, "output_off() [nothing to switch]",
                     driver.output_off)
        self._check_the_error_path()
        self._check_the_reset_state()
        self._check_the_integration_menu()
        self._check_the_ranges()
        self._check_the_switches()
        self._check_the_refusals()

        # Leave it as a run would find it.
        self.attempt(2, "reset() [left as a connect leaves it]",
                     driver.reset)
        self.check_queue(2, "configuration")

    def _grade(self, tier, name, expected, reader):
        """One readback against one expected value, exactly."""
        try:
            got = reader()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            return self.record(tier, name, "fail",
                               f"{type(exc).__name__}: {exc}")
        if got is None:
            return self.record(tier, name, "warn",
                               "the driver has no query for it")
        if isinstance(expected, float):
            same = abs(float(got) - expected) <= abs(expected) * 1e-6
        else:
            same = got == expected
        return self.record(tier, name, "pass" if same else "fail",
                           f"{got!r}" if same else
                           f"read {got!r}, expected {expected!r}")

    def _check_the_reset_state(self):
        """What `reset()` sent, read back - each a setting a reading
        depends on, and each one a previous session could have left
        otherwise."""
        driver = self.driver
        driver_reset = getattr(driver, "RESET_NPLC", None)
        self._check_the_function()
        self._grade(2, "reset: autorange on", True, driver.read_autorange)
        if driver_reset is not None:
            self._grade(2, "reset: integration time", float(driver_reset),
                        driver.read_nplc)
        self._grade(2, "reset: autozero on", True, driver.read_autozero)
        if driver.supports_high_impedance():
            self._grade(2, "reset: high-impedance input on", True,
                        driver.read_high_impedance)
        if driver.supports_input_shunt():
            self._grade(2, "reset: input connected (not shunted)", True,
                        driver.read_input_connected)
        self.check_queue(2, "the reset state")

    #: What a function reply starts with, per measured quantity.
    _FUNCTION_PREFIX = {"voltage": "VOLT", "current": "CURR"}

    def _check_the_function(self):
        """The function in force, on a meter that has more than one to
        choose from. A model with one function and no query for it has
        nothing to get wrong, and a warning every run would be noise."""
        driver = self.driver
        quantity = driver.measured_quantity()
        name = f"reset: function is DC {quantity}"
        if type(driver).read_function is BaseMeter.read_function:
            self.record(2, name, "skip",
                        f"one function only ({quantity}), and no query "
                        f"for it")
            return
        try:
            function = driver.read_function()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(2, name, "fail", f"{type(exc).__name__}: {exc}")
            return
        prefix = self._FUNCTION_PREFIX[quantity]
        right = (function is not None and function.startswith(prefix)
                 and "AC" not in function and "RAT" not in function)
        self.record(2, name,
                    "pass" if right else
                    ("warn" if function is None else "fail"),
                    f"{function!r}")

    def _nplc_points(self):
        """The integration times tier 2 sets: every menu entry, or on a
        continuous setting its two ends and one cycle between them."""
        driver = self.driver
        if driver.NPLC_CHOICES:
            return tuple(driver.NPLC_CHOICES)
        if not driver.NPLC_RANGE:
            return ()
        low, high = driver.NPLC_RANGE
        return tuple(sorted({float(low), float(high)}
                            | ({1.0} if low < 1.0 < high else set())))

    def _check_the_integration_menu(self):
        driver = self.driver
        points = self._nplc_points()
        if not points:
            self.record(2, "set_nplc()", "skip", "no integration setting")
            return
        for nplc in points:
            self.attempt(2, f"set_nplc({nplc:g})",
                         lambda n=nplc: driver.set_nplc(n))
            self._readback(2, driver.verify_nplc(nplc))
        self.check_queue(2, "the integration menu")

    def _check_the_ranges(self):
        driver = self.driver
        quantity = driver.measured_quantity()
        for value in driver.measure_ranges():
            self.attempt(2, f"set_{quantity}_range({value:g})",
                         lambda v=value: driver.set_measure_range(v))
            self._readback(2, driver.verify_measure_range(value))
        self._grade(2, "a fixed range turns autorange off", False,
                    driver.read_autorange)
        self.attempt(2, f"set_{quantity}_range(None)",
                     lambda: driver.set_measure_range(None))
        self._grade(2, "autorange back on", True, driver.read_autorange)
        self.check_queue(2, "the ranges")

    def _check_the_switches(self):
        driver = self.driver
        for on in (False, True):
            self.attempt(2, f"set_autozero({on})",
                         lambda o=on: driver.set_autozero(o))
            self._grade(2, f"autozero reads {on}", on, driver.read_autozero)
        if driver.supports_high_impedance():
            for on in (False, True):
                self.attempt(2, f"set_high_impedance({on})",
                             lambda o=on: driver.set_high_impedance(o))
                self._grade(2, f"high-impedance input reads {on}", on,
                            driver.read_high_impedance)
        if driver.supports_input_shunt():
            # Shunted, then connected again - so the input is measuring
            # when the rows after this one read it.
            for shunted in (True, False):
                self.attempt(2, f"set_input_shunt({shunted})",
                             lambda o=shunted: driver.set_input_shunt(o))
                self._grade(2, f"input connected reads {not shunted}",
                            not shunted, driver.read_input_connected)
        self.check_queue(2, "the input switches")

    def _check_the_refusals(self):
        """Each source method, asked for something, must refuse - and
        none of them may have reached the instrument."""
        driver = self.driver
        why = ("a meter has no source; accepting would record a level "
               "nothing produced")
        for name, action in (
                ("refuses a source function",
                 lambda: driver.set_source_function("voltage")),
                ("refuses a voltage level",
                 lambda: driver.set_voltage_level(1.0)),
                ("refuses a current level",
                 lambda: driver.set_current_level(1e-3)),
                ("refuses to switch an output on", driver.output_on),
                ("the gate refuses every operating point",
                 lambda: driver.validate_source_point(
                     voltage=1.0, current=1e-3, sourcing="voltage")),
                ("refuses 4-wire sensing",
                 lambda: driver.set_remote_sense(True))):
            self._expect_refusal(2, name, action, why)
        top = driver.measure_ranges()[-1]
        self._expect_refusal(
            2, "refuses a range above its highest",
            lambda: driver.set_measure_range(top * 2.0),
            f"{top:g} {driver.measured_unit()} is its highest range")
        self.check_queue(2, "the refusals")

    # ---- tier 3 ----
    def tier3_measurement(self):
        """Read the open input, time the readings, and ask after a pause."""
        driver = self.driver
        self._log("\nTier 3 - live reading")

        quantity = driver.measured_quantity()
        steps = [(f"set_{quantity}_range(None)",
                  lambda: driver.set_measure_range(None)),
                 (f"set_nplc({READING_NPLC:g})",
                  lambda: driver.set_nplc(READING_NPLC)),
                 ("set_autozero(True)", lambda: driver.set_autozero(True))]
        if driver.supports_high_impedance():
            steps.append(("set_high_impedance(False) [10 MOhm input]",
                          lambda: driver.set_high_impedance(False)))
        if not self.setup(3, "configure", steps):
            return
        try:
            self._check_the_reading()
            self._time_the_readings()
            self._time_the_slowest_reading()
            self._check_the_quiet_bus()
        finally:
            try:
                driver.reset()
            except TransportDesynchronised:
                raise
            except Exception:
                # Cleanup-only: the next connect resets it again.
                pass
        self.check_queue(3, "the live checks")

    def _check_the_reading(self):
        driver = self.driver
        quantity = driver.measured_quantity()
        unit = driver.measured_unit()
        other = "voltage" if quantity == "current" else "current"
        try:
            volts, amps = driver.measure()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, "measure()", "fail",
                        f"{type(exc).__name__}: {exc}")
            return
        reading, stray = driver.reading_of(volts, amps)
        self.record(3, "measure()",
                    "pass" if reading is not None and stray is None
                    else "fail",
                    f"{volts!r} V, {amps!r} A"
                    + ("" if stray is None else f" - a meter reading "
                       f"{quantity} put a number in the {other} column"))
        if reading is None:
            return
        if not self.open_circuit:
            self.record(3, "open-input reading is near zero", "skip",
                        f"{reading:.6g} {unit} - something is connected, so "
                        f"it is recorded, not graded")
            return
        bound = OPEN_INPUT_MAX[quantity]
        where = (" on the 10 MOhm input" if driver.supports_high_impedance()
                 else "")
        if driver.has_terminal_switch():
            check = ("Check nothing is across the terminals, and which pair "
                     "the front/rear switch selects")
        else:
            check = "Check nothing is connected to the input"
        self.record(3, "open-input reading is near zero",
                    "pass" if abs(reading) <= bound else "warn",
                    f"{reading:.6g} {unit}{where}"
                    + ("" if abs(reading) <= bound else
                       f" - more than pickup usually gives. {check}"))

    def _time_the_readings(self):
        """Per reading at the fastest integration - the figure the
        instruments table quotes."""
        driver = self.driver
        points = self._nplc_points()
        fastest = points[0] if points else None
        try:
            if fastest is not None:
                driver.set_nplc(fastest)
            started = time.perf_counter()
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
        at = f" at NPLC {fastest:g} with autozero" if fastest else ""
        self.record(3, "seconds per reading", "pass",
                    f"{each * 1000:.0f} ms{at}, autoranging, over "
                    f"{TIMED_READINGS} readings")

    def _time_the_slowest_reading(self):
        """One reading at the top of the integration menu, which has to
        outlast the default timeout without desynchronising the link."""
        driver = self.driver
        points = self._nplc_points()
        if not points:
            self.record(3, "a reading at the slowest integration", "skip",
                        "no integration setting")
            return
        slowest = points[-1]
        name = f"a reading at NPLC {slowest:g}"
        try:
            driver.set_nplc(slowest)
            expected = getattr(driver, "reading_time_s", lambda: None)()
            started = time.perf_counter()
            reading, _ = driver.reading_of(*driver.measure())
            took = time.perf_counter() - started
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, name, "fail", f"{type(exc).__name__}: {exc}")
            return
        guess = f", the driver expected {expected:.2f} s" if expected else ""
        self.record(3, name, "pass" if reading is not None else "fail",
                    f"{took:.2f} s{guess}; read {reading!r} "
                    f"{driver.measured_unit()}")

    def _check_the_quiet_bus(self):
        """A reading, a pause, and then the question a run ends with."""
        driver = self.driver
        name = "a pause after a reading leaves no error"
        try:
            driver.set_nplc(READING_NPLC)
            driver.measure()
            time.sleep(QUIET_BUS_PAUSE_S)
            code, message = driver.read_error()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, name, "fail", f"{type(exc).__name__}: {exc}")
            return
        if code:
            self.record(3, name, "fail",
                        f"{code}: {message} - reported after "
                        f"{QUIET_BUS_PAUSE_S:g} s of silence following a "
                        f"reading")
            self._drain_quietly(3)
            return
        self.record(3, name, "pass")

    # ---- the burst check ----
    def burst_configuration(self):
        """The block a connect sends: the reset, then a reading's
        configuration."""
        driver = self.driver
        driver.reset()
        driver.set_measure_range(None)
        driver.set_nplc(READING_NPLC)
        driver.set_autozero(True)
        if driver.supports_high_impedance():
            driver.set_high_impedance(True)

    def after_burst(self):
        """Back to the state a connect leaves.

        The burst runs last and ends on its own configuration, so
        without this the meter is handed back at one power-line cycle
        rather than at the reset state the rest of the report describes.
        Nothing is energised either way; this is about what the next
        person finds.
        """
        self.driver.reset()
