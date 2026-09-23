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
    assert remaining_seconds(10.0, estimate_s=60.0) == 50.0
    assert remaining_seconds(10.0, estimate_s=60.0, done=1,
                             expected=100) == 50.0


def test_the_pace_takes_over_once_a_few_readings_are_in():
    done = progress.MIN_READINGS_FOR_PACE
    # 3 readings in 6 s is 2 s each; 7 still to come.
    assert remaining_seconds(6.0, estimate_s=1000.0, done=done,
                             expected=done + 7) == pytest.approx(14.0)


def test_a_run_past_its_estimate_is_finishing_not_counting_up():
    assert remaining_seconds(90.0, estimate_s=60.0) == 0.0
    assert format_remaining(0.0) == "finishing..."


def test_nothing_to_go_on_says_nothing():
    assert remaining_seconds(5.0) is None
    assert format_remaining(None) == ""
    assert fraction_done(5.0, None) is None


def test_a_short_run_trusts_its_pace_before_the_usual_minimum():
    # Two readings expected, both in: the run is done measuring.
    assert remaining_seconds(4.0, estimate_s=100.0, done=2,
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
