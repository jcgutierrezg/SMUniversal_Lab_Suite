"""Packaging and layout invariants fixed in Wave 0b.

These are cheap to state and easy to break by accident, which is exactly
what makes them worth asserting.
"""
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _pyproject():
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


def _normalise(spec):
    """The distribution name a requirement string refers to."""
    return (spec.split(">")[0].split("<")[0].split("=")[0].split("[")[0]
            .strip().replace("_", "-").lower())


def test_minismu_is_declared_exactly_once():
    """miniSMU is declared in one place, and that place is an extra.

    The original fault this guards is a naming trap, and it survives the
    change of decision underneath it. `minismu-py` and `minismu_py`
    normalise to the same distribution, so a declaration in both
    `[project] dependencies` and an extra makes the extra silently a
    no-op: `uv sync --extra minismu` and a plain `uv sync` install
    exactly the same thing, and nothing says so.

    What changed in review A-11 is which single place is correct. It was
    mandatory, on the argument that a broken install should fail loudly
    at connect. That argument is about the *import*, and it still holds -
    `MiniSMUTransport.connect()` still imports lazily and still names
    what is missing. It was never an argument for putting one
    instrument's vendor library on every bench machine that owns none.

    So: exactly one declaration, and it is the `minismu` extra.
    """
    data = _pyproject()
    mandatory = [_normalise(d) for d in data["project"]["dependencies"]]
    extras = data["project"].get("optional-dependencies", {})

    assert "minismu-py" not in mandatory, (
        "miniSMU is one instrument's vendor library and belongs in the "
        "`minismu` extra; `bench` pulls it in for a bench machine")

    declaring = {name for name, deps in extras.items()
                 if any(_normalise(d) == "minismu-py" for d in deps)}
    assert declaring == {"minismu"}, (
        f"minismu-py should be declared by the `minismu` extra and "
        f"nothing else, found {sorted(declaring)}; both spellings "
        f"normalise to the same distribution, so a second declaration "
        f"does nothing but mislead")

    assert sum(1 for d in extras["minismu"]
               if _normalise(d) == "minismu-py") == 1


def test_the_bench_extra_restores_what_a_plain_install_used_to_get():
    """`uv sync --extra bench` must equal the pre-A-11 default install.

    The point of the extra is that the bench workflow got one flag
    longer and nothing else. Asserted against the named packages rather
    than against a count, because the failure this prevents is one of
    them being moved out and never put back - which nobody notices until
    an instrument is missing from a dropdown at the bench.
    """
    data = _pyproject()
    extras = data["project"].get("optional-dependencies", {})
    assert "bench" in extras, "the documented bench extra is gone"

    reachable = set()
    frontier = list(extras["bench"])
    while frontier:
        spec = frontier.pop()
        if _normalise(spec) == "smuniversal-lab-suite":
            inner = spec[spec.index("[") + 1:spec.index("]")]
            for name in inner.split(","):
                frontier.extend(extras.get(name.strip(), []))
            continue
        reachable.add(_normalise(spec))

    mandatory = {_normalise(d) for d in data["project"]["dependencies"]}
    was_mandatory_before_a11 = {"minismu-py", "pyusb", "libusb-package"}
    missing = was_mandatory_before_a11 - (reachable | mandatory)
    assert not missing, (
        f"{sorted(missing)} used to be installed by a plain `uv sync` "
        f"and is now reachable from neither the default dependencies "
        f"nor `--extra bench`, so a bench machine has silently lost it")


def test_app_runs_without_minismu_importable():
    """The app must still start if the vendor library cannot be imported.

    Mandatory in pyproject.toml means "installed by uv sync", not
    "guaranteed to import". A broken wheel, a partial install, or a
    version that will not load on a new Python all leave you with a
    package that is present and unusable.

    `MiniSMUTransport.connect()` imports it lazily so that case fails at
    connect time, naming the instrument, rather than stopping the whole
    application from starting - which would take four working
    instruments down with the fifth.
    """
    script = (
        "import sys\n"
        "sys.modules['minismu_py'] = None\n"   # any import raises
        "import core.base_app, drivers.registry\n"
        "from core.transports.minismu_transport import MiniSMUTransport\n"
        "print('ok')\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-1500:]
    assert "ok" in result.stdout


def test_registry_lives_under_drivers():
    """The registry imports every driver, so it belongs beside them.

    While it sat in `core/`, importing anything from the core pulled in
    all seven driver modules - the dependency pointed from the shell
    towards the plugins rather than the other way round.
    """
    assert (ROOT / "drivers" / "registry.py").exists()
    from drivers import registry
    assert callable(registry.identify)
    assert callable(registry.driver_for_idn)


def test_old_registry_import_still_works_but_warns():
    """External scripts importing the old path must keep working."""
    script = (
        "import warnings\n"
        "with warnings.catch_warnings(record=True) as caught:\n"
        "    warnings.simplefilter('always')\n"
        "    import core.driver_registry as old\n"
        "assert callable(old.identify)\n"
        "assert any(issubclass(w.category, DeprecationWarning) for w in caught), \\\n"
        "    'the shim should warn'\n"
        "print('ok')\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-1500:]


def test_no_internal_code_uses_the_deprecated_path():
    """Nothing shipped should still import the old location.

    If it did, the deprecation warning would fire during normal use and
    teach everyone to ignore it.
    """
    offenders = []
    for path in ROOT.rglob("*.py"):
        if any(part in (".venv", "__pycache__", "tests") for part in path.parts):
            continue
        if path.name == "driver_registry.py":
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) \
                    and "core.driver_registry" in stripped:
                offenders.append(f"{path.relative_to(ROOT)}: {stripped}")
    assert not offenders, offenders


def test_vanderpauw_uses_the_shared_temperature_panel():
    """The duplicated per-experiment copy is gone.

    `experiments/vanderpauw/panels/temp_panel.py` was a 267-line orphan
    beside the 281-line shared `core/gui/temp_panel.py`. Nothing
    imported it, and all three experiments already used the shared one,
    so it could only ever have drifted out of sync.
    """
    assert not (ROOT / "experiments" / "vanderpauw" / "panels"
                / "temp_panel.py").exists()
    assert (ROOT / "core" / "gui" / "temp_panel.py").exists()
    for name in ("vanderpauw", "hall", "iv_sweep"):
        exp = ROOT / "experiments" / name / "experiment.py"
        if exp.exists():
            text = exp.read_text(encoding="utf-8")
            assert "panels.temp_panel" not in text, name


def test_project_is_named_after_the_repository():
    assert _pyproject()["project"]["name"] == "smuniversal-lab-suite"


def test_no_tracked_path_is_a_symlink():
    """A symlink in the repository is almost always an accident.

    This one is written from a real incident rather than from theory. A
    virtualenv was symlinked into a working copy so the suite could run,
    `.gitignore` said `.venv/` **with a trailing slash** - which matches
    a directory, not a link of the same name - and `git add -A` swept it
    in. The delivered patch's first hunk was `new file mode 120000`
    pointing at an absolute path on a machine nobody else has.

    On Windows, creating a symlink usually fails without developer mode,
    so applying that patch aborted partway and left a tree with sixteen
    files deleted and nothing said about why.

    Nothing in this project needs a tracked symlink. If one is ever
    genuinely wanted, this test is the place to say so, in writing.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-s"],
        cwd=ROOT, text=True, capture_output=True,
    )
    if listing.returncode != 0:
        import pytest
        pytest.skip("not a git checkout")

    # Mode 120000 is git's symlink mode; 100644 and 100755 are files,
    # 160000 a submodule. Asked by mode rather than by inspecting the
    # working tree, because the question is what the *repository*
    # carries - a patch is generated from the index, not from disk.
    offenders = [
        line.split("\t", 1)[1]
        for line in listing.stdout.splitlines()
        if line.startswith("120000 ")
    ]
    assert not offenders, (
        "these are tracked as symlinks and will not survive a patch "
        f"applied on Windows: {offenders}"
    )


def test_the_virtualenv_cannot_be_tracked_whatever_it_is():
    """`.gitignore` must ignore `.venv` as a name, not as a directory.

    `.venv/` ignores a directory. `.venv` ignores a directory, a file,
    or a symlink. The trailing slash is the entire difference between
    the two, and it is invisible at a glance.
    """
    patterns = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert ".venv" in patterns, (
        "`.gitignore` must contain `.venv` with no trailing slash; found "
        f"{sorted(p for p in patterns if 'venv' in p)}"
    )

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".venv"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert tracked.returncode != 0, ".venv is tracked in the repository"
