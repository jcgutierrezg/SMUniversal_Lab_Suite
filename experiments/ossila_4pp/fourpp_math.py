"""
Four-point probe arithmetic: raw resistance -> sheet resistance,
resistivity and conductivity.

Three separate things multiply together, and it is worth keeping them
distinct because each fails differently:

    Rs = (pi / ln2) * R * F_thickness(t/s) * F_geometry(W/s, L/W)

`pi/ln2` = 4.53236 is the ideal case: a four-point probe on a sheet that
is infinitely thin and infinitely wide. Real samples are neither, so the
two correction factors pull that ideal back towards reality.

*Thickness* correction: once the sample gets thick compared with the
probe spacing, current spreads in three dimensions instead of two and
the ideal factor overestimates. Interpolated from the standard table,
which runs from t/s = 0.4 (factor 0.9995, i.e. nearly no correction) to
t/s = 2.0 (0.6336, a third off).

*Geometry* correction: the ideal assumes the current spreads outwards
forever. A finite rectangle sends it back off the edges. Depends on both
how wide the sample is relative to the probe spacing (W/s) and how
oblong it is (L/W).

Both tables and the factor are from the original script and are
reproduced unchanged. The differences are in what happens at the edges -
see the notes on each function.
"""
import math

import numpy as np
from scipy.interpolate import CubicSpline, griddata

# Ideal four-point-probe factor, pi/ln(2), for a thin infinite sheet.
IDEAL_FACTOR = 4.53236

# Probe spacing of the Ossila head, in mm. Fixed: the correction tables
# below are indexed by t/s and W/s, so this is not a free parameter that
# happens to have a default - changing it invalidates the tables.
PROBE_SPACING_MM = 1.27

# --- thickness correction, indexed by t/s ---
_T_S = np.array([0.4, 0.5, 0.5555, 0.6250, 0.7143, 0.8333,
                 1.0, 1.1111, 1.25, 1.4286, 1.6666, 2.0])
_T_FACTOR = np.array([0.9995, 0.9974, 0.9948, 0.9898, 0.9798, 0.9600,
                      0.9214, 0.8907, 0.8490, 0.7938, 0.7225, 0.6336])
_THICKNESS_SPLINE = CubicSpline(_T_S, _T_FACTOR)

# --- geometry correction, indexed by (W/s, L/W) ---
_W_S = [1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5, 7.5, 10, 15, 20, 40]
_L_W = [1, 2, 3, 4, 5]

_RECTANGULAR = np.array([
    [np.nan, np.nan, 0.2204, 0.2205, 0.2205],   # W/s = 1
    [np.nan, np.nan, 0.2751, 0.2751, 0.2751],   # 1.25
    [np.nan, 0.3263, 0.3286, 0.3286, 0.3286],   # 1.5
    [np.nan, 0.3794, 0.3803, 0.3803, 0.3803],   # 1.75
    [np.nan, 0.4292, 0.4297, 0.4297, 0.4297],   # 2
    [np.nan, 0.5192, 0.5194, 0.5194, 0.5194],   # 2.5
    [0.5422, 0.5957, 0.5958, 0.5858, 0.5858],   # 3
    [0.6870, 0.7115, 0.7115, 0.7115, 0.7115],   # 4
    [0.7744, 0.7887, 0.7887, 0.7887, 0.7887],   # 5
    [0.8846, 0.8905, 0.8905, 0.8905, 0.8905],   # 7.5
    [0.9313, 0.9345, 0.9345, 0.9345, 0.9345],   # 10
    [0.9682, 0.9696, 0.9696, 0.9696, 0.9696],   # 15
    [0.9822, 0.9830, 0.9830, 0.9830, 0.9830],   # 20
    [0.9955, 0.9957, 0.9957, 0.9957, 0.9957],   # 40
])

_grid_x, _grid_y = np.meshgrid(_W_S, _L_W, indexing="ij")
_GRID_POINTS = np.array([_grid_x.flatten(), _grid_y.flatten()]).T
_VALID = ~np.isnan(_RECTANGULAR.flatten())
_VALID_POINTS = _GRID_POINTS[_VALID]
_VALID_FACTORS = _RECTANGULAR.flatten()[_VALID]


def thickness_correction(thickness_mm, spacing_mm=PROBE_SPACING_MM):
    """Correction factor for a sample of finite thickness.

    Returns (factor, note). `note` is empty when the ratio sits inside
    the table, and otherwise explains what was assumed - the caller logs
    it so the operator sees that an edge case was hit rather than
    silently getting a number.

    Below the table (very thin sample) the factor tends to 1: the ideal
    thin-sheet assumption is already good, so 1.0 is right, not a guess.

    Above it, the original printed a message and left the factor
    *unassigned*, so the next line raised NameError (DEVIATION 8).
    Here the top of the
    table is held instead, and the note says so - the number is
    conservative and flagged rather than absent.
    """
    if thickness_mm <= 0:
        raise ValueError("Thickness must be greater than zero.")

    ratio = thickness_mm / spacing_mm

    if ratio < _T_S[0]:
        return 1.0, ""
    if ratio > _T_S[-1]:
        return float(_T_FACTOR[-1]), (
            f"t/s = {ratio:.3g} is above the correction table's limit of "
            f"{_T_S[-1]:g}; held at {_T_FACTOR[-1]:g}. The sample is thick "
            f"relative to the 1.27 mm probe spacing, so treat the sheet "
            f"resistance as approximate.")
    return float(_THICKNESS_SPLINE(ratio)), ""


def geometry_correction(width_mm, length_mm, spacing_mm=PROBE_SPACING_MM):
    """Correction factor for a finite rectangular sample.

    `width_mm` is the short side W, `length_mm` the long side L, both as
    marked on the diagram in the geometry panel.

    Returns (factor, note), as above.

    Outside the table the original substituted 1.0 silently
    (DEVIATION 9). 1.0 means
    "no correction needed", i.e. an effectively infinite sample - which
    for a sample too *small* to be in the table is precisely backwards,
    and inflates the result. The substitution is kept for continuity but
    the note now says it happened, so it can't pass unnoticed.
    """
    if width_mm <= 0 or length_mm <= 0:
        raise ValueError("Sample dimensions must be greater than zero.")

    w_over_s = width_mm / spacing_mm
    l_over_w = length_mm / width_mm

    factor = griddata(_VALID_POINTS, _VALID_FACTORS,
                      [w_over_s, l_over_w], method="cubic")
    value = float(np.asarray(factor).flatten()[0])

    if math.isnan(value):
        return 1.0, (
            f"W/s = {w_over_s:.3g}, L/W = {l_over_w:.3g} falls outside the "
            f"rectangular correction table; no geometry correction applied. "
            f"If the sample is small relative to the probe spacing the true "
            f"factor is well below 1, so this over-reports sheet resistance.")
    return value, ""


def sheet_resistance(resistance_ohm, width_mm, length_mm, thickness_um,
                     spacing_mm=PROBE_SPACING_MM):
    """Full chain from measured resistance to the derived quantities.

    Returns a dict with the sheet resistance, resistivity, conductivity,
    both correction factors, and any notes.

    Units, stated explicitly because the original's labels disagreed
    with its arithmetic:
        thickness_um  micrometres (as typed)
        Rs            ohms per square
        resistivity   ohm-metres  (SI)
        conductivity  siemens per metre

    The original (DEVIATION 10) computed resistivity as Rs x t with t in *millimetres*,
    giving ohm-millimetres, and labelled the result "mOhm/m" - which is
    neither what was computed nor a unit of resistivity. Its conductivity
    was right (the x1000 converts the same ohm-mm figure into S/m).
    Here resistivity is converted to ohm-metres, so conductivity is just
    its reciprocal and the labels match the arithmetic. Anyone comparing
    against old saved files should expect resistivity to differ by 1000x
    and read the unit column.
    """
    thickness_mm = thickness_um / 1000.0

    f_thickness, note_t = thickness_correction(thickness_mm, spacing_mm)
    f_geometry, note_g = geometry_correction(width_mm, length_mm, spacing_mm)

    rs = IDEAL_FACTOR * resistance_ohm * f_thickness * f_geometry

    resistivity = rs * (thickness_mm / 1000.0)          # ohm-metres
    conductivity = (1.0 / resistivity) if resistivity else float("inf")

    return {
        "sheet_resistance_ohm_sq": rs,
        "resistivity_ohm_m": resistivity,
        "conductivity_S_per_m": conductivity,
        "thickness_factor": f_thickness,
        "geometry_factor": f_geometry,
        "notes": [n for n in (note_t, note_g) if n],
    }


def triangular_current_list(start_current, stop_current, points):
    """Build a triangular sweep: 0 -> start -> stop -> 0.

    Reproduces `generate_triangular_sweep_string()` from the original,
    which was written and then never called.

    The shape matters for hysteretic samples: going out and coming back
    to the same current shows whether the material returns to where it
    started. Only the middle leg is the measurement; the outer legs
    bring the sample to the start point and back to zero, so
    `middle_slice()` below picks the measurement out again.

    Returns (levels, middle_start_index, middle_length).
    """
    points = int(points)
    if points < 2:
        raise ValueError("A sweep needs at least 2 points.")
    if start_current >= 0 or stop_current <= 0:
        raise ValueError(
            "A triangular sweep runs from a negative start current to a "
            "positive stop current.")

    extra = points // 2
    down = np.linspace(0.0, start_current, extra + 1, endpoint=False)
    middle = np.linspace(start_current, stop_current, points)
    up = np.linspace(stop_current, 0.0, extra + 1)[1:]

    levels = np.concatenate((down, middle, up))
    return [float(v) for v in levels], len(down), points


def reversal_pattern(current, reversals):
    """Alternate a current's polarity: +I, -I, +I, -I, ...

    This is the thermoelectric-offset cancellation the original set up
    and never wired in. Contact junctions between dissimilar metals
    generate their own small voltage, which adds to every reading
    regardless of the current direction. Reversing the current flips the
    sign of the *real* signal but not of the offset, so the offset
    subtracts out - see `average_reversals()`.

    `reversals` should be even, so that each polarity is measured the
    same number of times; an odd count would leave the average weighted
    towards whichever came first.
    """
    reversals = int(reversals)
    if reversals < 1:
        raise ValueError("Need at least one reading per current.")
    return [((-1) ** i) * current for i in range(reversals)]


def average_reversals(voltages):
    """Collapse a reversal group into one offset-free voltage.

    Readings alternate +I, -I, +I, ... so the even-indexed ones carry
    (signal + offset) and the odd ones (-signal + offset). Half their
    difference is the signal; their mean is the offset, which is
    returned as well because a large one is worth seeing - it usually
    means a warm or poorly seated probe.
    """
    values = [float(v) for v in voltages]
    if not values:
        raise ValueError("No readings to average.")

    positive = values[0::2]
    negative = values[1::2]
    if not negative:
        return values[0], 0.0

    mean_pos = sum(positive) / len(positive)
    mean_neg = sum(negative) / len(negative)
    return (mean_pos - mean_neg) / 2.0, (mean_pos + mean_neg) / 2.0


def fit_resistance(currents, voltages):
    """Straight-line fit of V against I. Returns (slope, intercept, r2).

    Sourcing current and measuring voltage, so the slope *is* the
    resistance - no reciprocal, unlike the voltage-sourced sweeps in the
    IV experiment.
    """
    x = np.asarray(currents, dtype=float)
    y = np.asarray(voltages, dtype=float)
    if len(x) < 2 or len(set(x.tolist())) < 2:
        raise ValueError("Need at least two distinct currents to fit.")

    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    ss_total = float(np.sum((y - np.mean(y)) ** 2))
    ss_residual = float(np.sum((y - fitted) ** 2))
    r_squared = 1.0 - (ss_residual / ss_total) if ss_total else 1.0
    return float(slope), float(intercept), float(r_squared)
