"""
Stable identifiers for samples, runs, readings and derived results
(review §15, group B3/B4).

Why this exists
---------------
Sample association currently rests entirely on the text in a sample-name
box. That text is editable, non-unique, and read at whatever moment the
code happens to read it. Three consequences follow, and all three are
silent:

* two different physical samples both labelled `ITO_1` merge into one
  CSV file and one set of calculated results;
* renaming the box mid-session relabels work already done;
* a derived value points at "whatever sample is showing" rather than at
  the measurements it was actually computed from.

The fix is the oldest one in laboratory practice: **the label on the
sample and the number in the logbook are two different things.** The
label is for humans and may be rewritten; the number is assigned once,
never reused, and is what every later record refers back to.

Identifier shapes
-----------------
Readable stem, then a disambiguating tail::

    sample   smp-20260808-a3f19c2b7d4e6f81
    run      ossila_4pp-0007-20260808T143012-3f9a1c22b7e04d61
    reading  ossila_4pp-0007-20260808T143012-3f9a1c22b7e04d61#0042
    result   res-20260808-5e1d7f0499b2ca03

The date is in every one of them on purpose. These end up in CSV
headers, log lines and eventually filenames, and an identifier you can
sort and skim at the bench is worth more than the extra bytes. A raw
UUID would be more compact and much less useful to read. The readable
part is first and unchanged, so what an operator actually reads - the
experiment, the sequence number, the date - is still the first thing
on the line.

How wide the random part has to be
----------------------------------
The tail is `_TAIL` hex characters from `uuid4`. It was 8, which is 32
bits, and the docstring here claimed that at a few hundred samples a
day a collision was expected "roughly every ten thousand years". That
arithmetic was wrong by more than two orders of magnitude, and wrong in
the reassuring direction.

Collisions here are per day, because the date is part of the
identifier and two different days cannot collide. The birthday
expectation for `n` draws from `N` values is about `n**2 / 2N`, so at
300 identifiers on one day::

    8 hex  = 32 bits:  300**2 / (2 * 2**32)  = 1.0e-5  per day
                       -> about 260 years between collisions
    16 hex = 64 bits:  300**2 / (2 * 2**64)  = 2.4e-15 per day
                       -> about 1.1e12 years

Two and a half centuries is not "never" for a laboratory record that
is meant to outlive the people who made it, and the record volume is
not 300 a day either - a `rec-` identifier is minted per *run*, not per
sample, and a periodic IV sweep commits one per cycle. At 10,000 a day
the 32-bit interval is under three years, and the 64-bit one is still
about 10^9.

So the tail is 16 hex characters, and `SampleRegistry` still checks for
a collision and re-draws, because the check costs nothing and the
failure would be baffling. The check is process-local and always was;
it is a backstop, not the guarantee. The guarantee is the width.

Old identifiers stay readable
-----------------------------
Stored CSVs carry 8-character tails and run identifiers with no session
part, and those files are the scientific record. `parse_object_id` and
`parse_run_id` accept both widths and both run shapes; only the new one
is ever written.

Why a run identifier carries a session
--------------------------------------
`RunController`'s sequence number counts runs within one controller, so
it restarts at 1 when the process does, and the timestamp that
disambiguates it has one-second resolution. Two consequences, and both
are real rather than theoretical:

* restart the application and press Run inside the same second as the
  previous session's first run, and both runs are `<name>-0001-<same
  second>`;
* two bench machines measuring the same experiment produce colliding
  first run identifiers whenever they start within the same second.

`run_id` is the join key between a stored measurement row and the
operational event log, so a collision does not merely duplicate a
label - it joins one machine's readings to another machine's
cancellation.

`SESSION_ID` is 64 random bits drawn once per process. Uniqueness
inside a process is still the counter's job; the session is what makes
two processes disjoint. Over a century of twenty benches running ten
sessions a day - about 730,000 sessions - the chance that any two ever
share one is around one in seventy million.

Threading
---------
`SampleRegistry` is guarded by a lock. It is expected to be used from
the UI thread, but a snapshot object built at Run press is read from a
worker, and "expected to be" is not a guarantee worth resting a
provenance chain on.
"""
from __future__ import annotations

import datetime
import re
import threading
import uuid
from collections import namedtuple
from dataclasses import dataclass

#: Length of the random tail, in hex characters. 16 is 64 bits; see the
#: table in the module docstring for why 8 was not enough.
_TAIL = 16

#: Tail widths that have ever been written, newest first. Readers accept
#: all of them; only `_TAIL` is minted. Stored files are the scientific
#: record and a reader that rejects last year's identifiers is a reader
#: that cannot open last year's data.
TAIL_WIDTHS = (16, 8)

#: This process, as 64 random bits.
#:
#: Drawn once at import, deliberately. Every run in one session shares
#: it, which is what makes "these runs came from one process" a
#: question the identifier answers - and a fresh draw per run would
#: cost the same bytes and say less.
SESSION_ID = uuid.uuid4().hex[:16]


def _stamp(when=None):
    return (when or datetime.datetime.now()).strftime("%Y%m%d")


def _tail():
    return uuid.uuid4().hex[:_TAIL]


# --------------------------------------------------------------------
# minting
# --------------------------------------------------------------------
def new_sample_id(when=None):
    """A fresh sample identifier: `smp-20260808-a3f19c2b7d4e6f81`."""
    return f"smp-{_stamp(when)}-{_tail()}"


def new_record_id(when=None):
    """A fresh stored-record identifier: `rec-20260808-9b2c4d6108f7a3e5`.

    Wave 7b. Distinct from a run identifier, and the distinction is
    load-bearing rather than tidiness: the IV sweep commits **several**
    stored records from one lifecycle run - one per cycle - and they all
    carry the same `run_id`. De-duplicating two saved snapshots on
    `run_id` would therefore collapse a periodic run's cycles into one
    row and throw the rest away.

    So `run_id` answers "which run produced this?", which is what the
    operational log joins on, and `record_id` answers "which stored row
    is this?", which is what a reader de-duplicates on. One column
    cannot be both.
    """
    return f"rec-{_stamp(when)}-{_tail()}"


def new_save_id(when=None):
    """An identifier for one press of Save: `sav-20260808-1c4e77b2049fd831`.

    Wave 7b. Every file written by a single Save carries the same one,
    which is what makes snapshot semantics legible on disk. Saving twice
    writes two overlapping files **on purpose** - option A of review
    §25 - and without a marker the second is indistinguishable from a
    first save that happened to contain more runs.

    With it: `save_id` says which files came from one press, `record_id`
    says which rows are the same measurement, and de-duplicating a
    concatenation of both on `record_id` is correct rather than hopeful.
    """
    return f"sav-{_stamp(when)}-{_tail()}"


def new_result_id(when=None):
    """A fresh derived-result identifier: `res-20260808-5e1d7f0499b2ca03`.

    Wave 4 attaches one of these to every calculated value, alongside
    the run and reading identifiers it came from.
    """
    return f"res-{_stamp(when)}-{_tail()}"


def format_run_id(name, sequence, when=None, session=None):
    """`ossila_4pp-0007-20260808T143012-3f9a1c22b7e04d61`.

    The Wave 1 stem is unchanged and still first, because it is what
    anybody actually reads: which experiment, which run of the session,
    when. The session is appended rather than woven in for the same
    reason.

    `sequence` counts runs within one controller, so it restarts at 1
    when the app does. The timestamp was supposed to disambiguate that
    restart and does not: it has one-second resolution, so a restart
    inside one second - or a second machine - produced the same first
    run identifier. Since `run_id` is the join key between stored
    measurement rows and the operational event log, that collision
    joins one run's readings to another run's outcome.

    `session` defaults to this process's `SESSION_ID` and is a
    parameter only so a test can pin one; nothing in the application
    passes it.
    """
    moment = (when or datetime.datetime.now()).strftime("%Y%m%dT%H%M%S")
    return f"{name}-{int(sequence):04d}-{moment}-{session or SESSION_ID}"


def reading_id(run_id, index):
    """`<run_id>#0042` - the index-th reading of that run.

    Deliberately derived rather than random. A reading has no identity
    apart from the run that produced it and its position within that
    run, and a derived identifier makes that relationship readable in a
    CSV instead of requiring a lookup table to recover it.

    `index` is 0-based on input and rendered 1-based, matching how the
    existing CSVs number `meas_number`.
    """
    return f"{run_id}#{int(index) + 1:04d}"


def split_reading_id(text):
    """`('run-id', 42)` from `'run-id#0042'`, or None if it is not one.

    The inverse of `reading_id`, so Wave 4's provenance chain can be
    walked backwards from a stored row without keeping a second index.
    """
    match = re.fullmatch(r"(.+)#(\d+)", str(text))
    if not match:
        return None
    return match.group(1), int(match.group(2)) - 1


# --------------------------------------------------------------------
# reading them back
# --------------------------------------------------------------------
#: Prefixes minted above, so a recogniser cannot drift from the minters.
ID_PREFIXES = ("smp", "rec", "sav", "res")

#: Built from `TAIL_WIDTHS` rather than written out, so widening the
#: tail again cannot leave the reader behind - which is the shape of
#: mistake that would make a file unreadable by the code that wrote it.
_OBJECT_ID = re.compile(
    rf"(?P<kind>{'|'.join(ID_PREFIXES)})-(?P<date>\d{{8}})-"
    rf"(?P<tail>{'|'.join(f'[0-9a-f]{{{w}}}' for w in TAIL_WIDTHS)})")

#: The session part is optional, which is what makes every run
#: identifier in every stored file written before this change still
#: parse. Only the form with a session is ever written.
_RUN_ID = re.compile(
    r"(?P<name>.+)-(?P<sequence>\d{4,})-(?P<when>\d{8}T\d{6})"
    r"(?:-(?P<session>[0-9a-f]{16}))?")

#: What `parse_object_id` returns. `kind` is one of `ID_PREFIXES`.
ObjectId = namedtuple("ObjectId", "kind date tail")

#: What `parse_run_id` returns. `session` is `None` for an identifier
#: minted before run identifiers carried one.
RunId = namedtuple("RunId", "name sequence when session")


def parse_object_id(text):
    """`ObjectId('smp', '20260808', 'a3f19c2b')`, or None.

    Accepts every tail width in `TAIL_WIDTHS`, not only the one being
    minted. Stored CSVs are the scientific record and they carry the
    8-character tails written before the widening; a reader that
    rejected them would be a reader that cannot open last year's data,
    which is a worse failure than the collision the widening fixes.

    Returns the parts as strings. The date is not converted to a
    `date`, because an identifier is an opaque label whose readability
    is a convenience - parsing it into a datetime invites code that
    *decides* something from it, and what the record was made from is
    the file's own timestamp field.
    """
    match = _OBJECT_ID.fullmatch(str(text))
    if not match:
        return None
    return ObjectId(match.group("kind"), match.group("date"),
                    match.group("tail"))


def parse_run_id(text):
    """`RunId('ossila_4pp', 7, '20260808T143012', '3f9a...')`, or None.

    The inverse of `format_run_id`, and it accepts both shapes: with a
    session, and without. Without is what every run identifier stored
    before the session was added looks like, and `session` is `None`
    there rather than an empty string - "this identifier predates
    sessions" is a fact, and it must not read as "this run had a blank
    session".
    """
    match = _RUN_ID.fullmatch(str(text))
    if not match:
        return None
    return RunId(match.group("name"), int(match.group("sequence")),
                 match.group("when"), match.group("session"))


# --------------------------------------------------------------------
# a sample: the label and the number in the logbook
# --------------------------------------------------------------------
@dataclass(frozen=True)
class SampleRef:
    """What a run records about which sample it measured.

    Frozen, and captured at Run press. The `label` here is the label at
    that moment; renaming the sample afterwards changes what the UI
    shows for future runs and leaves this one describing what was
    actually true when the measurement happened.

    `slug` is the label made safe for a filename, which is what
    `Experiment.current_sample_name()` produces today. Keeping it on the
    object means the CSV filename and the run's own record of itself
    cannot drift apart.
    """

    sample_id: str
    label: str

    @property
    def slug(self):
        """The label as it appears in a filename: `ITO batch 3` -> `ITO_batch_3`."""
        cleaned = re.sub(r"[^\w.\- ]", "", self.label).strip()
        return cleaned.replace(" ", "_") or "sample"

    def __str__(self):
        return f"{self.label} [{self.sample_id}]"


class SampleRegistry:
    """Labels to sample identifiers, for the whole application.

    Owned by `LabApp` and injected into experiments, the way Wave 1
    injects the driver registry and the ownership manager. Application
    scope rather than experiment scope is the load-bearing choice: a
    sample measured in Van der Pauw and then in Hall is one sample, and
    Wave 5's open question about carrying a sheet resistance from the
    first into the second is only answerable if both experiments agree
    on what that sample is. Per-experiment registries would mint two
    identifiers for one piece of material and make the carry-over
    unprovable.

    Two operations, and the difference between them matters:

    * `ref(label)` returns the existing sample with that label, minting
      one if the label is new. This is what a Run press calls, and it
      makes the common case - measure a sample, measure it again -
      require no ceremony at all.
    * `new(label)` always mints, even if the label is in use. This is
      the "second sample from the same batch, same name on the box"
      case, and it is the only way two samples can share a label and
      stay distinguishable. Wave 3 puts it behind a button.
    """

    def __init__(self):
        self._by_id = {}         # sample_id -> SampleRef
        self._by_label = {}      # label -> sample_id (most recent wins)
        self._lock = threading.RLock()

    # ---- lookup and minting ----
    def ref(self, label):
        """The sample currently known by `label`, minting if unknown.

        Look-up and mint happen under one lock hold. Releasing between
        the two would be a check-then-act race: two threads pressing Run
        on the same label would both miss, both mint, and the sample
        would silently split in half.

        Honest note on that race: under CPython's GIL the window is a
        few bytecodes wide and could not be reproduced on demand while
        this was written - a barrier-synchronised attempt with 24
        threads never once split a sample. So the single lock hold is
        not a fix for an observed fault; it is the cheaper of two
        correct-looking spellings, chosen because `python: ["3.14"]` is
        already in the CI matrix and a free-threaded build removes the
        GIL that is currently hiding the window. `test_identity.py`
        exercises it under contention but does not claim to prove it.
        """
        key = str(label).strip()
        with self._lock:
            sample_id = self._by_label.get(key)
            if sample_id is not None:
                return self._by_id[sample_id]
            return self._mint_locked(key)

    def new(self, label):
        """Mint a new sample under `label`, even if the label is taken.

        The new one becomes what `ref(label)` returns from now on.
        Earlier samples keep their identifiers and their results; they
        are simply no longer what that label points at.
        """
        with self._lock:
            return self._mint_locked(str(label).strip())

    def _mint_locked(self, key):
        """Caller must hold `self._lock`."""
        key = key or "sample"
        sample_id = new_sample_id()
        while sample_id in self._by_id:          # see the note on collisions
            sample_id = new_sample_id()
        ref = SampleRef(sample_id=sample_id, label=key)
        self._by_id[sample_id] = ref
        self._by_label[key] = sample_id
        return ref

    def get(self, sample_id):
        """The `SampleRef` for an identifier, or None."""
        with self._lock:
            return self._by_id.get(sample_id)

    # ---- renaming ----
    def rename(self, sample_id, label):
        """Give an existing sample a new label. The identifier does not move.

        Returns the updated `SampleRef`. Runs already completed keep the
        label they captured - this changes what the sample is called from
        now on, not what history says it was called then, which is the
        §15 acceptance criterion.
        """
        key = str(label).strip() or "sample"
        with self._lock:
            existing = self._by_id.get(sample_id)
            if existing is None:
                raise KeyError(f"no sample with id {sample_id!r}")
            updated = SampleRef(sample_id=sample_id, label=key)
            self._by_id[sample_id] = updated
            # drop the old label only if it still points here, so
            # renaming A to B does not steal B's identity
            if self._by_label.get(existing.label) == sample_id:
                del self._by_label[existing.label]
            self._by_label[key] = sample_id
            return updated

    # ---- inspection ----
    def labels(self):
        """Every label currently in use, in first-seen order."""
        with self._lock:
            return list(self._by_label)

    def all(self):
        """Every sample ever minted, in creation order."""
        with self._lock:
            return list(self._by_id.values())

    def __len__(self):
        with self._lock:
            return len(self._by_id)

    def __contains__(self, sample_id):
        with self._lock:
            return sample_id in self._by_id
