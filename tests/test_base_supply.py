"""The power-supply contract, tested against a supply that is not a
real model.

`test_tsx_p.py` proves one driver sends the right strings. This file is
about what `BaseSupply` promises whatever the model: that the level and
the compliance are one knob, that the guards run before the wire, that
"clamped" means the right thing in each source function, and that a
supply is refused by an experiment that has not invited it.

A minimal subclass stands in for an instrument, so a failure here is a
failure of the contract and cannot be a quirk of the TSX-P.
"""
import pytest

from smuniversal_lab_suite.core.limits import POSITIVE, LimitError, SMULimits
from smuniversal_lab_suite.core.ranges import RangePlan
from smuniversal_lab_suite.core.readback import (
    MISMATCHED,
    UNSUPPORTED,
    UNVERIFIED,
)
from smuniversal_lab_suite.drivers.base_instrument import BaseInstrument
from smuniversal_lab_suite.drivers.base_load import BaseLoad
from smuniversal_lab_suite.drivers.base_smu import BaseSMU
from smuniversal_lab_suite.drivers.base_supply import (
    CC,
    CROSSED,
    CV,
    BaseSupply,
)
from smuniversal_lab_suite.drivers.registry import KNOWN_SUPPLIES
from smuniversal_lab_suite.experiments.base_experiment import Experiment


class BenchSupply(BaseSupply):
    """The least a supply driver can be: two knobs, a switch, a meter."""

    DISPLAY_NAME = "Bench supply (test double)"
    LIMITS = SMULimits(max_voltage=30.0, max_current=5.0,
                       voltage_ranges=[30.0], current_ranges=[5.0],
                       voltage_polarity=POSITIVE, current_polarity=POSITIVE)
    RESOLUTION = {"voltage": 0.01, "current": 0.01}
    MIN_CURRENT_A = 0.01
    OVP_RANGE_V = (1.0, 33.0)

    def __init__(self):
        super().__init__(None)
        self.calls = []
        self.state = None
        self.holding = {"voltage": None, "current": None, "trip": None}

    def set_output_voltage(self, volts):
        self.calls.append(("voltage", volts))
        self.holding["voltage"] = volts

    def set_output_current(self, amps):
        self.calls.append(("current", amps))
        self.holding["current"] = amps

    def _switch_output(self, on):
        self.calls.append(("output", on))

    def _send_overvoltage_trip(self, volts):
        self.calls.append(("trip", volts))
        self.holding["trip"] = volts

    def regulation(self):
        return self.state

    def read_voltage_setpoint(self):
        return self.holding["voltage"]

    def read_overvoltage_trip(self):
        return self.holding["trip"]

    # The rest of `BaseInstrument`'s abstract surface, as inert as it
    # can honestly be.
    def set_remote_sense(self, on=True):
        raise NotImplementedError

    def set_source_delay(self, seconds):
        pass

    def read_error(self):
        return 0, "No error"

    def measure(self, timeout_s=3.0):
        return self.holding["voltage"], 0.0


# ---------------------------------------------------------------
# Where it sits
# ---------------------------------------------------------------


def test_a_supply_is_a_sibling_not_a_kind_of_smu_or_load(check):
    """`issubclass(supply, BaseSMU)` being true would put it through
    the SMU contract suites, and through any guard written against that
    class in the dangerous direction."""
    check("on BaseInstrument", issubclass(BaseSupply, BaseInstrument))
    check("not an SMU", not issubclass(BaseSupply, BaseSMU))
    check("not a load", not issubclass(BaseSupply, BaseLoad))
    check("there is at least one registered", len(KNOWN_SUPPLIES) >= 1)


def test_what_a_supply_declares_about_itself(check):
    check("it can source", BaseSupply.supports_sourcing())
    check("and it has a real compliance", BaseSupply.supports_compliance(),
          "a supply in current limit goes on regulating at the ceiling")
    check("it reports clamping through the shared method",
          BaseSupply.compliance_tripped
          is not BaseInstrument.compliance_tripped)
    check("no trip menu for the windows to offer",
          not BaseSupply.supports_ovp())
    check("and no settable trip until a model says so",
          not BaseSupply.supports_overvoltage_trip()
          and BenchSupply.supports_overvoltage_trip())


def test_a_driver_must_supply_the_four_commands(check):
    """Each raises by name rather than doing nothing. A silent no-op in
    a setter is fault 11 written on purpose."""

    class Hollow(BaseSupply):
        OVP_RANGE_V = (1.0, 10.0)

        def set_remote_sense(self, on=True): ...
        def set_source_delay(self, seconds): ...
        def read_error(self): return 0, ""
        def measure(self, timeout_s=3.0): return None, None

    hollow = Hollow(None)
    for name, action in (
            ("set_output_voltage", lambda: hollow.set_voltage_level(1.0)),
            ("set_output_current", lambda: hollow.set_current_limit(1.0)),
            ("_switch_output", hollow.output_on),
            ("_send_overvoltage_trip",
             lambda: hollow.set_overvoltage_trip(5.0))):
        try:
            action()
        except NotImplementedError as exc:
            check(f"{name} is named in the refusal", name in str(exc),
                  str(exc))
        else:
            check(f"{name} must be implemented", False, "it did nothing")


# ---------------------------------------------------------------
# Two knobs
# ---------------------------------------------------------------


def test_level_and_limit_reach_the_same_knob_through_the_same_guard(check):
    supply = BenchSupply()
    supply.set_voltage_level(5.0)
    supply.set_voltage_limit(6.0)
    supply.set_current_level(1.0)
    supply.set_current_limit(2.0)
    check("two voltage writes, two current writes",
          supply.calls == [("voltage", 5.0), ("voltage", 6.0),
                           ("current", 1.0), ("current", 2.0)],
          f"{supply.calls}")

    for name, setter, bad in (
            ("voltage level", supply.set_voltage_level, -1.0),
            ("voltage limit", supply.set_voltage_limit, -1.0),
            ("voltage level", supply.set_voltage_level, 31.0),
            ("voltage limit", supply.set_voltage_limit, 31.0),
            ("current level", supply.set_current_level, 0.0),
            ("current limit", supply.set_current_limit, 0.0),
            ("current level", supply.set_current_level, -1.0),
            ("current limit", supply.set_current_limit, 6.0)):
        supply.calls.clear()
        try:
            setter(bad)
        except LimitError:
            check(f"{name} {bad:g}: refused before the wire",
                  supply.calls == [], f"{supply.calls}")
        else:
            check(f"{name} {bad:g}: refused", False, "accepted")


def test_a_model_with_no_floor_declared_is_not_given_one(check):
    """`None` means the model has not said, and the base must not
    invent a floor - or a refusal - on its behalf."""

    class NoFloor(BenchSupply):
        MIN_CURRENT_A = None

    supply = NoFloor()
    supply.set_current_level(0.0)
    check("zero went through", supply.calls == [("current", 0.0)])
    supply.validate_source_point(voltage=1.0, current=0.0,
                                 sourcing="voltage")


def test_the_gate_checks_the_floor_under_both_roles(check):
    supply = BenchSupply()
    for sourcing, kwargs, role in (
            ("voltage", dict(voltage=5.0, current=0.001), "compliance"),
            ("current", dict(current=0.001, voltage=5.0), "level")):
        try:
            supply.validate_source_point(sourcing=sourcing, **kwargs)
        except LimitError as exc:
            check(f"sourcing {sourcing}: names the {role}",
                  role in str(exc), str(exc))
        else:
            check(f"sourcing {sourcing}: refused", False, "passed")

    # A compliance has no sign of its own. Only the commanded quantity
    # is polarity-checked, exactly as on a load.
    supply.validate_source_point(voltage=5.0, current=-1.0,
                                 sourcing="voltage")


def test_ranging_sends_nothing_and_says_what_is_in_force(check):
    supply = BenchSupply()
    plan = RangePlan.for_sourcing("voltage", source_range=5.0,
                                  measure_range=0.1)
    said = []
    described = supply.apply_ranges(plan, log=said.append)
    check("nothing was sent", supply.calls == [], f"{supply.calls}")
    check("the record says it is fixed", described.startswith("fixed"),
          described)
    check("and gives the span and the steps",
          "30 V" in described and "0.01 V" in described, described)
    check("the console is told what was asked for",
          said and plan.describe() in said[0], said)


# ---------------------------------------------------------------
# Clamped, in each source function
# ---------------------------------------------------------------


@pytest.mark.parametrize("mode,state,expected", [
    ("voltage", CV, False),
    ("voltage", CC, True),
    ("current", CC, False),
    ("current", CV, True),
    ("voltage", CROSSED, True),
    ("current", CROSSED, True),
    ("voltage", None, None),
    ("current", None, None),
])
def test_clamped_means_regulating_at_the_other_knob(mode, state, expected):
    supply = BenchSupply()
    supply.set_source_function(mode)
    supply.output_on()
    supply.state = state
    assert supply.compliance_tripped() is expected


def test_off_is_not_clamped_and_undeclared_is_not_known(check):
    supply = BenchSupply()
    supply.state = CC
    supply.set_source_function("voltage")
    check("output off: not clamped", supply.compliance_tripped() is False)

    supply = BenchSupply()
    supply.state = CC
    supply.output_on()
    check("no source function chosen: cannot say",
          supply.compliance_tripped() is None)

    supply.set_source_function("voltage")
    check("on and in current limit: clamped",
          supply.compliance_tripped() is True)
    supply.output_off()
    check("and off again: not clamped",
          supply.compliance_tripped() is False)

    check("a driver that cannot ask says so by default",
          BaseSupply.regulation(supply) is None
          and BaseSupply.protection_tripped(supply) is None)


# ---------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------


def test_a_setting_reads_back_to_within_one_step(check):
    supply = BenchSupply()
    supply.set_voltage_level(0.05)
    check("agreement is unverified by default",
          supply.verify_setpoint("voltage", 0.05).state == UNVERIFIED)
    supply.holding["voltage"] = 0.06
    check("one step of the grid still agrees",
          supply.verify_setpoint("voltage", 0.05).state == UNVERIFIED,
          "a fractional tolerance alone would call 10 mV on 50 mV a "
          "mismatch")
    supply.holding["voltage"] = 0.071
    check("more than a step does not",
          supply.verify_setpoint("voltage", 0.05).state == MISMATCHED)
    supply.holding["voltage"] = 20.15
    check("high up, the fraction is what allows it",
          supply.verify_setpoint("voltage", 20.0).state == UNVERIFIED)
    supply.holding["voltage"] = 20.5
    check("and what refuses it",
          supply.verify_setpoint("voltage", 20.0).state == MISMATCHED)


def test_a_query_the_driver_never_wired_up_is_unsupported(check):
    """Not unreadable: a model difference, not a query that stopped
    answering. `BenchSupply` reads its voltage back and not its
    current."""
    supply = BenchSupply()
    check("voltage is supported",
          BenchSupply.supports_setpoint_readback("voltage"))
    check("current is not",
          not BenchSupply.supports_setpoint_readback("current"))
    check("and is graded as such",
          supply.verify_setpoint("current", 1.0).state == UNSUPPORTED)
    with pytest.raises(ValueError):
        BenchSupply.supports_setpoint_readback("power")


def test_the_trip_is_range_checked_and_read_back(check):
    supply = BenchSupply()
    supply.set_overvoltage_trip(12.0)
    check("sent", supply.calls == [("trip", 12.0)])
    check("and readable",
          supply.verify_overvoltage_trip(12.0).state == UNVERIFIED)
    for bad in (0.5, 34.0):
        with pytest.raises(LimitError):
            supply.set_overvoltage_trip(bad)

    class NoTrip(BenchSupply):
        OVP_RANGE_V = None

    with pytest.raises(NotImplementedError):
        NoTrip().set_overvoltage_trip(5.0)


# ---------------------------------------------------------------
# By invitation
# ---------------------------------------------------------------


def test_a_supply_is_refused_by_a_role_that_has_not_accepted_it(check):
    """The gate itself, with no window involved.

    A supply passes `("sourcing",)` - it does source - so a capability
    requirement alone lets it into a four-contact tab. The caveat is
    what stops it, and the text is the instrument's own.
    """

    class Uninvited(Experiment):
        ROLES = {"source": "SMU"}
        ROLE_REQUIRES = {"source": ("sourcing",)}

    class Invited(Uninvited):
        ROLE_ACCEPTS = {"source": ("power_supply_grade",)}

    supply = BenchSupply()
    refused = Uninvited.unaccepted_caveats("source", supply)
    check("refused by default", list(refused) == ["power_supply_grade"],
          f"{refused}")
    check("with a reason an operator can read",
          "not a source-measure unit" in refused["power_supply_grade"],
          f"{refused}")
    check("accepted where the role says so",
          Invited.unaccepted_caveats("source", supply) == {})
    check("and only for that role",
          list(Invited.unaccepted_caveats("sense", supply))
          == ["power_supply_grade"])


def test_an_instrument_with_no_caveats_is_never_refused_by_this(check):
    """Every SMU and every load. The declaration is read with a default
    because it is not on `BaseInstrument`, and the default has to be
    "nothing to accept"."""
    check("the shared base declares none",
          not hasattr(BaseInstrument, "ROLE_CAVEATS"),
          "it has moved to BaseInstrument - the getattr default in "
          "Experiment.unaccepted_caveats and the note in base_supply.py "
          "can go")

    class Plain:
        pass

    check("no caveats, no refusal",
          Experiment.unaccepted_caveats("source", Plain()) == {})
    for fleet_base in (BaseSMU, BaseLoad):
        check(f"{fleet_base.__name__} carries none",
              Experiment.unaccepted_caveats("source", fleet_base) == {})


def test_every_registered_supply_is_by_invitation(check):
    """A supply that dropped its caveat would be accepted by Van der
    Pauw on its declarations alone."""
    for cls in KNOWN_SUPPLIES:
        check(f"{cls.__name__} declares a caveat",
              "power_supply_grade" in (cls.ROLE_CAVEATS or {}))
        check(f"{cls.__name__} declares its current floor",
              cls.MIN_CURRENT_A and cls.MIN_CURRENT_A > 0)
        check(f"{cls.__name__} declares one quadrant",
              cls.LIMITS.voltage_polarity == POSITIVE
              and cls.LIMITS.current_polarity == POSITIVE)
        check(f"{cls.__name__} declares its resolution",
              all(cls.RESOLUTION.get(q) for q in ("voltage", "current")))
