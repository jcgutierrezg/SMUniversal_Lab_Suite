"""Only one copy of the application per machine, proved across processes.

The property under test is inherently cross-process, so most of these
spawn a real child. An in-process test would be near-worthless here: a
second `SingleInstance` in the *same* process can be excluded by all
sorts of accidents - a module-level flag, a re-entrant guard, an object
that happens to still be alive - none of which would stop a second
copy of the application. The interesting answer is the one a separate
process gives.

The crash case gets the same treatment for the same reason. A lock that
survives `SIGKILL` is indistinguishable from a working lock right up
until a machine crashes mid-run, and then the application refuses to
start on a bench where nothing is running. So the child is killed
outright - no cleanup, no `finally`, no atexit - and the parent has to
be able to take the lock afterwards.

Nothing here sleeps. Every wait is on a fact: a line of output the child
prints, or `Popen.wait()` returning.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.single_instance import (APP_DIRNAME, AlreadyRunning,  # noqa: E402
                                  LOCK_FILENAME, SingleInstance,
                                  lock_directory)


#: Child that takes the lock, says so, and waits to be told to stop.
#: It reports on stdout because that is a fact the parent can wait for -
#: the alternative, sleeping and hoping the lock is held by now, is the
#: timing-dependent test this suite refuses to contain.
HOLDER = """
import sys
sys.path.insert(0, {root!r})
from core.single_instance import SingleInstance
lock = SingleInstance({path!r}).acquire()
print("HELD", flush=True)
sys.stdin.readline()
"""

#: Child that tries once and reports which way it went.
CONTENDER = """
import sys
sys.path.insert(0, {root!r})
from core.single_instance import AlreadyRunning, SingleInstance
try:
    SingleInstance({path!r}).acquire()
except AlreadyRunning:
    print("REFUSED", flush=True)
else:
    print("ACQUIRED", flush=True)
"""


def _spawn(source, path):
    return subprocess.Popen(
        [sys.executable, "-c", source.format(root=str(ROOT), path=str(path))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)


def _contend(path):
    """Run a second process against `path` and return its verdict."""
    out = subprocess.run(
        [sys.executable, "-c",
         CONTENDER.format(root=str(ROOT), path=str(path))],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


@pytest.fixture
def lock_path(tmp_path):
    return tmp_path / "test.lock"


# ------------------------------------------------------------------
# the property, across processes
# ------------------------------------------------------------------

def test_a_second_process_is_refused_while_the_first_holds_it(check, lock_path):
    """The whole point of the module.

    Two copies would each open the same VISA resources and each believe
    it controlled the output state - one could leave a sample energised
    while the other reported Stop complete.
    """
    path = lock_path
    holder = _spawn(HOLDER, path)
    try:
        check("the first process took the lock",
              holder.stdout.readline().strip() == "HELD")
        check("the second was refused", _contend(path) == "REFUSED")
    finally:
        holder.stdin.write("\n")
        holder.stdin.flush()
        holder.wait(timeout=60)


def test_the_lock_is_available_once_the_first_process_exits(check, lock_path):
    """The other half, and the one a broken lock passes without.

    A lock that is never released looks identical to a working one from
    the refusal test alone. Closing the bench software must not require
    a reboot.
    """
    path = lock_path
    holder = _spawn(HOLDER, path)
    check("the first process took the lock",
          holder.stdout.readline().strip() == "HELD")

    holder.stdin.write("\n")
    holder.stdin.flush()
    holder.wait(timeout=60)          # a fact, not a sleep

    check("a later process may take it", _contend(path) == "ACQUIRED")


def test_a_killed_process_does_not_leave_the_lock_stuck(check, lock_path):
    """The crash case, which is why the OS holds the lock.

    `SIGKILL` - `TerminateProcess` on Windows - runs no cleanup at all:
    no `finally`, no `atexit`, no `__exit__`. A lock implemented as "a
    file exists" would survive this and lock the bench out of its own
    software until somebody knew to delete a file they had never heard
    of.

    Because the OS owns the lock, there is nothing to go stale.
    """
    path = lock_path
    holder = _spawn(HOLDER, path)
    check("the first process took the lock",
          holder.stdout.readline().strip() == "HELD")

    holder.kill()
    holder.wait(timeout=60)

    check("the lock file is still on disk", path.exists(),
          "its existence is not what excludes anyone")
    check("and the lock is nonetheless free", _contend(path) == "ACQUIRED")


# ------------------------------------------------------------------
# the object's own behaviour
# ------------------------------------------------------------------

def test_release_then_reacquire_in_one_process(check, lock_path):
    lock = SingleInstance(lock_path)
    lock.acquire()
    check("held after acquire", lock.held)
    lock.release()
    check("not held after release", not lock.held)
    lock.acquire()
    check("and it can be taken again", lock.held)
    lock.release()


def test_acquire_is_idempotent_for_its_own_holder(check, lock_path):
    """Calling it twice must not release or double-lock.

    Not a hypothetical: a launcher that retries, or a future headless
    entry point that also guards itself, would do exactly this.
    """
    lock = SingleInstance(lock_path)
    try:
        lock.acquire()
        lock.acquire()
        check("still held", lock.held)
        check("and still excludes a second process",
              _contend(lock_path) == "REFUSED")
    finally:
        lock.release()


def test_release_is_safe_when_nothing_is_held(check, lock_path):
    lock = SingleInstance(lock_path)
    lock.release()
    lock.release()
    check("no exception, and nothing is held", not lock.held)


def test_the_context_manager_releases_on_the_way_out(check, lock_path):
    with SingleInstance(lock_path) as lock:
        check("held inside the block", lock.held)
        check("and it excludes another process while inside",
              _contend(lock_path) == "REFUSED")
    check("released on the way out", _contend(lock_path) == "ACQUIRED")


def test_an_exception_inside_the_block_still_releases(check, lock_path):
    """Otherwise a startup error would lock the machine until reboot."""
    with pytest.raises(ValueError):
        with SingleInstance(lock_path):
            raise ValueError("boom")
    check("the lock is free afterwards", _contend(lock_path) == "ACQUIRED")


# ------------------------------------------------------------------
# where the file goes
# ------------------------------------------------------------------

def test_the_lock_lives_on_the_machine_not_beside_the_application(check):
    """The network-share answer, pinned.

    Advisory locks over SMB and NFS are unreliable, and a lock file
    beside an application on a shared drive would be shared *between
    benches* - so bench B could not start while bench A was running.
    Keeping it in per-machine state makes the rule "one copy per
    machine", which is the right proxy: the instruments are attached to
    a machine.
    """
    directory = lock_directory()
    check("it is not inside the source tree",
          ROOT not in directory.parents and directory != ROOT,
          str(directory))
    check("it is namespaced to this application",
          APP_DIRNAME in directory.parts, str(directory))


def test_computing_the_lock_directory_creates_nothing(check, tmp_path):
    """The regression test for the Windows CI failure, on every platform.

    `lock_directory()` used to `mkdir(parents=True)` on its way out, so
    *asking where the lock lives* made directories. On Linux that was
    invisible - it created them, nothing objected. On Windows a test
    pointed `LOCALAPPDATA` at a path under `C:\\Users\\test`,
    `parents=True` walked up to create `C:\\Users\\test` itself, and the
    ACL on `C:\\Users` refused: `PermissionError: [WinError 5]`, raised
    by a function whose name promises to look something up.

    `core/event_log.py` calls it too, so constructing an `EventLog` -
    or printing a diagnostic, or building the documentation - was
    silently creating a tree as well.

    Runs everywhere now, which is the point.
    """
    for platform in ("win32", "linux", "darwin"):
        target = tmp_path / platform
        directory = lock_directory(
            platform=platform,
            environ={"LOCALAPPDATA": str(target), "XDG_STATE_HOME": str(target)},
            home=target)
        check(f"{platform}: a path is returned", directory is not None)
        check(f"{platform}: and nothing was created",
              not target.exists(), f"{target} appeared")


def test_the_windows_branch_prefers_local_appdata_over_roaming(check, tmp_path):
    """Roaming profiles synchronise between machines.

    A lock that follows a user from bench to bench would refuse to start
    on a machine where nothing is running - the exact failure this
    design exists to avoid, reintroduced by one word in an environment
    variable name.

    Exercised on whatever platform is running this, because the previous
    version skipped unless `sys.platform == "win32"` and therefore never
    ran on the machine where the code was written. That is how the
    `mkdir` fault above reached CI in the first place: the branch had a
    test, and the test could not run.
    """
    local = tmp_path / "AppData" / "Local"
    roaming = tmp_path / "AppData" / "Roaming"
    directory = lock_directory(
        platform="win32",
        environ={"LOCALAPPDATA": str(local), "APPDATA": str(roaming)},
        home=tmp_path)
    check("under Local", "Local" in directory.parts, str(directory))
    check("not under Roaming", "Roaming" not in directory.parts,
          str(directory))


def test_the_windows_branch_falls_back_to_temp_then_home(check, tmp_path):
    """A machine with no LOCALAPPDATA must still start.

    Rare, but it happens under service accounts and some CI images. The
    fallback matters more than where it lands: refusing to launch
    because an environment variable is missing would be a worse failure
    than putting the lock somewhere unusual.
    """
    temp = tmp_path / "Temp"
    check("falls back to TEMP",
          str(temp) in str(lock_directory(platform="win32",
                                          environ={"TEMP": str(temp)},
                                          home=tmp_path)))
    check("and to the home directory when even that is absent",
          str(tmp_path) in str(lock_directory(platform="win32", environ={},
                                              home=tmp_path)))


def test_the_posix_branch_honours_xdg_state_home(check, tmp_path):
    """The equivalent convention, and its documented default."""
    state = tmp_path / "state"
    check("XDG_STATE_HOME is used when set",
          str(state) in str(lock_directory(platform="linux",
                                           environ={"XDG_STATE_HOME": str(state)},
                                           home=tmp_path)))
    fallback = lock_directory(platform="linux", environ={}, home=tmp_path)
    check("and ~/.local/state is the default",
          fallback.parts[-3:-1] == (".local", "state"), str(fallback))


def test_the_default_lock_file_is_named_predictably(check):
    """So it can be found, described in a note, and excluded from backups."""
    check("a stable filename", LOCK_FILENAME.endswith(".lock"), LOCK_FILENAME)


# ------------------------------------------------------------------
# and the launcher uses it
# ------------------------------------------------------------------

def test_the_launcher_takes_the_lock_before_building_a_window(check):
    """Order matters: a refused launch must not flash a window first.

    Checked on the source because running the launcher opens a real
    window. Crude, but it pins the one property a later edit could
    plausibly get wrong.

    Reads `core/launcher.py` rather than `main.py` as of Wave 7e, when
    the body moved there so a console script could name it. `main.py` is
    now a shim, and asserting against a shim would have quietly stopped
    testing anything.
    """
    text = (ROOT / "core" / "launcher.py").read_text(encoding="utf-8")
    check("the launcher acquires the lock", "SingleInstance()" in text)
    # Bound to a name, not discarded. `SingleInstance().acquire()` as a
    # bare expression takes the lock and then drops the only reference
    # to it, so the object is collected, the handle closes, and the lock
    # is released while the application is still running. Nothing would
    # report that - the next launch would simply be allowed.
    check("and keeps a reference, so it is not collected",
          "= SingleInstance()" in text,
          "the lock object is discarded; GC would release it")
    check("and refuses rather than continuing",
          "AlreadyRunning" in text and "sys.exit(1)" in text)
    acquire_at = text.index("SingleInstance()")
    check("before it launches a window",
          acquire_at < text.index("spec = pick_window()"),
          "the lock is taken after a window is built")


def test_main_py_still_runs_the_same_launcher(check):
    """The shim must actually reach the guarded path.

    `main.py` is what everyone types and what every note documents. If
    it stopped routing through `core.launcher.main`, the lock would be
    bypassed by the most common way of starting the application, and the
    test above would still pass.
    """
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    check("it imports the shared entry point",
          "from core.launcher import" in text and "main" in text, text)
    check("and calls it under __main__",
          "__main__" in text and "main()" in text, text)


def test_acquire_creates_the_directory_it_needs(check, tmp_path):
    """The other half of the Windows fix, and a hole mutation testing found.

    Moving `mkdir` out of `lock_directory()` only works if the caller
    that writes puts it back. Every other test here hands over a
    `tmp_path` that already exists, so removing that `mkdir` from
    `acquire()` broke nothing and the suite stayed green - on a first
    launch, on a machine that had never run the application, it would
    have raised `FileNotFoundError` before the lock was ever taken.

    That is the first-run path for every bench machine, so it is worth a
    test that does not hand it a directory.
    """
    nested = tmp_path / "never" / "existed" / "before"
    check("the parent really is absent to begin with", not nested.exists())

    lock = SingleInstance(nested / "app.lock")
    try:
        lock.acquire()
        check("the lock was taken", lock.held)
        check("and the directory was created", nested.is_dir(), str(nested))
    finally:
        lock.release()
