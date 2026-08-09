"""Which function each registered method is, and what to feed it.

Separate from `test_calculation_golden.py` on purpose: the expected
*values* live in `tests/golden/*.json` and are written by
`tools/make_goldens.py`. Keeping the inputs here and the outputs there
means no single edit can move both, which is the only reason a golden
file is worth anything.

Cases were chosen to sit where the functions change behaviour, not in
the comfortable middle - below and above each correction table, at the
Van der Pauw symmetric case where Newton converges instantly and at a
lopsided one where it may not, and at a perfectly ohmic fit alongside a
noisy one.
"""
import math

from core.calculation import METHODS
from experiments.hall import hall_math
from experiments.iv_sweep import iv_math
from experiments.ossila_4pp import fourpp_math
from experiments.vanderpauw import vdp_math


def _fourpp(args):
    out = fourpp_math.sheet_resistance(
        args["resistance_ohm"], args["width_mm"], args["length_mm"],
        args["thickness_um"])
    # The numbers are the contract. The wording of a note is not - a
    # reworded warning must not turn the Windows job red - but whether
    # a note fires at all is behaviour, so the count is kept.
    return {
        "sheet_resistance_ohm_sq": out["sheet_resistance_ohm_sq"],
        "resistivity_ohm_m": out["resistivity_ohm_m"],
        "conductivity_S_per_m": out["conductivity_S_per_m"],
        "thickness_factor": out["thickness_factor"],
        "geometry_factor": out["geometry_factor"],
        "notes_count": len(out["notes"]),
    }


def _vdp(args):
    return {"sheet_resistance_ohm_sq":
            vdp_math.solve_vdp_sheet_resistance(args["Rh"], args["Rv"])}


def _hall_voltage(args):
    return {"hall_voltage_V": hall_math.hall_voltage(**args)}


def _sheet_density(args):
    return {"sheet_density_cm2": hall_math.sheet_carrier_density(
        args["current_a"], args["field_t"], args["hall_voltage_v"])}


def _mobility(args):
    return {"mobility_cm2_Vs": hall_math.hall_mobility(
        args["sheet_density_cm2"], args["sheet_resistance"])}


def _bulk_density(args):
    return {"bulk_density_cm3": hall_math.bulk_carrier_density(
        args["sheet_density_cm2"], args["thickness_cm"])}


def _hall_resistivity(args):
    return {"resistivity_ohm_cm": hall_math.resistivity(
        args["sheet_resistance"], args["thickness_cm"])}


def _iv_fit(args):
    slope, intercept, r_squared = iv_math.linear_fit(args["x"], args["y"])
    return {"slope": slope, "intercept": intercept, "r_squared": r_squared}


#: method -> the callable, its cases, and the comparison tolerance.
#:
#: Tolerance is 0 - exact, bit for bit - everywhere the arithmetic is
#: pure `math`, which is every method here except one. The 4PP chain
#: goes through `scipy`'s CubicSpline and griddata, and pinning a
#: SciPy interpolation to the last bit across four CI cells would
#: produce red jobs that say nothing about this code. 1e-12 relative is
#: far tighter than any physical claim the number supports and still
#: survives a SciPy point release.
CASES = {
    "fourpp_sheet_resistance": {
        "fn": _fourpp,
        "tolerance": 1e-12,
        "cases": [
            {"name": "the original notebook's worked example",
             "args": {"resistance_ohm": 100.0, "width_mm": 10.0,
                      "length_mm": 27.0, "thickness_um": 180.0}},
            {"name": "thin sample, thickness correction inactive",
             "args": {"resistance_ohm": 1500.0, "width_mm": 10.0,
                      "length_mm": 27.0, "thickness_um": 50.0}},
            {"name": "thick sample, above the thickness table",
             "args": {"resistance_ohm": 100.0, "width_mm": 10.0,
                      "length_mm": 27.0, "thickness_um": 4000.0}},
            {"name": "inside the thickness table",
             "args": {"resistance_ohm": 250.0, "width_mm": 10.0,
                      "length_mm": 27.0, "thickness_um": 1000.0}},
            {"name": "narrow sample, low W/s",
             "args": {"resistance_ohm": 100.0, "width_mm": 2.0,
                      "length_mm": 8.0, "thickness_um": 180.0}},
            {"name": "square sample, L/W = 1",
             "args": {"resistance_ohm": 100.0, "width_mm": 20.0,
                      "length_mm": 20.0, "thickness_um": 180.0}},
            {"name": "wide sample, off the top of the geometry table",
             "args": {"resistance_ohm": 100.0, "width_mm": 80.0,
                      "length_mm": 200.0, "thickness_um": 180.0}},
        ],
    },
    "vdp_sheet_resistance": {
        "fn": _vdp,
        "tolerance": 0.0,
        "cases": [
            {"name": "symmetric, Rh = Rv", "args": {"Rh": 1000.0, "Rv": 1000.0}},
            {"name": "mildly anisotropic", "args": {"Rh": 1000.0, "Rv": 1400.0}},
            {"name": "strongly anisotropic", "args": {"Rh": 10.0, "Rv": 900.0}},
            {"name": "low resistance film", "args": {"Rh": 0.05, "Rv": 0.06}},
            {"name": "high resistance film", "args": {"Rh": 4.7e6, "Rv": 5.1e6}},
        ],
    },
    "hall_voltage": {
        "fn": _hall_voltage,
        "tolerance": 0.0,
        "cases": [
            {"name": "clean eight-term average",
             "args": {"v13p": 1.0e-3, "v31p": -1.0e-3, "v24p": 1.1e-3,
                      "v42p": -1.1e-3, "v13n": -0.9e-3, "v31n": 0.9e-3,
                      "v24n": -1.0e-3, "v42n": 1.0e-3}},
            {"name": "with a large common offset that must cancel",
             "args": {"v13p": 5.1e-3, "v31p": 5.0e-3, "v24p": 5.2e-3,
                      "v42p": 4.9e-3, "v13n": 5.0e-3, "v31n": 5.1e-3,
                      "v24n": 4.9e-3, "v42n": 5.2e-3}},
            {"name": "n-type sign",
             "args": {"v13p": -2.0e-4, "v31p": 2.0e-4, "v24p": -2.0e-4,
                      "v42p": 2.0e-4, "v13n": 2.0e-4, "v31n": -2.0e-4,
                      "v24n": 2.0e-4, "v42n": -2.0e-4}},
        ],
    },
    "hall_sheet_carrier_density": {
        "fn": _sheet_density,
        "tolerance": 0.0,
        "cases": [
            {"name": "1 mA, 0.5 T, 1 mV",
             "args": {"current_a": 1e-3, "field_t": 0.5,
                      "hall_voltage_v": 1e-3}},
            {"name": "negative Hall voltage",
             "args": {"current_a": 1e-3, "field_t": 0.5,
                      "hall_voltage_v": -1e-3}},
            {"name": "small signal",
             "args": {"current_a": 1e-5, "field_t": 0.3,
                      "hall_voltage_v": 2.5e-6}},
        ],
    },
    "hall_mobility": {
        "fn": _mobility,
        "tolerance": 0.0,
        "cases": [
            {"name": "typical film",
             "args": {"sheet_density_cm2": 3.1e12,
                      "sheet_resistance": 4532.36}},
            {"name": "degenerate film",
             "args": {"sheet_density_cm2": 8.0e14, "sheet_resistance": 12.5}},
        ],
    },
    "hall_bulk_carrier_density": {
        "fn": _bulk_density,
        "tolerance": 0.0,
        "cases": [
            {"name": "180 um sample",
             "args": {"sheet_density_cm2": 3.1e12, "thickness_cm": 0.018}},
            {"name": "thin film",
             "args": {"sheet_density_cm2": 3.1e12, "thickness_cm": 1e-5}},
        ],
    },
    "hall_resistivity": {
        "fn": _hall_resistivity,
        "tolerance": 0.0,
        "cases": [
            {"name": "4532 ohm/sq at 180 um",
             "args": {"sheet_resistance": 4532.36, "thickness_cm": 0.018}},
            {"name": "low sheet resistance",
             "args": {"sheet_resistance": 12.5, "thickness_cm": 1e-5}},
        ],
    },
    "iv_linear_fit": {
        "fn": _iv_fit,
        "tolerance": 0.0,
        "cases": [
            {"name": "perfectly ohmic, R = 1000",
             "args": {"x": [-0.2, -0.1, 0.0, 0.1, 0.2],
                      "y": [-2e-4, -1e-4, 0.0, 1e-4, 2e-4]}},
            {"name": "with an offset current",
             "args": {"x": [-0.2, -0.1, 0.0, 0.1, 0.2],
                      "y": [-1.9e-4, -0.9e-4, 1e-5, 1.1e-4, 2.1e-4]}},
            {"name": "noisy, R^2 below 1",
             "args": {"x": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
                      "y": [1e-6, 1.05e-4, 1.9e-4, 3.2e-4, 3.9e-4, 5.1e-4]}},
        ],
    },
}

#: Registered methods with no golden file, and why.
#:
#: Listed rather than left out, so the gap is a statement instead of an
#: oversight. `test_calculation_golden.py` fails if a method is missing
#: from both this set and `CASES`.
NOT_YET_COVERED = {
    "vdp_resistivity":
        "computed inline in experiments/vanderpauw/experiment.py rather "
        "than in vdp_math; Wave 5 moves it into the maths module, and it "
        "gets a golden file when it lands there.",
}


def evaluate(method, args):
    """Run `method` on `args` and return the comparable output dict."""
    return CASES[method]["fn"](args)


def uncovered():
    """Registered methods with neither a case list nor a written excuse."""
    return sorted(set(METHODS) - set(CASES) - set(NOT_YET_COVERED))
