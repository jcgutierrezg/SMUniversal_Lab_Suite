"""Did the instrument spend part of a run clamped at a limit?

Post-processing on the data a run already collected, so it works on
every instrument, including the ones that cannot report a compliance
flag. A clamped run is still a tidy run: a sweep that ran into its limit
fits a convincing straight line, and a Van der Pauw block pinned at VLIM
averages to a perfectly plausible resistance. Neither says so.

Two rules, and a reading flagged by either counts once
------------------------------------------------------
**At the limit.** |measured| is at least `LIMIT_FRACTION` of the
compliance that was applied, at either polarity. Not 100 %: instruments
regulate slightly under the setting and read back a hair below it.

**Plateau.** `PLATEAU_MIN_POINTS` or more consecutive readings whose
*setpoints differ* but whose measured values agree to within
`PLATEAU_SPREAD` of their size, sitting at `PLATEAU_EXTREME_FRACTION` or
more of the largest |measured| in the run. That is a clamp at a level
nobody typed - a range ceiling, or a compliance the instrument quietly
reduced. The two guards keep it honest:

* setpoints must change, so Van der Pauw and Hall - which repeat one
  level N times and are *meant* to read the same value - never trip it;
* the plateau must be at the extreme of the run, so an open circuit
  reading noise near zero does not either.

Tuning
------
The four constants below are starting values chosen before bench use,
agreed on 2026-09-17. This is the one place to change them; the
experiments and the tests read them from here.
"""
import math
from dataclasses import dataclass

#: Fraction of the applied compliance at which a reading counts as
#: clamped.
LIMIT_FRACTION = 0.98

#: Shortest run of consecutive, differently-set readings that counts as
#: a plateau.
PLATEAU_MIN_POINTS = 3

#: Largest spread, relative to the plateau's own size, that still counts
#: as "the same value".
PLATEAU_SPREAD = 0.005

#: How close to the run's largest |measured| a plateau must sit.
PLATEAU_EXTREME_FRACTION = 0.90


@dataclass(frozen=True)
class ClampReport:
    """What `detect_clamping` found in one run."""

    flagged: int = 0          # readings flagged by either rule
    total: int = 0            # readings examined
    at_limit: int = 0
    plateau: int = 0
    instrument_flag: bool = False
    limit: float | None = None

    @property
    def suspected(self):
        return bool(self.flagged or self.instrument_flag)

    def describe(self, unit=""):
        """One sentence for the warning dialog, or "" when clean."""
        if not self.suspected:
            return ""
        parts = []
        if self.at_limit:
            limit = f" {self.limit:g} {unit}".rstrip() if self.limit else ""
            parts.append(f"{self.at_limit} of {self.total} readings at the"
                         f"{limit} compliance limit")
        if self.plateau:
            parts.append(f"{self.plateau} of {self.total} readings flat "
                         f"while the setpoint changed")
        if self.instrument_flag and not parts:
            parts.append("the instrument reported compliance")
        return "; ".join(parts)


def _number(value):
    return value if isinstance(value, (int, float)) \
        and not isinstance(value, bool) else None


def detect_clamping(setpoints, measured, limit=None, instrument_flag=False):
    """Check one run's readings. Returns a `ClampReport`.

    `setpoints` and `measured` are parallel sequences in reading order;
    blanks (None, "") are skipped. `limit` is the compliance applied, or
    None when there was none to apply - an electronic load, say - in
    which case only the plateau rule runs. `instrument_flag` is the
    instrument's own compliance flag where it has one.
    """
    pairs = [(_number(s), _number(m)) for s, m in zip(setpoints, measured)]
    pairs = [(s, m) for s, m in pairs if m is not None]
    total = len(pairs)
    limit = _number(limit)
    if limit is not None and limit <= 0:
        limit = None

    at_limit = set()
    if limit is not None:
        threshold = LIMIT_FRACTION * limit
        at_limit = {i for i, (_, m) in enumerate(pairs)
                    if abs(m) >= threshold}

    plateau = set()
    peak = max((abs(m) for _, m in pairs), default=0.0)
    if peak > 0:
        start = 0
        for end in range(1, total + 1):
            if end < total and _extends(pairs, start, end):
                continue
            window = range(start, end)
            if len(window) >= PLATEAU_MIN_POINTS:
                values = [pairs[i][1] for i in window]
                level = math.fsum(abs(v) for v in values) / len(values)
                if level >= PLATEAU_EXTREME_FRACTION * peak:
                    plateau.update(window)
            start = end

    return ClampReport(
        flagged=len(at_limit | plateau),
        total=total,
        at_limit=len(at_limit),
        plateau=len(plateau - at_limit),
        instrument_flag=bool(instrument_flag),
        limit=limit,
    )


def _extends(pairs, start, end):
    """True if reading `end` continues the plateau begun at `start`."""
    setpoint = pairs[end][0]
    previous = pairs[end - 1][0]
    if setpoint is None or previous is None or setpoint == previous:
        return False
    values = [pairs[i][1] for i in range(start, end + 1)]
    size = max(abs(v) for v in values)
    if size == 0:
        return False
    same_sign = all(v > 0 for v in values) or all(v < 0 for v in values)
    return same_sign and (max(values) - min(values)) <= PLATEAU_SPREAD * size
