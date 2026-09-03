"""Shared test fixtures.

The suite used to be 25 standalone scripts, each one re-defining the same
`check(name, condition, detail)` helper and appending failures to a
module-level list that a footer inspected before calling sys.exit(1).
Sixteen copies of the same nine lines.

That helper now lives here once, as a fixture. It keeps the behaviour
that made it useful - a failing check does *not* abort the rest of the
test, so one run tells you everything that is broken rather than only the
first thing - and adds the part it was missing: the failures are reported
to a real test runner instead of a print statement.

A test asks for it by naming it as a parameter:

    def test_something(check):
        check("the thing holds", value == expected, f"got {value}")

Any check that fails is collected, and the test fails at teardown with
every failure listed.
"""
import gc
import os
import sys
import time
from tkinter import messagebox as _tkinter_messagebox

import pytest


class _Checker:
    """Soft assertions: record failures, report them all at the end."""

    def __init__(self):
        self.failures: list[str] = []

    def __call__(self, name, condition, detail=""):
        if not condition:
            self.failures.append(f"{name}   {detail}".rstrip())
        return bool(condition)


@pytest.fixture
def check():
    checker = _Checker()
    yield checker
    if checker.failures:
        pytest.fail(
            f"{len(checker.failures)} check(s) failed:\n  - "
            + "\n  - ".join(checker.failures),
            pytrace=False,
        )


@pytest.fixture(scope="module", autouse=True)
def _reap_tk_roots_between_files():
    """Destroy any Tk root a test file leaves behind, once that file ends.

    As 25 separate scripts, each process built at most three Tk roots and
    then exited, so a root nobody destroyed was cleaned up by process
    teardown. Under one pytest process the suite builds 21 of them
    against a single shared Tcl runtime, and three were never explicitly
    destroyed. A leaked root gets finalised by the garbage collector at
    an arbitrary later moment, which tears down Tcl state underneath
    whichever test happens to be running - observed on Windows as
    `TclError: invalid command name "tcl_findLibrary"` raised from a
    tk.Tk() call in a completely unrelated file.

    Module scope is the right granularity, not function scope: several
    files deliberately share one root across their tests (see the
    order-dependence note in README.md), so reaping after every test
    would destroy a root its own file still needs. Reaping after each
    file gives the isolation the separate processes used to provide.
    """
    yield
    tk = sys.modules.get("tkinter")
    if tk is None:
        return
    gc.collect()
    for obj in [o for o in gc.get_objects() if isinstance(o, tk.Tk)]:
        try:
            obj.destroy()
        except Exception:
            pass          # already torn down, or its interpreter is gone
    gc.collect()


@pytest.fixture(scope="session", autouse=True)
def _retry_tk_construction():
    r"""Retry tk.Tk() on TclError, and report loudly when it helps.

    Windows produced an intermittent TclError during Wave 0: a Tcl file
    that exists on disk could not be read, reported with errno 0. It
    struck on two unrelated machines, on the bench and in CI, always in
    a different test, and it is not currently reproducing.

    Ruled out by experiment, not by argument: the Python distribution
    (Microsoft Store, uv-managed, and python.org all showed it),
    a synced filesystem (it happened on a clean CI runner under
    C:\hostedtoolcache), pytest's output capture (all three modes pass),
    how the child process is launched (all four modes pass), and
    matplotlib, PIL, ttk, worker threads and repeated create/destroy
    cycles (all pass in isolation on Windows).

    So the cause is unknown. This retry is insurance, not a diagnosis.
    It costs nothing while nothing fails, and if the fault returns the
    log tells us in one line whether a second attempt succeeds - which
    is the one question every remaining theory disagrees about. Do not
    delete it on the grounds that it never fires; that is the point.
    """
    tk = pytest.importorskip("tkinter")
    original = tk.Tk.__init__
    stats = {"retries": 0, "recovered": 0, "gave_up": 0}

    def patched(self, *args, **kwargs):
        last = None
        for attempt in range(5):
            try:
                original(self, *args, **kwargs)
                if attempt:
                    stats["recovered"] += 1
                    print(f"\n  [tk-retry] Tk() succeeded on attempt "
                          f"{attempt + 1} after TclError: {last}")
                return
            except tk.TclError as exc:
                last = str(exc).splitlines()[0][:100]
                stats["retries"] += 1
                time.sleep(0.25 * (attempt + 1))
        stats["gave_up"] += 1
        print(f"\n  [tk-retry] Tk() failed all 5 attempts: {last}")
        raise tk.TclError(last)

    tk.Tk.__init__ = patched
    yield
    tk.Tk.__init__ = original
    if stats["retries"]:
        print(f"\n  [tk-retry] attempts that raised: {stats['retries']}, "
              f"recovered by retry: {stats['recovered']}, "
              f"gave up: {stats['gave_up']}")


@pytest.fixture(autouse=True)
def _no_instrument_discovery(request, monkeypatch):
    r"""Stop the tests scanning for real instruments.

    `build_connection_panel()` populates the address dropdown as soon as
    it is built, so the operator sees what is plugged in without having
    to ask. That is right at the bench and wrong in a test: every
    `LabApp(...)` construction was calling `VisaTransport.list_available()`,
    which walks three backends and, through pyvisa-py, performs a
    **network scan** for TCPIP instruments.

    Two problems, and the smaller one is the speed.

    The real problem is that a test which reaches outside its own
    process for something it does not use can fail for reasons that have
    nothing to do with the code. Every GUI test here connects a
    `NullTransport` and touches no instrument - but before it got there
    it asked the lab's network what was out there, and on CI it asked
    GitHub's. That is a dependency nobody chose and nobody could see.

    The speed was how it surfaced. On Windows the suite spent most of
    its wall clock in discovery: files that build an app per test ran at
    5-7 seconds each, against 0.5 for files that build none, and each
    app construction emitted two `UserWarning`s from pyvisa-py about
    missing `psutil` and `zeroconf`. Warnings tracked app constructions
    exactly, and time tracked warnings.

    Note what the *tempting* fix would have done: installing psutil and
    zeroconf silences both warnings by making the scan more thorough -
    psutil is what lets pyvisa-py enumerate every network interface
    rather than just the default. Quieter, slower, and still reaching
    onto the network.

    Opting out
    ----------
    A test that is genuinely about discovery marks itself:

        pytestmark = [pytest.mark.instrument_discovery]

    `test_visa_backends.py` does exactly that. It substitutes its own
    fake pyvisa, so it never reaches a network either - but it needs the
    real `list_available()` to be the thing under test.

    This is a stub, not a policy about hardware. Nothing here prevents
    `tools/smu_checkup.py` or the app itself from scanning; it is scoped
    to the test session.
    """
    if request.node.get_closest_marker("instrument_discovery"):
        return

    try:
        from core.gui.connection_panel import TRANSPORTS
    except Exception:                       # pragma: no cover - no Tk present
        return

    for cls in set(TRANSPORTS.values()):
        monkeypatch.setattr(cls, "list_available",
                            classmethod(lambda cls: []), raising=False)
        if hasattr(cls, "scan_summary"):
            monkeypatch.setattr(cls, "scan_summary",
                                classmethod(lambda cls: []), raising=False)


@pytest.fixture(autouse=True)
def _save_folder_is_never_the_real_home(monkeypatch, tmp_path):
    """Point every app built in a test at a throwaway save folder.

    `LabApp` defaults `storage_path` to the user's home directory, which
    is right in production and wrong in a test: the suite would scan -
    and could in principle write to - whatever happens to be sitting in
    the developer's or the CI runner's home.

    That was latent until Wave 5c-ii gave the run path a reason to *look*
    at the folder. The save-collision pre-flight lists it for files
    matching the sample name, so a stray `sample_iv_sweep.csv` in home
    turned a passing test into a prompt, and - before the prompt was
    moved onto the `messagebox` seam - into a hang with nothing on screen
    to explain it. The seam fix stops the hang; this stops the test from
    depending on what is in a directory it does not own.

    Autouse and session-agnostic on purpose. Any test may construct a
    `LabApp`, and remembering to isolate the folder is exactly the kind
    of per-file discipline that gets forgotten in the tenth file.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    real_expanduser = os.path.expanduser

    def fake_expanduser(path):
        # Only strings can start with "~", but callers pass Path objects
        # too - matplotlib expands its own config path this way during
        # import. Anything that is not a plain string goes straight
        # through to the real implementation, which is what a stub
        # standing in for a stdlib function has to do: intercept the one
        # case it cares about and be transparent for every other.
        if isinstance(path, str) and (path == "~" or path.startswith("~")):
            return str(home) + path[1:]
        return real_expanduser(path)

    monkeypatch.setattr(os.path, "expanduser", fake_expanduser)


@pytest.fixture(autouse=True)
def _state_directory_is_never_the_real_one(monkeypatch, tmp_path):
    """Keep the lock file and the run event log out of the real profile.

    `LabApp` builds an `EventLog` by default (Wave 7d), so *any* test
    that constructs an app writes run records into per-machine state.
    Left alone that means the developer's own profile, and a suite that
    scribbles outside its temporary directory is one nobody can trust to
    have left the machine as it found it.

    Autouse for the same reason as the save-folder fixture above:
    remembering to isolate it per file is the discipline that gets
    forgotten in the tenth file.

    Why this exists **as well as** `expanduser` being patched
    ---------------------------------------------------------
    On Linux and macOS `lock_directory()` ends up at `Path.home()`,
    which goes through `os.path.expanduser`, so the fixture above
    already caught it - by luck rather than design.

    On Windows it does not. There the directory comes from the
    `LOCALAPPDATA` environment variable, which no amount of
    `expanduser` patching touches, so the suite would write into the
    real user profile on exactly the platform whose CI job is
    load-bearing here - and a Linux run could never show it. Setting
    both the environment variables covers every branch of
    `lock_directory()` on every platform.
    """
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(state))   # Windows
    monkeypatch.setenv("XDG_STATE_HOME", str(state))  # Linux and macOS
    monkeypatch.delenv("APPDATA", raising=False)


def _seam_modules():
    """Imported `core.*` / `experiments.*` modules holding a `messagebox`.

    Discovered rather than listed. A hard-coded list would go stale the
    first time an experiment grew its own `from tkinter import
    messagebox`, and it would go stale *silently* - the guard below
    would keep passing while covering one seam fewer.
    """
    for name, module in list(sys.modules.items()):
        if not name.startswith(("core.", "experiments.")):
            continue
        if module is not None and hasattr(module, "messagebox"):
            yield name, module


def _owning_test_module(installed):
    """Which test module holds `installed` as a module-level attribute."""
    for name, module in list(sys.modules.items()):
        if not name.startswith("test_") or module is None:
            continue
        for value in list(vars(module).values()):
            if value is installed:
                return name
    return None


#: The genuine module, captured before any test has had a chance to
#: replace it on a seam. Identity is what distinguishes "nobody patched
#: this" from "somebody patched it with their own recorder".
_REAL_MESSAGEBOX = _tkinter_messagebox


class _UnclaimedDialogSeam:
    """Stands on a dialog seam that no test has claimed.

    Records what would have been shown and returns, where the real
    module would have opened a window and run its own event loop until
    somebody clicked it. Returning is the whole point: the guard must
    turn a hang into a report, and a guard that raised from inside a
    queued UI callback would be swallowed by `_drain_ui`'s per-callback
    isolation and turn into a console line instead.
    """

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def refuse(title="", message="", **kwargs):
            self.calls.append((name, title))
            return None
        refuse.__name__ = name
        refuse._unclaimed_seam = self
        return refuse


@pytest.fixture(autouse=True)
def _a_gui_test_never_reaches_a_real_dialog(request, monkeypatch):
    """Fail a GUI test that lets a real modal dialog through.

    The fault this exists for
    -------------------------
    `test_link_lost_during_a_run.py` reached `messagebox.showwarning`
    without having stubbed it. What happened next depended on the
    machine, because the call is queued by `LabApp.ui()` and drained
    from a 10 ms `after()` timer: where the test's event-loop pumping
    spanned that 10 ms the dialog opened and blocked forever, and where
    it did not the warning was silently discarded and the test passed.
    CI hung for the platform's full six hours with an empty log; a
    developer machine showed the dialog; this container did neither.

    Both outcomes are bad, and the quiet one is worse — the message
    being discarded is the one telling an operator that a sample may
    still be energised.

    Why it is shaped this way
    -------------------------
    The companion guard above catches a recorder *stolen* by another
    file. It cannot catch a seam nobody patched at all, because there is
    no owner to disagree with. This one asks the other question: at the
    end of a GUI test, did anything reach the real module?

    Both halves are needed, and for different failures. A dialog that
    was drained shows up in `guard.calls`. One still sitting in the UI
    queue when the test ended shows up in `queued` - and that is the
    case a call-time check alone would miss, since on a machine where
    the pump never fires nothing is ever called.

    Seams are discovered, not listed, for the same reason as above.
    """
    if request.node.get_closest_marker("gui") is None:
        yield
        return

    guard = _UnclaimedDialogSeam()
    for _, module in _seam_modules():
        if getattr(module, "messagebox", None) is _REAL_MESSAGEBOX:
            monkeypatch.setattr(module, "messagebox", guard)

    queued = []
    base_app = sys.modules.get("core.base_app")
    if base_app is not None and hasattr(base_app, "LabApp"):
        real_ui = base_app.LabApp.ui

        def ui(self, fn, *args, **kwargs):
            if getattr(fn, "_unclaimed_seam", None) is guard:
                queued.append(getattr(fn, "__name__", "dialog"))
            return real_ui(self, fn, *args, **kwargs)

        monkeypatch.setattr(base_app.LabApp, "ui", ui)

    yield

    shown = [f"{name} {title!r}" for name, title in guard.calls]
    undrained = [n for n in queued if not guard.calls]
    if shown or undrained:
        detail = []
        if shown:
            detail.append("reached the real dialog module: "
                          + ", ".join(shown))
        if undrained:
            detail.append("left queued for the UI thread and never drained: "
                          + ", ".join(undrained))
        pytest.fail(
            f"{request.node.name} raised a dialog on a seam no test had "
            f"stubbed.\n  - " + "\n  - ".join(detail)
            + "\n\nUnstubbed, this blocks the suite on any machine whose "
              "event-loop pumping reaches the drain timer, and silently "
              "discards the message on any machine that does not. Stub "
              "`messagebox` on the seam - see the `dialogs` fixture in "
              "tests/test_link_lost_during_a_run.py - and assert what was "
              "raised.",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def _dialog_recorder_belongs_to_this_file(request):
    """Fail loudly when a GUI test's dialog recorder has been stolen.

    The fault this exists for
    -------------------------
    Nine test files replace `messagebox` on the shared modules -
    `core.base_app`, `experiments.base_experiment` and the experiment
    packages - and they do it **at import time**, each with its own
    recorder object. Import two of those files into one process and the
    last one imported wins: every other file's tests then assert against
    a recorder that nothing writes to.

    That fails in the dangerous direction. The assertions these files
    make about dialogs are mostly *absence* assertions - "no error
    dialog was raised" - and an empty recorder satisfies those whether
    or not the code under test is correct. The suite goes green while
    testing nothing.

    `run_tests.py` gives each GUI file its own process, so the hazard
    does not fire in the way this suite is actually run. This guard is
    for the way it is occasionally run by hand: `pytest tests/`, or
    `pytest tests/test_hall_lifecycle.py tests/test_hall_calculation.py`
    while chasing something. Without it, that run reports a pass that
    means less than it appears to.

    Why the check is shaped this way
    --------------------------------
    The obvious guard - "fail if more than one GUI module was imported
    into this process" - is wrong, and wrong in the direction that would
    have broken the suite. `run_tests.py`'s non-GUI pass is
    `pytest tests/ -m "not gui"`, and pytest *imports* every module it
    collects before deselecting any of them. So the correct command
    imports all twenty-five GUI files into one process, every time.
    Counting imports would have failed it.

    What actually matters is narrower and is what is checked here: at
    the moment a GUI test runs, is the object installed on each seam the
    one belonging to *this* file? Ownership is established by identity,
    not by name, so a file that renames its recorder is still covered.

    Deliberately silent about two cases:

    * files that install their recorder inside a fixture rather than at
      import (`test_hall_demo.py`, `test_minismu.py`) hold it in a local,
      so no module-level attribute claims it and no owner is found. They
      are already immune to the fault - a fixture installs at test time,
      after every import has happened.
    * a seam still holding the real `tkinter.messagebox`. Nobody has
      patched it, so nobody's recorder has been stolen.

    Both return "no owner", which is the honest answer rather than a
    guess. The full fix is per-test patch-and-restore in every GUI file;
    this is the cheap guard recorded alongside it in
    `docs/open/technical-debt.md`, and it does not replace it.
    """
    if request.node.get_closest_marker("gui") is None:
        yield
        return

    here = getattr(request.node.module, "__name__", None)
    stolen = []
    for seam_name, seam in _seam_modules():
        owner = _owning_test_module(seam.messagebox)
        if owner is not None and owner != here:
            stolen.append(f"{seam_name}.messagebox is {owner}'s recorder")

    if stolen:
        pytest.fail(
            f"{here} is running in a process where another test file owns "
            f"the dialog seam:\n  - " + "\n  - ".join(stolen)
            + "\n\nIts dialog assertions would pass against a recorder "
              "nothing writes to. Run the suite with "
              "`uv run python run_tests.py --all`, which gives each GUI "
              "file its own process; see tests/README.md.",
            pytrace=False,
        )
    yield
