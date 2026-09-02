---
type: rule
rule: 3
title: "Results and saving — no auto-save, ever"
---

# 3. Results and saving — no auto-save, ever

Runs are **not** written to disk as they complete. A run spoiled by a
misaligned sample or a badly seated contact must be discardable without
ever leaving a file behind.

The mechanism is `core/run_store.py` and is mostly inherited. Wiring a
new experiment in means `CSV_SLUG`, `CSV_TITLE`, and
`calculated_fields()`; at the end of a run, build a `Run` and commit it.
`_record_run` inserts the table row and registers the run under the
**same Treeview item id**, so a row and its raw data cannot drift apart.

`save_runs()`, `delete_ticked()` and `clear_output()` are inherited —
**do not reimplement them.** The results panel needs four buttons, in
this order:

```
Copy ticked → Calc  |  Save snapshot → CSV  |  Delete ticked  |  Clear all
```

**Saving is a snapshot, and the button says so** (Wave 7b, review §25).
A save writes *everything* in the store and leaves it there, so pressing
Save twice writes the earlier runs again. That overlap is the design,
not a defect — but it is only usable if the files admit it, which is why
every one carries `save_kind: snapshot`, a `save_id` shared by the files
one press produced, and a `record_id` on every row. Combining two
snapshots is `drop_duplicates(subset="record_id")`.

Option B — export only runs not yet saved — was rejected, and the reason
generalises. The `#` header holds the calculated results, derived from
every run in the store. A new-runs-only file would carry a sheet
resistance computed from readings that file does not contain: a
correct-looking number above a table that cannot produce it. That is the
house fault, not a formatting preference.

Every stored file also declares `schema`, `app_version` and `build_id`,
so a reader years later can tell what wrote it. The schema integer is
described in [the schema reference](../reference/schema.md).

`build_id` is there because `app_version` on its own was not an answer.
It is set by hand and stayed at `0.1.0` through every wave that changed
behaviour, so two files months and many commits apart claimed the same
application identity. `build_id` welds the commit on —
`0.1.0+g5e7308eff34a`, with `.dirty` when the tree had uncommitted
changes and `+unknown` where the build cannot be determined at all.
Never omitted: a missing key would read as "written by code that did
not record builds", which is a different fact from "could not tell".

Save writes **one CSV per sample name**: a `# key: value` header of
calculated results, then a long-form table, one row per raw reading with
per-run values repeated alongside. Verified to load as
`pd.read_csv(path, comment="#")` into a clean numeric frame that
`groupby` works on directly.

Calculated results attach **only** to the sample currently named in the
setup panel. The calculation panel holds one set of numbers, and copying
them onto every sample in the table would invent results for samples
never calculated.

**Known cost, accepted deliberately:** an unsaved run exists only in
memory. `has_unsaved_runs()` drives a confirmation on close and on Clear
all, but a crash or power cut loses unsaved work. If that ever bites,
the fix to offer is a quiet session-recovery file written as runs
complete and deleted on successful save — crash safety without clutter,
since it never accumulates. Not built, because it was not asked for.
