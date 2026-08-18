# Changelog

Newest first. Append-only: entries are not edited once written, because
this is the record of *why something changed and when* — the record of
what is true *now* lives in `docs/`.

The work so far was organised as numbered waves adopting one code
review. That numbering ends with Wave 7; later entries are just entries.

## Fixed sourcing vs time: the last sample, and the clock ceiling

Windows CI, after the merge. A well-behaved eleven-sample run returned
ten; Linux could not reproduce it.

- **The clock ceiling was pre-empting the sample due at exactly the
  duration.** That sample is inside the window the operator agreed to,
  but any lateness in the final wait puts elapsed past the ceiling
  before it has been taken. Windows' default timer granularity is about
  15.6 ms, so a 10 ms final wait overshoots by 5 ms — enough. The run
  looked healthy, was one sample short, and sat well inside the
  shortfall floor that would otherwise have refused it.
- **The ceiling now has a grace of one interval**, so a run may exceed
  its requested duration by up to one interval. That is the stated cost
  of not dropping the final sample, and it does not weaken what the
  ceiling is for: a run a whole interval behind the agreed window is the
  runaway case and is still stopped there.
- This is the float-division fault from the previous entry arriving
  through a second door — a comparison sitting exactly on a boundary,
  and the last sample of a healthy run quietly vanishing. Both are fixed
  by deciding what the boundary is *for* rather than by nudging a
  number.
- Two regression tests, deliberately not timing-dependent: one makes a
  single reading slow enough to put the clock past the duration before
  the final sample is due, reproducing the Windows shape on any
  platform; its pair asserts that the grace did not become an amnesty
  for a runaway run. The second's bound is derived from the stated
  contract rather than picked — a rounder one survived the mutation that
  widened the grace.

## Fixed sourcing vs time

The first experiment in this suite that is not a port. It holds one
source level and samples the other quantity against the clock —
leakage, bias stress, relaxation, self-heating — and it is the first
whose independent variable is time.

- **No driver changed.** Everything it needs was already on `BaseSMU`:
  `measure()` returns both quantities on every registered driver, so the
  experiment sits entirely on the existing contract. That was checked
  before the design was agreed rather than discovered afterwards.
- **Duration is authoritative and the loop is bounded by the clock**,
  not by its position on the nominal grid. The timer exists so nobody
  walks away from a live fixture, so a slow instrument must deliver
  fewer samples in the same window rather than the same samples over a
  longer one. A 60 s run at 5 ms on a 50 ms instrument would otherwise
  have held the output on for ten minutes.
- **`RunContext.expect()` cannot be used here** — an exact expected
  count would fail every honest run on a slow instrument. A conditional
  floor replaces it: half the nominal count for a run that reached its
  duration, two samples for one the operator ended or a read error cut
  short.
- **Two stop controls, because they are two operations.** "Finish and
  save" commits what was collected; "Stop and discard" is the house
  Stop, unchanged. Stop keeping its meaning is the load-bearing half —
  an operator who has pressed it a hundred times on Van der Pauw must
  not lose a run discovering it means something else here. Neither
  button talks to the instrument; both set a flag and the worker
  de-energises on the thread that owns the session, which is the
  discipline W6-2 established.
- **The time column is measured and the schedule aims at absolute
  deadlines.** `i * interval` would be
  [Reconstructed x-axes](docs/faults/09-reconstructed-x-axes.md) in a new place, and sleeping the
  interval between readings would be
  [Sweep completion slept rather than polled](docs/faults/05-slept-not-polled.md) in a new place. Late samples
  are counted and the achieved mean interval is stored beside the
  requested one.
- **A float-division fault, found while writing the tests.**
  `0.3 / 0.1` is `2.9999999999999996`, so a plain `int()` gave three
  samples where four were asked for and the sampling loop dropped the
  one due at t = 0.3. A 60 s run at 0.1 s lost its last sample the same
  way. Both the loop and the nominal count now carry a tolerance — and
  the reason it survived a first reading is that the two disagreed by
  computing the same wrong division, so they agreed with each other.
- **`tools/build_docs.py` no longer asserts that every experiment is a
  port.** The template said "Ported from `<origin>`" unconditionally,
  which rendered as "Ported from `New experiment`" — the generator
  making a false claim, which is the thing the generator exists to
  prevent. Non-port origins now render honestly.
- 26 new tests across `tests/test_fixed_source.py` (what the run
  records) and `tests/test_fixed_source_lifecycle.py` (the threaded
  route, and the two stop controls at the same boundary). 22 deliberate
  mutations run against them; the first round left four survivors —
  two real holes in the tests, two mutations shaped so they could not
  fail, which is the same fault as a test that cannot fail.

**Not commissioned.** Nothing here has met hardware. The first bench
session is expected to find something; commissioning a new path always
has.

## Wave 7g

- `uv.lock` regenerated. Wave 7e added `[build-system]` to make the
  project installable, which changes how uv classifies the project
  itself - `source = { virtual = "." }` became
  `source = { editable = "." }` - and the lockfile was never rebuilt.
  CI runs `uv sync --locked`, so both jobs failed at the first step with
  an error naming neither what had changed nor why.
- `tests/test_lockfile.py` holds `uv.lock` to `pyproject.toml`: the
  project name and version, the dependency list, the Python floor, and
  whether the project is a buildable package at all. Deliberately
  offline - `uv lock --check` would be complete but needs an index, and
  a suite that cannot pass without the network is one that fails on a
  bench machine for reasons unrelated to the code.
- It catches a dependency added or removed, a version bumped, the floor
  moved, or a build backend introduced. It cannot catch an upstream
  package changing its own requirements; `--locked` in CI still covers
  that.

## Wave 7f

A fix to Wave 7c, found by Windows CI.

- `lock_directory()` created what it returned. A function named for a
  question had a side effect, so *asking* where the lock lives made
  directories - for every caller, including `default_log_path()` in
  `core/event_log.py`, which meant constructing an `EventLog` or
  printing a diagnostic created a tree nobody asked for. It is now a
  pure query; `SingleInstance.acquire()` creates what it needs, as
  `EventLog.record()` already did.
- On Linux this was invisible: the directories were real, writable and
  unremarked. It took a Windows job, and a path under `C:\Users` whose
  ACL refuses `mkdir`, to turn a silent side effect into a
  `PermissionError` - which is what "Windows CI is load-bearing" means
  in practice.
- The test that exposed it named a real system location it did not own
  (`C:\Users\test\AppData\Local`) instead of `tmp_path`. Corrected,
  and `test_asking_where_the_lock_lives_creates_nothing` now guards
  both halves: the query creates nothing, and acquiring still does.

Review issues: none.
- `lock_directory()` takes `platform`, `environ` and `home` so both
  branches run on either operating system. This is the more important
  half: the fault reached CI because the only test of the Windows
  branch opened with `if sys.platform != "win32": skip`, so on the
  machine where the code was written it never ran at all. A branch that
  can only be tested on the platform you cannot run is a branch nobody
  tests. There are no skips left in that file.
- Mutation testing then found a second hole, in both writers. With
  `mkdir` moved out of the query, `SingleInstance.acquire()` and
  `EventLog.record()` each have to create their own parent - and every
  test handed them a `tmp_path` that already existed, so deleting those
  lines broke nothing. That is the first-run path on every bench
  machine. For the event log it would have been silent: `record`
  swallows its own errors by design, so the symptom would have been a
  log that was simply always empty.

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
