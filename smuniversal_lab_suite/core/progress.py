"""How far through a run is, and roughly how long is left.

Pure arithmetic, no Tk: the progress bar in `core/gui/run_controls.py`
calls these once a second, and the tests call them with numbers.

The estimate is for a person deciding whether to fetch a coffee, not for
scheduling. It is shown to the second and no finer, and it is allowed to
be wrong early in a run.

Two sources, in order of preference
-----------------------------------
**The pace so far.** Once a few readings have arrived, the time per
reading actually achieved is the best predictor of the rest: it already
contains the instrument's real integration time, the bus, the settle
delays and whatever else nobody modelled. Remaining time is that pace
times the readings still to come.

**The experiment's own estimate** from its settings, used until the pace
is available and for runs that cannot report one - a sweep that runs on
the instrument hands its readings back in one batch at the end, and a
Fixed source run has no expected count at all.
"""
import math

#: Readings needed before the pace is trusted over the estimate. Fewer
#: than this and a settle delay at the start dominates the average.
MIN_READINGS_FOR_PACE = 3

#: Assumed mains frequency for turning NPLC into seconds. 50 Hz is the
#: longer of the two, so an estimate made on a 60 Hz bench runs slightly
#: long rather than short. The pace correction absorbs the difference.
ESTIMATE_LINE_HZ = 50.0

#: Bus, parsing and host overhead per reading, in seconds. A round
#: number, not a measurement; see the module docstring.
READING_OVERHEAD_S = 0.05


def seconds_per_reading(nplc=None):
    """Rough wall-clock time for one reading at `nplc` (1 when unknown)."""
    try:
        cycles = float(nplc) if nplc not in (None, "") else 1.0
    except (TypeError, ValueError):
        cycles = 1.0
    return cycles / ESTIMATE_LINE_HZ + READING_OVERHEAD_S


def remaining_seconds(elapsed_s, estimate_s=None, done=0, expected=None):
    """Seconds left, or None when there is nothing to go on.

    `estimate_s` is the experiment's total for the whole run; `done` and
    `expected` are readings. Never negative: a run past its estimate has
    0 s left and is finishing, not counting up.
    """
    if expected and done >= min(MIN_READINGS_FOR_PACE, expected) and done:
        left = elapsed_s / done * max(expected - done, 0)
    elif estimate_s is not None:
        left = estimate_s - elapsed_s
    else:
        return None
    return max(0.0, left)


def fraction_done(elapsed_s, remaining_s):
    """0..1 for the bar: time spent over time spent plus time left."""
    if remaining_s is None:
        return None
    total = elapsed_s + remaining_s
    if total <= 0:
        return 0.0
    return min(1.0, max(0.0, elapsed_s / total))


def format_remaining(seconds):
    """`about 1 min 05 s left`, to the second and no finer.

    Rounded up, so the last second reads `about 1 s left` rather than
    `0 s`; zero itself means the work is done and the run is wrapping
    up.
    """
    if seconds is None:
        return ""
    whole = math.ceil(seconds)
    if whole <= 0:
        return "finishing..."
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"about {hours} h {minutes:02d} min {secs:02d} s left"
    if minutes:
        return f"about {minutes} min {secs:02d} s left"
    return f"about {secs} s left"
