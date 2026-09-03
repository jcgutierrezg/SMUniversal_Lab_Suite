#!/usr/bin/env python
"""Run the test suite with GUI files isolated in their own processes.

Why this exists
---------------
A substantial and growing share of the test files build real Tk windows
- `gui_files()` below is the list, and the run prints how many there are
rather than this docstring claiming a number that goes stale on the next
file added. Run them all in one pytest process and the suite creates
several Tk interpreters per file against a single shared Tcl runtime. On
Windows that runtime does not survive it: somewhere past the tenth root
or so, tk.Tk() starts failing in ways that have nothing to do with the
test that hits them - "invalid command name tcl_findLibrary" on one
Python build, "couldn't read file spinbox.tcl" (about a file that
demonstrably exists) on another. Both are the same underlying breakage
wearing different messages, and both are non-deterministic, so they
surface as an unrelated test failing at random.

Before the suite was converted to pytest it was a set of standalone
scripts, so each process built at most a few roots and then exited.
Process isolation was doing real work; it was just doing it by accident.
This runner does it on purpose:

    * everything without the `gui` marker runs in one fast process;
    * each GUI file gets a process to itself.

Linux tolerates the shared-runtime case, so this is not strictly needed
there, but running the same command everywhere means CI tests what you
test.

Usage
-----
    uv run python run_tests.py              # default: skips `slow`
    uv run python run_tests.py --all        # includes `slow`
    uv run python run_tests.py --slow-only
    uv run python run_tests.py -k pattern   # extra args go to pytest
    uv run python run_tests.py --jobs 4     # four groups at once
    uv run python run_tests.py --jobs 1     # the reference path

Each group is bounded: one that stops making progress is killed, named
and reported, and the remaining groups still run. `SMU_GROUP_TIMEOUT_S`
overrides the budget in seconds.

Running groups at once
----------------------
Groups are already separate processes, so several can run at once.
`--jobs` (or `SMU_JOBS`) says how many; the default leaves
`RESERVED_CORES` free, because this suite is run on the bench machine
while somebody is using it.

The budget is split rather than shared, because the two kinds of group
behave in opposite ways. Non-GUI files are CPU-bound and divide the
work; GUI files pump a Tk event loop and multiply it. So `--jobs 12`
means nine shard workers and `GUI_WORKERS` GUI workers, not twelve of
each kind competing.

Measured on this suite, `--all`, one 16-core machine:

    serial (--jobs 1)     836 s wall     647 s of GUI machine-time
    one pool of 12        558 s wall   4,781 s
    split 9 + 3           440 s wall   1,089 s

The middle row is the trap: twelve workers cost 7.4x the machine time
to run the same tests, returned only 1.5x, and made the desktop
unusable while it ran. Splitting the budget is both faster and cheaper.

Three things change when more than one group runs:

* the non-GUI files are dealt across shards rather than run as one
  process, since one process holding half the runtime sets a floor
  nothing else can get under;
* GUI groups are capped at `GUI_WORKERS` however wide `--jobs` is;
* tests marked `timing` are deselected from the parallel phase and run
  afterwards, alone.

That second one is the whole reason this is not simply a worker pool.
A test asserting `elapsed < 0.26` is making a claim about the machine as
much as about the code, and other pytest processes competing for the
same cores make it false with nothing wrong. It has already cost
this project two investigations that concluded the code was fine. Marks
go on *upper* bounds only - a lower bound like `elapsed >= 0.19` can
only be made more true by contention.

`--jobs 1` runs exactly the groups this runner has always run, in
order, with no sharding and no timing phase. It is the reference: a
result that differs between `--jobs 1` and `--jobs 12` is evidence about
the parallelism, not about the code. CI uses it.
"""
from __future__ import annotations

import concurrent.futures as cf
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
TESTS = ROOT / "tests"

#: Returned by run() for a group that was killed for exceeding its
#: budget. Not any real pytest exit code, so it cannot be confused with
#: one - notably 5, "nothing collected", which is a pass here.
TIMEOUT_RC = -1

#: How long one group may run before it is killed and named.
#:
#: A group that stops making progress has no way to say so on its own.
#: Its output is captured, so nothing reaches the terminal until it
#: exits, and if it never exits nothing ever does - under CI that means
#: a job that runs to the platform's own limit and reports a blank log,
#: from which the hung group cannot be identified at all.
#:
#: The budget is generous against the slowest group observed (the
#: non-GUI process, a little over two minutes on Linux and more on
#: Windows) because this is a liveness check, not a performance one.
#: Overriding it is for a machine slower than any seen so far, not for a
#: group that has started taking too long - that is the finding, not the
#: obstacle.
GROUP_TIMEOUT_S = float(os.environ.get("SMU_GROUP_TIMEOUT_S", "600"))

#: Cores left for whoever is using the machine. The suite is run on the
#: bench workstation during a commissioning session, not on an idle
#: build box, so the default deliberately does not take everything.
RESERVED_CORES = 4

#: Ceiling regardless of core count - see `worker_count()`.
MAX_WORKERS = 12

#: How many *GUI* groups may run at once, and why it is not the same
#: number as everything else.
#:
#: A GUI group is not CPU-bound. It builds a real Tk window and then
#: spends its time pumping an event loop, waiting on a worker thread,
#: and waiting on the clock. Run several and they do not share the
#: machine, they starve each other: measured here, 647 s of GUI work
#: became 4,781 s at twelve workers - 7.4x the machine time for the
#: same tests - and the whole run got only 1.5x faster. The widgets
#: were visibly slow to draw while it ran.
#:
#: The second cost is worse than the wasted time. `test_combined_window`
#: took 52 s alone and 455 s at twelve workers, against a
#: `GROUP_TIMEOUT_S` of 600. A passing test that close to the budget is
#: one slower machine away from being killed and reported as a hang -
#: the exact false signal this runner exists to prevent, reintroduced
#: by the thing meant to speed it up.
GUI_WORKERS = int(os.environ.get("SMU_GUI_JOBS", "3"))


def gui_files() -> list[Path]:
    """Test files carrying the `gui` marker, found by reading them.

    Deliberately a text search rather than a pytest collection pass:
    collection would import every module, which builds Tk roots, which
    is the thing this runner exists to avoid doing all at once.
    """
    out = []
    for path in sorted(TESTS.glob("test_*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            # only a real `pytestmark = [...]` assignment counts; a file
            # that merely mentions the marker in a docstring or an
            # assertion (tests/test_meta.py does) is not a GUI file
            if line.startswith("pytestmark") and "pytest.mark.gui" in line:
                out.append(path)
                break
    return out


def non_gui_files() -> list[Path]:
    """Every test file that `gui_files()` did not claim."""
    gui = {p.name for p in gui_files()}
    return [p for p in sorted(TESTS.glob("test_*.py")) if p.name not in gui]


def timing_files() -> list[Path]:
    """Files holding a test that asserts an upper bound on elapsed time.

    Found by reading, for the same reason `gui_files()` reads: asking
    pytest would import the modules, and the GUI ones build Tk roots.

    These are the tests a parallel run cannot host. A bound like
    `elapsed < 0.26` is a statement about the machine as much as about
    the code, and seven other pytest processes competing for the same
    cores make it false without anything being wrong. That already
    happened twice here against a 0.8 s bound - two separate
    investigations, both concluding the code was fine - which is the
    cost this marker exists to stop paying.

    A lower bound (`elapsed >= 0.19`) is not affected and is not marked:
    contention can only make it more true.
    """
    out = []
    for path in sorted(TESTS.glob("test_*.py")):
        if "@pytest.mark.timing" in path.read_text(encoding="utf-8"):
            out.append(path)
    return out


def shard(items: list[Path], n: int) -> list[list[Path]]:
    """Deal `items` round-robin into at most `n` non-empty groups.

    Round-robin rather than contiguous slices because the files are
    sorted by name and cost is not distributed by name: dealing spreads
    the slow ones instead of landing them in one shard that then decides
    how long the whole run takes.
    """
    n = max(1, min(n, len(items)))
    buckets: list[list[Path]] = [[] for _ in range(n)]
    for i, item in enumerate(items):
        buckets[i % n].append(item)
    return [b for b in buckets if b]


def worker_count(argv: list[str]) -> int:
    """How many groups may run at once.

    `--jobs N`, else `SMU_JOBS`, else `RESERVED_CORES` fewer than the
    machine has, capped at `MAX_WORKERS`.

    The reserve is the point: this suite is run on the bench machine
    while somebody is using it, and a runner that takes every core makes
    the desk unusable for the ten minutes it holds them. Leaving cores
    idle is the feature.

    The cap on top of that is not about cores at all. Every group is a
    fresh interpreter importing numpy, scipy and matplotlib, so what
    runs out first is memory and disk bandwidth, and past a point more
    workers only lengthens the slowest group.

    **`--jobs 1` is not merely the slow path - it is the reference
    one.** It runs exactly the groups this runner has always run, in
    exactly the order, with no sharding and no separate timing phase,
    so a result that differs between `--jobs 1` and `--jobs 8` is
    evidence about the parallelism rather than about the code. CI uses
    it deliberately.
    """
    value = None
    if "--jobs" in argv:
        i = argv.index("--jobs")
        if i + 1 < len(argv):
            value = argv[i + 1]
    else:
        for arg in argv:
            if arg.startswith("--jobs="):
                value = arg.split("=", 1)[1]
    if value is None:
        value = os.environ.get("SMU_JOBS", "auto")
    if value == "auto":
        return max(1, min((os.cpu_count() or 1) - RESERVED_CORES,
                          MAX_WORKERS))
    try:
        return max(1, int(value))
    except ValueError:
        # `from None`: a mistyped --jobs is a usage error, and the
        # ValueError underneath it says nothing the message does not.
        raise SystemExit(
            f"--jobs wants a number or 'auto', got {value!r}") from None


def run(args: list[str], label: str,
        timeout_s: float | None = None) -> tuple[int, str]:
    # Announced before it starts, not only when it finishes.
    #
    # print() to a pipe is block-buffered, and a whole run's output is
    # far under one buffer, so under CI nothing appeared until the
    # process exited. A group that never exits therefore produced an
    # empty log: identical whether it hung in the first group or the
    # last. flush=True is what makes the start line arrive in time to be
    # the thing that identifies it.
    print(f"  ....  {label}", flush=True)
    if timeout_s is None:
        timeout_s = GROUP_TIMEOUT_S
    started = time.perf_counter()
    # PYTHONDONTWRITEBYTECODE, because a stale `.pyc` can hide a change
    # to the source.
    #
    # CPython decides a cached `.pyc` is still good by comparing the
    # source file's **mtime and size**. Neither changes when an edit
    # swaps one string for another of the same length inside the same
    # mtime tick - `"0.1.0"` for `"0.2.0"`, `>=` for `<=`, `1e-3` for
    # `1e-9` - so the old bytecode keeps running against new source.
    #
    # That is a nuisance in ordinary work and a real hazard here,
    # because the house rule is to mutate the code and confirm a test
    # goes red. A masked mutation makes a perfectly good test look like
    # it proves nothing, and the natural response - rewrite the test
    # until it "catches" something - makes the suite worse. It cost
    # three mutation rounds in Wave 7b before it was spotted.
    #
    # Turning the cache off costs a recompile per subprocess, which is
    # small against the suite's runtime, and buys the guarantee that
    # what ran is what is on disk.
    # PYTHONUNBUFFERED, so that a group killed for exceeding its budget
    # still hands back the output it had produced. Without it the child's
    # own buffer dies with the child and a hang reports nothing about
    # where it got to.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    timed_out = False
    try:
        proc = subprocess.run([sys.executable, "-m", "pytest", *args],
                              cwd=ROOT, text=True, capture_output=True,
                              env=env, timeout=timeout_s)
        returncode, stdout = proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = TIMEOUT_RC
        # text=True makes these str, but TimeoutExpired carries whatever
        # had been read, which is None if that is nothing at all.
        stdout = exc.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
    elapsed = time.perf_counter() - started
    summary = ""
    for line in reversed(stdout.splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            summary = line.strip("= ")
            break
    status = {0: "PASS", 5: "SKIP", TIMEOUT_RC: "TIMEOUT"}.get(
        returncode, "FAIL")
    if returncode == 5:
        # exit code 5 is "no tests collected" - the whole file was
        # deselected by the active marker expression, not a failure
        summary = "deselected by marker"
    if timed_out:
        summary = f"killed after {timeout_s:.0f}s without finishing"
    print(f"  {status:<7} {label:<34} {elapsed:6.1f}s  {summary}", flush=True)
    if returncode not in (0, 5):
        # On a timeout this is the only record of how far the group got.
        print(stdout[-4000:] if stdout else "(the group produced no output)",
              file=sys.stderr, flush=True)
    return returncode, summary


def main() -> int:
    # Everything the runner does not consume is handed to pytest - that
    # is how `-k`, `-x` and `--lf` work here. So an option the runner
    # owns has to be removed explicitly, including the value after it:
    # a stray "12" left behind is read by pytest as a path to collect.
    extra = []
    drop_next = False
    for arg in sys.argv[1:]:
        if drop_next:
            drop_next = False
            continue
        if arg in ("--all", "--slow-only"):
            continue
        if arg == "--jobs":
            drop_next = True
            continue
        if arg.startswith("--jobs="):
            continue
        extra.append(arg)
    if "--slow-only" in sys.argv:
        marker = "slow"
    elif "--all" in sys.argv:
        marker = ""
    else:
        marker = "not slow"

    def with_marker(*extra_terms: str) -> list[str]:
        terms = [t for t in (marker, *extra_terms) if t]
        return ["-m", " and ".join(terms)] if terms else []

    def name(label: str, rc: int) -> str:
        # A timeout and a failure need different responses - one is a
        # test that disagrees with the code, the other is a group that
        # never got as far as an opinion - so the summary line says
        # which, rather than reporting both as "FAILED".
        return f"{label} (timed out)" if rc == TIMEOUT_RC else label

    jobs = worker_count(sys.argv[1:])
    failures: list[str] = []
    files = gui_files()

    # exit code 5 is "no tests collected", which is expected when a
    # whole file is deselected by the active marker expression.
    # A timed-out group is recorded and the run continues, so one
    # run names every group that hung rather than only the first.
    def record(label: str, rc: int) -> None:
        if rc not in (0, 5):
            failures.append(name(label, rc))

    if jobs == 1:
        # The reference path, unchanged: one non-GUI process, then one
        # process per GUI file, in order. No sharding and no separate
        # timing phase - nothing competes for the machine, so the
        # wall-clock bounds hold where they are written.
        print("non-GUI tests (one process):", flush=True)
        rc, _ = run(["-q", "--no-header", *with_marker("not gui"), *extra],
                    "tests/ [not gui]")
        if rc:
            failures.append(name("non-GUI suite", rc))

        print()
        print(f"GUI tests ({len(files)} files, one process each):",
              flush=True)
        for path in files:
            rc, _ = run(["-q", "--no-header", str(path.relative_to(ROOT)),
                         *with_marker(), *extra], path.name)
            record(path.name, rc)
    else:
        timed = timing_files()
        # `jobs - 1`, so the GUI pool is taken *out of* the budget
        # rather than added on top of it: --jobs 2 has to mean two
        # processes, not two plus the GUI allowance. Whatever is left
        # shards the non-GUI files, which are CPU-bound and do share a
        # machine, so they get the wide half.
        gui_jobs = max(1, min(GUI_WORKERS, jobs - 1))
        shard_jobs = max(1, jobs - gui_jobs)

        shards = shard(non_gui_files(), shard_jobs)
        shard_groups = [
            ([*(str(f.relative_to(ROOT)) for f in bucket),
              *with_marker("not gui", "not timing")],
             f"non-GUI shard {i}")
            for i, bucket in enumerate(shards, start=1)]
        gui_groups = [
            ([str(path.relative_to(ROOT)), *with_marker("not timing")],
             path.name)
            for path in files]

        print(f"{len(shard_groups)} non-GUI shards on {shard_jobs} "
              f"workers, {len(gui_groups)} GUI files on {gui_jobs}:",
              flush=True)

        def submit(pool, groups):
            return {pool.submit(run, ["-q", "--no-header", *args, *extra],
                                label): label
                    for args, label in groups}

        # Two pools, running at the same time: the shards finish early
        # and hand their cores back, and the GUI files - which set the
        # run's length - never have more than `gui_jobs` of themselves
        # competing, whatever else is happening.
        with cf.ThreadPoolExecutor(max_workers=shard_jobs) as fast,                 cf.ThreadPoolExecutor(max_workers=gui_jobs) as slow:
            futures = {**submit(fast, shard_groups),
                       **submit(slow, gui_groups)}
            for future in cf.as_completed(futures):
                record(futures[future], future.result()[0])

        # Serial, one file at a time, nothing else running. A GUI file
        # still gets its own process here for the reason it always does
        # - the Tk runtime, not the clock.
        if timed:
            print()
            print(f"timing tests ({len(timed)} files, serially):",
                  flush=True)
            for path in timed:
                label = f"{path.name} [timing]"
                rc, _ = run(["-q", "--no-header",
                             str(path.relative_to(ROOT)),
                             *with_marker("timing"), *extra], label)
                record(label, rc)

    print()
    if failures:
        print(f"FAILED: {', '.join(failures)}", flush=True)
        return 1
    print("All groups passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
