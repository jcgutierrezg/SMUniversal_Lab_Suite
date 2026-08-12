"""The declared Python floor must be one CI actually tests.

Why this file exists
--------------------
`pyproject.toml` said `requires-python = ">=3.10"` for most of this
project's life. It was not true. CPython 3.12 changed the built-in
`sum()` to use Neumaier compensated summation for floats, and
`experiments/iv_sweep/iv_math.py` sums with it - so on 3.11 the fitted
intercept comes out last-bit different and `tests/golden/iv_linear_fit.json`,
which compares exactly, goes red.

Nobody noticed because the CI matrix only ever ran 3.12 and 3.14. The
declaration claimed two versions that were never tested, and the first
machine outside CI took the claim at its word, installed 3.11, and hit
it. A bench machine, mid-commissioning.

The general shape is worth more than the specific bug: **a constraint
that nothing tests is a guess written in a config file.** These tests
make the guess into a claim CI has to back up.

What is checked
---------------
1. The floor equals the lowest version in the CI matrix - so the oldest
   supported interpreter is one that actually gets run.
2. `.python-version`, which is what `uv` installs on developer and bench
   machines, is a version the matrix covers - so the interpreter people
   actually use is not untested territory.

Both parse the real files rather than restating their contents, because
a copy of a version number in a test rots exactly as quietly as the
mismatch it is meant to catch.

No Tk, no instruments; runs in the fast shared process.
"""
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
PYTHON_VERSION_FILE = ROOT / ".python-version"


def _version(text):
    """'3.12' -> (3, 12). Tolerates a patch component."""
    parts = [int(p) for p in str(text).strip().strip('"\'').split(".")[:2]]
    return tuple(parts)


def _declared_floor():
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    spec = data["project"]["requires-python"]
    match = re.search(r">=\s*([\d.]+)", spec)
    assert match, (
        f"requires-python is {spec!r}, which has no '>=' floor this test "
        f"can read. If the form has changed deliberately, update this "
        f"parser rather than deleting the check.")
    return _version(match.group(1))


def _ci_matrix_versions():
    """The `python:` list from the test workflow's matrix.

    Parsed with a regex rather than a YAML library on purpose: the
    project has no YAML dependency, and adding one so a guard test can
    run would be a poor trade.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^\s*python:\s*\[(.+?)\]\s*$", text, re.MULTILINE)
    assert match, (
        "could not find a `python: [...]` matrix line in "
        f"{WORKFLOW.name}. If the matrix has been restructured, this "
        "parser needs updating - do not just delete the test, because "
        "the drift it catches put a bench machine on an untested "
        "interpreter.")
    found = [_version(v) for v in match.group(1).split(",")]
    assert found, "the CI matrix lists no Python versions"
    return sorted(found)


def test_the_floor_is_a_version_ci_actually_runs():
    """The oldest version the project claims to support must be one the
    matrix runs.

    A floor below the lowest tested version is an untested promise, and
    this is precisely how a bench machine ended up on 3.11.
    """
    floor = _declared_floor()
    tested = _ci_matrix_versions()
    lowest = tested[0]

    assert floor == lowest, (
        f"pyproject declares >={floor[0]}.{floor[1]} but the lowest "
        f"version CI runs is {lowest[0]}.{lowest[1]}. "
        f"Either add {floor[0]}.{floor[1]} to the CI matrix, or raise "
        f"requires-python to {lowest[0]}.{lowest[1]} - but do not leave "
        f"a supported version that nothing tests.")


def test_the_pinned_interpreter_is_one_ci_covers():
    """`.python-version` decides what `uv` installs on real machines.

    If that version is outside the matrix, every developer and bench
    machine is running an interpreter CI has never exercised - the same
    gap as above, pointed the other way.
    """
    if not PYTHON_VERSION_FILE.exists():
        pytest.skip(".python-version is not used in this project")

    pinned = _version(PYTHON_VERSION_FILE.read_text(encoding="utf-8"))
    tested = _ci_matrix_versions()

    assert pinned in tested, (
        f".python-version pins {pinned[0]}.{pinned[1]}, which the CI "
        f"matrix does not run (it runs "
        f"{', '.join(f'{a}.{b}' for a, b in tested)}). Every machine "
        f"using this repo would be on an interpreter nothing tests.")


def test_the_pinned_interpreter_satisfies_the_floor():
    """A pin below the declared floor would be self-contradictory, and
    `uv` would refuse to sync with an error that names neither file."""
    if not PYTHON_VERSION_FILE.exists():
        pytest.skip(".python-version is not used in this project")

    pinned = _version(PYTHON_VERSION_FILE.read_text(encoding="utf-8"))
    floor = _declared_floor()
    assert pinned >= floor, (
        f".python-version pins {pinned[0]}.{pinned[1]} but "
        f"requires-python demands >={floor[0]}.{floor[1]}")


def test_the_floor_is_at_least_where_sum_changed():
    """3.12 is a hard lower bound regardless of what the fleet runs.

    It is where CPython's built-in `sum()` began using Neumaier
    compensated summation for floats. The maths modules now use
    `math.fsum()`, which is exactly rounded and stable across versions,
    so this is defence in depth rather than the only protection - but
    `sum()` is one careless edit away from reappearing in a mean, and
    below 3.12 that edit would move results on some machines and not
    others.

    Separate from the matrix checks above on purpose: those keep the
    files consistent with each other, and this one says a floor below
    3.12 is wrong even if all three agree on it.
    """
    assert _declared_floor() >= (3, 12), (
        "the floor has been lowered below 3.12, where the float "
        "behaviour of the built-in sum() changed. The maths modules use "
        "math.fsum() and should be unaffected, but tests/golden/*.json "
        "compare exactly and any stray sum() in a mean would move on "
        "older interpreters.")
