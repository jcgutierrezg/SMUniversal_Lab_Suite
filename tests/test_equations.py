"""The equation tables, against the method table they describe.

The formulas shown in the Equations window live in the experiments' math
modules; the methods they name live in `core.calculation.METHODS`. Two
tables describing one set of facts drift, which is what this stops - the
same job `tests/test_version.py` does for the version number.

No Tk here: mathtext is parsed by matplotlib, so whether a formula is
*valid* can be checked without a window. The window itself is exercised
in `test_tooltips_and_equations_gui.py`.
"""
import io

import pytest
from matplotlib.figure import Figure

from smuniversal_lab_suite.core.calculation import METHODS, Equation
from smuniversal_lab_suite.core.gui.equations import number
from smuniversal_lab_suite.experiments.hall import hall_math
from smuniversal_lab_suite.experiments.iv_sweep import iv_math
from smuniversal_lab_suite.experiments.ossila_4pp import fourpp_math
from smuniversal_lab_suite.experiments.vanderpauw import vdp_math

MODULES = (vdp_math, hall_math, fourpp_math, iv_math)
ALL = [equation for module in MODULES for equation in module.EQUATIONS]


def test_every_method_has_an_equation_and_every_equation_a_method():
    described = [e.method for e in ALL]
    assert set(described) == set(METHODS), (
        f"only in METHODS: {set(METHODS) - set(described)}; "
        f"only in an EQUATIONS table: {set(described) - set(METHODS)}")
    assert len(described) == len(set(described)), "a method is described twice"


@pytest.mark.parametrize("equation", ALL, ids=[e.method for e in ALL])
def test_an_equation_is_typeset_without_a_tex_installation(equation):
    """Mathtext, not LaTeX: the bench machines have no TeX on them.

    A formula that does not parse falls back to its source text in the
    window rather than raising, which is the right behaviour at the
    bench and would hide a typo from everyone here.
    """
    figure = Figure(figsize=(0.01, 0.01))
    figure.text(0, 0, f"${equation.latex}$", fontsize=13)
    figure.savefig(io.BytesIO(), format="png", bbox_inches="tight")


@pytest.mark.parametrize("equation", ALL, ids=[e.method for e in ALL])
def test_an_equation_names_its_symbols(equation):
    assert isinstance(equation, Equation)
    assert equation.title, equation.method
    assert equation.symbols, (
        f"{equation.method} shows a formula with no symbols explained; "
        f"the units are half the answer")
    for symbol, meaning in equation.symbols:
        assert symbol and meaning, equation.method


@pytest.mark.parametrize("value, text", [
    (0.0816, "0.0816"),
    (4533.05, "4533"),
    (0, "0"),
    (1.8e-5, r"1.8\times10^{-5}"),
    (-3.1e12, r"-3.1\times10^{12}"),
    ("not a number", "not a number"),
])
def test_numbers_are_written_as_maths_not_as_python(value, text):
    assert number(value) == text
