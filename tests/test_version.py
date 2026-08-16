"""The application's version, and the one copy of it that is allowed.

`core/version.py` holds the number; `pyproject.toml` mirrors it. Two
copies of a fact drift, and this is the check that stops them - the same
argument `tests/test_python_floor.py` makes about `requires-python`, and
for the same reason: a constraint nothing tests is not a constraint.

Why the number is not simply read from packaging metadata is explained
in `core/version.py`. Short form: `importlib.metadata` reads an
installed distribution, and neither a checkout nor a frozen `.exe` is
one, so the lookup fails in both environments this application actually
runs in.
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.version import __version__, app_version  # noqa: E402


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

    `app_version()` exists so a future frozen build can stamp a git
    description in one place. If that ever stops returning the constant,
    it should be a deliberate change with this test updated, not a
    divergence nobody noticed.
    """
    assert app_version() == __version__
