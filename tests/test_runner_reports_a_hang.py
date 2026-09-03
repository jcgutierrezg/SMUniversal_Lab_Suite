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
        self.cmds = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(kwargs)
        self.cmds.append(list(cmd))
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

    `--jobs 1` is passed explicitly. It used to be the only behaviour
    and so did not need saying; it is now the reference path, and the
    exact group count this asserts is a property of that path - a
    parallel run shards the non-GUI files and adds a timing phase, so
    it runs a different number of groups on purpose. The parallel
    equivalent of this guarantee is the test below.
    """
    files = [ROOT / "tests" / "test_first.py", ROOT / "tests" / "test_second.py"]
    monkeypatch.setattr(run_tests, "gui_files", lambda: files)
    recorder = Recorder(Completed(), _timeout(), Completed())
    monkeypatch.setattr(run_tests.subprocess, "run", recorder)
    monkeypatch.setattr(sys, "argv",
                        ["run_tests.py", "--all", "--jobs", "1"])

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


# --- running groups at once, without making the clock a variable -----
#
# Parallelism is opt-out rather than opt-in, so these hold the parallel
# path to the same guarantees the serial one already had, plus the one
# it introduces: a test that measures elapsed time must never share the
# machine with another group.


def _parallel(monkeypatch, recorder, gui, non_gui, timing, jobs="4"):
    """Drive `main()` with the file lists substituted."""
    monkeypatch.setattr(run_tests, "gui_files", lambda: gui)
    monkeypatch.setattr(run_tests, "non_gui_files", lambda: non_gui)
    monkeypatch.setattr(run_tests, "timing_files", lambda: timing)
    monkeypatch.setattr(run_tests.subprocess, "run", recorder)
    monkeypatch.setattr(sys, "argv",
                        ["run_tests.py", "--all", "--jobs", jobs])
    out = StringIO()
    with redirect_stdout(out), redirect_stderr(StringIO()):
        rc = run_tests.main()
    return rc, out.getvalue()


def test_a_hung_group_in_a_parallel_run_still_lets_the_others_finish(
        monkeypatch):
    """The serial path's guarantee, restated for the parallel one.

    `test_one_hung_group_does_not_hide_the_ones_after_it` asserts this
    for `--jobs 1` by counting groups. That count is specific to the
    reference path, so it cannot be reused here - a parallel run shards
    the non-GUI files and adds a timing phase deliberately. What must
    hold in both is the property itself: one group that never returns
    does not stop the rest being run and reported.
    """
    gui = [ROOT / "tests" / f"test_g{i}.py" for i in range(3)]
    non_gui = [ROOT / "tests" / f"test_n{i}.py" for i in range(4)]
    recorder = Recorder(Completed(), _timeout(), Completed())
    rc, out = _parallel(monkeypatch, recorder, gui, non_gui, [])

    assert rc == 1
    assert "timed out" in out, out
    # every shard and every GUI file was still handed to pytest
    assert len(recorder.calls) >= len(gui) + 1, (
        f"only {len(recorder.calls)} groups ran; a timeout in one "
        f"worker must not cancel the others"
    )


def test_every_non_gui_file_lands_in_exactly_one_shard():
    """Sharding must partition, not sample.

    A file dropped here does not fail: it passes, silently, by never
    being run. That is the one outcome a test runner must not have, so
    it is asserted directly rather than inferred from a green suite.
    """
    files = [Path(f"test_{i}.py") for i in range(23)]
    for jobs in (1, 2, 5, 23, 50):
        buckets = run_tests.shard(files, jobs)
        flat = [f for b in buckets for f in b]
        assert sorted(flat) == sorted(files), (jobs, buckets)
        assert len(flat) == len(set(flat)), f"duplicated at jobs={jobs}"
        assert all(b for b in buckets), f"empty bucket at jobs={jobs}"


def test_the_default_leaves_cores_for_whoever_is_using_the_machine(
        monkeypatch):
    """`auto` must not claim the whole machine.

    The suite runs on the bench workstation during a commissioning
    session. A runner that takes every core makes the desk unusable for
    as long as it holds them, which is a good way to teach somebody to
    stop running the suite.
    """
    monkeypatch.delenv("SMU_JOBS", raising=False)
    monkeypatch.setattr(run_tests.os, "cpu_count", lambda: 16)
    jobs = run_tests.worker_count([])
    assert jobs <= 16 - run_tests.RESERVED_CORES, jobs
    assert jobs <= run_tests.MAX_WORKERS, jobs

    monkeypatch.setattr(run_tests.os, "cpu_count", lambda: 2)
    assert run_tests.worker_count([]) >= 1, "never zero workers"


def test_a_parallel_run_defers_every_timing_test_to_the_serial_phase(
        monkeypatch):
    """The point of the whole arrangement.

    `elapsed < 0.26` is a claim about the machine as much as about the
    code, and other pytest processes competing for the same cores
    make it false with nothing wrong. So the parallel phase must
    deselect those tests, and the serial phase must then actually run
    them - deselecting alone would quietly stop testing them, which is
    worse than the flake.
    """
    gui = [ROOT / "tests" / "test_g0.py"]
    non_gui = [ROOT / "tests" / "test_n0.py"]
    timing = [ROOT / "tests" / "test_n0.py"]
    recorder = Recorder(Completed())
    _parallel(monkeypatch, recorder, gui, non_gui, timing)

    joined = [" ".join(c) for c in recorder.cmds]
    parallel_phase = [c for c in joined if "not timing" in c]
    serial_phase = [c for c in joined
                    if "timing" in c and "not timing" not in c]

    assert len(parallel_phase) == 2, joined
    assert len(serial_phase) == 1, (
        "the timing tests were deselected from the parallel phase and "
        "then never run anywhere"
    )


def test_the_runners_own_option_does_not_reach_pytest(monkeypatch):
    """`--jobs` is the runner's, and pytest has never heard of it.

    Unrecognised arguments are the runner's own passthrough contract:
    anything it does not consume goes to pytest, which is how `-k` and
    `-x` work. So an option it forgets to strip does not warn - it makes
    every group exit on a usage error, and the run reports as a
    wholesale failure with nothing to do with the tests.
    """
    recorder = Recorder(Completed())
    _parallel(monkeypatch, recorder, [ROOT / "tests" / "test_g0.py"],
              [ROOT / "tests" / "test_n0.py"], [], jobs="2")
    assert recorder.cmds, "no group was run at all"
    for cmd in recorder.cmds:
        assert "--jobs" not in cmd, cmd
        # the count itself must not survive as a stray positional -
        # pytest would read a bare "2" as a path and collect nothing
        assert "2" not in cmd, cmd


def test_the_gui_budget_does_not_grow_with_jobs(monkeypatch):
    """`--jobs` widens the shards; it must not widen the GUI pool.

    GUI groups are not CPU-bound - they pump a Tk event loop and wait -
    so running more of them at once does not divide the work, it
    multiplies it. Measured on this suite: 647 s of GUI work became
    4,781 s at twelve workers, for a run that got 1.5x faster overall.

    The bound is asserted rather than left to the default because the
    tempting change is to "simplify" this back to one worker count. The
    number that must not move is the GUI one.
    """
    gui = [ROOT / "tests" / f"test_g{i}.py" for i in range(8)]
    non_gui = [ROOT / "tests" / f"test_n{i}.py" for i in range(8)]
    _, out = _parallel(monkeypatch, Recorder(Completed()), gui, non_gui,
                       [], jobs="12")

    m = re.search(r"(\d+) GUI files on (\d+)", out)
    assert m, out
    assert int(m.group(2)) <= run_tests.GUI_WORKERS, out
    assert int(m.group(1)) == len(gui), out


def test_a_small_jobs_count_is_not_exceeded_by_the_gui_pool(monkeypatch):
    """`--jobs 2` means two, not two plus the GUI budget."""
    gui = [ROOT / "tests" / "test_g0.py"]
    non_gui = [ROOT / "tests" / "test_n0.py"]
    _, out = _parallel(monkeypatch, Recorder(Completed()), gui, non_gui,
                       [], jobs="2")
    shards = int(re.search(r"(\d+) non-GUI shards on (\d+)", out).group(2))
    gui_jobs = int(re.search(r"GUI files on (\d+)", out).group(1))
    assert shards + gui_jobs <= 2, out
