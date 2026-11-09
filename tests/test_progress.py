"""The time-left arithmetic behind every tab's progress bar.

Pure numbers, no Tk. The bar itself is exercised in
`test_clamp_and_progress_gui.py`.
"""
import pytest

from smuniversal_lab_suite.core import progress
from smuniversal_lab_suite.core.progress import (
    format_remaining,
    fraction_done,
    remaining_seconds,
    seconds_per_reading,
)


def test_the_estimate_is_used_until_readings_arrive():
    assert remaining_seconds(10.0, estimate=60.0) == 50.0
    assert remaining_seconds(10.0, estimate=60.0, done=1,
                             expected=100) == 50.0


def test_the_pace_takes_over_once_a_few_readings_are_in():
    done = progress.MIN_READINGS_FOR_PACE
    # 3 readings in 6 s is 2 s each; 7 still to come.
    assert remaining_seconds(6.0, estimate=1000.0, done=done,
                             expected=done + 7) == pytest.approx(14.0)


def test_a_run_past_its_estimate_is_finishing_not_counting_up():
    assert remaining_seconds(90.0, estimate=60.0) == 0.0
    assert format_remaining(0.0) == "finishing..."


def test_nothing_to_go_on_says_nothing():
    assert remaining_seconds(5.0) is None
    assert format_remaining(None) == ""
    assert fraction_done(5.0, None) is None


def test_a_short_run_trusts_its_pace_before_the_usual_minimum():
    # Two readings expected, both in: the run is done measuring.
    assert remaining_seconds(4.0, estimate=100.0, done=2,
                             expected=2) == 0.0


@pytest.mark.parametrize("seconds, text", [
    (0.2, "about 1 s left"),
    (42.0, "about 42 s left"),
    (41.01, "about 42 s left"),
    (65.0, "about 1 min 05 s left"),
    (3725.0, "about 1 h 02 min 05 s left"),
])
def test_the_display_is_to_the_second(seconds, text):
    assert format_remaining(seconds) == text


def test_the_bar_fraction_is_time_spent_over_the_whole():
    assert fraction_done(30.0, 90.0) == pytest.approx(0.25)
    assert fraction_done(0.0, 0.0) == 0.0


def test_a_reading_costs_its_integration_time_plus_overhead():
    assert seconds_per_reading(10) == pytest.approx(
        10 / progress.ESTIMATE_LINE_HZ + progress.READING_OVERHEAD_S)
    assert seconds_per_reading(None) == seconds_per_reading(1)
    assert seconds_per_reading("") == seconds_per_reading(1)


# ---------------------------------------------------------------
# The measured pace, and an estimate in two parts
# ---------------------------------------------------------------

def _simulate(setup_s, per_reading_s, readings, estimate, gaps=(),
              until=None):
    """Tick once a second through a run, as the bar does, and yield
    (t, shown, truth) - the time left shown and the time really left.

    Readings start after `setup_s` and come every `per_reading_s`;
    `gaps` is a list of (after_reading, seconds) pauses, such as a
    periodic run's standby.
    """
    times = []
    t = setup_s
    for n in range(1, readings + 1):
        t += per_reading_s
        times.append(t)
        for after, seconds in gaps:
            if after == n:
                t += seconds
    end = times[-1]
    pace = progress.Pace()
    tick = 1.0
    while tick < (until or end):
        done = sum(1 for x in times if x <= tick)
        pace.observe(tick, done)
        shown = remaining_seconds(tick, estimate, done, readings,
                                  pace.seconds_per_reading())
        yield tick, shown, end - tick
        tick += 1.0


def test_the_wait_before_the_first_reading_is_not_charged_to_it():
    """The old pace divided all the elapsed time by the readings so far,
    so the set-up and the start delay made the first readings look
    slow: 5 s before a 0.234 s reading said 1.4 s each, and the time
    left read six times too long."""
    pace = progress.Pace()
    pace.observe(1.0, 0)
    pace.observe(6.0, 4)        # set-up, start delay, then four readings
    pace.observe(7.0, 8)
    pace.observe(8.0, 12)
    assert pace.seconds_per_reading() == pytest.approx(0.25)


def test_a_gap_with_no_readings_is_not_charged_to_them():
    pace = progress.Pace()
    pace.observe(0.0, 1)
    for k in range(1, 10):
        pace.observe(float(k), 1 + 5 * k)       # 0.2 s each
    pace.observe(70.0, 50)                      # a 60 s standby, then 4
    assert pace.seconds_per_reading() == pytest.approx(0.2)


def test_the_pace_is_not_rounded_to_whole_readings_per_tick():
    """0.234 s readings land 4 or 5 to a one-second tick. A median of
    the ticks would say 0.2 or 0.25; the sum says 0.234."""
    times = [0.234 * n for n in range(1, 200)]
    pace = progress.Pace()
    for tick in range(0, 40):
        pace.observe(float(tick), sum(1 for x in times if x <= tick))
    assert pace.seconds_per_reading() == pytest.approx(0.234, rel=0.03)


def test_a_single_sweep_is_close_from_its_first_few_points():
    """100 points at 0.2 s on an instrument whose reading costs 34 ms -
    the settings guess 50 ms - after 3 s of set-up and a 2 s start
    delay. Once the pace is in, within a second or 8% of the truth -
    the first measured interval holds a whole number of readings to a
    one-second tick, which is where the 8% goes."""
    estimate = progress.RunEstimate(
        fixed_s=2.0, per_reading_s=0.2 + progress.seconds_per_reading(0.01),
        readings=100)
    for t, shown, truth in _simulate(5.0, 0.234, 100, estimate):
        if t >= 7.0:
            assert shown == pytest.approx(truth, abs=max(1.0, 0.08 * truth)),                 (t, shown, truth)


def test_a_periodic_standby_is_counted_down_not_lost():
    """Two sweeps of 50 points with a 30 s standby between them: during
    the standby the time left keeps falling by a second a second, and
    still includes the second sweep."""
    estimate = progress.RunEstimate(
        fixed_s=30.0, per_reading_s=0.25, readings=100)
    seen = {round(t): (shown, truth) for t, shown, truth in _simulate(
        1.0, 0.25, 100, estimate, gaps=[(50, 30.0)])}
    for t in (20, 30, 40):              # inside the standby
        shown, truth = seen[t]
        assert shown == pytest.approx(truth, abs=2.0), (t, shown, truth)


def test_the_settings_figure_stands_until_the_pace_is_known():
    estimate = progress.RunEstimate(fixed_s=2.0, per_reading_s=0.5,
                                    readings=10)
    assert remaining_seconds(0.0, estimate) == pytest.approx(7.0)
    assert remaining_seconds(1.0, estimate) == pytest.approx(6.0)
    assert estimate.total_s == pytest.approx(7.0)
    # The last reading is in: wrapping up, whatever the figures say.
    assert remaining_seconds(1.0, estimate, done=10) == 0.0
