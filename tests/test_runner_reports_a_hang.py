"""The runner must be able to report a group that never finishes.

A pull-request run hung in `run_tests.py --all` on Linux and produced a
log with nothing in it at all. Both halves of that were the harness, not
the tests:

* `run()` prints only once a group has *finished*, and `print()` to a
  pipe is block-buffered. A whole run's output fits inside one buffer,
  so under CI nothing reached the log until the process exited - and it
  never exited. An empty log is identical whether the first group hung
  or the last.
* Nothing bounded a group, so the job ran toward the platform's own
  limit rather than failing with a name attached.

The result was a failure that could not be localised even in principle,
in a suite whose entire purpose is that a fault says so. These tests
hold the runner to reporting one.

They drive `run()` with a substituted `subprocess.run` rather than a
genuinely slow child, so nothing here waits on a clock: the timeout is
raised as the fact it represents. A test that hung to prove hangs are
caught would be the same defect one layer up.
"""
import re
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_tests  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


class Recorder:
    """Stands in for `subprocess.run`, recording how it was called.

    `raises` decides the behaviour of each successive call: a
    `TimeoutExpired` instance is raised, anything else is returned.
    """

    def __init__(self, *behaviours):
        self.behaviours = list(behaviours)
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(kwargs)
        behaviour = self.behaviours[min(len(self.calls) - 1,
                                        len(self.behaviours) - 1)]
        if isinstance(behaviour, BaseException):
            raise behaviour
        return behaviour


class Completed:
    """The parts of `CompletedProcess` that `run()` reads."""

    def __init__(self, returncode=0, stdout="1 passed in 0.01s\n"):
        self.returncode = returncode
        self.stdout = stdout


def _timeout(output="collected 3 items\ntests/test_thing.py ..", seconds=600):
    return subprocess.TimeoutExpired(cmd=["pytest"], timeout=seconds,
                                     output=output)


def _run(monkeypatch, behaviour, label="test_thing.py", **kwargs):
    """Call `run()` with a substituted subprocess, capturing both streams."""
    recorder = Recorder(behaviour)
    monkeypatch.setattr(run_tests.subprocess, "run", recorder)
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc, summary = run_tests.run(["-q"], label, **kwargs)
    return rc, summary, out.getvalue(), err.getvalue(), recorder


def test_a_group_that_never_finishes_is_named_and_counted_as_a_failure(
        monkeypatch):
    """The whole point: the hung group must be identifiable.

    Not merely non-zero - non-zero was already true of a failure. The
    status has to distinguish "the tests disagreed with the code" from
    "the group never got as far as an opinion", because the responses
    are different.
    """
    rc, summary, out, _, _ = _run(monkeypatch, _timeout())

    assert rc == run_tests.TIMEOUT_RC, rc
    assert "TIMEOUT" in out, out
    assert "test_thing.py" in out, out
    assert "600" in summary, summary


def test_the_group_is_announced_before_it_starts(monkeypatch):
    """A start line, not only a finish line.

    This is the half that a bounded run still would not give us. If a
    group is announced only on completion, the group that hung is the
    one *missing* from the log - which works right up until the buffer
    means none of them are there. The assertion is made from inside the
    substituted subprocess, so it is checking the ordering of the real
    thing rather than the ordering of the final text.
    """
    seen = {}
    out = StringIO()

    def watcher(cmd, **kwargs):
        seen["before"] = out.getvalue()
        return Completed()

    monkeypatch.setattr(run_tests.subprocess, "run", watcher)
    with redirect_stdout(out):
        run_tests.run(["-q"], "test_thing.py")

    assert "test_thing.py" in seen["before"], (
        "the group was not announced before its subprocess started, so a "
        f"group that never returns leaves no trace of itself. Saw: "
        f"{seen['before']!r}"
    )


def test_what_the_group_managed_to_print_survives_being_killed(monkeypatch):
    """On a kill this is the only evidence of how far it got.

    `capture_output=True` means the child's output goes nowhere visible
    unless the runner forwards it. For a group that was killed, that
    output is the difference between "test_thing.py hung" and
    "test_thing.py hung after collecting 3 items and running two".
    """
    _, _, _, err, _ = _run(monkeypatch, _timeout())

    assert "collected 3 items" in err, err


def test_a_group_that_printed_nothing_says_that_rather_than_nothing(
        monkeypatch):
    """Silence must be reported as silence.

    `TimeoutExpired.output` is None when the child produced nothing at
    all before it was killed. Forwarding that unchecked prints an empty
    line, which reads as though the runner failed to report rather than
    as a fact about the group.
    """
    _, _, _, err, _ = _run(monkeypatch, _timeout(output=None))

    assert "no output" in err, err


def test_the_budget_actually_reaches_the_subprocess(monkeypatch):
    """The discriminating half.

    Everything above passes just as well if `run()` catches a
    `TimeoutExpired` that nothing will ever raise, because no timeout
    was passed to the child. This is the test that fails when the
    keyword is dropped.
    """
    _, _, _, _, recorder = _run(monkeypatch, Completed())

    assert recorder.calls[0].get("timeout") == run_tests.GROUP_TIMEOUT_S, (
        "run() did not pass its budget to subprocess.run, so nothing "
        "bounds the group and the TimeoutExpired handler is unreachable"
    )


def test_an_explicit_budget_overrides_the_default(monkeypatch):
    _, _, _, _, recorder = _run(monkeypatch, Completed(), timeout_s=12.0)

    assert recorder.calls[0].get("timeout") == 12.0, recorder.calls[0]


def test_the_child_is_unbuffered_so_a_kill_still_yields_its_output(
        monkeypatch):
    """Buffered output dies with the process that was holding it.

    Without this the previous test's evidence is only available when the
    child exits cleanly, which is exactly the case we do not need it in.

    The variable is removed from the ambient environment first. `run()`
    builds the child's environment from `os.environ`, so on any machine
    that already exports it - a CI job that sets it at the job level, or
    a container that ships with it - this test passes whether or not
    `run()` sets anything at all. A mutation round caught exactly that:
    deleting the assignment left the test green.
    """
    monkeypatch.delenv("PYTHONUNBUFFERED", raising=False)
    _, _, _, _, recorder = _run(monkeypatch, Completed())

    env = recorder.calls[0].get("env") or {}
    assert env.get("PYTHONUNBUFFERED") == "1", (
        "the pytest subprocess buffers its own output, so a group killed "
        "for hanging hands back nothing about where it got to"
    )


def test_one_hung_group_does_not_hide_the_ones_after_it(monkeypatch):
    """A run should name every group that hung, not just the first.

    If the first timeout aborted the run, diagnosing a hang that affects
    several files would take one CI round trip per file.

    The timeout is placed on the first *GUI* file rather than on the
    non-GUI group, because that is where the many groups are and so
    where an early exit costs the most. An earlier version of this test
    hung the non-GUI group instead and a mutation adding `break` to the
    GUI loop survived it: the loop it was meant to protect was never
    reached with a timeout in hand.
    """
    files = [ROOT / "tests" / "test_first.py", ROOT / "tests" / "test_second.py"]
    monkeypatch.setattr(run_tests, "gui_files", lambda: files)
    recorder = Recorder(Completed(), _timeout(), Completed())
    monkeypatch.setattr(run_tests.subprocess, "run", recorder)
    monkeypatch.setattr(sys, "argv", ["run_tests.py", "--all"])

    out = StringIO()
    with redirect_stdout(out), redirect_stderr(StringIO()):
        rc = run_tests.main()

    assert rc == 1
    assert len(recorder.calls) == 1 + len(files), (
        f"the run stopped after {len(recorder.calls)} groups; a timeout "
        f"must not prevent the remaining ones from running"
    )
    assert "timed out" in out.getvalue(), out.getvalue()


def test_the_ci_job_is_bounded(monkeypatch):
    """A mechanical check, because the consequence is invisible locally.

    Nothing about a run on a bench machine notices that the workflow has
    no `timeout-minutes`. The cost only appears on a hung CI job, months
    later, as hours of runner time and a cancellation notice that names
    nothing.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^\s*timeout-minutes:\s*(\d+)\s*$", text, re.MULTILINE)

    assert match, (
        f"{WORKFLOW.name} declares no `timeout-minutes`, so a hung job "
        f"runs to the platform default of six hours before it is "
        f"cancelled - and a cancellation says nothing about what hung."
    )
    assert int(match.group(1)) <= 60, (
        f"`timeout-minutes: {match.group(1)}` is long enough that a hang "
        f"is cheaper to notice by watching than by waiting. The suite's "
        f"slowest observed run is well under ten minutes."
    )
