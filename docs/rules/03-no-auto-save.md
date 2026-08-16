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
Copy ticked → Calc  |  Save → CSV  |  Delete ticked  |  Clear all
```

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
