"""The load contract's own semantics, before any load exists.

`BaseLoad` is a contract rather than a driver, so what is testable here
is the part it implements on every driver's behalf - and that part is
where the errors would be silent:

  * the **sign flip**, which if forgotten produces a complete,
    plausible, inverted IV curve that fits to a resistance of the wrong
    sign;
  * the **refusal to source**, which if it fell through would sink the
    magnitude instead and look exactly like success;
  * the **polarity gate** in `core.limits`, which is the only thing
    standing between a -0.2 V request and an instrument that cannot go
    below zero;
  * the **headroom floor**, which is where a load stops following its
    setpoint without saying so.

The fake below is the smallest thing that can answer: it is not a model
of any instrument, and it is not trying to be.
"""
import pytest

from smuniversal_lab_suite.core.gui.widgets import apply_compliance
from smuniversal_lab_suite.core.limits import (
    EITHER,
    NEGATIVE,
    POSITIVE,
    LimitError,
    SMULimits,
)
from smuniversal_lab_suite.drivers.base_instrument import BaseInstrument
from smuniversal_lab_suite.drivers.base_load import BaseLoad
from smuniversal_lab_suite.drivers.base_smu import BaseSMU

LOAD_LIMITS = SMULimits(
    max_voltage=120.0,
    max_current=30.0,
    voltage_ranges=[18.0, 120.0],
    current_ranges=[3.0, 30.0],
    max_power=150.0,
    # A sink, in this suite's convention: volts positive, amps negative.
    voltage_polarity=POSITIVE,
    current_polarity=NEGATIVE,
)


class FakeLoad(BaseLoad):
    """Answers, and records what it was told. Models nothing."""

    DISPLAY_NAME = "Fake Load"
    MODEL_IDS = ["FAKELOAD"]
    LIMITS = LOAD_LIMITS

    def __init__(self):
        super().__init__(transport=None)
        self.sent = []
        self.reading = (2.5, 4.0)        # volts, amps SINKING (positive)
        self.headroom = None

    # -- BaseInstrument's abstracts, minimally --
    def set_source_function(self, mode):
        self.sent.append(("mode", mode))

    def set_voltage_level(self, volts):
        self.sent.append(("volts", volts))

    def set_remote_sense(self, on=True):
        self.sent.append(("sense", on))

    def set_source_delay(self, seconds):
        self.sent.append(("delay", seconds))

    def output_on(self):
        self.sent.append(("input", True))

    def output_off(self):
        self.sent.append(("input", False))

    def read_error(self):
        return 0, "No error"

    # -- what BaseLoad asks for --
    def measure_sinking(self, timeout_s=3.0):
        return self.reading

    def set_sink_current(self, amps):
        self.sent.append(("sink", amps))

    def minimum_operating_voltage(self, amps):
        return self.headroom


# ---------------------------------------------------------------
# The sign flip
# ---------------------------------------------------------------


def test_a_sinking_current_is_reported_negative(check):
    """The convention, at the only place it is applied.

    The load's own ammeter says +4 A. An SMU measuring the same cell at
    the same point would say -4 A, because the current flows into its
    HI terminal. One column, one meaning, whichever instrument answered.
    """
    load = FakeLoad()
    volts, amps = load.measure()
    check("the voltage is untouched", volts == 2.5, f"got {volts!r}")
    check("the sink current comes back negative", amps == -4.0,
          f"got {amps!r} - an inverted IV curve is the failure this "
          f"prevents, and it fits to a resistance of the wrong sign")


def test_the_flip_survives_a_missing_reading(check):
    """`None` means no reading, and negating it must not invent one."""
    load = FakeLoad()
    load.reading = (2.5, None)
    volts, amps = load.measure()
    check("None stays None", amps is None, f"got {amps!r}")
    check("and the other column is unharmed", volts == 2.5)


def test_a_driver_cannot_forget_the_flip(check):
    """`measure()` is implemented by BaseLoad, not left to each driver.

    A driver overriding it would be opting out of the convention
    silently, so the contract is that drivers implement
    `measure_sinking()` and never touch `measure()`.
    """
    check("BaseLoad implements measure()",
          BaseLoad.measure is not BaseInstrument.measure)
    check("FakeLoad does not override it",
          FakeLoad.measure is BaseLoad.measure,
          "a driver that overrides measure() bypasses the sign flip")


# ---------------------------------------------------------------
# Refusing to source
# ---------------------------------------------------------------


def test_a_positive_current_request_is_refused(check):
    """Not clamped, not abs()'d - refused.

    Taking the magnitude would sink 2 A when asked to source 2 A, which
    is the error that looks exactly like success.
    """
    load = FakeLoad()
    with pytest.raises(LimitError) as caught:
        load.set_current_level(2.0)
    check("the message says which way round it went",
          "can only sink" in str(caught.value), str(caught.value))
    check("and nothing was sent", load.sent == [], f"sent {load.sent}")


def test_a_negative_current_request_sinks_its_magnitude(check):
    """The instrument's own command takes a positive magnitude."""
    load = FakeLoad()
    load.set_current_level(-4.0)
    check("the setpoint is a positive magnitude",
          load.sent == [("sink", 4.0)], f"sent {load.sent}")


def test_zero_is_allowed(check):
    """Zero has no sign and is where every settle-to-zero path goes."""
    load = FakeLoad()
    load.set_current_level(0.0)
    check("zero is sent", load.sent == [("sink", 0.0)], f"sent {load.sent}")


# ---------------------------------------------------------------
# No compliance
# ---------------------------------------------------------------


def test_a_load_declares_no_compliance(check):
    check("a load has none", not FakeLoad.supports_compliance())
    check("an SMU has one", BaseSMU.HAS_COMPLIANCE is True)
    check("and the conservative default is none",
          BaseInstrument.HAS_COMPLIANCE is False,
          "an instrument that says nothing must not be assumed to "
          "protect anything")


def test_the_compliance_setters_raise_rather_than_no_op(check):
    """Fault 11 is doing nothing quietly. Raising is the opposite."""
    load = FakeLoad()
    for call in (lambda: load.set_current_limit(1e-3),
                 lambda: load.set_voltage_limit(1.0)):
        with pytest.raises(NotImplementedError) as caught:
            call()
        check("the message names the reason",
              "no" in str(caught.value).lower()
              and "compliance" in str(caught.value).lower(),
              str(caught.value))


def test_apply_compliance_records_a_reason_rather_than_none(check):
    """What reaches the metadata when there is no compliance.

    `None` would read as "not recorded". The run has to say there was
    no ceiling, because that is a fact about the measurement.
    """
    logged = []
    result = apply_compliance(FakeLoad(), "voltage", 1e-3, logged.append)
    check("a reason comes back, not None", isinstance(result, str),
          f"got {result!r}")
    check("it says which instrument and why",
          "Fake Load" in result and "compliance" in result, result)
    check("and the console was told", logged, "nothing logged")


# ---------------------------------------------------------------
# The polarity gate
# ---------------------------------------------------------------


def test_the_gate_refuses_the_half_of_a_sweep_a_load_cannot_reach(check):
    """-0.2 V to 0.8 V, which is the real sweep this was written for.

    Both endpoints are checked by the experiment, so the negative one
    is refused before the run rather than discovered as a truncated
    curve afterwards.
    """
    LOAD_LIMITS.validate_source_point(voltage=0.8, sourcing="voltage")
    with pytest.raises(LimitError) as caught:
        LOAD_LIMITS.validate_source_point(voltage=-0.2, sourcing="voltage")
    check("it explains what would otherwise happen",
          "cannot reverse its terminals" in str(caught.value),
          str(caught.value))


def test_the_polarity_rule_applies_to_the_commanded_axis_only(check):
    """The compliance passed alongside a level is a magnitude.

    Every experiment calls the gate with a swept level for one argument
    and a compliance for the other. Checking the sign of the second
    refused a legal run at the bench: a voltage sweep to 0.7 V with the
    current range at 30 A came back "Requested current 30 A is
    positive", about a dropdown value that was never a request to
    source anything.
    """
    # Sourcing volts: the 30 A range is a bound, not a request.
    LOAD_LIMITS.validate_source_point(voltage=0.7, current=30.0,
                                      sourcing="voltage")
    # And the level's own sign is still checked.
    with pytest.raises(LimitError):
        LOAD_LIMITS.validate_source_point(voltage=-0.2, current=30.0,
                                          sourcing="voltage")
    # The mirror image, sourcing current. 5 V rather than 18 V because
    # 18 V at 10 A is 180 W and the power ceiling would refuse it for a
    # reason that has nothing to do with polarity - which is itself the
    # check working.
    LOAD_LIMITS.validate_source_point(current=-10.0, voltage=5.0,
                                      sourcing="current")
    with pytest.raises(LimitError):
        LOAD_LIMITS.validate_source_point(current=+10.0, voltage=5.0,
                                          sourcing="current")
    # Said nothing about which axis: no polarity check at all, and the
    # maxima still apply.
    LOAD_LIMITS.validate_source_point(voltage=-0.2, current=+30.0)
    with pytest.raises(LimitError):
        LOAD_LIMITS.validate_source_point(voltage=999.0)


def test_a_bipolar_instrument_is_unaffected(check):
    """Every SMU in the fleet, behaving exactly as before.

    The polarity fields default to EITHER, and on EITHER the sign is
    not looked at - which is what nine commissioned drivers were
    checked against.
    """
    smu = SMULimits(max_voltage=210.0, max_current=1.05)
    check("the default is EITHER", smu.current_polarity == EITHER
          and smu.voltage_polarity == EITHER)
    smu.validate_source_point(voltage=-200.0, current=-1.0)


def test_an_unrecognised_polarity_is_refused(check):
    """A typo must not read as 'no constraint' and pass everything."""
    with pytest.raises(ValueError):
        SMULimits(max_voltage=1.0, max_current=1.0, voltage_polarity="pos")


# ---------------------------------------------------------------
# The continuous power ceiling
# ---------------------------------------------------------------


def test_the_power_ceiling_bites_in_the_middle(check):
    """A hyperbola, not a rectangle.

    Both endpoints of a solar sweep are well inside the flat maxima; it
    is the maximum power point in between that goes over. A corner list
    cannot express that, which is why `max_power` exists.
    """
    LOAD_LIMITS.validate_source_point(voltage=0.6, current=-10.0)   # 6 W
    with pytest.raises(LimitError) as caught:
        LOAD_LIMITS.validate_source_point(voltage=40.0, current=-5.0)
    check("it names the wattage", "200 W" in str(caught.value),
          str(caught.value))


def test_no_ceiling_declared_means_no_check(check):
    """Every SMU here declares none, and must be unaffected."""
    smu = SMULimits(max_voltage=210.0, max_current=3.0)
    check("the default is None", smu.max_power is None)
    smu.validate_source_point(voltage=210.0, current=3.0)       # 630 W


# ---------------------------------------------------------------
# Headroom
# ---------------------------------------------------------------


def test_headroom_is_unmeasured_until_somebody_measures_it(check):
    """The default has to read as 'nobody looked', never as 'fine'."""
    check("the state defaults to unmeasured",
          BaseLoad.HEADROOM_STATE == BaseLoad.HEADROOM_UNMEASURED)
    check("and a base load declares no floor",
          not BaseLoad.declares_headroom())


def test_overriding_the_method_is_not_declaring_a_floor(check):
    """Documentation must not read as a measurement.

    A driver overriding `minimum_operating_voltage()` to return None
    with a paragraph explaining why nobody has measured it is doing the
    right thing. Treating the override itself as the declaration - which
    is how the SMU side works, correctly, for a different reason - would
    turn that paragraph into a claim that a floor exists.
    """
    check("FakeLoad overrides the method",
          FakeLoad.minimum_operating_voltage
          is not BaseLoad.minimum_operating_voltage)
    check("but declares nothing, because its state says unmeasured",
          not FakeLoad.declares_headroom())

    class Measured(FakeLoad):
        HEADROOM_STATE = BaseLoad.HEADROOM_MEASURED

    check("a state of 'measured' is what declares one",
          Measured.declares_headroom())


def test_an_undeclared_floor_refuses_nothing(check):
    """`None` is a gap, and a gap must not be enforced as a limit."""
    load = FakeLoad()
    load.headroom = None
    load.guard_operating_point(volts=0.0, amps=10.0)


def test_a_declared_floor_refuses_below_it(check):
    """Where an IV curve stops being a measurement.

    At 10 A this fake needs 1.5 V, and a solar cell's whole operating
    range is below that - which is exactly the finding that decides
    whether a load can measure a given cell at all.
    """
    load = FakeLoad()
    load.headroom = 1.5
    load.guard_operating_point(volts=2.0, amps=10.0)
    with pytest.raises(LimitError) as caught:
        load.guard_operating_point(volts=0.65, amps=10.0)
    message = str(caught.value)
    check("it names the floor and the current",
          "1.5 V" in message and "10 A" in message, message)
    check("and says the failure is silent",
          "no error is raised" in message, message)
