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
    """Retry tk.Tk() on TclError, and report loudly when it helps.

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
