"""`uv.lock` must not fall behind `pyproject.toml`.

CI runs `uv sync --locked`, which refuses to proceed if the lockfile
does not match the project metadata. That is the right thing for CI to
do, but it means the *first* report of a stale lockfile arrives as a red
build on every platform at once, after a push, with an error that names
neither what changed nor why.

That is exactly how it happened in Wave 7: adding `[build-system]` to
make the project installable changed how uv classifies the project
itself - `source = { virtual = "." }` became `source = { editable = "." }` -
and the lockfile was never regenerated. One line, both CI jobs red, and
nothing locally to suggest anything was wrong.

Why this test exists rather than "remember to run `uv lock`"
------------------------------------------------------------
Because that is a rule someone has to remember, whose omission has no
symptom until later - the shape of fault this project keeps finding, and
keeps replacing with a check.

Deliberately offline. `uv lock --check` would be the complete answer,
but it is a subprocess that may reach the network, and a test suite that
needs an index to pass is one that fails on a bench machine for reasons
having nothing to do with the code. What is compared here instead is
everything a person edits by hand: the project's name, version,
requires-python, its dependency list, and whether it is a buildable
package at all. Resolution details - transitive pins, wheel hashes -
are uv's business and are left to `--locked` in CI.

So this catches the realistic causes: a dependency added or removed, a
version bumped, the Python floor moved, or a build backend introduced.
It does not catch a dependency's *own* requirements changing upstream,
which no local check could.
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _lock():
    return tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))


def _root_package(lock, name):
    for package in lock.get("package", []):
        if package.get("name") == name:
            return package
    return None


def _requirement_name(spec):
    """`pyvisa-py>=0.7` -> `pyvisa-py`, normalised the way uv records it."""
    name = re.split(r"[<>=!~\[; ]", spec, maxsplit=1)[0].strip()
    return name.lower().replace("_", "-").replace(".", "-")


def test_the_lockfile_knows_this_project(check):
    """The root package must be in the lock under the declared name."""
    project = _pyproject()["project"]
    name = project["name"].lower().replace("_", "-")
    entry = _root_package(_lock(), name)
    check(f"{name} has an entry in uv.lock", entry is not None,
          "run `uv lock`")
    if entry is None:
        return
    check("and the versions agree",
          entry.get("version") == project["version"],
          f"uv.lock says {entry.get('version')!r}, pyproject says "
          f"{project['version']!r} - run `uv lock`")


def test_the_lockfile_lists_the_dependencies_pyproject_declares(check):
    """A dependency added or removed without relocking fails here.

    Compared as a set of names rather than of specifiers, because the
    specifier lives in `[package.metadata]` while the resolved
    dependency list is by name - and the names are what change when
    somebody edits `dependencies`.
    """
    project = _pyproject()["project"]
    declared = {_requirement_name(spec) for spec in project["dependencies"]}
    entry = _root_package(_lock(), project["name"].lower().replace("_", "-"))
    if entry is None:
        return
    locked = {d["name"] for d in entry.get("dependencies", [])}

    missing = sorted(declared - locked)
    extra = sorted(locked - declared)
    check("every declared dependency is locked", not missing,
          f"{missing} in pyproject.toml but not uv.lock - run `uv lock`")
    check("and the lock holds nothing extra", not extra,
          f"{extra} in uv.lock but not pyproject.toml - run `uv lock`")


def _resolved_extra(groups, name, seen=None):
    """The distributions an extra installs, following self-references.

    Review A-11 composed extras out of each other - `bench` is
    `smuniversal-lab-suite[minismu,usb]` - so that a package is declared
    in exactly one place. That is the property `test_packaging.py`
    guards, and it is worth keeping: two spellings of the same
    distribution across two extras is the trap that made the original
    `minismu` extra a silent no-op.

    uv.lock records the *flattened* answer, because that is what gets
    installed. So the comparison below has to flatten too, or it would
    read a correct lock as a stale one and send someone to `uv lock` for
    a difference no relock can remove.

    `seen` breaks a cycle rather than recursing forever. A cycle here is
    a pyproject mistake, and the honest behaviour is to return what is
    reachable and let the mismatch be reported.
    """
    seen = set() if seen is None else seen
    if name in seen:
        return set()
    seen.add(name)

    out = set()
    for spec in groups.get(name, []):
        if _requirement_name(spec) == "smuniversal-lab-suite":
            inner = spec[spec.index("[") + 1:spec.index("]")]
            for referenced in inner.split(","):
                out |= _resolved_extra(groups, referenced.strip(), seen)
        else:
            out.add(_requirement_name(spec))
    return out


def test_the_lockfile_lists_optional_dependencies(check):
    """Optional extras are metadata too; CI's --locked checks them."""
    project = _pyproject()["project"]
    groups = project.get("optional-dependencies", {})
    declared_groups = {group: _resolved_extra(groups, group)
                       for group in groups}
    entry = _root_package(_lock(), project["name"].lower().replace("_", "-"))
    if entry is None:
        return
    locked_groups = {
        group: {item["name"] for item in specs}
        for group, specs in entry.get("optional-dependencies", {}).items()
    }
    check("optional dependency groups agree",
          set(locked_groups) == set(declared_groups),
          f"pyproject has {sorted(declared_groups)}, uv.lock has "
          f"{sorted(locked_groups)} - run `uv lock`")
    for group, declared in declared_groups.items():
        locked = locked_groups.get(group, set())
        check(f"optional group {group!r} agrees", locked == declared,
              f"pyproject has {sorted(declared)}, uv.lock has "
              f"{sorted(locked)} - run `uv lock`")


def test_the_lockfile_agrees_about_being_a_buildable_package(check):
    """The exact drift that turned both CI jobs red in Wave 7.

    uv records a project with no build backend as `virtual` - present in
    the tree, not installable. Adding `[build-system]` makes it
    `editable`, and the lockfile has to be regenerated to say so. The
    change is one word in a file nobody opens by hand, and `uv sync`
    without `--locked` papers over it locally.
    """
    pyproject = _pyproject()
    entry = _root_package(
        _lock(), pyproject["project"]["name"].lower().replace("_", "-"))
    if entry is None:
        return

    buildable = "build-system" in pyproject
    source = entry.get("source", {})
    if buildable:
        check("a buildable project is locked as editable",
              "editable" in source,
              f"pyproject declares [build-system] but uv.lock says "
              f"{source} - run `uv lock`")
    else:
        check("a non-buildable project is locked as virtual",
              "virtual" in source,
              f"pyproject has no [build-system] but uv.lock says "
              f"{source} - run `uv lock`")


def test_the_lockfile_agrees_about_the_python_floor(check):
    """`requires-python` is recorded in the lock and pinned by a test.

    `tests/test_python_floor.py` already holds the floor, the CI matrix
    and `.python-version` to each other. The lockfile is the fourth copy
    of that number, and it went unchecked until now.
    """
    declared = _pyproject()["project"].get("requires-python")
    locked = _lock().get("requires-python")
    check("uv.lock records a floor", locked is not None)
    check("and it matches pyproject", locked == declared,
          f"uv.lock says {locked!r}, pyproject says {declared!r} - "
          f"run `uv lock`")
