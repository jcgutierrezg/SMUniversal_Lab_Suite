"""What an instrument can hold, and what its compliance can be.

Three declarations arrived with the Keithley 487, all on
`BaseInstrument` so that an experiment asks them of whatever it is
holding:

* `SOURCE_FUNCTIONS` - the quantities `set_source_function()` takes.
  The 487 holds a voltage only, and a four-contact tab has to refuse it
  at Connect rather than fail at Run.
* `COMPLIANCE_CHOICES` - a compliance that is a menu, not a number.
* `COMPLIANCE_SETS_MEASURE_RANGE` - False where the compliance is a
  protection only, so the measurement range is not derived from it.

Tested here against stand-ins rather than the 487's driver, so a failure
is a failure of the contract and of the panels' helpers, not a quirk of
one model. The 487 is held to them in its own file.
"""
from smuniversal_lab_suite.core.checkup.probes import probe_levels_for
from smuniversal_lab_suite.core.gui.widgets import (
    compliance_label_text,
    compliance_values,
    measure_range_for,
    refresh_source_modes,
    require_source_mode,
)
from smuniversal_lab_suite.core.limits import SMULimits
from smuniversal_lab_suite.core.ranges import AUTO
from smuniversal_lab_suite.drivers.base_instrument import BaseInstrument
from smuniversal_lab_suite.drivers.registry import (
    KNOWN_LOADS,
    KNOWN_SMUS,
    KNOWN_SUPPLIES,
)
from smuniversal_lab_suite.experiments.fixed_source.experiment import (
    FixedSourceExperiment,
)
from smuniversal_lab_suite.experiments.hall.experiment import HallExperiment
from smuniversal_lab_suite.experiments.iv_sweep.experiment import (
    IVSweepExperiment,
)
from smuniversal_lab_suite.experiments.ossila_4pp.experiment import (
    Ossila4PPExperiment,
)
from smuniversal_lab_suite.experiments.vanderpauw.experiment import (
    VanDerPauwExperiment,
)

MENU = (25e-6, 2.5e-3)


class VoltageOnly:
    """A 487-shaped instrument: holds a voltage, limit on a menu."""

    DISPLAY_NAME = "Voltage-only (test double)"
    CAN_SOURCE = True
    SOURCE_FUNCTIONS = ("voltage",)
    COMPLIANCE_CHOICES = {"current": MENU}
    COMPLIANCE_SETS_MEASURE_RANGE = False
    HAS_COMPLIANCE = True
    LIMITS = SMULimits(max_voltage=505.0, max_current=2.5e-3,
                       voltage_ranges=[50.5, 505.0],
                       current_ranges=[2e-9, 2e-6, 2e-3])

    source_functions = classmethod(BaseInstrument.source_functions.__func__)
    supports_sourcing = classmethod(BaseInstrument.supports_sourcing.__func__)
    supports_current_sourcing = classmethod(
        BaseInstrument.supports_current_sourcing.__func__)
    supports_compliance = classmethod(
        BaseInstrument.supports_compliance.__func__)
    compliance_choices = classmethod(
        BaseInstrument.compliance_choices.__func__)
    compliance_sets_measure_range = classmethod(
        BaseInstrument.compliance_sets_measure_range.__func__)


class Radio:
    def __init__(self):
        self.state = "normal"

    def config(self, state):
        self.state = state


class Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def test_every_registered_instrument_holds_both_quantities(check):
    """Until the 487, every driver took both, and the default says so.
    A driver that narrows it has to mean it."""
    check("the default is both",
          BaseInstrument.SOURCE_FUNCTIONS == ("voltage", "current"))
    for cls in (*KNOWN_SMUS, *KNOWN_LOADS, *KNOWN_SUPPLIES):
        if cls.SOURCE_FUNCTIONS != ("voltage", "current"):
            continue
        check(f"{cls.__name__} holds both",
              set(cls.source_functions()) == {"voltage", "current"})


def test_current_sourcing_needs_both_a_source_and_a_current(check):
    """A load holds a current by sinking it, so it is not a current
    source. The 487 sources, but not a current. Only the two together
    are what a four-contact measurement needs."""
    for cls in KNOWN_SMUS + KNOWN_SUPPLIES:
        if "current" in cls.SOURCE_FUNCTIONS:
            check(f"{cls.__name__} pushes a current",
                  cls.supports_current_sourcing())
    for cls in KNOWN_LOADS:
        check(f"{cls.__name__} does not",
              not cls.supports_current_sourcing())
    check("a voltage-only source does not",
          not VoltageOnly.supports_current_sourcing())
    check("but it does source", VoltageOnly.supports_sourcing())


def test_four_contact_tabs_refuse_a_voltage_only_source(check):
    """By capability: the role names `current_sourcing`, and the
    instrument declares it cannot."""
    for experiment in (VanDerPauwExperiment, HallExperiment,
                       Ossila4PPExperiment):
        required = experiment.ROLE_REQUIRES.get("source", ())
        check(f"{experiment.__name__} requires current sourcing",
              "current_sourcing" in required, f"{required}")
        refused = [c for c in required
                   if not getattr(VoltageOnly, f"supports_{c}")()]
        check(f"{experiment.__name__} refuses it",
              refused == ["current_sourcing"], f"{refused}")
    for experiment in (IVSweepExperiment, FixedSourceExperiment):
        required = experiment.ROLE_REQUIRES.get("source", ())
        check(f"{experiment.__name__} takes it",
              all(getattr(VoltageOnly, f"supports_{c}")()
                  for c in required), f"{required}")


def test_the_radio_for_a_missing_mode_is_greyed_and_the_form_moves(check):
    radios = {"voltage": Radio(), "current": Radio()}
    var = Var("current")
    logged = []
    moved = refresh_source_modes(radios, var, VoltageOnly, logged.append)
    check("current greyed", radios["current"].state == "disabled")
    check("voltage live", radios["voltage"].state == "normal")
    check("the form moved to voltage", var.get() == "voltage")
    check("and said so", moved and logged, f"{logged}")

    # And back: an instrument with both re-enables what was greyed.
    class Both(VoltageOnly):
        SOURCE_FUNCTIONS = ("voltage", "current")

    moved = refresh_source_modes(radios, var, Both)
    check("re-enabled", radios["current"].state == "normal")
    check("nothing to move", moved is False)


def test_a_missing_mode_is_refused_at_run(check):
    """The radio is greyed at connect, but a mode can arrive from a form
    filled in before the instrument was connected."""
    try:
        require_source_mode(VoltageOnly, "current")
    except ValueError as exc:
        check("names what it can do", "voltage" in str(exc), str(exc))
    else:
        check("current refused", False)
    require_source_mode(VoltageOnly, "voltage")
    require_source_mode(None, "current")


def test_a_compliance_menu_is_offered_as_a_menu(check):
    values, menu = compliance_values(VoltageOnly, "voltage", ["1"])
    check("the menu, safest first", values == ["2.5e-05", "0.0025"],
          f"{values}")
    check("read-only", menu is True)

    class Plain(VoltageOnly):
        COMPLIANCE_CHOICES = None

    values, menu = compliance_values(Plain, "voltage", ["1"])
    check("otherwise the range list", values == ["2e-09", "2e-06", "0.002"],
          f"{values}")
    check("editable", menu is False)
    values, menu = compliance_values(None, "voltage", ["1"])
    check("and the fallback with nothing connected",
          (values, menu) == (["1"], False))


def test_a_protection_only_compliance_leaves_the_range_to_the_instrument(
        check):
    """The reason the declaration exists: 25 uA would otherwise pin a
    picoammeter to its 200 uA range."""
    check("AUTO on the 487 shape",
          measure_range_for(VoltageOnly, 25e-6) is AUTO)

    class Plain(VoltageOnly):
        COMPLIANCE_SETS_MEASURE_RANGE = True

    check("the compliance elsewhere",
          measure_range_for(Plain, 1e-4) == 1e-4)
    check("the compliance with nothing connected",
          measure_range_for(None, 1e-4) == 1e-4)
    label, note = compliance_label_text(VoltageOnly, "voltage")
    check("still called a compliance", "compliance" in label, label)
    check("and the note says it is a protection only",
          "protection only" in note, note)


def test_the_checkup_probes_at_a_value_on_the_menu(check):
    """A compliance off the menu is refused outright, so the probe
    cannot be clamped onto one - it takes the safest entry."""
    probe = probe_levels_for(VoltageOnly())
    check("current compliance on the menu",
          probe.compliance_i == MENU[0], f"{probe.compliance_i}")
    check("and said so",
          any("nothing else" in note for note in probe.notes),
          f"{probe.notes}")
