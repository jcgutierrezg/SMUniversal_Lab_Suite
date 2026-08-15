import sys, os

"""The ranging contract: every axis goes where its name says.

Wave 6d-i. Adds `RangePlan` and `apply_ranges()`; nothing has adopted
them yet, so every existing test stays green and a failure here is
unambiguously a fault in the new layer.

The fault being designed out is described at the top of `core/ranges.py`:
`set_current_range()` meant a *source* range on two drivers, a *measure*
range on five, and both on one. Nothing produced a wrong number only
because every current-sourcing experiment poured and measured the same
litre. That coincidence ends the moment an experiment lets the operator
source one quantity and measure another.
"""
import pytest

from core.ranges import AUTO, RangeError, RangePlan
from test_checkup_all_drivers import CASES


def make(driver_cls, transport_factory):
    transport = transport_factory()
    if not getattr(transport, "connected", False):
        transport.connect("fake")
    return driver_cls(transport), transport


FIXED = RangePlan(source_current=1e-3, source_voltage=2.0,
                  measure_current=1e-3, measure_voltage=2.0)
AUTO_PLAN = RangePlan(source_current=AUTO, source_voltage=AUTO,
                      measure_current=AUTO, measure_voltage=AUTO)


# ---------------------------------------------------------------
# A. the plan object itself
# ---------------------------------------------------------------

def test_a_plan_needs_every_axis(check):
    """No partial plans. An unstated range is one inherited from the
    previous run, which is the fault this replaces."""
    with pytest.raises(TypeError):
        RangePlan(source_current=1e-3)
    check("a three-axis plan is refused", True)


def test_a_plan_refuses_values_that_are_not_ranges(check):
    for bad in (None, "1e-3", object()):
        with pytest.raises(RangeError):
            RangePlan(source_current=bad, source_voltage=AUTO,
                      measure_current=AUTO, measure_voltage=AUTO)
    check("None, strings and objects are all refused", True)

    with pytest.raises(RangeError):
        RangePlan(source_current=-1e-3, source_voltage=AUTO,
                  measure_current=AUTO, measure_voltage=AUTO)
    check("a negative magnitude is refused", True)


def test_auto_is_truthy(check):
    """`if plan.source_current:` must not quietly mean 'not auto'.

    A falsy sentinel would make that idiom read backwards, and it is the
    idiom someone will reach for.
    """
    check("AUTO is truthy", bool(AUTO) is True)
    check("and it describes itself", repr(AUTO) == "AUTO")


def test_the_wider_of_two_axes_wins_and_auto_beats_everything(check):
    plan = RangePlan(source_current=1e-3, source_voltage=2.0,
                     measure_current=1e-6, measure_voltage=AUTO)
    check("the wider fixed value is chosen",
          plan.widest("source_current", "measure_current") == 1e-3)
    check("AUTO beats any fixed value",
          plan.widest("source_voltage", "measure_voltage") is AUTO)


# ---------------------------------------------------------------
# B. every driver carries out a plan
# ---------------------------------------------------------------

@pytest.mark.parametrize("name,driver_cls,transport_factory", CASES,
                         ids=[c[0] for c in CASES])
def test_every_driver_can_carry_out_a_fixed_plan(check, name, driver_cls,
                                                 transport_factory):
    driver, transport = make(driver_cls, transport_factory)
    try:
        summary = driver.apply_ranges(FIXED, log=lambda m: None)
    except NotImplementedError as exc:
        check(f"{name}: a declared axis is missing an implementation",
              False, str(exc))
        return
    check(f"{name}: a fixed plan is carried out", isinstance(summary, str),
          f"returned {summary!r}")


@pytest.mark.parametrize("name,driver_cls,transport_factory", CASES,
                         ids=[c[0] for c in CASES])
def test_every_driver_can_carry_out_an_auto_plan(check, name, driver_cls,
                                                 transport_factory):
    driver, transport = make(driver_cls, transport_factory)
    try:
        driver.apply_ranges(AUTO_PLAN, log=lambda m: None)
    except NotImplementedError as exc:
        check(f"{name}: an axis is missing an implementation", False,
              str(exc))
        return
    check(f"{name}: an all-auto plan is carried out", True)


def test_an_instrument_without_autorange_widens_rather_than_refusing(check):
    """Decision W6d-2, applied to AUTO as well as to a conflict.

    The first version of this refused AUTO on the U2722A, which has no
    autorange. That was wrong twice over. It produced a mid-run abort on
    a model-agnostic caller - the checkup asks every instrument for an
    all-AUTO plan - and it ignored the reasoning already settled for
    shared knobs: the widest range never clamps a level and never
    overranges a reading, so it is the one realisation of "let the
    instrument choose" that cannot produce a wrong number.

    Silence would still be wrong. Leaving the range wherever it was
    means the 1 uA it resets to, which clamps almost everything.
    """
    from drivers.keysight_u2722a import KeysightU2722A
    case = [c for c in CASES if c[0] == "KeysightU2722A"]
    check("the no-autorange model is in CASES", bool(case))
    if not case:
        return

    _, driver_cls, transport_factory = case[0]
    driver, transport = make(driver_cls, transport_factory)
    if not hasattr(transport, "sent"):
        pytest.skip("fake transport does not record writes")

    transport.sent.clear()
    driver._apply_source_current_range(AUTO)
    widest = max(KeysightU2722A.CURRENT_RANGE_TOKENS)[1]
    check("AUTO selects the widest current range this model has",
          any(widest in t for t in transport.sent),
          f"sent {transport.sent}, expected {widest}")


# ---------------------------------------------------------------
# C. the axes are not crossed
# ---------------------------------------------------------------

#: For drivers with independent axes, what each axis must and must not
#: put on the wire. The whole point of the wave is that these no longer
#: overlap.
AXIS_MARKERS = {
    "Keithley2450": (":SOUR:CURR:RANG", ":SENS:CURR:RANG"),
    "Keithley2401": (":SOUR:CURR:RANG", ":SENS:CURR:RANG"),
    "KeysightB2901A": (":SOUR:CURR:RANG", ":SENS:CURR:RANG"),
    "GWInstekGSM20H10": ("SOUR:CURR:RANG", "SENS:CURR:DC:RANG"),
    "Keithley2611A": ("source.rangei", "measure.rangei"),
    "Keithley2635B": ("source.rangei", "measure.rangei"),
}


@pytest.mark.parametrize("name,driver_cls,transport_factory", CASES,
                         ids=[c[0] for c in CASES])
def test_the_source_axis_does_not_send_a_measure_command(
        check, name, driver_cls, transport_factory):
    """The specific confusion this wave removes.

    Before it, asking the 2450 for a current range set a *source* range
    while asking the B2901A set a *measure* one, and the caller had no
    way to say which it wanted. Now the source hook must send only the
    source command and the measure hook only the measure command.
    """
    markers = AXIS_MARKERS.get(name)
    if markers is None:
        pytest.skip(f"{name} has no independent source range to check")
    source_marker, measure_marker = markers

    driver, transport = make(driver_cls, transport_factory)
    if not hasattr(transport, "sent"):
        pytest.skip(f"{name}'s fake transport does not record writes")

    transport.sent.clear()
    driver._apply_source_current_range(1e-3)
    sent = " ".join(transport.sent)
    check(f"{name}: the source axis sends the source command",
          source_marker in sent, f"sent {transport.sent}")
    check(f"{name}: and does not touch the measure range",
          measure_marker not in sent, f"sent {transport.sent}")

    transport.sent.clear()
    driver._apply_measure_current_range(1e-3)
    sent = " ".join(transport.sent)
    check(f"{name}: the measure axis sends the measure command",
          measure_marker in sent, f"sent {transport.sent}")
    check(f"{name}: and does not touch the source range",
          source_marker not in sent, f"sent {transport.sent}")


# ---------------------------------------------------------------
# D. one-knob instruments resolve, loudly
# ---------------------------------------------------------------

def test_a_shared_knob_takes_the_wider_and_says_so(check):
    """Decision W6d-2, and it fails safe by construction.

    A range wider than asked for never clamps a source level and never
    overranges a reading; the only cost is resolution. Losing a digit is
    a worse measurement. Clamping is a wrong one.
    """
    shared = [(n, c, t) for n, c, t in CASES
              if not c.INDEPENDENT_SOURCE_RANGE]
    check("at least one driver shares a range knob", bool(shared),
          "nothing exercises the reconciliation path")

    for name, driver_cls, transport_factory in shared:
        driver, transport = make(driver_cls, transport_factory)
        said = []
        plan = RangePlan(source_current=1e-3, source_voltage=2.0,
                         measure_current=1e-6, measure_voltage=2.0)
        driver.apply_ranges(plan, log=said.append)
        joined = " ".join(said)
        check(f"{name}: the conflict is reported", bool(said),
              "nothing was said about a conflict that exists")
        check(f"{name}: and the message names the wider value chosen",
              "0.001" in joined or "1e-03" in joined or "wider" in joined,
              joined)


def test_a_shared_knob_stays_quiet_when_there_is_no_conflict(check):
    """The control. A driver that complained on every plan would be
    ignored within a week."""
    shared = [(n, c, t) for n, c, t in CASES
              if not c.INDEPENDENT_SOURCE_RANGE]
    for name, driver_cls, transport_factory in shared:
        driver, transport = make(driver_cls, transport_factory)
        said = []
        driver.apply_ranges(FIXED, log=said.append)
        check(f"{name}: no complaint when source and measure agree",
              not said, " ".join(said))


# ---------------------------------------------------------------
# E. the axis a plan must never set
# ---------------------------------------------------------------

def test_for_sourcing_leaves_the_sourced_quantitys_measure_range_auto(check):
    """The rule that error 823 is telling us about.

    On the 2400 family the measured value of the sourced quantity is
    read back from the source, so it has no independent measurement
    range. Setting one is rejected - error 823, "Invalid with source
    read-back on", on both the 2401 and the GSM-20H10 (deviation 41).

    It is meaningless on every SMU; those two are simply the models
    honest enough to refuse. `for_sourcing` makes it unrepresentable
    rather than merely detectable, which matters because every
    experiment got it wrong on first attempt - including, in this very
    wave, the one written to get ranging right.
    """
    v = RangePlan.for_sourcing("voltage", source_range=2.0,
                               measure_range=1e-3)
    check("sourcing voltage: the measure voltage axis is AUTO",
          v.measure_voltage is AUTO, f"{v.describe()}")
    check("and the source voltage axis carries the span",
          v.source_voltage == 2.0, f"{v.describe()}")
    check("and current is measured on the given range",
          v.measure_current == 1e-3, f"{v.describe()}")

    i = RangePlan.for_sourcing("current", source_range=1e-3,
                               measure_range=2.0)
    check("sourcing current: the measure current axis is AUTO",
          i.measure_current is AUTO, f"{i.describe()}")
    check("and the source current axis carries the level",
          i.source_current == 1e-3, f"{i.describe()}")


def test_for_sourcing_refuses_a_mode_it_does_not_know(check):
    with pytest.raises(RangeError):
        RangePlan.for_sourcing("resistance", source_range=1.0,
                               measure_range=1.0)
    check("an unknown source mode is refused", True)


def test_every_experiment_builds_its_plan_through_for_sourcing(check):
    """Grep-level, deliberately.

    `for_sourcing` only protects callers that use it. A plan built with
    the plain constructor can still set the forbidden axis, and the
    experiments are exactly where that mistake was made. This is the
    check that notices a new experiment - or a future edit - going
    around it.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted((root / "experiments").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "RangePlan(" in stripped:
                offenders.append(f"{path.name}:{number}")
    check("no experiment builds a RangePlan directly",
          not offenders,
          ", ".join(offenders) + " - use RangePlan.for_sourcing()")
