"""Five faults found measuring a solar cell on the 72-13200, 2026-10-07.

1. A sweep ending exactly on a limit was refused by rounding error.
2. Nothing said when the load did not reach the levels it was asked for.
3. A current sweep left the load on its 30 A range whatever the span.
4. A per-point delay shorter than the load's settling time was accepted.
5. The gate multiplied the swept current by the voltage *range* and
   refused anything over 150 W / 18 V = 8.33 A.

The readings used for the regulation report are the shapes the bench
recorded that day, at the values it recorded them.
"""
import time

import pytest
from test_72_13200 import build

from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.core.ranges import NOT_SOURCED, RangePlan
from smuniversal_lab_suite.drivers.keithley_2401 import Keithley2401
from smuniversal_lab_suite.drivers.multicomp_72_13200 import (
    MulticompPro7213200,
)
from smuniversal_lab_suite.experiments.iv_sweep.experiment import (
    IVSweepExperiment,
)


def sweep(load, mode, start, stop, points):
    load.start_linear_sweep(mode, start, stop, points, 0.0)
    deadline = time.monotonic() + 5.0
    while load.sweep_points_ready() < points:
        assert time.monotonic() < deadline, "the sweep did not finish"
        time.sleep(0.01)
    return load.read_sweep(points)


def setpoints(transport, header):
    return [c for c in transport.sent
            if c.upper().startswith(header) and "UPP" not in c.upper()
            and "?" not in c]


# ---------------------------------------------------------------------
# 1. limits, and levels that are on them but for rounding
# ---------------------------------------------------------------------


def test_a_sweep_down_to_the_cv_floor_completes(check):
    """0.7 -> 0.1 V in 13 points computes its last level as
    0.09999999999999998, which was refused as "below 0.1 V"."""
    load, t = build()
    # The control: the arithmetic really does land under the floor.
    last = 0.7 + (0.1 - 0.7) / 12 * 12
    check("the computed last level is under 0.1", last < 0.1, repr(last))

    sourced, _ = sweep(load, "voltage", 0.7, 0.1, 13)

    check("all 13 points were taken", len(sourced) == 13, len(sourced))
    check("and the last setpoint sent is the floor itself",
          setpoints(t, ":VOLT")[-1] == ":VOLTage 0.1V",
          setpoints(t, ":VOLT")[-1])


def test_a_level_really_below_the_floor_is_still_refused(check):
    load, _ = build()
    for volts in (0.0999, 0.05, 0.0):
        with pytest.raises(ValueError):
            load.set_voltage_level(volts)
        with pytest.raises(LimitError):
            load.validate_source_point(voltage=volts, current=3.0,
                                       sourcing="voltage")
    check("the gate takes the floor less a rounding error", True)
    load.validate_source_point(voltage=0.09999999999999998, current=3.0,
                               sourcing="voltage")


def test_a_current_sweep_back_to_zero_completes(check):
    """-0.026 -> 0 A in 14 points computes its last level as +3.5e-18 A,
    which was refused as a request to source."""
    load, t = build()
    last = -0.026 + (0.0 - -0.026) / 13 * 13
    check("the computed last level is a positive rounding error",
          0 < last < 1e-12, repr(last))

    sourced, _ = sweep(load, "current", -0.026, 0.0, 14)

    check("all 14 points were taken", len(sourced) == 14, len(sourced))
    check("and the last setpoint sent is zero",
          setpoints(t, ":CURR")[-1] == ":CURRent 0A",
          setpoints(t, ":CURR")[-1])


def test_a_real_request_to_source_is_still_refused(check):
    load, _ = build()
    for amps in (1e-6, 0.001, 5.0):
        with pytest.raises(LimitError):
            load.set_current_level(amps)
    check("refused at every size that is not a rounding error", True)


# ---------------------------------------------------------------------
# 2. the regulation report
# ---------------------------------------------------------------------


def levels(start, stop, n):
    return [start + (stop - start) / (n - 1) * k for k in range(n)]


def test_a_locked_up_voltage_sweep_is_reported(check):
    """Room light, 0.15 -> 0.8 V: the cell held at 0.09-0.25 V, 24-30 mA,
    every point, with the setpoint above it."""
    load, _ = build()
    asked = levels(0.15, 0.8, 100)
    volts = [0.09 + 0.0016 * k for k in range(100)]
    amps = [-0.024 - 0.00005 * k for k in range(100)]

    text = load.regulation_report("voltage", asked, volts, amps)

    check("every point is counted", "100 of 100" in text, text)
    check("as held below the setpoint", "BELOW the setpoint" in text, text)
    check("and the remedy is named", "Sweep current" in text, text)


def test_a_fully_on_stretch_is_reported_with_where_to_start(check):
    """Lamp on, 0.1 -> 0.8 V: fully on at 0.478 V / 8.15 A for the first
    53 points, regulating from there to open circuit at 0.7355 V."""
    load, _ = build()
    asked = levels(0.1, 0.8, 100)
    volts, amps = [], []
    for want in asked:
        if want < 0.478:
            volts.append(0.478)
            amps.append(-8.15)
        elif want < 0.7355:
            volts.append(want)
            amps.append(-8.15 * (0.7355 - want) / 0.26)
        else:
            volts.append(0.7355)
            amps.append(0.0)

    text = load.regulation_report("voltage", asked, volts, amps)

    # 54 setpoints lie under 0.478 V; the last of them is 3 mV under,
    # which is within tolerance and counts as followed. The bench run
    # this is modelled on reported the same 53.
    check("the pinned points are counted", "53 of 100" in text, text)
    check("as below what the load can reach", "fully on" in text, text)
    check("with the voltage to start from", "start the sweep at 0.478 V"
          in text, text)
    check("and the points above open circuit are not a complaint",
          "BELOW" not in text and "tripped" not in text, text)


def test_a_sweep_that_was_followed_reports_nothing(check):
    load, _ = build()
    asked = levels(0.5, 0.7, 21)
    text = load.regulation_report(
        "voltage", asked, [v + 0.0003 for v in asked],
        [-8.0 * (0.74 - v) for v in asked])
    check("nothing to say", text == "", text)


def test_an_input_that_is_not_sinking_is_reported(check):
    """Source above the setpoint and no current: off, or tripped."""
    load, _ = build()
    asked = levels(0.3, 0.5, 5) + [0.6]
    volts = [0.3, 0.35, 0.4, 0.45, 0.5, 0.72]
    amps = [-8.0, -8.0, -8.0, -8.0, -8.0, 0.0]
    asked[5] = 0.6
    volts[5] = 0.72
    text = load.regulation_report("voltage", asked, volts, amps)
    check("one point, named as off or tripped",
          "1 of 6" in text and "tripped" in text, text)


def test_a_source_limited_current_sweep_is_reported(check):
    """Room light, 0 -> -5 A in 50 mA steps on a cell good for 24 mA."""
    load, _ = build()
    asked = levels(0.0, -5.0, 100)
    volts = [0.5951] + [0.0] * 99
    amps = [0.0] + [-0.0243] * 99

    text = load.regulation_report("current", asked, volts, amps)

    check("the 99 pinned points are counted", "99 of 100" in text, text)
    check("with the current that did flow", "0.0243 A" in text, text)


def test_a_current_sweep_the_source_could_supply_reports_nothing(check):
    load, _ = build()
    asked = levels(0.0, -8.0, 100)
    # 0.3% short of every level: 24 mA at 8 A, which is more than the
    # 5 mA floor of the tolerance and inside its 1%.
    text = load.regulation_report(
        "current", asked, [0.73 - 0.017 * abs(a) for a in asked],
        [a * 0.997 for a in asked])
    check("nothing to say", text == "", text)


class _Sample:
    label = "2-3"


class _Experiment:
    """Just enough of IVSweepExperiment to call its helpers without Tk."""

    def __init__(self, driver):
        self.app = type("App", (), {"instruments": {"source": driver}})()
        self.lines = []
        self._regulation_messages = []

    def log(self, *parts):
        self.lines.append(" ".join(str(p) for p in parts))


def test_the_iv_sweep_passes_a_sweep_to_the_report_and_keeps_the_note(check):
    load, _ = build()
    exp = _Experiment(load)
    params = {"mode": "voltage", "start": 0.15, "stop": 0.8,
              "sample": _Sample()}
    volts = [0.09 + 0.0016 * k for k in range(100)]
    amps = [-0.024] * 100

    IVSweepExperiment._note_regulation(exp, load, params, "run", 100,
                                       volts, amps)

    check("it is logged as a warning",
          any(line.startswith("WARNING: run:") for line in exp.lines),
          exp.lines)
    check("and kept for the dialog, naming the sample and the run",
          len(exp._regulation_messages) == 1
          and exp._regulation_messages[0].startswith("2-3 run:"),
          exp._regulation_messages)
    check("with the voltage read as a voltage and the current as a current",
          "measured 0.2484 V at 0.024 A" in exp._regulation_messages[0],
          exp._regulation_messages)


def test_a_current_sweep_hands_its_columns_over_the_other_way_round(check):
    """Sourced is the current and measured the voltage, in that mode."""
    load, _ = build()
    exp = _Experiment(load)
    params = {"mode": "current", "start": 0.0, "stop": -5.0,
              "sample": _Sample()}

    IVSweepExperiment._note_regulation(
        exp, load, params, "run", 100, [0.0] + [-0.0243] * 99,
        [0.5951] + [0.0] * 99)

    check("the shortfall is found, at the current that flowed",
          len(exp._regulation_messages) == 1
          and "99 of 100" in exp._regulation_messages[0]
          and "0.0243 A flowed" in exp._regulation_messages[0],
          exp._regulation_messages)


def test_an_instrument_with_no_report_is_not_asked(check):
    exp = _Experiment(None)
    smu = Keithley2401(None)
    IVSweepExperiment._note_regulation(
        exp, smu, {"mode": "voltage", "start": 0.0, "stop": 1.0,
                   "sample": _Sample()}, "run", 3, [0.0, 0.5, 1.0],
        [0.0, 1e-3, 2e-3])
    check("nothing logged, nothing kept",
          exp.lines == [] and exp._regulation_messages == [],
          (exp.lines, exp._regulation_messages))


# ---------------------------------------------------------------------
# 3. the current range follows a current sweep
# ---------------------------------------------------------------------


@pytest.mark.parametrize("span, ceiling", [(0.026, "3A"), (2.9, "3A"),
                                           (8.0, "30A")])
def test_a_current_sweep_picks_its_own_current_range(check, span, ceiling):
    load, t = build()
    load.apply_ranges(RangePlan.for_sourcing(
        "current", source_range=span, measure_range=18.0))
    sent = [c for c in t.sent if c.upper().startswith(":CURRENT:UPP")
            and "?" not in c]
    check(f"a sweep to {span:g} A asks for the {ceiling} range",
          sent == [f":CURRent:UPPer {ceiling}"], sent)


def test_a_voltage_sweep_still_takes_its_current_range_from_the_dropdown(
        check):
    load, t = build()
    load.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=30.0))
    sent = [c for c in t.sent if c.upper().startswith(":CURRENT:UPP")
            and "?" not in c]
    check("30 A, as chosen", sent == [":CURRent:UPPer 30A"], sent)


def test_a_chosen_current_range_is_not_replaced_by_the_span(check):
    """The span fills in for AUTO. It does not overrule a number."""
    load, t = build()
    load.apply_ranges(RangePlan(source_voltage=NOT_SOURCED,
                                source_current=0.026, measure_current=30.0,
                                measure_voltage=18.0))
    sent = [c for c in t.sent if c.upper().startswith(":CURRENT:UPP")
            and "?" not in c]
    check("30 A, as chosen", sent == [":CURRent:UPPer 30A"], sent)


# ---------------------------------------------------------------------
# 4. the per-point delay
# ---------------------------------------------------------------------


def test_the_load_declares_how_long_a_point_takes(check):
    load, _ = build()
    for mode in ("voltage", "current"):
        check(f"{mode}: its measured settling time",
              load.minimum_point_delay(mode)
              == MulticompPro7213200.SETTLING_S == 0.45,
              load.minimum_point_delay(mode))


def test_a_delay_shorter_than_that_is_refused_before_the_run(check):
    load, _ = build()
    exp = _Experiment(load)
    for delay in (0.0, 0.1, 0.44):
        with pytest.raises(ValueError) as refused:
            IVSweepExperiment._check_point_delay(exp, "current", delay)
        check(f"{delay:g} s names the minimum", "0.45 s" in str(
            refused.value), str(refused.value))
    for delay in (0.45, 0.5, 2.0):
        IVSweepExperiment._check_point_delay(exp, "voltage", delay)
    check("0.45 s and above are accepted", True)


def test_an_smu_is_not_held_to_a_delay_it_never_declared(check):
    exp = _Experiment(Keithley2401(None))
    IVSweepExperiment._check_point_delay(exp, "voltage", 0.0)
    check("a zero delay is accepted on an SMU", True)


# ---------------------------------------------------------------------
# 5. the gate does not multiply a level by a range
# ---------------------------------------------------------------------


@pytest.mark.parametrize("amps, volt_range", [(-8.5, 18.0), (-10.0, 18.0),
                                              (-30.0, 18.0), (-8.0, 120.0)])
def test_a_current_sweep_is_not_capped_by_the_voltage_range(check, amps,
                                                           volt_range):
    """150 W / 18 V = 8.33 A was the ceiling, on a cell under 5 W."""
    load, _ = build()
    load.validate_source_point(current=amps, voltage=volt_range,
                               sourcing="current")
    check(f"{amps:g} A on the {volt_range:g} V range is accepted", True)


def test_a_voltage_sweep_is_not_capped_by_the_current_range(check):
    load, _ = build()
    load.validate_source_point(voltage=12.0, current=30.0,
                               sourcing="voltage")
    check("12 V on the 30 A range is accepted", True)


def test_each_value_is_still_held_to_its_own_maximum(check):
    load, _ = build()
    for kwargs in (dict(current=-31.0, voltage=18.0, sourcing="current"),
                   dict(current=-5.0, voltage=121.0, sourcing="current"),
                   dict(voltage=121.0, current=3.0, sourcing="voltage"),
                   dict(voltage=5.0, current=31.0, sourcing="voltage"),
                   dict(current=5.0, voltage=18.0, sourcing="current")):
        with pytest.raises(LimitError):
            load.validate_source_point(**kwargs)
    check("over-range and wrong-sign requests are refused", True)


def test_a_real_operating_point_is_still_held_to_the_power_ceiling(check):
    """With no `sourcing`, both numbers are levels and the product
    means what it says."""
    load, _ = build()
    with pytest.raises(LimitError) as refused:
        load.validate_source_point(current=10.0, voltage=18.0)
    check("180 W is refused against 150 W", "150 W" in str(refused.value),
          str(refused.value))
    load.validate_source_point(current=8.0, voltage=18.0)
