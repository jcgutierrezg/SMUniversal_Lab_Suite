"""What version of this application is running, and which build.

Why this is a module and not `importlib.metadata`
-------------------------------------------------
The obvious spelling is `importlib.metadata.version("smuniversal-lab-suite")`,
and it is wrong here for two reasons that both bite at exactly the
moment the number matters most.

`importlib.metadata` reads an **installed distribution**. This project
is run from a checkout (`uv run python main.py`) and is intended to ship
as a frozen `.exe`; neither is an installed distribution, so the lookup
raises `PackageNotFoundError` in both of the environments that actually
exist. Wave 7e settles the packaging question, and this still holds
afterwards: a frozen executable has no dist-info to read.

So the number lives in the code, which is the thing that is definitely
present at runtime, and `pyproject.toml` mirrors it.

The mirror is the hazard, and `tests/test_version.py` is the answer
-------------------------------------------------------------------
Two copies of a fact drift. The whole documentation rebuild happened
because four files each held their own copy of what the code did.

The lesson from `tests/test_python_floor.py` applies unchanged: a
constraint nothing tests is not a constraint. That test exists because
`requires-python` claimed support for two Python versions nobody ran,
and the claim sat there being false until a bench machine believed it.
A version number is the same shape of claim, and it goes stale the same
silent way - a release tagged 0.2.0 whose event log says 0.1.0 sends
whoever is reading that log to the wrong commit.

So: change it here, and the test tells you to change it there.

Why the version alone was never enough
--------------------------------------
`0.1.0` was set once and has not moved since. Every wave of
behaviour-changing work landed under it, so every stored file produced
by materially different code claims the same application identity -
which defeats the whole purpose of stamping a version into scientific
output. "Which code computed this?" is the question the header exists
to answer, and `app_version` alone answers it to a resolution of
*months*.

`build_id()` closes that. It is the version with the commit welded on::

    0.1.0+g5e7308eff34a          a clean checkout at that commit
    0.1.0+g5e7308eff34a.dirty    the same commit, plus uncommitted changes
    0.1.0+unknown                no way to tell (see below)

The shape is a PEP 440 local version, so the whole string is still a
recognisable version and `tests/test_version.py`'s shape check still
applies to it. The `g` prefix is `git describe`'s, and the twelve hex
characters are the width `core.provenance` already prints in every
checkup report header - one width across the repository rather than two.

The `.dirty` suffix is not decoration. A sha naming a commit that does
not contain what ran is a lie by omission, which is the argument
`core.provenance.head_commit` already makes for bench reports; this is
the same claim about the same tree, so it uses the same function rather
than shelling out to git a second time.

What a commit sha can and cannot promise
----------------------------------------
[Fault 24](../docs/faults/24-derived-from-a-rewritable-date.md) says a
derived claim must not rest on something the delivery pipeline can
rewrite, and a sha is rewritable: a squash-merge replaces it. That rule
governs *generated files that are rebuilt and compared* - the failure
was `main` going red with nothing changed. A stored CSV is not rebuilt
and never compared against a fresh render; it is an append-only record
of what ran at one moment. So the sha is used here for what it is: a
pointer that is exact when the commit still exists, accompanied by a
dirty flag when it describes a tree that never existed anywhere. It is
strictly more than the version alone could say, and it is honest about
the case where it can say nothing.

The frozen build has no git, and must not need it
-------------------------------------------------
A frozen `.exe` on a bench machine has no repository, and possibly no
`git` on PATH at all. Correctness cannot depend on either, so the
commit is *baked in at build time* - `BUILD_COMMIT` below - and the git
lookup is only the fallback for a checkout.

Where the build cannot be determined, the field says `unknown` rather
than being omitted. An absent key reads as "this version of the writer
did not record builds"; `0.1.0+unknown` reads as "this writer records
builds and could not determine one", and they are different facts.

Where it is used
----------------
Every stored file records both `app_version` and `build_id`, and so
does every line of the operational event log. That is the point of
having them at all: a file produced last March needs to say which code
produced it, because "the calculation changed in April" is otherwise
unanswerable from the file.

Calculation-method versions (`core.calculation.METHODS`) are a
different mechanism solving a different problem - which *formula*
produced a number, pinned by `tests/golden/*.json` - and are untouched
by any of this.
"""
from __future__ import annotations

import os
import sys
import threading

#: The checkout this file lives in, which is the tree whose commit the
#: git lookup must ask about. Deliberately not the working directory:
#: review §42's acceptance criterion is that the application launches
#: from an arbitrary one, and a `git rev-parse` run there would report
#: whatever repository the operator happened to be standing in, or
#: nothing at all.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The single source of truth. `pyproject.toml` mirrors this, and
#: `tests/test_version.py` fails if the two disagree.
__version__ = "0.1.0"

#: The commit this build was made from, written by the freeze step.
#:
#: **Empty in the repository, and `tests/test_version.py` enforces
#: that.** A stamped value committed here would be a constant naming
#: one commit while sitting in every commit after it - a wrong answer
#: that looks authoritative, which is worse than no answer. The
#: procedure that fills it in is in `docs/workflow/packaging.md`.
BUILD_COMMIT = ""

#: Whether the tree the frozen build was made from had uncommitted
#: changes. Set alongside `BUILD_COMMIT` by the same step; a release
#: build should never have to set it true.
BUILD_DIRTY = False

#: What the build field says when there is no way to determine a build.
#: Explicit, because an omitted field and an unanswerable one are
#: different facts and must not look the same.
UNKNOWN_BUILD = "unknown"

#: How much of the sha is recorded. The same twelve characters
#: `core.provenance` prints in a checkup report header, so a build id
#: and a report header can be compared by eye without counting digits.
SHA_LENGTH = 12

_lock = threading.Lock()
_build_id = None


def app_version():
    """The running application's version, as a string.

    A function rather than only a constant so that callers do not each
    import the name and pin it at import time.

    Deliberately still the bare number. It is what `pyproject.toml`
    mirrors and what `tests/test_version.py` compares, and welding a
    commit onto it here would break that mirror for no gain - the
    commit has its own field, `build_id()`.
    """
    return __version__


def build_id():
    """The version with the build welded on: `0.1.0+g5e7308eff34a`.

    Resolved once and cached. Three reasons, and the third is the one
    that matters:

    * it is written into every CSV row's header and every event log
      line, and a `git` subprocess per save is not free;
    * the answer cannot change for a running process in the way that
      matters - the code that is loaded was loaded at import;
    * a value that changed mid-session would make two files written by
      one process disagree about which code wrote them, which is
      exactly the confusion this field exists to remove.

    Never raises. A build that cannot be determined is reported as
    `0.1.0+unknown`, not omitted and not guessed.
    """
    global _build_id
    with _lock:
        if _build_id is None:
            _build_id = _resolve_build_id()
        return _build_id


def reset_build_id_cache():
    """Forget the cached build id, so the next call resolves again.

    For tests, and for a build step that stamps `BUILD_COMMIT` into an
    already-imported module. Nothing in the application calls it.
    """
    global _build_id
    with _lock:
        _build_id = None


def _resolve_build_id():
    """`build_id()` without the cache. See that docstring."""
    sha, dirty = build_commit()
    if not sha:
        return f"{__version__}+{UNKNOWN_BUILD}"
    suffix = ".dirty" if dirty else ""
    return f"{__version__}+g{sha[:SHA_LENGTH]}{suffix}"


def build_commit():
    """`(sha, dirty)` for the build that is running, or `(None, False)`.

    Two sources, in this order, and the order is the whole design:

    1. `BUILD_COMMIT`, baked in by the freeze step. A frozen build has
       no repository to ask, so this is the only source it has - and it
       wins even in a checkout, because a value someone deliberately
       stamped is a stronger statement than whatever tree the process
       happens to be standing in.
    2. `core.provenance.head_commit()`, the same function every checkup
       report uses. Skipped entirely under a frozen interpreter: there
       is nothing to find, and a frozen `.exe` launched from inside
       some unrelated checkout would otherwise report that checkout's
       commit as its own.

    `head_commit()` already returns `(None, False, [])` rather than
    raising when git is missing or this is not a checkout, so the
    "no git on PATH" case arrives here as a value, not an exception.
    """
    if BUILD_COMMIT:
        return (BUILD_COMMIT, bool(BUILD_DIRTY))
    if getattr(sys, "frozen", False):
        return (None, False)
    # Imported here rather than at module scope: `core.provenance`
    # imports `subprocess`, and this module is imported by everything
    # that writes a file. The cost belongs to the one call that needs
    # it, not to every import of the version number.
    from core.provenance import head_commit
    sha, dirty, _paths = head_commit(_ROOT)
    return (sha or None, bool(dirty))
