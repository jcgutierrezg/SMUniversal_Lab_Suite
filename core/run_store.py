"""
Completed runs held in memory, and the CSV they get written to.

Why this exists
---------------
Runs used to be written to a .txt the moment they finished. That meant a
misaligned sample or a badly seated contact left a file behind exactly
like a good measurement did, and the folder filled with results nobody
wanted to keep.

So runs now accumulate here instead. The operator ticks the bad ones,
deletes them, and presses Save once - producing one CSV per sample name
holding only the runs worth keeping.

The cost of that change is real and worth stating: an unsaved run exists
only in memory. Experiment.has_unsaved_runs() drives a confirmation
prompt on close, but a power cut or a hard crash still loses whatever
hasn't been saved. At 200 points and a 2 s settle that can be a quarter
of an hour of measuring.

File format
-----------
One file, two parts:

    # key: value        <- metadata and calculated results
    # ...
    meas_number,position,point,voltage_V,...    <- one row per raw reading
    1,1,1,0.0999,...

The `#` block is the same convention every other file in this suite uses,
so one reader handles all of them. Tools skip it too -
`pd.read_csv(path, comment="#")` gives the table straight back.

Note what the `#` block is *not* for, as of Wave 5c: it is not an
interface between two experiments. The Van der Pauw sheet resistance used
to reach Hall by being written here and parsed back; it now crosses in
memory as a `DerivedResult`, and the header is a record for whoever opens
the file later rather than something the software reads back.

The table is in long form: one row per raw reading, with the per-run
values repeated alongside. That is redundant on disk and the right shape
for plotting - filter by column and the data is ready, no reshaping.
"""
import csv
import datetime
import io

from core.identity import new_record_id, new_save_id
from core.version import app_version


class Run:
    """One completed run: what it was, what came out, and every raw
    reading behind it.

    `metadata` holds the per-run values (position, level, stage
    temperature...) that get repeated on each row of the CSV.
    `readings` is a list of dicts, one per raw reading.
    """

    __slots__ = ("sample", "metadata", "readings", "timestamp", "record_id")

    def __init__(self, sample, metadata, readings, record_id=None):
        self.sample = sample
        self.metadata = dict(metadata)
        self.readings = list(readings)
        self.timestamp = datetime.datetime.now().isoformat()
        # Minted here rather than by each experiment, deliberately.
        #
        # Wave 7 makes saving an explicit snapshot: every save writes the
        # whole store, so two saves overlap on purpose and a reader
        # de-duplicates them. That only works if every row carries an
        # identifier, and an identifier each experiment has to remember
        # to add is one a future experiment will forget - silently, with
        # the only symptom appearing when somebody concatenates two files
        # months later and gets duplicate rows they cannot tell apart.
        #
        # Putting it on `Run` makes forgetting it unrepresentable, the
        # same reason `RangePlan.for_sourcing()` was built that way in
        # Wave 6d.
        #
        # `record_id` is accepted as an argument only so a test can pin
        # one; nothing in the application passes it.
        self.record_id = record_id or new_record_id()


class RunStore:
    """Runs waiting to be saved, keyed by whatever the caller uses to
    identify a table row.

    Keying on the caller's own identifier - in practice the Treeview item
    id - means the table and the store cannot drift apart: deleting a row
    and deleting its run are the same operation with the same key.
    """

    def __init__(self):
        self._runs = {}          # key -> Run, insertion-ordered
        self._saved = True       # nothing to lose yet

    def add(self, key, run):
        self._runs[key] = run
        self._saved = False

    def remove(self, keys):
        """Drop runs by key. Returns how many were actually removed."""
        removed = 0
        for key in list(keys):
            if self._runs.pop(key, None) is not None:
                removed += 1
        if removed:
            self._saved = False
        return removed

    def get(self, key):
        """The `Run` stored under `key`, or None.

        Added in Wave 4. Copying a row into the calculation panel now
        has to read that run's identifiers as well as its number, and
        reaching into `_runs` from an experiment to do it would make the
        store's internals part of its interface by accident.
        """
        return self._runs.get(key)

    def clear(self):
        self._runs.clear()
        self._saved = True

    def mark_saved(self):
        self._saved = True

    @property
    def has_unsaved(self):
        """True if there are runs in memory that haven't been written."""
        return bool(self._runs) and not self._saved

    def __len__(self):
        return len(self._runs)

    def samples(self):
        """Distinct sample names, in the order they were first measured."""
        seen = []
        for run in self._runs.values():
            if run.sample not in seen:
                seen.append(run.sample)
        return seen

    def runs_for(self, sample):
        """Every run recorded under `sample`, in measurement order."""
        return [r for r in self._runs.values() if r.sample == sample]

    def all_runs(self):
        """Every run held, in measurement order, whatever the sample.

        Added in Wave 5c for the same reason `get()` was added in Wave
        4: something outside needed to look across the runs - here, to
        find the stage temperatures behind a derived result - and doing
        it by reaching into `_runs` would make the store's internals
        part of its interface by accident.
        """
        return list(self._runs.values())


#: Bumped whenever the header keys or the column layout of a stored file
#: change in a way a reader could notice.
#:
#: One integer for every file this suite writes, rather than one per file
#: kind. Two schemes would need someone to remember which was which, and
#: the version's whole job is to be readable by someone who was not here
#: - `# schema: 3` against a table in `docs/reference/schema.md` is a
#: question anyone can answer.
#:
#: 1 - Wave 7b. `record_id` column; `schema`, `app_version` and
#:     `save_id` header keys. Everything written before this wave is
#:     unversioned, and absence therefore reads as "older than 1", which
#:     is true and is why the numbering starts at 1 rather than 0.
FILE_SCHEMA = 1


def build_sample_summary(sample, sample_id, sections):
    """Render one sample's headline results as a small CSV (Wave 5c-ii).

    Pure string work - no filesystem - so the format is tested directly
    and the app keeps using `write_atomic()`.

    `sections` is a list of (experiment title, rows), where rows is a
    list of (label, value, unit, result_id) or None. A None section is
    written as an explicit "not calculated" line rather than left out,
    so a summary missing half its measurements cannot be mistaken for a
    sample that was only half measured.

    The body is a real table - label, value, unit, source - not another
    `#` block, so it opens as columns in Excel, which is how these get
    read. The `#` preamble is the same convention as every data file
    here, and `pd.read_csv(path, comment="#")` gives the table straight
    back.
    """
    header = [
        "# Sample summary",
        f"# schema: {FILE_SCHEMA}",
        f"# app_version: {app_version()}",
        f"# sample: {sample}",
        f"# sample_id: {sample_id}",
        f"# generated: {datetime.datetime.now().isoformat()}",
        "#",
        "# Headline results only. The full data and provenance are in the",
        "# per-measurement CSVs; this file is regenerated on each save and",
        "# describes what has been calculated so far, not the sample's whole",
        "# history.",
        "#",
    ]

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["measurement", "quantity", "value", "unit", "source"])
    for title, rows in sections:
        if not rows:
            writer.writerow([title, "not calculated", "", "", ""])
            continue
        for label, value, unit, result_id in rows:
            writer.writerow([title, label, value, unit, result_id])

    return "\n".join(header) + "\n" + buffer.getvalue()


def build_sample_csv(sample, runs, title, calculated=None, save_id=None):
    """Render one sample's runs as CSV text.

    Pure string work - no filesystem - so the format can be tested
    directly and the caller keeps using write_atomic().

    `calculated` is an ordered mapping of the derived results (Rs, V_H,
    carrier density...). It goes in the `#` header rather than the table
    because those values describe the sample as a whole, not any
    individual reading.
    """
    header = [
        f"# {title}",
        f"# schema: {FILE_SCHEMA}",
        f"# app_version: {app_version()}",
        f"# sample: {sample}",
        f"# saved: {datetime.datetime.now().isoformat()}",
        # Snapshot, not an incremental export. Every save writes the whole
        # store, so two saves overlap deliberately; `save_id` marks which
        # press produced this file and `record_id` de-duplicates the rows.
        f"# save_kind: snapshot",
        f"# save_id: {save_id or new_save_id()}",
        f"# runs: {len(runs)}",
    ]

    if calculated:
        header.append("#")
        header.append("# --- calculated ---")
        for key, value in calculated.items():
            if value not in (None, "", "-"):
                header.append(f"# {key}: {value}")

    header.append("#")

    # Column order: metadata first (what the run was), then the reading
    # itself. Keys are collected in first-seen order rather than sorted,
    # so the CSV reads in the order the code declares them.
    meta_keys = []
    reading_keys = []
    for run in runs:
        for key in run.metadata:
            if key not in meta_keys:
                meta_keys.append(key)
        for reading in run.readings:
            for key in reading:
                if key not in reading_keys:
                    reading_keys.append(key)

    # `record_id` first: it is what identifies the row, so it belongs
    # where a reader's eye and `usecols=` both land first.
    columns = ["record_id", "run_timestamp"] + meta_keys + reading_keys

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for run in runs:
        base = ([run.record_id, run.timestamp]
                + [run.metadata.get(k, "") for k in meta_keys])
        for reading in run.readings:
            writer.writerow(base + [reading.get(k, "") for k in reading_keys])

    return "\n".join(header) + "\n" + buffer.getvalue()
