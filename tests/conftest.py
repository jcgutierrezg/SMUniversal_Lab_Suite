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
