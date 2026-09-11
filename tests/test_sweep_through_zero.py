"""A sweep through zero reaches the other side, on every driver.

The sub-count floor refuses a level too small for the active range to
express. It exempted exactly zero and nothing else, and a sweep's zero
point is computed: `start + step * i` in the software sweep,
`np.linspace` in the 4PP triangle. For many ordinary point counts that
computes to about 1e-20 rather than 0. A −100 uA to +100 uA current
sweep in 201 points puts −1.36e-20 A at its midpoint, the floor refused
it, and the run ended at point 100 - a current IV sweep on the 2401,
2635B and B2901A, a 4PP sweep on every driver with a current floor, and
voltage sweeps too on the U2722A, whose own refusal had the same gap.

The checkup never sweeps through zero, and the experiment tests run on
the DummySMU, which declares no floor - so nothing in the suite could
see it. This runs the level lists those experiments actually compute
through each real driver's own level setter, on each driver's own fake.

And the discriminating half: a level genuinely below the floor is still
refused. A fix that stopped refusing anything would pass the first half.
"""
import numpy as np
from test_checkup_all_drivers import CASES

from core.ranges import RangeError, RangePlan
from experiments.ossila_4pp.fourpp_math import triangular_current_list

#: The current sweep that ended at its midpoint.
CURRENT_SPAN = 1e-4
CURRENT_POINTS = 201

#: A voltage sweep whose zero point also computes to a residue - one of
#: the 31 odd point counts over this span that do.
VOLTAGE_SPAN = 1.0
VOLTAGE_POINTS = 99

#: The drivers that refuse sub-floor levels on the current axis. Every
#: other driver in CASES declares no floor there, so the discriminating
#: half has nothing to refuse on it.
FLOORED = {"Keithley2401", "Keithley2611A", "Keithley2635B",
           "GWInstekGSM20H10", "KeysightB2901A", "KeysightU2722A"}


def _driver(driver_cls, transport_factory):
    transport = transport_factory()
    if not getattr(transport, "connected", False):
        transport.connect("fake")
    return driver_cls(transport)


def _sweep_levels(span, points):
    """Both ways the experiments compute a sweep, deduplicated."""
    step = 2 * span / (points - 1)
    computed = [-span + step * i for i in range(points)]
    return computed + [float(v) for v in np.linspace(-span, span, points)]


#: Drivers on which the whole sweep is refused by design, for a reason
#: other than the residue. Checked in both directions: the residue point
#: must still be accepted there, and if the whole sweep ever is, the
#: behaviour recorded here has changed and the entry has to be revisited.
WIDEST_RANGE = {
    ("KeysightU2722A", "current"): (
        "one knob per quantity with no autorange, so the plan's AUTO "
        "takes the widest range, R120mA, and a level set straight after "
        "the plan - as 4PP, VdP, Hall and fixed source do - is refused "
        "under its 73 uA floor. The IV sweep picks a range for its own "
        "span and is not affected. Decided, not a fault: the driver "
        "warns, and the remedy is another instrument or explicit ranges "
        "- see docs/instruments/keysight-u2722a.md."),
}


def _first_refusal(set_level, levels):
    for level in levels:
        try:
            set_level(level)
        except RangeError as exc:
            return level, exc
    return None


def _check_sweep(check, name, quantity, set_level, levels, span):
    residue = [v for v in levels if v != 0 and abs(v) < span * 1e-12]
    refused = _first_refusal(set_level, residue)
    check(f"{name}: the zero point the sweep computed is accepted",
          refused is None,
          f"refused {refused[0]!r}: {refused[1]}" if refused else "")

    refused = _first_refusal(set_level, levels)
    if (name, quantity) in WIDEST_RANGE:
        check(f"{name}: still refuses the sweep for the recorded reason - "
              f"if not, remove it from WIDEST_RANGE",
              refused is not None, WIDEST_RANGE[name, quantity])
        return
    check(f"{name}: every level of the sweep is accepted",
          refused is None,
          f"refused {refused[0]!r}: {refused[1]}" if refused else "")


def test_the_grids_under_test_do_not_reach_exact_zero(check):
    """Otherwise every test below passes on an exact zero and proves
    nothing about the residue."""
    for span, points in ((CURRENT_SPAN, CURRENT_POINTS),
                         (VOLTAGE_SPAN, VOLTAGE_POINTS)):
        residue = [v for v in _sweep_levels(span, points)
                   if v != 0 and abs(v) < span * 1e-12]
        check(f"+/-{span:g} in {points} points has a residue at zero",
              bool(residue), "the grid reaches exact zero")
    triangle, _, _ = triangular_current_list(-CURRENT_SPAN, CURRENT_SPAN,
                                             101)
    residue = [v for v in triangle if v != 0 and abs(v) < 1e-15]
    check("the 4PP triangle in 101 points has a residue at zero",
          bool(residue), "the triangle reaches exact zero")


def test_a_current_sweep_through_zero_is_not_refused(check):
    triangle, _, _ = triangular_current_list(-CURRENT_SPAN, CURRENT_SPAN,
                                             101)
    levels = _sweep_levels(CURRENT_SPAN, CURRENT_POINTS) + triangle
    for name, driver_cls, transport_factory in CASES:
        driver = _driver(driver_cls, transport_factory)
        driver.apply_ranges(RangePlan.for_sourcing(
            "current", source_range=CURRENT_SPAN, measure_range=2.0),
            log=lambda _message: None)
        _check_sweep(check, name, "current", driver.set_current_level, levels,
                     CURRENT_SPAN)


def test_a_voltage_sweep_through_zero_is_not_refused(check):
    levels = _sweep_levels(VOLTAGE_SPAN, VOLTAGE_POINTS)
    for name, driver_cls, transport_factory in CASES:
        driver = _driver(driver_cls, transport_factory)
        driver.apply_ranges(RangePlan.for_sourcing(
            "voltage", source_range=VOLTAGE_SPAN, measure_range=1e-3),
            log=lambda _message: None)
        _check_sweep(check, name, "voltage", driver.set_voltage_level, levels,
                     VOLTAGE_SPAN)


def test_a_level_genuinely_below_the_floor_is_still_refused(check):
    """About 95 pA on the 100 uA range: under ten counts on every
    driver with a floor, and a million times above float residue."""
    for name, driver_cls, transport_factory in CASES:
        if name not in FLOORED:
            continue
        driver = _driver(driver_cls, transport_factory)
        driver.apply_ranges(RangePlan.for_sourcing(
            "current", source_range=CURRENT_SPAN, measure_range=2.0))
        refused = _first_refusal(driver.set_current_level,
                                 [CURRENT_SPAN / 2 ** 20])
        check(f"{name}: a sub-floor level is refused", refused is not None,
              "accepted")
