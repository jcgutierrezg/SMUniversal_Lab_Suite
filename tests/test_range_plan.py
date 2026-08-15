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
    except RangeError as exc:
        # The U2722A has no autorange at all. Refusing is correct - and
        # this is the check that would fail if it started pretending.
        check(f"{name}: refuses AUTO because it has none, and says so",
              not driver.INDEPENDENT_SOURCE_RANGE, str(exc))
        return
    except NotImplementedError as exc:
        check(f"{name}: an axis is missing an implementation", False,
              str(exc))
        return
    check(f"{name}: an all-auto plan is carried out", True)


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
