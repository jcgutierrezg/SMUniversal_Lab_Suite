"""The maths modules must sum with `math.fsum`, not the built-in.

Why a test that reads source code
---------------------------------
This is unusual and it is deliberate. The behaviour it guards cannot be
observed from the outside on a supported interpreter: on Python 3.14,
`sum()` and `math.fsum()` agree for every realistic input - 500,000
randomised Hall-shaped and wide-dynamic-range cases produced no
divergence at all. So a value-comparing test would pass either way, and
the golden files pass either way too.

What makes the distinction worth keeping is *why* they agree. CPython
3.12 gave the built-in `sum()` Neumaier compensated summation for
floats. That is an **implementation detail of one interpreter**, not a
language guarantee: it is absent below 3.12, is not promised by the
language reference, and nothing obliges another implementation to do it.
`math.fsum` is documented as returning the correctly rounded sum, and
has behaved that way since it was added.

So the change this test guards converted an accident into a contract.
The project already paid for the accident once: `requires-python` said
`>=3.10`, a bench machine installed 3.11 mid-commissioning, and the
exact-comparison goldens went red because the fitted intercept moved in
the last bits.

The floor is now 3.14 and `tests/test_python_floor.py` keeps it honest,
so this is defence in depth. It earns its place because the reversion is
so easy and so invisible: someone adds a mean to `hall_math`, writes
`sum(values) / len(values)` out of habit, every test passes, and the
guarantee is quietly gone.

What is allowed
---------------
* `math.fsum(...)` - the point of the exercise.
* `np.sum(...)` / `.sum()` on arrays - numpy has its own summation,
  unaffected by the CPython change, and mixing strategies inside one
  numpy fit would be worse than either.
* the built-in `sum()` over **integers**, which is exact and where
  `fsum` would wrongly return a float. Mark those with the comment
  `# int-sum` so the exemption is stated rather than inferred - and note
  the marker only applies to lines that visibly count (`sum(1 for ...)`,
  `sum(len(x) ...)`). A mutation pass showed that an unrestricted marker
  lets a float mean be silenced with a five-character edit, so the
  escape hatch is deliberately harder to reach for than the correct
  spelling.

No Tk, no instruments; runs in the fast shared process.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Modules whose arithmetic ends up in saved measurements.
MATHS_MODULES = [
    "experiments/iv_sweep/iv_math.py",
    "experiments/ossila_4pp/fourpp_math.py",
    "experiments/hall/hall_math.py",
    "experiments/vanderpauw/vdp_math.py",
    "experiments/hall/experiment.py",
    "experiments/vanderpauw/experiment.py",
    "experiments/ossila_4pp/experiment.py",
]

#: A bare `sum(` - not `fsum(`, not `np.sum(`, not `.sum(`.
BARE_SUM = re.compile(r"(?<![\w.])sum\s*\(")

#: The shapes an `# int-sum` exemption may take. Counting constructs
#: only: `sum(1 for ...)`, `sum(len(x) for ...)`, `sum(int(...) ...)`.
#:
#: The marker is narrowed on purpose. A bare comment that exempts any
#: line would let a float mean be silenced with a five-character edit,
#: which a mutation pass duly demonstrated - the guard has to be harder
#: to switch off than to obey.
COUNTING_SUM = re.compile(r"(?<![\w.])sum\s*\(\s*(1\s+(for|if)|len\(|int\()")


def _offending_lines(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    out = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue            # prose about sum() is not a call to it
        if BARE_SUM.search(line):
            if "# int-sum" in line and COUNTING_SUM.search(line):
                continue        # stated exemption, and it looks like one
            out.append((number, stripped))
    return out


@pytest.mark.parametrize("module", MATHS_MODULES)
def test_no_bare_sum_in_the_maths(module):
    """A float mean computed with the built-in `sum` depends on an
    interpreter implementation detail. Use `math.fsum`."""
    if not (ROOT / module).exists():
        pytest.skip(f"{module} does not exist in this tree")

    offenders = _offending_lines(module)
    assert not offenders, (
        f"{module} sums floats with the built-in sum():\n" +
        "\n".join(f"  line {n}: {t}" for n, t in offenders) +
        "\n\nUse math.fsum, which is documented to return the correctly "
        "rounded sum on every interpreter. The built-in's accuracy comes "
        "from Neumaier compensation added in CPython 3.12 - an "
        "implementation detail, not a guarantee. If this line sums "
        "integers, where the built-in is exact and fsum would wrongly "
        "return a float, mark it with a `# int-sum` comment.")


def test_the_guard_would_actually_fire():
    """The regex has to distinguish a bare `sum(` from the spellings
    that are fine, or this whole file is decoration.

    Checked directly rather than trusted: a pattern that matched
    nothing, or matched everything, would leave every test above
    passing for the wrong reason.
    """
    assert BARE_SUM.search("x = sum(values) / len(values)")
    assert BARE_SUM.search("total = sum(v for v in xs)")

    assert not BARE_SUM.search("x = math.fsum(values) / n")
    assert not BARE_SUM.search("ss = float(np.sum((y - fitted) ** 2))")
    assert not BARE_SUM.search("total = arr.sum()")
    assert not BARE_SUM.search("from math import fsum")


def test_the_exemption_marker_only_covers_counting():
    """The escape hatch must not be usable on a float mean.

    Mutation-found: with an unrestricted marker, reverting a mean to the
    built-in `sum` and appending `# int-sum` passed every test here. The
    exemption now has to look like a count as well as claim to be one.
    """
    assert COUNTING_SUM.search("n = sum(1 for r in results)  # int-sum")
    assert COUNTING_SUM.search("n = sum(len(g) for g in groups)  # int-sum")

    assert not COUNTING_SUM.search("mean = sum(values) / n  # int-sum"), (
        "a float mean must not be exemptible by comment alone")
    assert not COUNTING_SUM.search("t = sum(v * 2 for v in xs)  # int-sum")


def test_fsum_and_the_builtin_agree_here_but_only_by_luck():
    """Documents the finding that motivated the change.

    They agree on this interpreter, which is exactly why no golden
    moved and no method version was bumped. The reason to prefer fsum
    is that its accuracy is promised and the built-in's is not.
    """
    import math
    values = [1e-3 + v * 1e-12 for v in range(8)]
    assert sum(values) == math.fsum(values), (
        "if this ever fails, the two strategies have diverged on a "
        "supported interpreter, and the golden files and method "
        "versions need revisiting rather than this test relaxing")
