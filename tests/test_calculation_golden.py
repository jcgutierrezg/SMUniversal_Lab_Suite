"""
A historical derived result must stay reproducible after the
calculation code changes. See house rule 10.

What a version constant is worth
--------------------------------
Nothing, on its own. `METHODS` could say every method is at version 1
forever while the formulas underneath drifted, and no test would notice
- which would be worse than having no versions at all, because a stored
`hall_mobility:1` would then be a claim the file cannot back up.

This is what makes the constant load-bearing. Each method has a file of
known inputs and the outputs they produced when that version was
declared. Change a formula and these go red. The response is one of two
things, and both are deliberate acts:

  * it was a mistake         -> revert it, the guard did its job;
  * it was intended          -> bump the version in
                                `core.calculation.METHODS`, run
                                `uv run python tools/make_goldens.py`,
                                and commit the moved numbers *with the
                                formula change* so the diff shows what
                                the correction actually did.

The one thing that must not happen is regenerating the files to make a
red test go green without reading what moved. That converts the guard
into a rubber stamp.

Relationship to the parity tests
--------------------------------
`test_hall_math.py` and `test_iv_math.py` check the maths against the
original notebooks - "is this the right formula". These check it against
its own recent past - "is this still the formula that produced the
numbers in the files on disk". Different questions; a change can pass
either one and fail the other.

No Tk, so this runs in the fast shared process.
"""
import json
import math
from pathlib import Path

import pytest
from golden_cases import CASES, NOT_YET_COVERED, evaluate, uncovered

from core.calculation import METHODS, version_of

GOLDEN = Path(__file__).parent / "golden"


def _load(method):
    return json.loads((GOLDEN / f"{method}.json").read_text(encoding="utf-8"))


def _methods():
    return sorted(CASES)


# --------------------------------------------------------------------
# coverage: no method may quietly go unguarded
# --------------------------------------------------------------------
def test_every_registered_method_is_covered_or_excused():
    """A new entry in METHODS with no golden file and no stated reason
    is an unguarded calculation, and it would be invisible."""
    assert not uncovered(), (
        "these methods are registered but have neither golden cases nor an "
        f"entry in NOT_YET_COVERED: {uncovered()}")


def test_the_excuses_are_still_true():
    """A method listed as not-yet-covered must still be registered.

    Otherwise the excuse outlives the thing it was excusing and the set
    slowly fills with names that mean nothing.
    """
    stale = sorted(set(NOT_YET_COVERED) - set(METHODS))
    assert not stale, f"NOT_YET_COVERED names unregistered methods: {stale}"


def test_a_golden_file_exists_for_every_case_list():
    missing = [m for m in _methods() if not (GOLDEN / f"{m}.json").exists()]
    assert not missing, (
        f"no golden file for {missing} - run "
        f"`uv run python tools/make_goldens.py`")


# --------------------------------------------------------------------
# the guard itself
# --------------------------------------------------------------------
@pytest.mark.parametrize("method", _methods())
def test_golden_file_matches_the_registered_version(method):
    """The file records which version produced its numbers.

    If they disagree, either the version moved without the numbers being
    regenerated, or the numbers were regenerated against a stale table.
    Both leave a stored result claiming a version that never produced it.
    """
    stored = _load(method)["version"]
    assert stored == version_of(method), (
        f"{method}: golden file says v{stored}, METHODS says "
        f"v{version_of(method)}. Regenerate the file if the bump was "
        f"deliberate.")


@pytest.mark.parametrize("method", _methods())
def test_golden_cases_still_reproduce(method, check):
    """Method versioning, executed rather than asserted.

    Comparison is exact wherever the arithmetic is pure `math`. The 4PP
    chain runs through SciPy's CubicSpline and griddata, so it gets a
    1e-12 relative tolerance instead - tighter by orders of magnitude
    than anything the physics supports, and loose enough that a SciPy
    point release on one of the four CI cells does not produce a red job
    that says nothing about this code.
    """
    data = _load(method)
    tolerance = data["tolerance"]

    for case in data["cases"]:
        actual = evaluate(method, case["args"])
        for key, expected in sorted(case["expect"].items()):
            got = actual[key]
            if tolerance == 0.0:
                ok = got == expected
                detail = f"{got!r} != {expected!r}"
            else:
                scale = max(abs(expected), 1e-30)
                ok = math.isclose(got, expected, rel_tol=tolerance,
                                  abs_tol=tolerance * scale)
                detail = f"{got!r} vs {expected!r} (rel tol {tolerance})"
            check(f"{method} / {case['name']} / {key}", ok, detail)


@pytest.mark.parametrize("method", _methods())
def test_golden_cases_are_not_all_the_same_shape(method):
    """A golden file of one comfortable mid-range case guards nothing.

    Two or more, and the inputs must actually differ - a copy-pasted
    case list would otherwise pass this and still cover a single point.
    """
    cases = _load(method)["cases"]
    assert len(cases) >= 2, f"{method}: needs more than one golden case"
    distinct = {json.dumps(c["args"], sort_keys=True) for c in cases}
    assert len(distinct) == len(cases), f"{method}: duplicate golden cases"
