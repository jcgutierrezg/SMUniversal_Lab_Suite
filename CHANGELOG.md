# Changelog

Newest first. Append-only: entries are not edited once written, because
this is the record of *why something changed and when* — the record of
what is true *now* lives in `docs/`.

The work so far was organised as numbered waves adopting one code
review. That numbering ends with Wave 7; later entries are just entries.

## Wave 7e

Packaging (§42), and the close of the wave numbering.

- `[build-system]` added: the project can be built and installed. Before
  this, `import core` worked only when the working directory happened to
  be the checkout, so §42's acceptance criterion failed at *import* -
  several steps before it reached a resource file. Verified end to end:
  installed into a clean 3.14 environment, imported from `/tmp`,
  resolving to `site-packages`, with the 4PP diagram present.
- Layout stays flat. A `src/` layout stops the source shadowing the
  installed copy, which matters for a library and much less for an
  application with one entry point - and an *editable* `src/` install
  would not have caught a missing data file anyway. Checking the built
  artifact does; `tests/test_build_artifact.py` does that.
- `tests/test_build_artifact.py` enumerates non-Python files from the
  tree and requires each in a genuinely built wheel, so a new image is
  covered when it is added rather than when somebody remembers a rule.
  The declared package list is checked against the tree too.
- The first build configuration carried `artifacts = ["**/assets/**"]`
  with a comment asserting it was essential. It did nothing - that key
  is for files version control excludes, and the asset was already
  included. Mutation testing found it; the line is gone and the
  reasoning is in `docs/workflow/packaging.md`.

Review issues: §42.
- The launcher body moved to `core/launcher.py` and `main.py` became a
  shim that calls it. `pyproject.toml` declares a console script,
  `smu-lab-suite`, so after `uv pip install -e .` the application opens
  from any directory - which is what "ship it as an `.exe`" was mostly
  asking for, without bundling an interpreter or making a second copy
  of the repo that `git pull` cannot update.
- The entry point names `core.launcher`, never `main`: a console script
  target must be importable, and a top-level `main` module in
  site-packages collides with every other package's idea of that name.
  Both properties are tested, and the target is resolved the way an
  installed script resolves it rather than pattern-matched.

## Wave 7d

Operational event log (review §26).

- Every run now leaves a record of how it ended - completed, cancelled
  or failed - in a JSON Lines file in per-machine state. Previously a
  cancelled run's only trace was a console line that vanished with the
  window, so "nothing was saved" and "somebody stopped it because the
  probe slipped" were indistinguishable afterwards.
- **It records that a run happened, never what it measured.** §26's
  boundary; guarded by a test that puts a distinctive value in a run's
  readings and asserts it appears nowhere in the log, so a leak through
  any field - including one added later - goes red.
- One line per run, not per state transition: a run is the unit of
  investigation, and transitions are already on the operator console.
- JSON Lines rather than CSV, because the field list will grow. A new
  key is invisible to an old reader; a new CSV column shifts everything
  after it, which is the shape of the Wave 4 sentinel fault.
- Wired at `RunController._record`, the single choke point every
  terminal status passes through, so a future terminal path cannot skip
  logging. The controller takes a *callable*, not a path, so run control
  keeps no dependency on the filesystem.
- A log that cannot be written never fails a run: it complains once to
  the console and stays silent thereafter.
- Two defects found by the new tests, both silent: the parameter
  fingerprint used `repr()`, which renders an ordinary object as its
  memory address, so two identically configured runs produced different
  digests - a field full of plausible hex that answered nothing. And a
  line torn by a power cut would have had the *next* run's event glued
  onto it, losing both.
- Stored beside the single-instance lock in per-machine state rather
  than beside the application: a frozen `.exe` under `Program Files`
  sits where ordinary users cannot write, and one on a shared drive
  would pool every bench's runs into one file.

Review issues: §26.
- `test_no_reading_value_reaches_the_operational_log` was rewritten
  after a mutation round: the first version defined a marker value,
  never put it anywhere the log could reach, and then checked the file
  did not contain it - true whether or not the code was correct. It is
  now two tests, for two different properties: readings are cleared
  before the sink is called at all, and parameters are fingerprinted
  rather than transcribed.

## Wave 7c-ii

- Only one copy of the application may run per machine. `main.py` takes
  a lock before building any window and refuses with a dialog
  otherwise. Two copies would each open the same instruments and each
  believe it controlled the output state.
- The lock is held by the **operating system** - `msvcrt.locking` on
  Windows, `fcntl.flock` elsewhere - rather than being a file whose
  existence means "running". The OS releases it when the process ends
  however it ends, so a crash or a kill cannot leave the bench locked
  out of its own software. `tests/test_single_instance.py` proves that
  by killing a holder outright.
- The lock file lives in per-machine state (`%LOCALAPPDATA%`, or
  `$XDG_STATE_HOME`), never beside the application: advisory locks over
  SMB and NFS are unreliable, and a lock beside an application on a
  shared drive would be shared between benches.
- Consequence worth knowing at the bench: a second copy is refused even
  when it would have driven a different SMU.

Review issues: none directly; prerequisite for §26.

## Wave 7c-i

- `run_tests.py` passes `PYTHONDONTWRITEBYTECODE=1` to every pytest
  subprocess. CPython validates a cached `.pyc` on the source's mtime
  and size, so a same-length edit inside one mtime tick leaves stale
  bytecode running - which silently invalidates mutation testing, the
  technique most of this project's real defects were found by. Cost
  three mutation rounds in Wave 7b before it was spotted.
- `tests/test_bytecode_staleness.py` demonstrates the mechanism rather
  than trusting it, pinning both mtimes with `os.utime` so the
  condition is reproduced deterministically.

Review issues: none.

## Wave 7b-ii

Save semantics: option A, immutable snapshot, made legible on disk.

- Every stored file declares `schema` (`core.run_store.FILE_SCHEMA`, now
  1) and `app_version`, plus `save_kind: snapshot` and a `save_id`
  shared by every file one press of Save writes. Combining two
  snapshots is `drop_duplicates(subset="record_id")`.
- `core/version.py` is the single source of truth for the application
  version; `pyproject.toml` mirrors it and `tests/test_version.py`
  fails if they drift. Not read from packaging metadata:
  `importlib.metadata` needs an installed distribution, and neither a
  checkout nor the intended frozen `.exe` is one.
- The Save button reads **Save snapshot → CSV** in all four
  experiments, and the confirmation says the runs stay in the table.
- Option B - export only new runs - was rejected and the reasoning
  recorded in house rule 3: the `#` header carries calculated results
  derived from every run in the store, so a new-runs-only file would
  state a sheet resistance computed from readings it does not contain.
- `tests/test_shared_controls.py` found the header row by position
  (`splitlines()[5]`); it now finds it by content. Four new header
  lines would have aimed it at a `#` comment, where each `in` check is
  trivially false.

Review issues: §25.

## Wave 7b-i

Run identity, ahead of the save-semantics change that needs it.

- The IV sweep bound each stored run to whatever the sample-name box
  said when the *sweep finished*, read from the worker thread. Retyping
  the box mid-run re-filed the remaining sweeps, and a periodic run
  could split its cycles across two samples with nothing logged. It now
  captures a frozen `SampleRef` at the Run press, like the other three
  experiments, and records `run_id`, `sample_id` and `sample_label`.
- `Run` mints its own `record_id`, written as the first CSV column.
  `run_id` identifies a lifecycle run and `record_id` a stored row -
  not the same thing, because one periodic IV run commits several
  records sharing a `run_id`. De-duplicating on `run_id` would delete
  real cycles.
- `tests/test_iv_identity.py` adds the thread-affinity check the IV
  sweep alone never had; 4PP has had one since Wave 3.

Review issues: §17, §25.

## Wave 7a

Tooling guards, ahead of the persistence work. No production code.

- `tests/test_docs.py`: every Markdown table must have a header, a
  separator and at least one body row, with square columns. `plan.md`'s
  status table had been truncated to a header and a bare `|` since the
  documentation rebuild, and rendered as an empty grid rather than as
  damage.
- `tests/test_docs.py`: `plan.md`'s "complete through Wave N" is checked
  against `CHANGELOG.md`'s wave headings, so the status line cannot fall
  behind the work by omission.
- `tests/conftest.py`: a GUI test whose dialog recorder has been stolen
  by another test file in the same process now fails, instead of passing
  its absence-of-dialog assertions against a recorder nothing writes to.
- `docs/plan.md`: status restored, Wave 7 split into 7a-7e, and both
  open decisions recorded as answered - save semantics A, and no second
  instance.

Review issues: none directly; §25 and §26 scoped.

## Documentation rebuild

Five patches replacing four root documents that had grown to carry a
plan, a changelog and a reference manual at once — and had begun
disagreeing with the code and with themselves.

- `docs-skeleton-v1` — vault tree, frontmatter schema, generators, guards
- `docs-instruments-v1` — one note per driver, deviations rehomed
- `docs-experiments-v1` — one note per measurement, script archaeology
- `docs-architecture-v1` — house rules, faults, the `core/` map
- `docs-retire-v1` — bench pages, the review index, the old files deleted

What it corrected on the way through is listed in
`docs/reference/migration-status.md`. The mechanism that stops it
recurring: **a documentation claim a machine can check is not written by
a human.** Driver envelopes, commissioning status, deviation numbers and
the review index are all generated, and `tests/test_docs.py` fails if a
committed copy disagrees with a fresh build.

## Wave 6d-ii

Adopt `apply_ranges()` in the experiments and the checkup; delete `set_current_range` / `set_voltage_range`.

Review issues: fault 16.

## Wave 6d-i

Ranging contract: `RangePlan`, `apply_ranges()`, per-axis hooks on every driver. Capability only - nothing adopts it.

Review issues: fault 16.

## Wave 6e

Reconnect after transport failure — delivered with 6c.

Review issues: §33.

## Wave 6c

Sweep traces: hardware sweep setup and completion, arming vs stepping, error-queue drain, abort spelling.

Review issues: §33.

## Wave 6b

Per-driver command traces; dialect hygiene; cross-experiment enforcement of house rule 12.

Review issues: §33, C4.

## Wave 6a

IV run lifecycle + standby/sweep contract + sweep ownership.

Review issues: A7, A8, §19, §20.

## Wave 5c-ii

Per-sample summary file + the save-collision pre-flight.

Review issues: §16, §17.

## Wave 5c-i

In-memory Rs handoff: `UpstreamResult`, the provider seam, the CSV load path deleted.

Review issues: §16, §17.

## Wave 5b

Combined VdP + Hall window, tabbed shell.

Review issues: operator feedback.

## Wave 5a-ii

Rollout: Hall, same pattern.

Review issues: Milestone 3.

## Wave 5a-i

Rollout: Van der Pauw onto the run lifecycle + calculation layer.

Review issues: Milestone 3.

## Wave 4

Calculation integrity: `core/calculation.py`, provenance, method versions, golden files; 4PP pilot.

Review issues: B5–B8, §16–18, §27–28.

## Wave 3

Pilot integration: 4PP only.

Review issues: A4, A6, A8 in situ.

## Wave 2

Typed inputs & identity.

Review issues: B1, B3, B4, §14, §15, §24, §54.

## Wave 1

Run-control core + instrument ownership + connection health; `LabApp` constructor injection.

Review issues: A1, A2, A3, A5, A9, A10, C3.

## Wave 0b

miniSMU dependency, `driver_registry` → `drivers/registry.py`, orphaned VdP `temp_panel.py` deleted, MIT licence, rename, GitHub Actions.

Review issues: C1, D1, D3, D5, D7.

## Wave 0a

pytest conversion: 25 scripts → 166 tests, `check()` as a soft-assert fixture, `run_tests.py` process isolation.

Review issues: C6.
