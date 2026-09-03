"""The application's version and build, and the one copy of each allowed.

`core/version.py` holds the number; `pyproject.toml` mirrors it. Two
copies of a fact drift, and this is the check that stops them - the same
argument `tests/test_python_floor.py` makes about `requires-python`, and
for the same reason: a constraint nothing tests is not a constraint.

Why the number is not simply read from packaging metadata is explained
in `core/version.py`. Short form: `importlib.metadata` reads an
installed distribution, and neither a checkout nor a frozen `.exe` is
one, so the lookup fails in both environments this application actually
runs in.

The second half of this file is about `build_id()`, which exists
because the version alone was not enough: `0.1.0` did not move across
every behaviour-changing wave, so every stored file claimed the same
application identity whatever code wrote it.

These tests **inject** the environment rather than reading the ambient
one. A test asserting that a frozen build reports `unknown` is worth
nothing if it passes because this machine happens to have git; the
whole point of the frozen path is that it holds where git is absent,
and the only way to check that is to make it absent. Same argument as
[fault 19](../docs/faults/19-non-discriminating-probe.md).
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import version  # noqa: E402
from core.version import __version__, app_version, build_id  # noqa: E402


@pytest.fixture(autouse=True)
def _forget_the_cached_build():
    """`build_id()` caches, deliberately. Tests must not inherit it.

    Both directions: a test that patched the resolution must not leave
    its answer behind for the next one, and a test that patches must
    not be answered from a value cached before it patched.
    """
    version.reset_build_id_cache()
    yield
    version.reset_build_id_cache()


def test_the_code_and_pyproject_agree_on_the_version():
    """The mirror, checked.

    Bumping a release means editing `core/version.py`; this is what
    tells you that `pyproject.toml` needs the same edit, at the moment
    you make it rather than months later when a stored file's
    `app_version` header sends somebody to the wrong commit.
    """
    data = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = data["project"]["version"]
    assert declared == __version__, (
        f"pyproject.toml says {declared!r} and core/version.py says "
        f"{__version__!r}. They are one fact; change both."
    )


def test_the_version_is_a_version():
    """A shape check, so an empty string or a placeholder cannot ship.

    `app_version()` ends up in the header of every stored file and in
    every operational log line. A blank there is worse than a wrong
    number, because it reads as "this field is not used" rather than as
    a mistake.
    """
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[.\-+].+)?", app_version()), (
        f"{app_version()!r} is not a recognisable version string")


def test_the_helper_and_the_constant_do_not_disagree():
    """Belt and braces, but cheap.

    `app_version()` deliberately stays the bare number: it is what
    `pyproject.toml` mirrors and what the test above compares, and
    welding a commit onto it would break that mirror. The commit has
    its own field, `build_id()`, tested below.
    """
    assert app_version() == __version__


# ------------------------------------------------------------------
# the build identifier
# ------------------------------------------------------------------
SHA = "5e7308eff34a79954ab61fa04b23a8b9ce8f59ce"


def _pin(monkeypatch, sha, dirty=False):
    """Answer `head_commit()` with a fixed result.

    Patched at `core.provenance`, which is where `core.version` imports
    it from - the import happens inside the call rather than at module
    scope, so there is no name bound in `core.version` to patch.
    """
    monkeypatch.setattr("core.provenance.head_commit",
                        lambda root=None: (sha, dirty, []))
    version.reset_build_id_cache()


def _no_git(monkeypatch):
    """Make git unavailable, loudly.

    Not "assume this machine has none" - that is the non-discriminating
    probe. A frozen build must not reach for git at all, and the only
    way to check it does not is to make reaching for it fail.
    """
    def explode(root=None):                    # pragma: no cover - must not run
        raise AssertionError("a frozen build must not consult git")

    monkeypatch.setattr("core.provenance.head_commit", explode)
    monkeypatch.setattr(sys, "frozen", True, raising=False)


def test_a_clean_checkout_stamps_its_commit(check, monkeypatch):
    """`0.1.0+g5e7308eff34a` - the version, and the code behind it.

    Twelve hex characters, the same width `core.provenance` prints in a
    checkup report header, so a stored file and a bench report can be
    compared by eye without counting digits.
    """
    _pin(monkeypatch, SHA)
    check("the version is still the stem",
          build_id().startswith(f"{__version__}+"), build_id())
    check("and the commit is welded on",
          build_id() == f"{__version__}+g5e7308eff34a", build_id())


def test_a_modified_tree_says_so(check, monkeypatch):
    """The flag is not decoration.

    A sha alone would name a commit that does not contain what ran,
    which is the argument `core.provenance.head_commit` already makes
    for bench reports. A file written from a modified tree has to be
    distinguishable from one written from the commit it names, because
    they are not the same code.
    """
    _pin(monkeypatch, SHA, dirty=True)
    check("the suffix is there", build_id().endswith(".dirty"), build_id())
    check("and the commit is still named",
          build_id() == f"{__version__}+g5e7308eff34a.dirty", build_id())
    _pin(monkeypatch, SHA, dirty=False)
    check("a clean tree carries no suffix", ".dirty" not in build_id(),
          build_id())


def test_a_frozen_build_reads_the_baked_in_constant(check, monkeypatch):
    """The shipping case, and the one that must not need git.

    A frozen `.exe` on a bench machine has no repository and may have
    no `git` on PATH at all. It receives the commit at build time; this
    checks the stamp is used, and that the git lookup is not even
    attempted - a frozen executable launched from inside some unrelated
    checkout must not report that checkout's commit as its own.
    """
    _no_git(monkeypatch)
    monkeypatch.setattr(version, "BUILD_COMMIT", SHA)
    version.reset_build_id_cache()
    check("the baked-in commit is what it reports",
          build_id() == f"{__version__}+g5e7308eff34a", build_id())

    monkeypatch.setattr(version, "BUILD_DIRTY", True)
    version.reset_build_id_cache()
    check("and a build made from a modified tree still says so",
          build_id() == f"{__version__}+g5e7308eff34a.dirty", build_id())


def test_a_frozen_build_with_no_stamp_says_unknown(check, monkeypatch):
    """Explicit, not absent, and not a crash.

    An omitted key reads as "this writer did not record builds";
    `0.1.0+unknown` reads as "this writer records builds and could not
    determine one". Those are different facts about the file, and a
    provenance stamp that silently vanishes is the failure this field
    exists to remove.
    """
    _no_git(monkeypatch)
    monkeypatch.setattr(version, "BUILD_COMMIT", "")
    version.reset_build_id_cache()
    check("it says so in words",
          build_id() == f"{__version__}+{version.UNKNOWN_BUILD}", build_id())


def test_a_checkout_with_no_git_says_unknown(check, monkeypatch):
    """`git` missing, or this is not a checkout - a zip download.

    `head_commit` already returns `(None, False, [])` rather than
    raising for both, so this arrives as a value. What is checked here
    is that the value becomes an explicit marker rather than an empty
    field or a `None` rendered into a header as the word "None".
    """
    _pin(monkeypatch, None)
    check("unknown, in words",
          build_id() == f"{__version__}+{version.UNKNOWN_BUILD}", build_id())
    check("and never the word None", "None" not in build_id(), build_id())


def test_the_build_id_is_still_a_recognisable_version(check, monkeypatch):
    """A PEP 440 local version, so the shape check above covers it too.

    It goes into the same header field family as `app_version` and is
    read by the same eyes; a form no version parser accepts would be a
    gratuitous obstacle for whoever writes the reader.
    """
    shape = re.compile(r"\d+\.\d+\.\d+(?:[.\-+].+)?")
    for sha, dirty in ((SHA, False), (SHA, True), (None, False)):
        _pin(monkeypatch, sha, dirty)
        check(f"{build_id()} parses", bool(shape.fullmatch(build_id())),
              build_id())


def test_the_build_id_is_resolved_once(check, monkeypatch):
    """Cached, and the caching is load-bearing rather than an optimisation.

    It is written into every saved file's header and every event log
    line. Two files written by one press of Save must not disagree
    about which code wrote them, and the unwind path of a failing run
    must not be waiting on a `git` subprocess.
    """
    calls = []

    def counted(root=None):
        calls.append(root)
        return (SHA, False, [])

    monkeypatch.setattr("core.provenance.head_commit", counted)
    version.reset_build_id_cache()
    first = build_id()
    for _ in range(20):
        build_id()
    check("git was consulted once", len(calls) == 1, calls)
    check("and the answer never moved", build_id() == first)


def test_the_lookup_asks_about_this_checkout_not_the_working_directory(check,
                                                                      monkeypatch):
    """The application must launch from anywhere.

    A `git rev-parse` with no `cwd` asks about whatever directory the
    operator happened to launch from, which on a bench machine is as
    likely to be some other repository as this one - and it would
    answer, plausibly and wrongly.
    """
    seen = []

    def counted(root=None):
        seen.append(root)
        return (SHA, False, [])

    monkeypatch.setattr("core.provenance.head_commit", counted)
    version.reset_build_id_cache()
    build_id()
    check("a root was passed", seen == [version._ROOT], seen)
    check("and it is this checkout",
          Path(version._ROOT).resolve() == ROOT.resolve(), version._ROOT)


def test_the_committed_tree_carries_no_stamp(check):
    """`BUILD_COMMIT` is empty in the repository, and must stay that way.

    A stamped value committed here would be a constant naming one
    commit while sitting in every commit after it - a wrong answer that
    looks authoritative, which is strictly worse than `unknown`. The
    freeze step writes it into the copy it is about to freeze; nothing
    writes it into the checkout. The procedure is in
    `docs/workflow/packaging.md`.
    """
    source = (ROOT / "core" / "version.py").read_text(encoding="utf-8")
    check("the constant is empty", version.BUILD_COMMIT == "",
          repr(version.BUILD_COMMIT))
    check("not dirty either", version.BUILD_DIRTY is False)
    check("and the file on disk agrees", 'BUILD_COMMIT = ""' in source)
