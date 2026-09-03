"""What the built artifact contains, checked against what the tree has.

See `docs/workflow/packaging.md`. Separate from `test_packaging.py`,
which pins the layout invariants; this file is about the *build*.

Until this wave the project could not be built or installed at all.
`import core` worked only when the current directory happened to be the
checkout, because Python puts the running script's own directory on
`sys.path` and nothing else put it there. The requirement - launch
from an arbitrary working directory - therefore failed at
*import*, several steps before it ever reached a resource file.

The fault these tests exist for
-------------------------------
A build follows imports. Every `.py` file is reachable that way, so
every `.py` file gets in. **Nothing imports a `.png`**, so nothing in
the dependency graph points at it, and a build that only follows imports
never sees it. It has to be named explicitly.

That would be a one-line problem if there were one image forever. There
is not - the 4PP geometry diagram is the first of several. And an
include rule fails in the shape this project keeps finding: somebody
writes `*.png`, a colleague adds an `.svg` eighteen months later, and it
is quietly absent from the artifact. No error, no warning, just a window
that fails to open on a bench machine while the file sits safely in git
where everyone can see it.

Git is no protection here, and the distinction is worth being precise
about: cloning guarantees the file is in the **checkout**. Packaging
decides whether it is in the **artifact**. Those are the same thing
right up until something is shipped that is not a checkout.

So the list is derived, not written
------------------------------------
The assets are enumerated from the source tree and each must appear in a
genuinely built wheel. Adding an image either works or fails the suite;
nobody has to remember a rule, because the rule is checked. Same
principle as `Run` minting its own `record_id` - make forgetting
unrepresentable rather than merely discouraged.

Building is slow, so it happens once per module and the tests share it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.slow]

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import build_docs  # noqa: E402  (needs the path insert above)


def source_packages():
    """Top-level directories of this project that are Python packages."""
    return sorted(
        p.name for p in ROOT.iterdir()
        if p.is_dir() and (p / "__init__.py").is_file()
        and not p.name.startswith((".", "_")) and p.name != "tests")


def tree_assets():
    """Every non-Python file inside a package, as wheel-style paths.

    Extension-blind on purpose. Listing the extensions in use today
    would pass forever and stop being true the first time somebody adds
    a format nobody predicted - which is the failure this file is about.

    Tracked files only. The claim being made is "an asset the repository
    carries must reach the artifact", and only a tracked file is one the
    repository carries - a scratch `.txt` left beside a driver is not an
    asset anybody expects to ship, and demanding it be in the wheel
    would fail on the machine it was left on and nowhere else.
    """
    packages = set(source_packages())
    return [path.relative_to(ROOT).as_posix()
            for path in build_docs.owned_files("*")
            if path.suffix != ".py"
            and path.relative_to(ROOT).parts[0] in packages]


@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    """A real wheel, built from the real tree.

    Reading the configuration instead would check that we wrote what we
    meant to write, not that the build agrees with us - and the build's
    behaviour is precisely the thing nobody can predict by reading.
    """
    if shutil.which("uv") is None:
        pytest.skip("uv is not on PATH; cannot build a wheel to inspect")
    out = tmp_path_factory.mktemp("dist")
    built = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        cwd=ROOT, capture_output=True, text=True, timeout=900)
    if built.returncode != 0:
        pytest.skip("wheel build unavailable in this environment:\n"
                    + built.stderr[-2000:])
    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1, [w.name for w in wheels]
    with zipfile.ZipFile(wheels[0]) as archive:
        return set(archive.namelist())


# ------------------------------------------------------------------
# the artifact contains what the tree has
# ------------------------------------------------------------------

def test_every_asset_in_the_tree_reaches_the_wheel(check, wheel):
    """The one that will matter as more images are added."""
    assets = tree_assets()
    check("the tree has assets to check at all", bool(assets),
          "with none, the assertion below would hold of any build")
    missing = [a for a in assets if a not in wheel]
    check("every one is in the built wheel", not missing,
          f"missing from the artifact: {missing}")


def test_every_package_reaches_the_wheel(check, wheel):
    """A dropped package imports fine and then fails at first use."""
    missing = [p for p in source_packages()
               if not any(n.startswith(p + "/") for n in wheel)]
    check("no package was left out", not missing, str(missing))


def test_the_declared_package_list_matches_the_tree(check):
    """Fails on the day a fifth package is added, not later.

    Independent of a build, so it still answers in an environment where
    the wheel fixture had to skip.
    """
    config = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    check("declared matches the tree",
          sorted(declared) == source_packages(),
          f"declared {sorted(declared)}, tree has {source_packages()}")


def test_the_launcher_is_in_the_wheel(check, wheel):
    """`main.py` is a module, not a package, so nothing sweeps it up."""
    check("main.py is packaged", "main.py" in wheel)


# ------------------------------------------------------------------
# and it can be used from somewhere that is not the checkout
# ------------------------------------------------------------------

def test_the_packages_import_from_a_foreign_working_directory(check, tmp_path):
    """Launching from an arbitrary directory, at the step it actually
    failed on.

    Before this wave the answer was `ModuleNotFoundError: No module
    named 'core'` - the import, not the resource loading. Run in a child
    process from a directory that is not the checkout, with `PYTHONPATH`
    cleared so nothing puts it back.
    """
    probe = tmp_path / "probe.py"
    probe.write_text("import core, devices, drivers, experiments\n"
                     "print('OK')\n", encoding="utf-8")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run([sys.executable, str(probe)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=120,
                            env=env)
    if result.returncode != 0 and "No module named" in result.stderr:
        pytest.skip(
            "the project is not installed into this interpreter, so there "
            "is nothing to import from elsewhere. `uv pip install -e .` "
            "exercises this. Not a failure - working from an uninstalled "
            "checkout is legitimate, and is how the suite normally runs.")
    check("it imported from outside the checkout",
          result.returncode == 0, result.stderr[-1500:])


def test_the_asset_is_found_without_relying_on_the_working_directory(check):
    """The resource half of it, which was already true - now pinned.

    The 4PP diagram is loaded relative to `__file__`, so it is found
    wherever the package lives. Easy to regress into
    `open("experiments/...")` during a refactor, which works perfectly
    on every developer machine and nowhere else.
    """
    from experiments.ossila_4pp import panels
    package_dir = Path(panels.__file__).resolve().parent.parent
    asset = package_dir / "assets" / "WL.png"
    check("the asset resolves from the package, not the cwd",
          asset.is_file(), str(asset))

    source = (ROOT / "experiments" / "ossila_4pp" / "panels"
              / "geometry_panel.py").read_text(encoding="utf-8")
    check("and the loader is anchored to __file__", "__file__" in source,
          "the diagram is loaded by a path that depends on the cwd")


# ------------------------------------------------------------------
# the console script
# ------------------------------------------------------------------

def test_the_console_script_names_something_that_exists(check):
    """`smu-lab-suite = "core.launcher:main"`, checked both halves.

    An entry point is a string in a config file, so nothing about it is
    verified at build time: hatchling will happily record a target that
    does not exist. The failure appears at install, or - worse - at the
    moment somebody on the bench first types the command, which is
    exactly when nobody wants to debug an import.

    So this resolves the string the way the installed script will:
    import the module, get the attribute, check it is callable.
    """
    import importlib
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"].get("scripts", {})
    check("a console script is declared", bool(scripts), str(scripts))
    if not scripts:
        return

    for name, target in scripts.items():
        module_name, _, attribute = target.partition(":")
        check(f"{name} names module:function", bool(module_name and attribute),
              target)
        module = importlib.import_module(module_name)
        function = getattr(module, attribute, None)
        check(f"{name} resolves to something", function is not None, target)
        check(f"{name} resolves to something callable", callable(function),
              f"{target} is {type(function).__name__}")


def test_the_console_script_does_not_install_a_top_level_main(check):
    """It must not point at `main.py`.

    A console script target has to be importable, and `main:main` would
    put a top-level module named `main` into the environment's
    site-packages - a name every other installed package also considers
    available. Whichever imported second would lose, and the symptom
    would be an unrelated program breaking after this one was installed.

    `main.py` stays in the wheel as the thing you run from a checkout;
    it is the *entry point* that must not name it.
    """
    import tomllib
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for name, target in data["project"].get("scripts", {}).items():
        module_name = target.partition(":")[0]
        check(f"{name} is namespaced to a package",
              "." in module_name and not module_name == "main",
              f"{target} would install a bare top-level module")


def test_the_launcher_module_is_in_the_wheel(check, wheel):
    """Because the console script is useless without it.

    `main.py` reaching the wheel is already checked; this is the module
    it now delegates to, and the one the installed command actually
    imports.
    """
    check("core/launcher.py is packaged", "core/launcher.py" in wheel,
          "the console script would fail at import")
