"""Packaging and layout invariants fixed in Wave 0b.

These are cheap to state and easy to break by accident, which is exactly
what makes them worth asserting.
"""
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "smuniversal_lab_suite"


def _pyproject():
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


def _normalise(spec):
    """The distribution name a requirement string refers to."""
    return (spec.split(">")[0].split("<")[0].split("=")[0].split("[")[0]
            .strip().replace("_", "-").lower())


def test_minismu_is_declared_exactly_once():
    """miniSMU is declared in one place: the one install's dependencies.

    The fault this guards is a naming trap. `minismu-py` and
    `minismu_py` normalise to the same distribution, so a second
    declaration under the other spelling does nothing but mislead
    whoever reads the file next.
    """
    data = _pyproject()
    declared = [d for d in data["project"]["dependencies"]
                if _normalise(d) == "minismu-py"]
    assert len(declared) == 1, (
        f"minismu-py should be declared exactly once, found {declared}; "
        f"both spellings normalise to the same distribution")


def test_every_instruments_library_is_in_the_one_install():
    """A plain `uv sync` gives a machine every instrument.

    Asserted against the named packages rather than a count, because
    the failure this prevents is one of them being moved out - into an
    extra, say - and never noticed until an instrument is missing from a
    dropdown at the bench.
    """
    mandatory = {_normalise(d)
                 for d in _pyproject()["project"]["dependencies"]}
    needed = {"minismu-py", "pyusb", "libusb-package", "ni-gpib-usb-hs"}
    missing = needed - mandatory
    assert not missing, (
        f"{sorted(missing)} is not in the default install, so a machine "
        f"that runs a plain `uv sync` has silently lost an instrument")


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
        "import smuniversal_lab_suite.core.base_app\n"
        "import smuniversal_lab_suite.drivers.registry\n"
        "from smuniversal_lab_suite.core.transports.minismu_transport import MiniSMUTransport\n"
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
    assert (PKG / "drivers" / "registry.py").exists()
    from smuniversal_lab_suite.drivers import registry
    assert callable(registry.identify)
    assert callable(registry.driver_for_idn)


def test_vanderpauw_uses_the_shared_temperature_panel():
    """The duplicated per-experiment copy is gone.

    `experiments/vanderpauw/panels/temp_panel.py` was a 267-line orphan
    beside the 281-line shared `core/gui/temp_panel.py`. Nothing
    imported it, and all three experiments already used the shared one,
    so it could only ever have drifted out of sync.
    """
    assert not (PKG / "experiments" / "vanderpauw" / "panels"
                / "temp_panel.py").exists()
    assert (PKG / "core" / "gui" / "temp_panel.py").exists()
    for name in ("vanderpauw", "hall", "iv_sweep"):
        exp = PKG / "experiments" / name / "experiment.py"
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


def _gitignore_patterns():
    return {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


#: Names that must be ignored as *names* rather than as directories, and
#: why each one is here.
#:
#: The rule they share is the trailing slash: `.venv/` ignores a
#: directory, `.venv` ignores a directory, a file, or a symlink, and the
#: difference is invisible at a glance. It cost a delivered patch whose
#: first hunk was `new file mode 120000` pointing at an absolute path on
#: the author's machine - see `test_no_tracked_path_is_a_symlink`.
#:
#: A list rather than one test, because the next thing that grows inside
#: a checkout will be neither of these two, and the cost of adding it
#: should be one line.
NAMES_IGNORED_WHATEVER_THEY_ARE = {
    ".venv": "a virtualenv, symlinked into the tree at least once",
    ".claude": "agent worktrees - a complete second copy of the source",
}


def test_these_names_cannot_be_tracked_whatever_they_are():
    """Each must be ignored as a bare name, and none may be tracked."""
    patterns = _gitignore_patterns()
    for name, why in NAMES_IGNORED_WHATEVER_THEY_ARE.items():
        assert name in patterns, (
            f"`.gitignore` must contain `{name}` with no trailing slash "
            f"({why}); found "
            f"{sorted(p for p in patterns if name.lstrip('.') in p)}"
        )
        assert f"{name}/" not in patterns, (
            f"`{name}/` matches a directory only, so a symlink of that "
            f"name is not ignored by it. Drop the trailing slash."
        )

        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", name],
            cwd=ROOT, text=True, capture_output=True,
        )
        assert tracked.returncode != 0, f"{name} is tracked in the repository"
