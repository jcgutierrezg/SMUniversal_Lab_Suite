"""The Tk thread-affinity diagnostic. See house rule 8.

Tested against a five-line stand-in rather than against `tkinter.Variable`,
which is why this file has no `gui` marker and stays in `run_tests.py`'s
fast shared process. The guard does not know or care that its target is
a Tk class - `install_tk_guard()` is a one-line wrapper that supplies
one - so a fake proves the machinery and a Tk root would only prove that
`tkinter` exists.
"""
import threading

import pytest

from core.thread_guard import (
    ThreadAffinityError,
    ThreadAffinityGuard,
    install_from_environment,
)


class FakeVariable:
    """Stands in for `tkinter.Variable`: something with get and set."""

    def __init__(self, value=None):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value
        return value


def _in_thread(fn, name="worker"):
    """Run `fn` in a named thread and re-raise whatever it raised."""
    box = {}

    def target():
        try:
            box["result"] = fn()
        except BaseException as exc:       # noqa: BLE001 - re-raised below
            box["error"] = exc

    thread = threading.Thread(target=target, name=name)
    thread.start()
    thread.join(5)
    assert not thread.is_alive(), "worker did not finish"
    if "error" in box:
        raise box["error"]
    return box.get("result")


# ------------------------------------------------------------------
# it stays out of the way
# ------------------------------------------------------------------
def test_same_thread_access_is_not_a_violation():
    var = FakeVariable(3)
    with ThreadAffinityGuard(FakeVariable) as guard:
        assert var.get() == 3
        var.set(7)
        assert var.get() == 7
    assert guard.violations == []
    assert guard.calls == 3


def test_values_pass_through_untouched():
    """A diagnostic that changes behaviour is not a diagnostic."""
    var = FakeVariable()
    with ThreadAffinityGuard(FakeVariable):
        var.set("100u")
        assert var.get() == "100u"


def test_methods_are_restored_on_exit():
    """A guard left installed on `tkinter.Variable` outlives the test
    that installed it and slows every widget read afterwards."""
    original_get = FakeVariable.get
    with ThreadAffinityGuard(FakeVariable):
        assert FakeVariable.get is not original_get
    assert FakeVariable.get is original_get


def test_remove_is_idempotent():
    guard = ThreadAffinityGuard(FakeVariable).install()
    guard.remove()
    guard.remove()
    assert FakeVariable.get.__name__ == "get"


# ------------------------------------------------------------------
# it reports the fact
# ------------------------------------------------------------------
def test_cross_thread_access_is_recorded():
    var = FakeVariable(5)
    with ThreadAffinityGuard(FakeVariable) as guard:
        assert _in_thread(var.get, name="measure-worker") == 5

    assert len(guard.violations) == 1
    violation = guard.violations[0]
    assert violation.method == "get"
    assert violation.thread_name == "measure-worker"
    assert "test_thread_guard.py" in violation.where()


def test_violation_names_the_calling_line_not_the_wrapper():
    """The whole value of the diagnostic is that it points at the
    experiment line responsible, not at the wrapper that caught it."""
    var = FakeVariable(1)

    def worker():
        return var.get()

    with ThreadAffinityGuard(FakeVariable) as guard:
        _in_thread(worker)

    where = guard.violations[0].where().replace("\\", "/")
    # note the path, not the bare filename: this test file is itself
    # called test_thread_guard.py, and matching on the filename alone
    # would fail on a correct implementation
    assert "core/thread_guard.py" not in where
    assert "worker" in where


def test_logging_mode_does_not_break_the_run():
    """The bench default. A raise inside a worker turns a provenance bug
    into an aborted measurement, which is the worse of the two."""
    var = FakeVariable(2)
    lines = []
    with ThreadAffinityGuard(FakeVariable, log=lines.append) as guard:
        assert _in_thread(var.get) == 2          # returned normally
    assert len(guard.violations) == 1
    assert lines and "thread-guard" in lines[0]


def test_a_broken_log_sink_cannot_break_a_run():
    def exploding(_):
        raise RuntimeError("console is gone")

    var = FakeVariable(2)
    with ThreadAffinityGuard(FakeVariable, log=exploding) as guard:
        assert _in_thread(var.get) == 2
    assert len(guard.violations) == 1


def test_strict_mode_raises_at_the_offending_call():
    """The right mode for a test, the wrong one for a bench session."""
    var = FakeVariable(2)
    with ThreadAffinityGuard(FakeVariable, strict=True):
        with pytest.raises(ThreadAffinityError):
            _in_thread(var.get)


def test_report_groups_by_call_site():
    var = FakeVariable(0)

    def worker():
        for _ in range(3):
            var.get()

    with ThreadAffinityGuard(FakeVariable) as guard:
        _in_thread(worker, name="sweep-worker")
        var.get()                                # same thread: fine

    report = guard.report()
    assert "3 cross-thread access(es)" in report
    assert "sweep-worker" in report


def test_clean_report_says_how_much_was_watched():
    """'No violations' is only reassuring if it also says the guard was
    actually watching something."""
    var = FakeVariable(0)
    with ThreadAffinityGuard(FakeVariable) as guard:
        var.get()
        var.set(1)
    assert "2 guarded call(s)" in guard.report()


def test_owner_is_the_installing_thread_not_the_main_thread():
    """Ties the check to whichever thread built the widgets, so the
    guard stays correct if a Tk root is ever created off the main
    thread, and so a fixture can install one."""
    var = FakeVariable(0)
    guards = []

    def install_and_use():
        guard = ThreadAffinityGuard(FakeVariable).install()
        guards.append(guard)
        var.get()                # same thread as the install: fine

    _in_thread(install_and_use, name="owner-thread")
    guard = guards[0]
    try:
        assert guard.violations == []
        var.get()                # main thread is now the foreign one
        assert len(guard.violations) == 1
        assert guard.violations[0].owner_thread_name == "owner-thread"
    finally:
        guard.remove()


# ------------------------------------------------------------------
# the environment switch
# ------------------------------------------------------------------
def test_environment_switch_is_off_by_default(monkeypatch):
    monkeypatch.delenv("SMULAB_TK_THREAD_GUARD", raising=False)
    assert install_from_environment() is None


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_environment_switch_treats_falsey_values_as_off(monkeypatch, value):
    monkeypatch.setenv("SMULAB_TK_THREAD_GUARD", value)
    assert install_from_environment() is None
