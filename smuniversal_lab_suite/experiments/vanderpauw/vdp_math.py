"""
Van der Pauw sheet-resistance solver.

Logic copied verbatim from the original notebook - only relocated to its
own module so it can be unit-tested / reused without dragging in Tkinter.
"""
import math


def solve_vdp_sheet_resistance(Rh, Rv, tol=1e-9, maxiter=200):
    """
    Solve the Van der Pauw equation for sheet resistance Rs:

        exp(-pi*Rh/Rs) + exp(-pi*Rv/Rs) = 1

    given the two measured resistances Rh and Rv (both must be > 0).
    There's no closed-form solution, so this uses Newton-Raphson first
    (fast, usually converges in a handful of iterations), and falls back
    to a bisection search if Newton's method fails to converge or steps
    outside a sane range - bisection is slower but guaranteed to find the
    root once it's bracketed.

    `tol` is the convergence tolerance on the equation residual; `maxiter`
    caps the Newton-Raphson attempts before falling back to bisection.
    Raises RuntimeError if a root can't be bracketed at all (shouldn't
    happen for physically sensible Rh/Rv).
    """
    if Rh <= 0 or Rv <= 0:
        raise ValueError("Rh and Rv must be positive")
    pi = math.pi

    # f(Rs) is the VdP equation rearranged to equal zero at the solution
    def f(Rs):
        return math.exp(-pi * Rh / Rs) + math.exp(-pi * Rv / Rs) - 1.0

    # df(Rs) is f's derivative, needed for Newton-Raphson steps
    def df(Rs):
        e1 = math.exp(-pi * Rh / Rs)
        e2 = math.exp(-pi * Rv / Rs)
        return (pi * Rh / (Rs * Rs)) * e1 + (pi * Rv / (Rs * Rs)) * e2

    Rs = 0.5 * (Rh + Rv)
    if Rs <= 0:
        Rs = max(Rh, Rv)
    try:
        frs = f(Rs)
    except OverflowError:
        frs = float("inf")
    if abs(frs) < tol:
        return Rs

    for _ in range(maxiter):
        try:
            frs = f(Rs)
            if abs(frs) < tol:
                return Rs
            dfrs = df(Rs)
            if dfrs == 0 or not math.isfinite(dfrs):
                break
            delta = frs / dfrs
            Rs_new = Rs - delta
            if Rs_new <= 0 or not math.isfinite(Rs_new):
                break
            if abs(delta) > 0.5 * Rs:
                Rs_new = Rs - 0.5 * delta
            Rs = Rs_new
        except Exception:
            break

    low = min(Rh, Rv) * 1e-6
    high = max(Rh, Rv) * 1e6
    fl = f(low)
    fh = f(high)
    if fl == 0:
        return low
    if fh == 0:
        return high
    if fl * fh > 0:
        found = False
        for factor in [1e-6, 1e-4, 1e-2, 1, 1e2, 1e4, 1e6]:
            test = max(Rh, Rv) * factor
            try:
                fv = f(test)
            except OverflowError:
                fv = float("inf")
            if fv == 0:
                return test
            if fl * fv < 0:
                high = test
                fh = fv
                found = True
                break
            if fv * fh < 0:
                low = test
                fl = fv
                found = True
                break
        if not found:
            raise RuntimeError("Could not bracket root for Van der Pauw solver")

    for _ in range(200):
        mid = 0.5 * (low + high)
        fm = f(mid)
        if abs(fm) < 1e-12 or (high - low) / max(1.0, mid) < tol:
            return mid
        if fl * fm < 0:
            high = mid
            fh = fm
        else:
            low = mid
            fl = fm
    return 0.5 * (low + high)


def resistivity(sheet_resistance, thickness_cm):
    """Bulk resistivity from a sheet resistance and a thickness.

    rho = Rs * t, with Rs in ohms per square and t in centimetres,
    giving ohm-centimetres.

    Moved here from the experiment. It was one line inside
    `VanDerPauwExperiment.calculate_vdp()`:

        rho = rs * (self.thickness_um * 1e-4)   # um -> cm

    which folded a unit conversion and a physical relation into one
    expression, and left `vdp_resistivity` as the only method in
    `core.calculation.METHODS` with no golden file, because there was no
    function for a golden file to call. Both problems go away together.

    The conversion out of SI now lives in
    `VanDerPauwParameters.as_math_thickness_cm()`, so this takes the
    centimetres it needs and does no unit arithmetic of its own. That is
    the same division of labour `fourpp_math.sheet_resistance` has with
    `as_math_geometry()`.

    Identical in form to `hall_math.resistivity()`, and deliberately not
    shared with it. They are two experiments' statements of the same
    relation, and one may need versioning without the other -
    `vdp_resistivity:1` and `hall_resistivity:1` are separate entries in
    METHODS for exactly that reason.
    """
    if thickness_cm <= 0:
        raise ValueError("Thickness must be positive")
    return sheet_resistance * thickness_cm
