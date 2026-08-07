"""
Hall arithmetic, checked two independent ways.

1. Against a reference implementation transcribed verbatim from
   Hall_v4.ipynb. The port must be bit-identical to the original across
   randomised inputs - the same standard the Van der Pauw solver was held
   to. A refactor that quietly changes a number is the failure this
   catches.

2. Against a constructed case with a known answer: eight voltages built
   from a known Hall voltage buried under a resistive offset a thousand
   times larger. Recovering the carrier density proves the offset
   cancellation, the unit conversions, and the mobility relation in one
   number.
"""
import sys
import math
import random

from experiments.hall import hall_math

Q_E = 1.602176634e-19


# ---- reference: copied straight out of the original notebook ----
def ref_vh(v13p, v31p, v24p, v42p, v13n, v31n, v24n, v42n):
    return (v13p - v13n - v31p + v31n + v24p - v24n - v42p + v42n) / 8.0


def ref_ns_cm2(I, B, VH):
    return (I * B) * 1e-4 / (Q_E * VH)


def ref_mu(ns_cm2, Rs):
    return 1.0 / (Q_E * ns_cm2 * Rs)


def ref_thickness_cm(thickness_um):
    return float(thickness_um) * 1e-4


def ref_rho(Rs, thickness_cm):
    return Rs * thickness_cm


def ref_ns_cm3(ns_cm2, thickness_cm):
    return ns_cm2 / thickness_cm


# ---- 1. bit-identical to the original ----
def _collect_matches_original():
    """Randomised comparison against the transcribed reference."""
    rng = random.Random(20260729)     # fixed seed: reproducible failures
    bad = []

    for _ in range(2000):
        voltages = [rng.uniform(-0.05, 0.05) for _ in range(8)]
        current = rng.choice([1e-6, 1e-5, 1e-4, 1e-3, 47e-6])
        field = rng.uniform(0.05, 2.0)
        sheet_r = rng.uniform(1.0, 1e6)
        thickness_um = rng.uniform(0.01, 500.0)

        vh_ref = ref_vh(*voltages)
        vh_got = hall_math.hall_voltage(*voltages)
        if vh_got != vh_ref:
            bad.append(("hall_voltage", vh_got, vh_ref))
            continue
        if vh_ref == 0:
            continue

        ns_ref = ref_ns_cm2(current, field, vh_ref)
        ns_got = hall_math.sheet_carrier_density(current, field, vh_ref)
        if ns_got != ns_ref:
            bad.append(("sheet_carrier_density", ns_got, ns_ref))

        mu_ref = ref_mu(ns_ref, sheet_r)
        mu_got = hall_math.hall_mobility(ns_ref, sheet_r)
        if mu_got != mu_ref:
            bad.append(("hall_mobility", mu_got, mu_ref))

        t_ref = ref_thickness_cm(thickness_um)
        t_got = hall_math.um_to_cm(thickness_um)
        if t_got != t_ref:
            bad.append(("um_to_cm", t_got, t_ref))

        rho_ref = ref_rho(sheet_r, t_ref)
        rho_got = hall_math.resistivity(sheet_r, t_ref)
        if rho_got != rho_ref:
            bad.append(("resistivity", rho_got, rho_ref))

        n3_ref = ref_ns_cm3(ns_ref, t_ref)
        n3_got = hall_math.bulk_carrier_density(ns_ref, t_ref)
        if n3_got != n3_ref:
            bad.append(("bulk_carrier_density", n3_got, n3_ref))

    return bad


# ---- 2. analytic round trip ----
def _collect_analytic_roundtrip():
    """Build eight voltages from a known n_s and recover it.

    The eight readings each carry a resistive offset 1000x larger than
    the Hall term. The sign pattern in the eight-term average is what
    removes it; if that pattern is ever mistyped, the recovered density
    is wrong by orders of magnitude and this fails loudly.
    """
    bad = []

    ns_true_cm2 = 1e13                  # cm^-2
    ns_true_m2 = ns_true_cm2 * 1e4      # m^-2
    current = 100e-6                    # A
    field = 0.82                        # T

    vh_true = current * field / (Q_E * ns_true_m2)
    offset = vh_true * 1000.0           # resistive drop swamping the signal

    # signs chosen so the eight-term average returns exactly vh_true
    v13p = offset + vh_true
    v13n = offset - vh_true
    v31p = offset - vh_true
    v31n = offset + vh_true
    v24p = offset + vh_true
    v24n = offset - vh_true
    v42p = offset - vh_true
    v42n = offset + vh_true

    vh = hall_math.hall_voltage(v13p, v31p, v24p, v42p,
                                v13n, v31n, v24n, v42n)
    if not math.isclose(vh, vh_true, rel_tol=1e-9):
        bad.append(("V_H recovery", vh, vh_true))

    ns = hall_math.sheet_carrier_density(current, field, vh)
    if not math.isclose(ns, ns_true_cm2, rel_tol=1e-9):
        bad.append(("n_s recovery", ns, ns_true_cm2))

    # mobility against its definition, mu = 1/(q*n_s*R_s)
    sheet_r = 250.0
    mu = hall_math.hall_mobility(ns, sheet_r)
    mu_expected = 1.0 / (Q_E * ns_true_cm2 * sheet_r)
    if not math.isclose(mu, mu_expected, rel_tol=1e-9):
        bad.append(("mobility", mu, mu_expected))

    # bulk and thin-film mobility must agree - thickness cancels
    thickness_cm = hall_math.um_to_cm(1.5)
    n_bulk = hall_math.bulk_carrier_density(ns, thickness_cm)
    rho = hall_math.resistivity(sheet_r, thickness_cm)
    mu_bulk = 1.0 / (Q_E * n_bulk * rho)
    if not math.isclose(mu_bulk, mu, rel_tol=1e-9):
        bad.append(("bulk vs sheet mobility", mu_bulk, mu))

    return bad


# ---- 3. offset rejection ----
def _collect_offset_rejection():
    """Any constant added to all eight readings must vanish.

    Thermoelectric and contact offsets are exactly this: a common term
    that survives every reversal. The coefficients sum to zero, so it
    cancels - this asserts that property directly.
    """
    bad = []
    base = [0.031, -0.012, 0.027, -0.009, 0.030, -0.011, 0.026, -0.010]
    reference = hall_math.hall_voltage(*base)

    for offset in (1e-6, 1e-3, 1.0, 100.0):
        shifted = [v + offset for v in base]
        got = hall_math.hall_voltage(*shifted)
        if not math.isclose(got, reference, rel_tol=1e-9, abs_tol=1e-15):
            bad.append((f"offset {offset:g}", got, reference))
    return bad


# ---- 4. failure modes ----
def _collect_error_cases():
    """Zero V_H and non-positive thickness must raise, not return
    nonsense that looks like a measurement."""
    bad = []

    try:
        hall_math.sheet_carrier_density(1e-4, 0.82, 0.0)
        bad.append(("V_H = 0", "no exception", "ZeroDivisionError"))
    except ZeroDivisionError:
        pass

    try:
        hall_math.hall_mobility(0.0, 250.0)
        bad.append(("n_s = 0", "no exception", "ZeroDivisionError"))
    except ZeroDivisionError:
        pass

    for thickness in (0.0, -1.0):
        try:
            hall_math.resistivity(250.0, thickness)
            bad.append((f"thickness {thickness:g}", "no exception", "ValueError"))
        except ValueError:
            pass
        try:
            hall_math.bulk_carrier_density(1e13, thickness)
            bad.append((f"bulk thickness {thickness:g}", "no exception", "ValueError"))
        except ValueError:
            pass

    return bad


TESTS = [
    ("bit-identical to original notebook", _collect_matches_original),
    ("analytic round trip (known n_s)", _collect_analytic_roundtrip),
    ("resistive offset cancels", _collect_offset_rejection),
    ("error cases raise", _collect_error_cases),
]

if __name__ == "__main__":
    failures = 0
    for name, fn in TESTS:
        bad = fn()
        print(f"  {'ok  ' if not bad else 'FAIL'}  {name}")
        for item in bad[:5]:
            print(f"          {item}")
        failures += len(bad)

    # show the worked example, so the numbers are visible not just asserted
    ns_true, I, B = 1e13, 100e-6, 0.82
    vh = I * B / (Q_E * ns_true * 1e4)
    print(f"\n  worked example: n_s = {ns_true:g} cm^-2, I = {I:g} A, B = {B:g} T")
    print(f"                  -> V_H = {vh*1e3:.4f} mV")
    print(f"                  -> recovered n_s = "
          f"{hall_math.sheet_carrier_density(I, B, vh):.6g} cm^-2")

    print(f"\n{'PASS' if not failures else f'{failures} FAILURE(S)'}")
    sys.exit(1 if failures else 0)


# --- Wave 0a: these used to return a list of failures that only the
# --- __main__ block inspected. Under pytest a returned value is
# --- ignored, so without these wrappers all of them would pass
# --- unconditionally. The collectors above are unchanged.

def test_matches_original():
    bad = _collect_matches_original()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_analytic_roundtrip():
    bad = _collect_analytic_roundtrip()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_offset_rejection():
    bad = _collect_offset_rejection()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_error_cases():
    bad = _collect_error_cases()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"
