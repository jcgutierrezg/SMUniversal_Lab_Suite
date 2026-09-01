#!/usr/bin/env python
"""Run the test suite with GUI files isolated in their own processes.

Why this exists
---------------
Eleven test files build real Tk windows. Run them all in one pytest
process and the suite creates 21 Tk interpreters against a single shared
Tcl runtime. On Windows that runtime does not survive it: somewhere past
the tenth or so, tk.Tk() starts failing in ways that have nothing to do
with the test that hits them - "invalid command name tcl_findLibrary" on
one Python build, "couldn't read file spinbox.tcl" (about a file that
demonstrably exists) on another. Both are the same underlying breakage
wearing different messages, and both are non-deterministic, so they
surface as an unrelated test failing at random.

Before the suite was converted to pytest it was 25 separate scripts, so
each process built at most three roots and then exited. Process
isolation was doing real work; it was just doing it by accident. This
runner does it on purpose:

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

Each group is bounded: one that stops making progress is killed, named
and reported, and the remaining groups still run. `SMU_GROUP_TIMEOUT_S`
overrides the budget in seconds.
"""
from __future__ import annotations

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
    extra = [a for a in sys.argv[1:]
             if a not in ("--all", "--slow-only")]
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

    failures: list[str] = []
    print("non-GUI tests (one process):", flush=True)
    rc, _ = run(["-q", "--no-header", *with_marker("not gui"), *extra],
                "tests/ [not gui]")
    if rc:
        failures.append(name("non-GUI suite", rc))

    files = gui_files()
    print(f"\nGUI tests ({len(files)} files, one process each):", flush=True)
    for path in files:
        rc, _ = run(["-q", "--no-header", str(path.relative_to(ROOT)),
                     *with_marker(), *extra], path.name)
        # exit code 5 is "no tests collected", which is expected when a
        # whole file is deselected by the active marker expression.
        # A timed-out group is recorded and the run continues, so one
        # run names every group that hung rather than only the first.
        if rc not in (0, 5):
            failures.append(name(path.name, rc))

    print()
    if failures:
        print(f"FAILED: {', '.join(failures)}", flush=True)
        return 1
    print("All groups passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
