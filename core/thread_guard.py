"""
A diagnostic that answers "is anything still reading Tk from a worker?"
(review §14, group B2).

Why this is a diagnostic and not a fix
--------------------------------------
The project rule from Wave 0 is that a fix for a fault you cannot
reproduce on demand is a guess, and that the thing to build instead is
something that can return a fact. "No worker thread touches a Tk
variable" is exactly that shape of claim: it is easy to assert in a
docstring, easy to believe after a code review, and impossible to prove
by reading, because the offending call is usually three frames down
inside a helper that looks harmless.

Tk's own failure mode makes this worse. Calling into a Tcl interpreter
from the wrong thread does not reliably raise. It usually works. It
works on the bench for weeks and then produces a hang, or a `RuntimeError:
main thread is not in main loop`, or a value from the wrong widget - at
which point the stack trace points at the symptom, not at the call that
broke the rule.

So this does not prevent anything. It **records** - which call, which
thread, which stack - and lets the caller decide whether that is a log
line or an exception.

The analogy
-----------
A tell-tale on a pressure vessel. It does not hold the pressure in; it
tells you afterwards, unambiguously, that the limit was passed, so you
stop arguing about whether it was.

Using it
--------
Off by default. Wave 3 turns it on in the demo-mode cancellation matrix,
where every code path runs and no instrument is at risk::

    from core.thread_guard import ThreadAffinityGuard, install_tk_guard

    guard = install_tk_guard(strict=False)     # log only
    ...                                         # exercise the experiment
    assert not guard.violations, guard.report()

Or set `SMULAB_TK_THREAD_GUARD=1` in the environment before starting the
app, which installs it in logging mode for a bench session.

`strict=True` raises `ThreadAffinityError` at the offending call instead
of recording it. That is the right mode for a test and the wrong mode
for a bench session: a raise inside a worker turns a provenance bug into
an aborted measurement, which is a worse outcome than a wrong label on a
run you can repeat.

Why it patches a class you hand it
----------------------------------
`install_tk_guard()` is a thin wrapper that passes `tkinter.Variable`.
The machinery itself takes any class, which means the whole of this
module is testable with a five-line stand-in and without a display - so
`tests/test_thread_guard.py` runs in `run_tests.py`'s fast shared
process rather than needing a Tk root and a process of its own.
"""
from __future__ import annotations

import os
import threading
import traceback
from dataclasses import dataclass


class ThreadAffinityError(RuntimeError):
    """Raised by a strict guard when a guarded call crosses threads."""


@dataclass(frozen=True)
class Violation:
    """One guarded call made from the wrong thread."""

    method: str
    thread_name: str
    owner_thread_name: str
    stack: tuple

    def where(self):
        """The application frame that made the call.

        Walks outwards past this module's own frames, so the report
        names the experiment line responsible rather than the wrapper
        that caught it.
        """
        for frame in reversed(self.stack):
            if "core/thread_guard.py" not in frame.replace("\\", "/"):
                return frame.strip()
        return self.stack[-1].strip() if self.stack else "<unknown>"

    def __str__(self):
        return (f"{self.method}() called from thread "
                f"{self.thread_name!r} (owner: {self.owner_thread_name!r})"
                f"\n    at {self.where()}")


class ThreadAffinityGuard:
    """Records calls to `methods` on `target` made off the owning thread.

    The owning thread is whichever thread installs the guard, not
    `main_thread()`. They are the same in this application, but tying
    the check to the installing thread means the guard is still correct
    if a Tk root is ever built somewhere else, and means the test suite
    can install one from a fixture thread.
    """

    def __init__(self, target, methods=("get", "set"), strict=False,
                 log=None):
        self.target = target
        self.methods = tuple(methods)
        self.strict = strict
        self.log = log
        self.owner = threading.current_thread()
        self.violations = []
        self.calls = 0                     # total guarded calls, for context
        self._originals = {}
        self._lock = threading.Lock()
        self._installed = False

    # ---- lifecycle ----
    def install(self):
        if self._installed:
            return self
        for name in self.methods:
            original = getattr(self.target, name)
            self._originals[name] = original
            setattr(self.target, name, self._wrap(name, original))
        self._installed = True
        return self

    def remove(self):
        """Put the original methods back.

        Always call this - a guard left installed on `tkinter.Variable`
        outlives the test that installed it and slows every widget read
        in the process afterwards.
        """
        if not self._installed:
            return
        for name, original in self._originals.items():
            setattr(self.target, name, original)
        self._originals.clear()
        self._installed = False

    def __enter__(self):
        return self.install()

    def __exit__(self, exc_type, exc, tb):
        self.remove()
        return False

    # ---- the wrapper ----
    def _wrap(self, name, original):
        def guarded(*args, **kwargs):
            current = threading.current_thread()
            with self._lock:
                self.calls += 1
            if current is not self.owner:
                self._record(name, current)
            return original(*args, **kwargs)

        guarded.__name__ = getattr(original, "__name__", name)
        guarded.__doc__ = getattr(original, "__doc__", None)
        guarded.__wrapped__ = original
        return guarded

    def _record(self, name, thread):
        # The stack is captured here rather than at reporting time
        # because by the time anybody reads the report the worker has
        # long since unwound, and a violation without a stack tells you
        # only that the rule was broken somewhere.
        violation = Violation(
            method=name,
            thread_name=thread.name,
            owner_thread_name=self.owner.name,
            stack=tuple(traceback.format_stack()[:-2]),
        )
        with self._lock:
            self.violations.append(violation)
        if self.log:
            try:
                self.log(f"[thread-guard] {violation}")
            except Exception:
                # Cleanup-only: a diagnostic must not break a run. The
                # violation is already in `self.violations` above, which
                # is what the reports read, and `strict` still raises
                # below - so losing the console line loses neither the
                # record nor the refusal.
                pass
        if self.strict:
            raise ThreadAffinityError(str(violation))

    # ---- reporting ----
    def report(self):
        """Every violation, grouped by call site, newest last."""
        if not self.violations:
            return (f"No cross-thread access in {self.calls} guarded "
                    f"call(s).")
        by_site = {}
        for v in self.violations:
            by_site.setdefault(v.where(), []).append(v)
        lines = [f"{len(self.violations)} cross-thread access(es) in "
                 f"{self.calls} guarded call(s):"]
        for site, group in by_site.items():
            threads = sorted({v.thread_name for v in group})
            lines.append(f"  {len(group)}x from {', '.join(threads)}")
            lines.append(f"      {site}")
        return "\n".join(lines)

    def clear(self):
        with self._lock:
            self.violations.clear()
            self.calls = 0


def install_tk_guard(strict=False, log=None):
    """Guard `tkinter.Variable.get` and `.set`. Returns the guard.

    `tkinter` is imported here rather than at module scope so that this
    module can be imported - and tested - in an environment with no Tk
    at all, which is what a headless CI container is.
    """
    import tkinter

    return ThreadAffinityGuard(tkinter.Variable, ("get", "set"),
                               strict=strict, log=log).install()


def install_from_environment(log=None):
    """Install a logging guard if `SMULAB_TK_THREAD_GUARD` is set.

    Returns the guard, or None if the variable is unset or empty. Lets a
    bench session be run with the tell-tale on without editing any code:

        set SMULAB_TK_THREAD_GUARD=1
        uv run python main.py
    """
    flag = os.environ.get("SMULAB_TK_THREAD_GUARD", "").strip().lower()
    if flag in ("", "0", "false", "no"):
        return None
    return install_tk_guard(strict=flag in ("strict", "raise"), log=log)
