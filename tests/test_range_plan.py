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

from core.ranges import AUTO, NOT_SOURCED, RangeError, RangePlan
from drivers.base_smu import BaseSMU
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


# ------------------------------------------------------------------
# NOT_SOURCED: the axis that carries nothing
# ------------------------------------------------------------------
def test_for_sourcing_marks_the_unsourced_axis(check):
    """`AUTO` and "not being sourced" are different statements.

    They were spelled the same until 2026-08-20. `AUTO` asks the
    instrument to choose a range; `NOT_SOURCED` says nothing will come
    out of that axis, so there is nothing to choose. A driver receiving
    `AUTO` could not tell them apart, and two of the seven instruments
    commissioned that week were damaged by acting on the wrong one.
    """
    volt = RangePlan.for_sourcing("voltage", source_range=0.1,
                                  measure_range=1e-3)
    check("sourcing voltage leaves the current source axis unsourced",
          volt.source_current is NOT_SOURCED, repr(volt.source_current))
    check("the sourced axis keeps its magnitude", volt.source_voltage == 0.1)
    check("the measured axis keeps its magnitude", volt.measure_current == 1e-3)
    check("the sourced quantity's measure axis stays AUTO",
          volt.measure_voltage is AUTO, repr(volt.measure_voltage))

    curr = RangePlan.for_sourcing("current", source_range=1e-6,
                                  measure_range=1.0)
    check("sourcing current leaves the voltage source axis unsourced",
          curr.source_voltage is NOT_SOURCED, repr(curr.source_voltage))

    check("and it reads as itself in the description",
          "not sourced" in volt.describe(), volt.describe())


def test_an_unsourced_axis_never_wins_a_shared_knob(check):
    """This is what cost the U2722A its compliance.

    With `AUTO` on the unsourced axis, the shared-knob reconciliation
    took the wider - and `AUTO` beat every fixed value, so the knob went
    to the instrument's widest range. A 100 uA compliance is 0.08% of
    120 mA, which that instrument refuses outright with `-222 Data out
    of range`: not a resolution cost, an unsettable limit and a sweep
    that sources nothing.

    An axis carrying nothing has no claim on a knob shared with an axis
    that is carrying something.
    """
    plan = RangePlan.for_sourcing("voltage", source_range=0.1,
                                  measure_range=1e-3)
    check("the shared current knob follows the compliance, not the void",
          plan.widest("source_current", "measure_current") == 1e-3,
          repr(plan.widest("source_current", "measure_current")))

    both = RangePlan(source_current=NOT_SOURCED, source_voltage=1.0,
                     measure_current=NOT_SOURCED, measure_voltage=AUTO)
    check("two unsourced axes leave the knob genuinely unconstrained",
          both.widest("source_current", "measure_current") is AUTO,
          repr(both.widest("source_current", "measure_current")))

    fixed = RangePlan(source_current=NOT_SOURCED, source_voltage=1.0,
                      measure_current=AUTO, measure_voltage=AUTO)
    check("AUTO still beats a fixed value when both axes are real",
          fixed.widest("source_current", "measure_current") is AUTO)


def test_the_default_rendering_changes_nothing_for_the_unharmed(check):
    """Five of seven instruments were fine and must stay fine.

    `BaseSMU._render_not_sourced` turns the marker back into `AUTO`, so
    a driver that says nothing behaves exactly as it did when it was
    commissioned. Only a driver that overrides it - having been checked
    at the bench - does anything different.
    """
    for name, driver_cls, transport_factory in CASES:
        transport = transport_factory()
        if not getattr(transport, "connected", False):
            transport.connect("fake")
        driver = driver_cls(transport)
        overrides = (type(driver)._render_not_sourced
                     is not BaseSMU._render_not_sourced)
        rendered = driver._render_not_sourced(NOT_SOURCED)
        if overrides:
            check(f"{name}: overrides, and does not render it as AUTO",
                  rendered is not NOT_SOURCED, repr(rendered))
        else:
            check(f"{name}: default renders the marker as AUTO",
                  rendered is AUTO, repr(rendered))
        check(f"{name}: a real magnitude passes through untouched",
              driver._render_not_sourced(1e-3) == 1e-3)
        check(f"{name}: AUTO passes through untouched",
              driver._render_not_sourced(AUTO) is AUTO)


def test_the_two_harmed_instruments_no_longer_touch_the_unsourced_axis(check):
    """The bench findings of 2026-08-20, held in place.

    Both instruments were harmed by a command sent *only* to express
    indifference about an axis carrying nothing, and in opposite ways:

      * GSM-20H10 - `SOUR:CURR:RANG:AUTO ON` while sourcing voltage
        silently reset the current compliance from 105 uA to 1 nA, and
        the voltage mirror took 21 V to 200 uV (fault 23).
      * U2722A - no autorange, so the driver substituted the widest
        fixed range; a 100 uA compliance on the 120 mA range is 0.08% of
        it and the instrument refused it with `-222`, failing four
        checks including the sweep.

    Checked on the wire rather than through `_render_not_sourced`,
    because what matters is what reaches the instrument. Asserting the
    hook returns `None` would pass against a driver that then went on to
    send the command anyway.
    """
    from drivers.gwinstek_gsm20h10 import GWInstekGSM20H10
    from drivers.keysight_u2722a import KeysightU2722A
    from test_u2722a import U2722ATransport

    plan_v = RangePlan.for_sourcing("voltage", source_range=0.1,
                                    measure_range=1e-4)
    plan_i = RangePlan.for_sourcing("current", source_range=1e-6,
                                    measure_range=1.0)

    def gsm_sends(plan):
        transport = next(factory for name, _, factory in CASES
                         if name == "GWInstekGSM20H10")()
        if not getattr(transport, "connected", False):
            transport.connect("fake")
        driver = GWInstekGSM20H10(transport)
        transport.sent.clear()
        driver.apply_ranges(plan, log=lambda *a: None)
        return transport.sent

    # One plan per transport. Running both into one list would let the
    # *sourced* axis of the second plan - which legitimately sends
    # `SOUR:CURR:RANG:AUTO OFF` while sourcing current - satisfy or
    # break an assertion meant for the first.
    sourcing_v = gsm_sends(plan_v)
    check("GSM: nothing at all on the current source axis while "
          "sourcing voltage",
          not [c for c in sourcing_v if c.startswith("SOUR:CURR:RANG")],
          [c for c in sourcing_v if c.startswith("SOUR:CURR:RANG")])
    check("GSM: the sourced axis is still ranged",
          "SOUR:VOLT:RANG 1.000000e-01" in sourcing_v,
          [c for c in sourcing_v if c.startswith("SOUR:VOLT:RANG")])
    check("GSM: the measured axis is still ranged",
          "SENS:CURR:DC:RANG 1.000000e-04" in sourcing_v,
          [c for c in sourcing_v if c.startswith("SENS:CURR:DC:RANG")])

    sourcing_i = gsm_sends(plan_i)
    check("GSM: nothing at all on the voltage source axis while "
          "sourcing current",
          not [c for c in sourcing_i if c.startswith("SOUR:VOLT:RANG")],
          [c for c in sourcing_i if c.startswith("SOUR:VOLT:RANG")])
    check("GSM: the sourced axis is still ranged in current mode",
          "SOUR:CURR:RANG 1.000000e-06" in sourcing_i,
          [c for c in sourcing_i if c.startswith("SOUR:CURR:RANG")])

    # The U2722A is fixed by the reconciliation, not by a driver
    # override - `INDEPENDENT_SOURCE_RANGE` is False, so both source
    # axes go through `RangePlan.widest()` and the marker is resolved
    # before any hook sees it. A mutation round proved an override here
    # unreachable, so there is none to test; this checks the wire.
    u_transport = U2722ATransport()
    u = KeysightU2722A(u_transport)
    u_transport.sent.clear()
    u.apply_ranges(plan_v, log=lambda *a: None)
    check("U2722A: the shared current knob is not widened to R120mA",
          u_transport.current_range != "R120mA", u_transport.current_range)
    check("U2722A: it follows the compliance instead",
          u_transport.current_range == "R100uA", u_transport.current_range)


def test_a_shared_knob_hook_receives_the_compliance_not_the_void(check):
    """On one-knob instruments the reconciliation is the whole fix.

    The U2722A needs no driver override because
    `INDEPENDENT_SOURCE_RANGE` is False: both source axes go through
    `RangePlan.widest()`, and that is where an axis carrying nothing
    loses its claim on a knob shared with an axis carrying something.

    The first version of this test asserted the hook never receives the
    raw marker. A mutation round showed that could not fail -
    `_render_not_sourced` converts it before any hook is called, so the
    assertion was true whatever `widest()` did. Fault 19, in a test
    written to guard against exactly that class of thing.

    What discriminates is the *value*: the hook must receive the
    compliance, not `AUTO`. Sourcing 0.1 V with a 100 uA compliance, the
    shared current knob belongs to the compliance.
    """
    plan = RangePlan.for_sourcing("voltage", source_range=0.1,
                                  measure_range=1e-4)
    for name, driver_cls, transport_factory in CASES:
        if driver_cls.INDEPENDENT_SOURCE_RANGE:
            continue
        transport = transport_factory()
        if not getattr(transport, "connected", False):
            transport.connect("fake")
        driver = driver_cls(transport)

        seen = []
        inner = driver._apply_source_current_range

        def watch(value, _inner=inner, _seen=seen):
            _seen.append(value)
            return _inner(value)
        driver._apply_source_current_range = watch

        driver.apply_ranges(plan, log=lambda *a: None)
        check(f"{name}: the shared current knob got the compliance",
              seen == [1e-4], repr(seen))
