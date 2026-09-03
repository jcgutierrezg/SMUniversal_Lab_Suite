"""House rule 13, on the modules where a silent failure costs a result.

Why a test that reads source code
---------------------------------
The same reason `test_no_bare_sum.py` does. The thing being guarded is
not observable from outside: a handler that suppresses correctly and a
handler that suppresses a de-energise are the same shape, run the same
way, and both make the suite green. Only the *reason* separates them,
and a reason that is not written down is not available to the next
person.

Ruff was the obvious tool and cannot do it. `S110` and `S112` flag
`try/except/pass` and `try/except/continue` by shape, which means 74
findings on this tree, of which most are correct cleanup. That gate
would be red from the day it was switched on, and a permanently red
gate is how the next real one gets waved through. So `S110`/`S112` are
in `pyproject.toml`'s ignore list with that reasoning, and this file
does the part a linter cannot: it asks for the invariant, on the files
where getting it wrong costs a measurement rather than a repaint.

What it can and cannot prove
----------------------------
It proves a reason was **written**. It cannot prove the reason is
**true** - no test can. What that buys is that the reason arrives as an
artefact in the diff that introduces the suppression, where a reviewer
can disagree with it, instead of as a silence that nobody can argue
with three years later.

The surface is deliberately partial. 55 of the tree's 62 blind
suppressions had no stated reason when this was written; the drivers,
transports, panels and tools are recorded in
`docs/open/technical-debt.md` as a per-area pass. Adding a file to
`GUARDED` is how that debt is paid, one area at a time.

No Tk, no instruments; runs in the fast shared process.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: The modules a silent failure costs a result on.
#:
#: Chosen by what the file decides, not by how much of it there is:
#: whether the sample is de-energised, whether readings may be kept,
#: whether a claim is released, and what a stored record says about
#: where it came from. Faults 29 and 30 were both on this surface.
GUARDED = [
    "core/run_control.py",          # outcomes, commit gate, shutdown reports
    "core/run_store.py",            # the readings, and what reaches disk
    "core/event_log.py",            # the operational record
    "core/provenance.py",           # what a stored value says it came from
    "core/identity.py",             # the join keys between the two
    "core/calculation.py",          # derived values and their sources
    "core/ownership.py",            # who is allowed to drive an instrument
    "core/version.py",              # the build stamped into every file
    "core/base_app.py",             # connect, disconnect, close
    "core/single_instance.py",      # the lock that stops two of them
    "core/thread_guard.py",         # the affinity violations report
    "core/transports/base.py",      # the desync latch
    "experiments/base_experiment.py",   # run start, cancel, save, delete
    "drivers/base_smu.py",          # the driver contract itself
]

#: How much comment counts as a stated reason.
#:
#: A length rather than a marker word, after weighing both. A required
#: token - the `# int-sum` pattern - works where the exemption is one
#: narrow thing; here the legitimate reasons are genuinely various
#: ("this is the reader", "the record is written elsewhere", "the
#: sample was already put away"), and a token would collapse them into
#: a rubber stamp that says nothing. A length cannot be satisfied by
#: `# ok` or `# fine`, which is the failure mode that actually happens.
MIN_REASON_CHARS = 30


def _blind_handlers(path):
    """Every `except ...:` whose whole body is `pass` or `continue`.

    Read from the AST rather than by regex, because the thing being
    counted is a handler with no body, and "no body" is a fact about
    the parse tree. A regex would miss `except OSError:\\n    pass  #`
    written across a line continuation, and would also match the word
    inside a docstring.
    """
    source = path.read_text(encoding="utf-8")
    lines = source.split("\n")
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = node.body
        if not (len(body) == 1
                and isinstance(body[0], (ast.Pass, ast.Continue))):
            continue
        window = lines[node.lineno - 1:body[0].end_lineno]
        reason = ""
        for line in window:
            _, marker, comment = line.partition("#")
            if marker:
                reason += comment.strip() + " "
        found.append((node.lineno, reason.strip(),
                      lines[node.lineno - 1].strip()))
    return found


@pytest.mark.parametrize("module", GUARDED)
def test_a_suppressed_exception_states_its_invariant(module):
    """House rule 13, on one guarded module."""
    path = ROOT / module
    assert path.exists(), (
        f"{module} is on the guarded surface and does not exist. "
        f"A file renamed out from under this list drops the rule "
        f"silently, which is the one way this test can stop working "
        f"without failing.")

    offenders = [(lineno, text)
                 for lineno, reason, text in _blind_handlers(path)
                 if len(reason) < MIN_REASON_CHARS]

    assert not offenders, (
        f"{module} suppresses an exception without saying why:\n" +
        "\n".join(f"  line {n}: {t}" for n, t in offenders) +
        "\n\nHouse rule 13: a safety, data-preservation or provenance "
        "path does not suppress at all - it returns a value the caller "
        "must branch on, or it raises. A cleanup-only suppression "
        "carries a comment naming the invariant that makes it safe: "
        "what is already recorded, what has already happened, or what "
        "would happen instead. See docs/rules/"
        "13-exceptions-are-not-suppressed-silently.md.")


def test_the_guarded_surface_is_not_empty_and_names_real_modules():
    """A list that quietly emptied itself would pass every test above.

    `parametrize` over an empty list collects nothing and reports
    success, so the surface has to be asserted separately from the rule
    it carries.
    """
    assert len(GUARDED) >= 10, GUARDED
    missing = [m for m in GUARDED if not (ROOT / m).exists()]
    assert not missing, missing


def test_the_detector_finds_a_suppression_and_ignores_a_handled_one(tmp_path):
    """The check has to be able to fail, or the file above is decoration.

    Both directions, because a detector that matched everything would
    also be useless: the second case is a handler that does something,
    which is not a suppression however broad its class.
    """
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def bare():\n"
        "    try:\n"
        "        go()\n"
        "    except Exception:\n"
        "        pass\n"
        "\n"
        "def explained():\n"
        "    try:\n"
        "        go()\n"
        "    except Exception:\n"
        "        # Cleanup only: the record is written elsewhere and\n"
        "        # nothing downstream reads this result.\n"
        "        pass\n"
        "\n"
        "def handled():\n"
        "    try:\n"
        "        go()\n"
        "    except Exception as exc:\n"
        "        report(exc)\n",
        encoding="utf-8", newline="\n")

    found = _blind_handlers(sample)
    assert len(found) == 2, (
        f"expected the two suppressions and not the handled one, got "
        f"{found}")

    unexplained = [n for n, reason, _ in found
                   if len(reason) < MIN_REASON_CHARS]
    assert unexplained == [4], (
        f"only the undocumented handler should be reported, got "
        f"{unexplained}")


def test_a_short_comment_does_not_count_as_a_reason(tmp_path):
    """The threshold is the whole difference between this test and a
    box-ticking exercise. `# ok` must not satisfy it."""
    sample = tmp_path / "short.py"
    sample.write_text(
        "def f():\n"
        "    try:\n"
        "        go()\n"
        "    except Exception:\n"
        "        pass  # ok\n",
        encoding="utf-8", newline="\n")

    (lineno, reason, _), = _blind_handlers(sample)
    assert lineno == 4
    assert len(reason) < MIN_REASON_CHARS, reason
