"""
IV sweep arithmetic: straight-line fit, resistance, R².

Ported from the regression block in IV_Meas_2611A_-_Development.py. The
maths is unchanged - same np.polyfit, same R² from the residual and
total sums of squares - but it lives here instead of inline in the
measurement routine, so it can be tested against known data without an
instrument or a GUI.

Two things the original did that are preserved deliberately:

  * The fit is measured-against-sourced, in that order. For a voltage
    sweep that is I against V, so the slope is a conductance and the
    resistance is its reciprocal.
  * R² is computed against the mean of the measured values, which is the
    standard coefficient of determination.

One thing that is *not* preserved: the original rounded the stored
resistance to 3 decimal places and the intercept and R² to 10 before
saving them. Rounding a resistance to 3 dp throws away everything below
a milliohm, which is silently destructive for low-resistance samples -
a 0.0004 Ω contact reads as 0.0. Values are kept full-precision here and
formatted only for display.
"""
import math


def linear_fit(x_values, y_values):
    """Least-squares straight line through (x, y).

    Returns (slope, intercept, r_squared).

    Uses plain sums rather than numpy so that the maths is readable and
    the module has no import cost - it is the same normal equations
    np.polyfit(deg=1) solves.

    Raises ValueError when the points can't define a line: fewer than
    two of them, mismatched lengths, or every x identical (a vertical
    line has no finite slope).
    """
    xs = [float(x) for x in x_values]
    ys = [float(y) for y in y_values]

    if len(xs) != len(ys):
        raise ValueError("x and y must be the same length.")
    n = len(xs)
    if n < 2:
        raise ValueError("Need at least 2 points to fit a line.")

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    if ss_xx == 0:
        raise ValueError("All x values are identical - slope is undefined.")

    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    # R² against the mean of y, matching the original's ss_total /
    # ss_residual formulation.
    ss_total = sum((y - mean_y) ** 2 for y in ys)
    ss_residual = sum((y - (slope * x + intercept)) ** 2
                      for x, y in zip(xs, ys))
    if ss_total == 0:
        # every measured value identical: the line is flat and perfect,
        # which is degenerate but not an error
        r_squared = 1.0 if ss_residual == 0 else 0.0
    else:
        r_squared = 1.0 - (ss_residual / ss_total)

    return slope, intercept, r_squared


def resistance_from_fit(slope, mode):
    """Convert a fitted slope into a resistance in ohms.

    `mode` is the sweep's source function:

        'voltage'  sourced V, measured I  ->  slope is 1/R, so R = 1/slope
        'current'  sourced I, measured V  ->  slope is R directly

    Getting this backwards is the easiest mistake in the whole
    experiment and produces a plausible-looking wrong number, which is
    why it is one named function rather than an inline reciprocal at
    each call site.

    Returns None for a zero slope - an open circuit in voltage mode, a
    short in current mode - rather than raising, because a single bad
    sweep shouldn't abort a periodic run.
    """
    if mode not in ("voltage", "current"):
        raise ValueError(f"Unknown sweep mode: {mode!r}")
    if slope == 0 or not math.isfinite(slope):
        return None
    resistance = (1.0 / slope) if mode == "voltage" else float(slope)
    return resistance if math.isfinite(resistance) else None


def fit_sweep(sourced, measured, mode):
    """Fit one sweep and return (slope, intercept, r_squared, resistance).

    Returns (None, None, None, None) when the data can't be fitted,
    so a caller can record the run without its fit rather than losing
    the raw points.
    """
    try:
        slope, intercept, r_squared = linear_fit(sourced, measured)
    except (ValueError, TypeError):
        return (None, None, None, None)
    return (slope, intercept, r_squared, resistance_from_fit(slope, mode))
