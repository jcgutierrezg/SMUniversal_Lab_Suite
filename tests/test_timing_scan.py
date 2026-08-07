import sys, os, importlib.util

"""The timing scan.

Built because a two-point fit of a two-parameter model has zero degrees
of freedom: it passes through both points by construction, so it can
neither be wrong nor be checked. That is how the miniSMU's sample rate
was "confirmed" at 18200 S/s and then again at 100000 S/s - the second
may well be right, but the agreement quoted for it was arithmetic, not
evidence.

So what is tested here is that the tool recovers a known slope from
synthetic instruments, and - more importantly - that it says so when the
model does NOT hold.
"""
spec = importlib.util.spec_from_file_location(
    "timing_scan",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "tools", "timing_scan.py"))
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)

from drivers.dummy_smu import DummySMU


def test_fit_recovers_a_known_line(check):
    global xs
    xs = [0.001, 0.01, 0.1, 0.5]
    ys = [0.006 + 2.0 * x for x in xs]
    overhead, slope, residuals = scan.fit_line(xs, ys)
    check("slope is recovered", abs(slope - 2.0) < 1e-9, f"{slope}")
    check("intercept is recovered", abs(overhead - 0.006) < 1e-9, f"{overhead}")
    check("and a perfect line has no residuals",
          max(abs(r) for r in residuals) < 1e-12)

    # One aperture, the 2611A's case.
    ys = [0.0156 + 1.0 * x for x in xs]
    _, slope, _ = scan.fit_line(xs, ys)
    check("one aperture per reading is recovered", abs(slope - 1.0) < 1e-9)


def test_a_curved_response_shows_up_in_the_residuals(check):
    # If the cost is not linear in the aperture, the straight-line fit still
    # returns a slope - and that slope is meaningless. The residuals are the
    # only thing that says so, which is why two points can never help: with
    # two points they are identically zero whatever the truth is.
    ys = [0.006 + 2.0 * x + 8.0 * x * x for x in xs]
    _, slope, residuals = scan.fit_line(xs, ys)
    spread = max(abs(r) for r in residuals)
    check("a quadratic response leaves large residuals",
          spread / max(ys) > 0.05, f"{spread / max(ys):.3f} of full scale")

    # Counting sign changes does NOT find this: a line forced through a
    # curve leaves +,-,-,+ , which has two sign changes, the same as noise.
    # What identifies it is the ends and the middle sitting on opposite
    # sides of the line.
    signs = [1 if r > 0 else -1 for r in residuals]
    changes = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    check("counting sign changes would have missed it",
          changes == 2, f"{changes} sign changes - indistinguishable from noise")
    check("but the ends-versus-middle test finds it",
          scan.curvature(residuals) > 0.5, f"{scan.curvature(residuals):.2f}")

    straight = [0.006 + 2.0 * x for x in xs]
    noisy = [y + n for y, n in zip(straight, (0.0001, -0.0001, 0.0001, -0.0001))]
    _, _, clean_residuals = scan.fit_line(xs, noisy)
    check("and scatter on a straight line does not trip it",
          scan.curvature(clean_residuals) < 0.5,
          f"{scan.curvature(clean_residuals):.2f}")


def test_two_points_cannot_be_checked(check):
    xs2, ys2 = [0.001, 0.5], [0.006, 1.0]
    _, _, residuals2 = scan.fit_line(xs2, ys2)
    check("two points always fit exactly, whatever the data",
          max(abs(r) for r in residuals2) < 1e-12,
          "zero degrees of freedom - the fit cannot be wrong and cannot be "
          "validated, which is the whole reason this tool exists")


def test_scan_points(check):
    class Coarse(DummySMU):
        NPLC_RANGE = (0.01, 10.0)

        @classmethod
        def clamp_nplc(cls, nplc):
            # A deliberately coarse ladder: several requests land on the
            # same achievable value.
            import math as _m
            low, high = cls.NPLC_RANGE
            n = min(max(float(nplc), low), high)
            return low * (2 ** round(_m.log2(n / low)))


    class Fake:
        NPLC_RANGE = Coarse.NPLC_RANGE
        clamp_nplc = Coarse.clamp_nplc


    points = scan.scan_points(Fake(), 8)
    check("duplicates from a coarse ladder are collapsed",
          len(points) == len(set(points)), points)
    check("the span reaches both ends of the range",
          min(points) <= 0.02 and max(points) >= 5.0, points)
    check("and it is spread logarithmically, not linearly",
          points[1] / points[0] > 1.5,
          f"{points[:3]} - linear spacing would crowd every point at the "
          f"slow end where overhead is invisible")


def test_degenerate_timings(check):
    import subprocess
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run(
        [sys.executable, os.path.join(here, "tools", "timing_scan.py"),
         "--address", "demo", "--transport", "demo", "--points", "5"],
        capture_output=True, text=True)
    out = r.stdout + r.stderr
    check("an instrument that answers instantly is reported, not fitted",
          "no integration time here to measure" in out, out[-200:])
    check("and no fit is printed for it",
          "apertures per reading" not in out,
          "fitting a line through microseconds of jitter gives a confident "
          "and meaningless number")


def test_refuses_two_points(check):
    import subprocess
    r = subprocess.run(
        [sys.executable,
         os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "tools", "timing_scan.py"),
         "--address", "demo", "--transport", "demo", "--points", "2"],
        capture_output=True, text=True)
    check("fewer than three points is refused", r.returncode != 0)
    check("with the reason given",
          "exact by construction" in (r.stderr + r.stdout),
          (r.stderr + r.stdout)[-120:])
