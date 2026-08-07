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
