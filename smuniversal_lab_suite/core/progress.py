"""How far through a run is, and roughly how long is left.

Pure arithmetic, no Tk: the progress bar in `core/gui/run_controls.py`
calls these once a second, and the tests call them with numbers.

The estimate is for a person deciding whether to fetch a coffee, not for
scheduling. It is shown to the second and no finer, and it is allowed to
be wrong early in a run.

A run's time comes in two parts
-------------------------------
An experiment describes its run as a `RunEstimate`: a **fixed** part that
does not grow with the readings - start delays, the standby holds of a
periodic run - and a cost **per reading**, the settle delay plus the
reading itself. The two are kept apart because they are corrected
differently once the run is under way.

**The per-reading cost is measured.** `Pace` watches the reading count
tick by tick and works out what a reading actually takes on this
instrument at these settings - integration, bus, autozero, everything
nobody modelled. It ignores the time before the first reading arrives,
which is set-up and the start delay rather than readings, and the gaps
in which none arrive, such as a periodic run's standby. Until a few
readings are in, the experiment's own figure stands in for it.

**The fixed part is counted down** from the experiment's figure, against
the time the run has spent on anything other than readings.

Until 1.0.8 the pace was the whole elapsed time divided by the readings
so far, which charged the set-up and the start delay to the first few
readings and overstated the time left by several times early in a run;
and a sweep's readings only reached the count when it ended, so a
single IV sweep never had a pace at all and ran on its settings
estimate, which left out the reading time entirely. Experiments now
report readings still being taken - `RunContext.in_flight` - so a sweep
is counted point by point.
"""
import math
from collections import deque
from dataclasses import dataclass

#: Readings needed before the pace is trusted over the estimate. Fewer
#: than this and one slow reading dominates.
MIN_READINGS_FOR_PACE = 3

#: How many recent tick-to-tick intervals the pace is averaged over.
#: Recent rather than all, so a run whose pace changes - a later sweep
#: at another range - is followed.
PACE_WINDOW = 30

#: An interval this many times slower than the typical one held a gap
#: in which readings were not being taken, and is left out of the pace.
GAP_FACTOR = 3.0

#: Assumed mains frequency for turning NPLC into seconds. 50 Hz is the
#: longer of the two, so an estimate made on a 60 Hz bench runs slightly
#: long rather than short. The pace correction absorbs the difference.
ESTIMATE_LINE_HZ = 50.0

#: Bus, parsing and host overhead per reading, in seconds. A round
#: number, not a measurement: it is only used until the pace is known.
READING_OVERHEAD_S = 0.05


def seconds_per_reading(nplc=None):
    """Rough wall-clock time for one reading at `nplc` (1 when unknown)."""
    try:
        cycles = float(nplc) if nplc not in (None, "") else 1.0
    except (TypeError, ValueError):
        cycles = 1.0
    return cycles / ESTIMATE_LINE_HZ + READING_OVERHEAD_S


@dataclass(frozen=True)
class RunEstimate:
    """A run's expected duration, in the two parts that behave
    differently. See the module docstring.

    `fixed_s` is time that does not grow with the readings, `per_reading_s`
    what one counted reading is expected to cost - settle delay
    included - and `readings` how many the run counts.
    """
    fixed_s: float = 0.0
    per_reading_s: float = 0.0
    readings: int = 0

    @property
    def total_s(self):
        return self.fixed_s + self.per_reading_s * self.readings


class Pace:
    """Time per reading as it is actually being achieved.

    Fed the reading count once a tick. Each tick in which the count rose
    gives an interval: the time since the count last rose, over the
    readings that arrived in it. The first rise is only a baseline - the
    time before it was set-up and the start delay - and an interval much
    slower than the typical one held a gap, not readings.
    """

    def __init__(self):
        self._last = None
        self._intervals = deque(maxlen=PACE_WINDOW)

    def observe(self, now, done):
        """Note the count `done` at monotonic time `now`."""
        if self._last is None or done < self._last[1]:
            # Nothing to measure from yet, or the count went back - a
            # run's readings are never taken away, so start again.
            self._intervals.clear()
            self._last = None if done <= 0 else (now, done)
            return
        then, before = self._last
        if done > before:
            self._intervals.append((now - then, done - before))
            self._last = (now, done)

    def seconds_per_reading(self):
        """The pace, or None until enough readings have been timed."""
        if sum(n for _, n in self._intervals) < MIN_READINGS_FOR_PACE:
            return None
        rates = sorted(dt / n for dt, n in self._intervals)
        typical = rates[len(rates) // 2]
        kept = [(dt, n) for dt, n in self._intervals
                if dt / n <= typical * GAP_FACTOR]
        readings = sum(n for _, n in kept)
        if readings < MIN_READINGS_FOR_PACE:
            return None
        return sum(dt for dt, _ in kept) / readings


def remaining_seconds(elapsed_s, estimate=None, done=0, expected=None,
                      pace_s=None):
    """Seconds left, or None when there is nothing to go on.

    `estimate` is the experiment's `RunEstimate`, or a plain number of
    seconds for the whole run; `done` and `expected` are readings, and
    `pace_s` the measured seconds per reading when there is one. Never
    negative: a run past its estimate has 0 s left and is finishing, not
    counting up.
    """
    if isinstance(estimate, RunEstimate):
        expected = expected or estimate.readings
        if not expected:
            return max(0.0, estimate.total_s - elapsed_s)
        if done >= expected:
            # The last reading is in: what is left is wrapping up.
            return 0.0
        per = pace_s if pace_s is not None else estimate.per_reading_s
        on_readings = done * per
        fixed_left = max(0.0, estimate.fixed_s
                         - max(0.0, elapsed_s - on_readings))
        return max(0, expected - done) * per + fixed_left

    if expected and done >= expected:
        return 0.0
    if expected and pace_s is not None:
        return max(0, expected - done) * pace_s
    if expected and done >= min(MIN_READINGS_FOR_PACE, expected) and done:
        left = elapsed_s / done * max(expected - done, 0)
    elif estimate is not None:
        left = estimate - elapsed_s
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
