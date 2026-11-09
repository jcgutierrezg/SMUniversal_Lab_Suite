"""The post-run compliance check, on synthetic data.

Each case is a shape a real run takes. The ones that must *not* be
flagged matter as much as the ones that must: a warning that fires on
every Van der Pauw block or every open circuit is a warning nobody reads.
"""
from smuniversal_lab_suite.core import clamping
from smuniversal_lab_suite.core.clamping import detect_clamping


def _sweep(n=21, span=1.0):
    return [-span + 2 * span * i / (n - 1) for i in range(n)]


def test_an_ohmic_sweep_inside_its_limit_is_clean():
    volts = _sweep()
    amps = [v / 1000.0 for v in volts]
    report = detect_clamping(volts, amps, limit=0.01)
    assert not report.suspected
    assert report.describe("A") == ""


def test_a_sweep_pinned_at_its_compliance_is_flagged_at_both_ends():
    limit = 5e-4
    volts = _sweep()
    amps = [max(-limit, min(limit, v / 1000.0)) for v in volts]
    report = detect_clamping(volts, amps, limit=limit)
    assert report.suspected
    assert report.at_limit == 12        # |V| >= 0.5 V at 1 kΩ
    assert "12 of 21 readings at the 0.0005 A compliance limit" \
        in report.describe("A")


def test_readings_just_under_the_limit_still_count():
    limit = 0.3
    under = limit * clamping.LIMIT_FRACTION
    report = detect_clamping([1e-4, 2e-4], [under, limit * 0.5],
                             limit=limit)
    assert report.at_limit == 1


def test_a_plateau_below_the_typed_limit_is_flagged():
    """A clamp at a level nobody typed - a range ceiling, say."""
    volts = _sweep()
    ceiling = 2e-4
    amps = [max(-ceiling, min(ceiling, v / 1000.0)) for v in volts]
    report = detect_clamping(volts, amps, limit=0.1)
    assert report.at_limit == 0
    assert report.plateau >= 2 * clamping.PLATEAU_MIN_POINTS
    assert "flat while the setpoint changed" in report.describe("A")


def test_repeated_setpoints_are_meant_to_agree():
    """A block that reads one level N times is meant to agree."""
    setpoints = [1e-4] * 10 + [-1e-4] * 10
    volts = [0.1] * 10 + [-0.1] * 10
    assert not detect_clamping(setpoints, volts, limit=0.3).suspected


def test_an_open_circuit_reading_noise_is_not_a_clamp():
    volts = _sweep()
    noise = [(-1) ** i * (1 + i % 3) * 1e-12 for i in range(len(volts))]
    assert not detect_clamping(volts, noise, limit=0.01).suspected


def test_no_compliance_to_apply_leaves_only_the_plateau_rule():
    """An electronic load records a sentence, not a limit."""
    volts = _sweep()
    amps = [v / 1000.0 for v in volts]
    note = "none - this instrument has no compliance"
    report = detect_clamping(volts, amps, limit=note)
    assert report.limit is None
    assert not report.suspected


def test_blanks_are_skipped_and_the_instrument_flag_counts():
    report = detect_clamping([1, 2, 3], ["", None, 0.1], limit=1.0,
                             instrument_flag=True)
    assert report.total == 1
    assert report.suspected
    assert report.describe() == "the instrument reported compliance"


# Run 21 of the 2026-11-09 Hall bench session (PosD+, 10 uA on a
# 17.7 Ohm/sq film), the last twenty points as the meter reported them:
# a sweep whose voltage barely moves, at three digits of resolution.
FLAT_SWEEP_SETPOINTS = [5.19e-6 + 2.53e-7 * i for i in range(20)]
FLAT_SWEEP_VOLTS = [-2.16e-05, -2.16e-05, -2.16e-05, -2.17e-05, -2.18e-05,
                    -2.17e-05, -2.18e-05, -2.22e-05, -2.23e-05, -2.22e-05,
                    -2.28e-05, -2.31e-05, -2.33e-05, -2.38e-05, -2.33e-05,
                    -2.31e-05, -2.33e-05, -2.4e-05, -2.41e-05, -2.39e-05]


def test_a_flat_low_resistance_sweep_trips_the_plateau_rule():
    """Why Van der Pauw and Hall turn the rule off: on this shape it
    reads meter resolution as a clamp."""
    report = detect_clamping(FLAT_SWEEP_SETPOINTS, FLAT_SWEEP_VOLTS,
                             limit=0.3)
    assert report.at_limit == 0
    assert report.plateau > 0


def test_with_the_plateau_rule_off_a_flat_sweep_is_clean():
    report = detect_clamping(FLAT_SWEEP_SETPOINTS, FLAT_SWEEP_VOLTS,
                             limit=0.3, plateau=False)
    assert not report.suspected


def test_with_the_plateau_rule_off_an_open_contact_is_still_flagged():
    """Run 23 of the same session: an open contact pins every reading
    at the compliance. The at-limit rule alone catches it."""
    setpoints = _sweep(n=80, span=1e-5)
    report = detect_clamping(setpoints, [0.3] * 80, limit=0.3,
                             plateau=False)
    assert report.suspected
    assert report.at_limit == 80
    assert report.plateau == 0


def test_with_the_plateau_rule_off_a_range_ceiling_goes_unflagged():
    """The cost, stated: a clamp below the typed limit is no longer
    seen. Accepted for Van der Pauw and Hall, whose limit is always
    applied and whose sweeps are small."""
    volts = _sweep()
    ceiling = 2e-4
    amps = [max(-ceiling, min(ceiling, v / 1000.0)) for v in volts]
    assert not detect_clamping(volts, amps, limit=0.1,
                               plateau=False).suspected
