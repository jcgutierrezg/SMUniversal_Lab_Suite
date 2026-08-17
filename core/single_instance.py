"""One copy of the application per machine.

Why this exists
---------------
`core/ownership.py` stops two *experiments in one process* from claiming
the same instrument. It is a Python object, so it knows nothing about a
second copy of the application, and a second copy is the worse case:
two processes would each open the same VISA resource and each believe it
controls the output state. One would happily leave a sample energised
while the other reported that Stop had completed.

`SampleRegistry` has the same blind spot for a milder reason - two
processes would mint different `sample_id`s for the same physical
sample, and the files would never join up.

The design question, and why it is about crashes
------------------------------------------------
The obvious implementation is a file whose *existence* means "running":
create it at startup, delete it on exit. That is a note pinned to the
door saying *I am in here*. It works right up until the process dies
without tidying up - a crash, Task Manager, a power cut - and then the
note stays pinned forever and the application refuses to start on a
machine where nothing is running.

Every fix for that makes it worse. Store the PID and check whether it is
alive? PIDs are reused, so eventually the note names some unrelated
process and the app locks itself out anyway - or, if the number happens
to be free, unlocks when it should not. Add a timestamp and ignore old
notes? Now the lock has an expiry, and a long measurement outlives it.

So the note is the wrong object. What is wanted is a lock **the
operating system holds on your behalf**: not a note on the door, but the
OS holding the door shut. The OS releases it when the process ends, for
any reason at all, including the ones that skip your cleanup code. A
crash cannot leave a stale lock because there is nothing written down to
go stale.

Both platforms provide exactly this:

  * Windows - `msvcrt.locking(fd, LK_NBLCK, 1)`
  * Linux and macOS - `fcntl.flock(fd, LOCK_EX | LOCK_NB)`

The file is only somewhere for the lock to live. Its contents are never
read and its survival across reboots means nothing.

Where the file lives, and the network-share question
-----------------------------------------------------
On the machine, never beside the application.

Two reasons, and the second is the one that was asked about. Advisory
locks over SMB and NFS are unreliable - the guarantee is weak, varies by
server, and can silently degrade to no lock at all, which would leave
this module reporting success while protecting nothing. And if the
application lives on a share used by several benches, a lock file beside
it would be shared *between machines*, so bench B could not start while
bench A was running. That is not the rule anyone wants.

Putting it under `%LOCALAPPDATA%` (Windows) or `~/.local/state` (POSIX)
makes the rule "one copy per machine", which is the right proxy for the
hazard: the instruments are attached to a machine. `LOCALAPPDATA` rather
than `APPDATA` specifically, because roaming profiles synchronise
between machines and a lock that follows a user around is nonsense.

What this deliberately does not do
-----------------------------------
It does not identify the other instance, focus its window, or offer to
take over. Naming the holder means writing a PID down, which reintroduces
the staleness this design exists to avoid, for a nicer dialog.

It is also per *machine*, not per instrument - so a second copy is
refused even when it would have driven a different SMU. That follows
from the decision recorded in `docs/plan.md`, and it is worth knowing at
the bench: running the 4PP and an IV sweep simultaneously means two
machines, not two windows.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: The lock filename. Not a secret and not read - only locked.
LOCK_FILENAME = "smuniversal_lab_suite.lock"

#: Used to build the per-machine state directory.
APP_DIRNAME = "SMUniversal_Lab_Suite"


class AlreadyRunning(RuntimeError):
    """Another copy of the application holds the lock on this machine."""


def lock_directory(platform=None, environ=None, home=None):
    """Where the lock file lives. Answers the question; creates nothing.

    Honours the platform convention rather than inventing one, so the
    file lands where a system administrator would look for it and gets
    cleaned up by the same tools.

    Purely a query, and that is a correction rather than a preference.
    It used to `mkdir(parents=True)` on the way out, which meant that
    *asking where the lock lives* made directories - including for
    callers with no intention of writing anything. `default_log_path()`
    in `core/event_log.py` calls this, so constructing an `EventLog`, or
    printing a diagnostic, or building documentation, silently created a
    tree.

    Windows CI found it. A test set `LOCALAPPDATA` to a path under
    `C:\\Users\\test`, and `parents=True` walked up and tried to create
    `C:\\Users\\test` itself - which the ACL on `C:\\Users` refuses.
    `PermissionError: [WinError 5]`, from a function whose name promises
    to look something up. On Linux the same call had been quietly
    creating directories for real, where nothing objected and nothing
    noticed.

    A function named for a question should not have side effects; the
    caller that actually writes creates what it needs, which is
    `SingleInstance.acquire()` here and `EventLog.record()` there.

    The arguments exist so both branches can be exercised on either
    platform, and that is the more important half of the fix. The bug
    above shipped because the only test of the Windows branch began
    `if sys.platform != "win32": skip` - so on the machine where the
    code was written it never ran at all, and the first thing to
    execute it was Windows CI. A branch that can only be tested on the
    platform you cannot run is a branch nobody tests.

    Defaults are read at call time rather than at import, so a test that
    patches the environment does not have to reload the module.
    """
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)

    if platform == "win32":
        # LOCALAPPDATA, never APPDATA. Roaming profiles synchronise
        # between machines, and a lock that follows a user from bench to
        # bench would refuse to start where nothing is running.
        base = environ.get("LOCALAPPDATA") or environ.get("TEMP")
        root = Path(base) if base else home
    else:
        base = environ.get("XDG_STATE_HOME")
        root = Path(base) if base else home / ".local" / "state"
    return root / APP_DIRNAME


def _lock_fileno(handle):
    """Take the OS lock, or raise `BlockingIOError`/`OSError`.

    Both calls are the *non-blocking* variants on purpose. A blocking
    lock would make a second launch hang with no window and no message,
    which is indistinguishable from the application being broken.
    """
    if sys.platform == "win32":
        import msvcrt
        handle.seek(0)
        # One byte at offset 0 is the whole protocol. Locking a region
        # rather than the file is what Windows offers; the region just
        # has to be the same one every time.
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_fileno(handle):
    if sys.platform == "win32":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class SingleInstance:
    """Holds the machine-wide lock for as long as it is open.

    Usable as a context manager. The file handle is kept as an attribute
    and that is load-bearing rather than tidy: closing the handle
    releases the lock, so letting it be garbage-collected would drop the
    lock while the application was still running - and nothing would
    report it. The next launch would simply succeed.
    """

    def __init__(self, path=None):
        self.path = Path(path) if path else lock_directory() / LOCK_FILENAME
        self._handle = None

    @property
    def held(self):
        return self._handle is not None

    def acquire(self):
        """Take the lock, or raise `AlreadyRunning`.

        The file is opened `a+b` and padded to one byte before locking,
        because Windows locks a byte *range* and the range has to exist.
        Appending never truncates, so a concurrent launch cannot empty
        the file out from under the holder.
        """
        if self.held:
            return self
        # Created here, by the caller that actually writes, rather than
        # by `lock_directory()` - see that function for what went wrong
        # when the query created it instead.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            _lock_fileno(handle)
        except OSError as exc:
            handle.close()
            raise AlreadyRunning(
                f"Another copy of the application is running on this "
                f"machine (lock: {self.path})") from exc
        except BaseException:
            handle.close()
            raise
        self._handle = handle
        return self

    def release(self):
        """Give the lock up. Safe to call twice.

        Rarely needed - the OS does this when the process ends, which is
        the whole point of the design - but an explicit release keeps
        tests honest and lets a launcher retry.
        """
        if not self.held:
            return
        handle, self._handle = self._handle, None
        try:
            _unlock_fileno(handle)
        except OSError:
            # Closing releases it regardless; an error here would be
            # noise on a path that is already succeeding.
            pass
        finally:
            handle.close()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False
