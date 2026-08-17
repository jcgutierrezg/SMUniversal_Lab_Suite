"""What happened to runs that produced no data.

Review §26. The finding is short and the consequence is not: *discarding
cancelled runs should not remove all evidence that a cancellation or
fault occurred.*

Today a run that is cancelled, or that fails, or - worst - that ends
with the output not confirmed off, produces a `TerminalStatus`, prints
one line to the console, appends to a fifty-entry in-memory ring, and is
gone when the window closes. Every one of §26's suggested fields is
already computed. None of them survives the session.

That is the whole of this module: a sink, not new logic.

Why it is a separate file from the data
---------------------------------------
Because the two are read by different people for different reasons, and
mixing them corrupts both. §26's boundary is explicit: no provisional
measurement readings in the operational log. A cancelled run's readings
are *discarded on purpose* - they are the readings taken before somebody
hit Stop, and a file containing them, sitting next to real exports, is
an invitation to a mistake nobody would make deliberately.

So this log records that a run happened and how it ended. It never
records what was measured. `tests/test_event_log.py` pins that by
putting a distinctive value in a run's readings and asserting it appears
nowhere in the log.

Why JSON Lines
--------------
One JSON object per line, appended, never rewritten.

The alternative was CSV, and this project has already paid for the
lesson that makes it wrong. A CSV log has a fixed column order, so
adding a field later means either a new column at the end (and readers
that index by position silently shift) or a schema dance for every
change. Wave 4's sentinel fault was exactly this shape: a column moved
and a current landed where a voltage was expected - a number of the
right form, wrong by a factor of resistance.

A JSON object has no column order. An old reader simply does not see a
new key, and cannot mistake it for a different one. For an append-only
diagnostic file that will certainly grow fields, that property is worth
more than being openable in Excel - and `pandas.read_json(lines=True)`
covers the Excel case anyway.

Where it lives, and why not beside the application
---------------------------------------------------
Per-machine state, alongside the single-instance lock, rather than in
the application folder.

The application folder was the original intention, chosen against the
obvious wrong answer of putting it in the results folder. The reasoning
still holds - operational records must not sit among scientific exports
where they can be loaded by mistake - but the destination no longer
works, for a reason that only became clear once the deployment target
was settled: a frozen executable installed under `Program Files` sits in
a directory ordinary users cannot write to, and one on a shared drive
would collect every bench's runs in one file, or fail on a read-only
share. Either way the log would fail to write at exactly the moment
something had gone wrong and it was most needed.

Per-machine state keeps it out of the data, keeps it writable, and keeps
one bench's log about one bench.

Failing to log must never fail a run
-------------------------------------
A full disk, a locked file, a permissions change - none of those are
reasons to turn a completed measurement into a failed one. Every write
is guarded, and a failure reports itself once to the operator console
and is then silent. This is the same rule house rule 11 applies to the
summary file: a secondary artefact that cannot be written must not take
the primary one down with it.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import threading
from collections.abc import Mapping
from pathlib import Path

from core.single_instance import lock_directory
from core.version import app_version

#: The log filename in the state directory.
LOG_FILENAME = "run-events.jsonl"

#: Rotate once the file passes this, keeping one previous generation.
#:
#: A line is a few hundred bytes, so this is on the order of ten
#: thousand runs - years of bench work - and the previous generation is
#: kept so a rotation in the middle of an investigation does not destroy
#: the thing being investigated.
MAX_BYTES = 5 * 1024 * 1024

#: Bumped when the meaning of a field changes. New fields do not need a
#: bump: a reader that does not know a key simply does not see it, which
#: is the reason for choosing JSON Lines over CSV.
EVENT_SCHEMA = 1


def parameter_fingerprint(parameters):
    """A short stable digest of the parameter snapshot.

    §26 asks for a "parameter snapshot hash" rather than the parameters
    themselves, and the distinction is the point: the question the log
    has to answer is *"were these two runs configured the same way?"*,
    which a digest answers exactly, without copying a settings dump into
    every line.

    Sorted keys, so two identical configurations built in a different
    order agree. `repr` rather than `json.dumps` because a parameter
    value may be any object an experiment cares to put there - a
    `SampleRef`, an enum - and this must never raise on the way to
    recording that something went wrong.
    """
    fields = _as_fields(parameters)
    if not fields:
        return ""
    try:
        items = sorted((str(k), _stable_repr(v)) for k, v in fields.items())
    except Exception:
        return ""
    digest = hashlib.sha256(repr(items).encode("utf-8", "replace"))
    return digest.hexdigest()[:16]


def _stable_repr(value, depth=0):
    """A representation that depends on the value, not on the object.

    Plain `repr` was the obvious choice and is wrong, which a test
    caught: an object without a custom `__repr__` renders as
    `<Thing object at 0x7f8ee638d400>`, so two runs configured
    identically produce different digests and the fingerprint answers
    nothing. It would have failed in the direction that looks like it
    works - a field full of plausible hex, never matching.

    So: primitives by value, containers element-wise, dataclasses and
    ordinary objects by their fields, and anything left by type name
    only. Bounded depth, because a parameter snapshot holding a
    reference back to the experiment must not turn a log write into a
    stack overflow.
    """
    if isinstance(value, (str, int, float, bool, type(None))):
        return repr(value)
    if depth >= 4:
        return f"<{type(value).__name__}>"
    if isinstance(value, Mapping):
        return "{" + ",".join(
            f"{k!r}:{_stable_repr(v, depth + 1)}"
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_stable_repr(v, depth + 1) for v in value) + "]"
    if isinstance(value, (set, frozenset)):
        return "{" + ",".join(
            sorted(_stable_repr(v, depth + 1) for v in value)) + "}"
    fields = _as_fields(value)
    if fields:
        return (f"{type(value).__name__}(" + ",".join(
            f"{k}={_stable_repr(v, depth + 1)}"
            for k, v in sorted(fields.items())) + ")")
    text = repr(value)
    # `<Thing object at 0x...>` is an address, not a value.
    if " object at 0x" in text:
        return f"<{type(value).__name__}>"
    return text


def _as_fields(parameters):
    """A parameter snapshot as a plain dict, whatever shape it arrived in.

    Three experiments pass a typed parameters dataclass and the IV sweep
    passes a plain dict, and `RunContext` stores whichever it was given
    without converting. A fingerprint that only understood mappings
    would return `""` for three experiments out of four - and would do
    it silently, so the log would look complete while the field that
    answers "were these configured the same?" was empty on most lines.
    """
    if parameters is None:
        return {}
    if isinstance(parameters, Mapping):
        return dict(parameters)
    if dataclasses.is_dataclass(parameters) and not isinstance(parameters, type):
        return {f.name: getattr(parameters, f.name, None)
                for f in dataclasses.fields(parameters)}
    data = getattr(parameters, "__dict__", None)
    return dict(data) if isinstance(data, dict) else {}


def sample_identity(parameters):
    """The `sample_id` of the sample a run was configured for.

    Same two shapes as above: an attribute on the typed dataclass, a key
    in the IV sweep's dict. Read from the snapshot rather than from the
    name box, because the box may have been retyped since the run
    started - the fault Wave 7b-i fixed in the IV sweep. The log has to
    say which sample was measured, not which name is on screen now.
    """
    sample = None
    if isinstance(parameters, Mapping):
        sample = parameters.get("sample")
    elif parameters is not None:
        sample = getattr(parameters, "sample", None)
    return getattr(sample, "sample_id", "") or ""


def _exception_category(detail):
    """The exception type named at the start of a failure detail.

    `RunContext` records failures as `"TypeError: ..."`. §26 asks for an
    exception *category* separately from the message, because the
    category is what you group by when asking "is this the same fault as
    last week?" and the message is usually unique.
    """
    if not detail:
        return ""
    head = detail.split(":", 1)[0].strip()
    # A type name, not a sentence. Anything with a space is prose.
    if head and " " not in head and head[:1].isupper():
        return head
    return ""


def build_event(status, *, experiment="", sample_id="", instruments=None,
                parameters=None, metadata=None):
    """One run's terminal status as a flat, JSON-safe dictionary.

    Every field §26 asks for, named here in one place so that adding one
    is a single edit rather than a hunt through call sites.

    Deliberately flat and deliberately all-strings-and-numbers: this is
    written from a worker thread while a run is unwinding, and a
    surprise in serialisation at that moment would be the second failure
    in a row.
    """
    shutdown = status.shutdown
    event = {
        "schema": EVENT_SCHEMA,
        "timestamp": status.timestamp,
        "run_id": status.run_id,
        "experiment": experiment,
        "sample_id": sample_id,
        "instruments": dict(instruments or {}),
        "parameter_fingerprint": parameter_fingerprint(parameters),
        "outcome": str(status.outcome),
        "stage": status.stage or "",
        "detail": status.detail or "",
        "exception_category": _exception_category(status.detail),
        "shutdown_status": str(shutdown.status),
        "shutdown_detail": shutdown.detail or "",
        # Deliberately a *count*, never the readings themselves. §26's
        # boundary: provisional measurements do not belong in the
        # operational log, and a cancelled run's readings are the ones
        # taken before somebody hit Stop.
        "readings_discarded": int(status.readings_discarded or 0),
        "app_version": app_version(),
    }
    if metadata:
        # Namespaced, so an experiment's own key can never collide with
        # a field above and silently replace it.
        event["metadata"] = {str(k): str(v) for k, v in dict(metadata).items()}
    return event


def default_log_path():
    return lock_directory() / LOG_FILENAME


class EventLog:
    """Append-only JSON Lines sink for terminal run statuses.

    Thread-safe: `_record` runs on whichever thread the run was unwound
    on, and two experiments in one window have two controllers.
    """

    def __init__(self, path=None, max_bytes=MAX_BYTES, log=None):
        self.path = Path(path) if path else default_log_path()
        self.max_bytes = max_bytes
        self._log = log
        self._lock = threading.Lock()
        self._complained = False

    def record(self, event):
        """Append one event. Never raises.

        Returns True if written. A failure is reported to the operator
        console **once** - a disk that is full will fail on every run,
        and twenty identical lines teach the operator to ignore the
        console.
        """
        try:
            line = json.dumps(event, default=str, ensure_ascii=False)
        except Exception as exc:               # pragma: no cover - defensive
            self._complain(f"could not serialise a run event: {exc}")
            return False
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed()
                with open(self.path, "a", encoding="utf-8") as handle:
                    self._close_a_torn_line(handle)
                    handle.write(line + "\n")
            return True
        except OSError as exc:
            self._complain(f"could not write the run event log: {exc}")
            return False

    @staticmethod
    def _close_a_torn_line(handle):
        """Start a new line if the last write did not finish one.

        A power cut mid-append leaves a partial line with no newline.
        Without this the next run's event is glued onto the end of it,
        and *both* become unparseable - so a crash would cost the
        record of the run after it as well as its own. Found by a test
        that wrote a torn line deliberately.
        """
        if handle.tell() == 0:
            return
        with open(handle.name, "rb") as check:
            check.seek(-1, os.SEEK_END)
            if check.read(1) != b"\n":
                handle.write("\n")

    def _rotate_if_needed(self):
        """Move the current file aside once it is large enough.

        One previous generation is kept. Rotating to `.1` and discarding
        anything older bounds the disk use without the log ever being
        the reason an investigation has nothing to look at.
        """
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.max_bytes:
            return
        previous = self.path.with_suffix(self.path.suffix + ".1")
        try:
            os.replace(self.path, previous)
        except OSError:
            pass

    def _complain(self, message):
        if self._complained:
            return
        self._complained = True
        if self._log:
            try:
                self._log(f"{message}. Runs are unaffected; operational "
                          f"history is not being recorded.")
            except Exception:                  # pragma: no cover - defensive
                pass

    def read_all(self):
        """Every event currently in the live file, oldest first.

        For tests and for whoever is investigating. A malformed line is
        skipped rather than raising: a log truncated by a power cut
        should still yield everything before the truncation.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return []
        events = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        return events
