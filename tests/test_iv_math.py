"""
IV sweep arithmetic, checked against cases with known answers.

The fit itself is three lines of algebra, so the risk isn't that the
regression is wrong - it's that the *resistance* is taken from the wrong
side of it. Sourcing volts and measuring amps gives a slope of 1/R;
sourcing amps and measuring volts gives a slope of R. Confusing the two
produces a number that looks entirely reasonable and is wrong by a
factor of R squared, with nothing in the output to hint at it.

So the mode-dependent conversion gets its own test, on a sample whose
resistance is known exactly.
"""
import sys
from experiments.iv_sweep.iv_math import (linear_fit, resistance_from_fit,
                                          fit_sweep)

R_SAMPLE = 2500.0        # ohm
TOLERANCE = 1e-9


def check(name, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"   {detail}" if detail else ""))
    return [] if condition else [name]


def _collect_perfect_line():
    """A noiseless line must come back exactly, with R² = 1."""
    xs = [i * 0.1 for i in range(-10, 11)]
    ys = [3.0 * x + 1.5 for x in xs]
    slope, intercept, r_squared = linear_fit(xs, ys)

    bad = []
    bad += check("slope recovered", abs(slope - 3.0) < 1e-9, f"{slope:.12g}")
    bad += check("intercept recovered", abs(intercept - 1.5) < 1e-9,
                 f"{intercept:.12g}")
    bad += check("R² is 1", abs(r_squared - 1.0) < 1e-12, f"{r_squared:.12g}")
    return bad


def _collect_voltage_mode_resistance():
    """Source V, measure I: slope is 1/R, so R must come back as R."""
    xs = [-1.0 + i * 0.05 for i in range(41)]          # volts
    ys = [x / R_SAMPLE for x in xs]                    # amps, I = V/R
    slope, _, _ = linear_fit(xs, ys)
    resistance = resistance_from_fit(slope, "voltage")

    return check("voltage mode -> R", abs(resistance - R_SAMPLE) < 1e-6,
                 f"{resistance:.10g} Ω (expected {R_SAMPLE:g})")


def _collect_current_mode_resistance():
    """Source I, measure V: slope IS R."""
    xs = [-1e-3 + i * 5e-5 for i in range(41)]         # amps
    ys = [x * R_SAMPLE for x in xs]                    # volts, V = I*R
    slope, _, _ = linear_fit(xs, ys)
    resistance = resistance_from_fit(slope, "current")

    return check("current mode -> R", abs(resistance - R_SAMPLE) < 1e-6,
                 f"{resistance:.10g} Ω (expected {R_SAMPLE:g})")


def _collect_modes_are_not_interchangeable():
    """The guard the whole module exists for: feeding a voltage-mode
    sweep through the current-mode conversion must NOT quietly return
    the right answer."""
    xs = [-1.0 + i * 0.05 for i in range(41)]
    ys = [x / R_SAMPLE for x in xs]
    slope, _, _ = linear_fit(xs, ys)

    wrong = resistance_from_fit(slope, "current")
    return check("wrong mode gives wrong answer",
                 abs(wrong - R_SAMPLE) > 1.0,
                 f"{wrong:.6g} Ω vs {R_SAMPLE:g} Ω")


def _collect_noisy_fit_is_close():
    """With 1% scatter the fit should still land within a fraction of a
    percent - the whole reason for fitting instead of taking V/I at one
    point."""
    import random
    random.seed(20260731)
    xs = [-1.0 + i * 0.02 for i in range(101)]
    ys = [(x / R_SAMPLE) * (1 + random.gauss(0, 0.01)) for x in xs]
    slope, _, r_squared = linear_fit(xs, ys)
    resistance = resistance_from_fit(slope, "voltage")
    error = abs(resistance - R_SAMPLE) / R_SAMPLE

    bad = check("noisy fit within 0.5%", error < 0.005,
                f"{resistance:.6g} Ω, error {error*100:.3f}%")
    bad += check("noisy R² still high", r_squared > 0.99,
                 f"{r_squared:.6f}")
    return bad


def _collect_degenerate_inputs():
    """Bad data must be reported, not guessed at."""
    bad = []

    try:
        linear_fit([1.0], [1.0])
        bad += check("single point rejected", False)
    except ValueError:
        bad += check("single point rejected", True)

    try:
        linear_fit([1.0, 1.0, 1.0], [1.0, 2.0, 3.0])
        bad += check("vertical line rejected", False)
    except ValueError:
        bad += check("vertical line rejected", True)

    try:
        linear_fit([1.0, 2.0], [1.0])
        bad += check("length mismatch rejected", False)
    except ValueError:
        bad += check("length mismatch rejected", True)

    # fit_sweep swallows all of the above and reports "no fit", so a bad
    # sweep in a long periodic run doesn't take the run down with it
    result = fit_sweep([1.0], [1.0], "voltage")
    bad += check("fit_sweep degrades gracefully", result == (None, None, None, None),
                 str(result))

    # an open circuit: every current reading zero -> zero slope -> no R
    slope, _, _, resistance = fit_sweep([0.0, 1.0, 2.0], [0.0, 0.0, 0.0],
                                        "voltage")
    bad += check("zero slope gives no resistance", resistance is None,
                 f"slope={slope}, R={resistance}")
    return bad


def _collect_precision_not_rounded():
    """The original rounded stored resistance to 3 decimal places, which
    zeroes anything below a milliohm. Check a low-resistance sample
    survives."""
    tiny = 4e-4      # 0.4 mohm contact
    xs = [-1e-3 + i * 5e-5 for i in range(41)]
    ys = [x * tiny for x in xs]
    slope, _, _ = linear_fit(xs, ys)
    resistance = resistance_from_fit(slope, "current")

    return check("sub-milliohm resistance preserved",
                 abs(resistance - tiny) / tiny < 1e-6,
                 f"{resistance:.10g} Ω (original would store 0.0)")


if __name__ == "__main__":
    bad = []
    for test in (_collect_perfect_line,
                 _collect_voltage_mode_resistance,
                 _collect_current_mode_resistance,
                 _collect_modes_are_not_interchangeable,
                 _collect_noisy_fit_is_close,
                 _collect_degenerate_inputs,
                 _collect_precision_not_rounded):
        print(f"\n{test.__name__}:")
        bad += test()

    print(f"\n{'PASS' if not bad else f'{len(bad)} FAILURE(S): ' + ', '.join(bad)}")
    sys.exit(1 if bad else 0)


# --- Wave 0a: these used to return a list of failures that only the
# --- __main__ block inspected. Under pytest a returned value is
# --- ignored, so without these wrappers all of them would pass
# --- unconditionally. The collectors above are unchanged.

def test_perfect_line():
    bad = _collect_perfect_line()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_voltage_mode_resistance():
    bad = _collect_voltage_mode_resistance()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_current_mode_resistance():
    bad = _collect_current_mode_resistance()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_modes_are_not_interchangeable():
    bad = _collect_modes_are_not_interchangeable()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_noisy_fit_is_close():
    bad = _collect_noisy_fit_is_close()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_degenerate_inputs():
    bad = _collect_degenerate_inputs()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_precision_not_rounded():
    bad = _collect_precision_not_rounded()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"
