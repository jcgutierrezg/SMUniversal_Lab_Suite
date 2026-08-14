# Development wave plan

The review document (`LAB54_DEVELOPMENT_REVIEW_AND_WORKFLOW.md`) lists
around 38 individual issues. Tackling them one at a time means touching
the same files repeatedly and re-verifying after every change. This
groups them into waves instead.

The grouping principle is **not** "similar topics". It is *can this
break the running application?* Most of the work is new code with no
callers yet — a run-state machine, an ownership manager, a parameter
snapshot. None of that needs to touch an experiment to be written or
proven. Those waves carry no regression risk and are cheap to test
exhaustively. Only a small number of waves wire the new machinery into
the experiments, and those are the ones that need care.

The analogy: you bench-test a subassembly with a dummy load before it
goes into the chassis. Waves 1, 2, 4 and 6 are bench work. Waves 3, 5
and 7 are installation.

---

## Status

| Wave | Contents | Review issues | State |
|---|---|---|---|
| **0a** | pytest conversion: 25 scripts → 166 tests, `check()` as a soft-assert fixture, `run_tests.py` process isolation | C6 | **done** |
| **0b** | miniSMU dependency, `driver_registry` → `drivers/registry.py`, orphaned VdP `temp_panel.py` deleted, MIT licence, rename, GitHub Actions | C1, D1, D3, D5, D7 | **done** |
| **1** | Run-control core + instrument ownership + connection health; `LabApp` constructor injection | A1, A2, A3, A5, A9, A10, C3 | **done** |
| **2** | Typed inputs & identity | B1, B3, B4, §14, §15, §24, §54 | **done** |
| **3** | Pilot integration: 4PP only | A4, A6, A8 in situ | **done** |
| **4** | Calculation integrity: `core/calculation.py`, provenance, method versions, golden files; 4PP pilot | B5–B8, §16–18, §27–28 | **done** |
| **5a-i** | Rollout: Van der Pauw onto the run lifecycle + calculation layer | Milestone 3 | **done** |
| **5a-ii** | Rollout: Hall, same pattern | Milestone 3 | **done** |
| **5b** | Combined VdP + Hall window, tabbed shell | operator feedback | **done** |
| **5c-i** | In-memory Rs handoff: `UpstreamResult`, the provider seam, the CSV load path deleted | §16, §17 | **done** |
| **5c-ii** | Per-sample summary file + the save-collision pre-flight | §16, §17 | **done** |
| **6a** | IV run lifecycle + standby/sweep contract + sweep ownership | A7, A8, §19, §20 | **done** |
| **6b** | Per-driver command traces; cross-experiment enforcement of house rule 12 | §33, C4 | |
| **7** | Persistence, save semantics, operational log, packaging | B9, B10, D2, D4, D8, C7–C10 | |

---

## Wave 2 — Typed inputs & identity

**Free-standing. Almost nothing imports it yet.**

- Frozen dataclasses for run parameters, captured at the moment Run is
  pressed. Editing a Tk variable mid-run must not change what the run is
  doing.
- Shared validators. `int(float(x))` silently accepts `2.5` as 2 at five
  call sites: 4PP points and reversals, IV points, runs and cycles.
  Non-integers must be rejected, not truncated. Note that most other
  `int(float(...))` occurrences are drivers parsing SCPI error codes and
  are correct — do not "fix" those.
- Stable identifiers: sample ID, run ID, row ID, result ID. Wave 4
  depends on these to trace a derived result back to its inputs.
- Unit conventions stated once and applied consistently (§54).

**Proof:** build a params object, mutate every source variable, assert
the snapshot is unchanged. Property tests over the validators.

**Why before the pilot:** an experiment needs lifecycle, ownership *and*
a parameter snapshot at the same instant — the moment Run is pressed.
Integrating with only two of the three guarantees touching every
experiment twice.

### What shipped

Four modules in `core/`, nothing importing them from an experiment yet.

| Module | Holds |
|---|---|
| `core/validation.py` | `ValidationError` and the shared validators. `whole_number` rejects `2.5` instead of truncating it (§24). |
| `core/identity.py` | Sample, run, reading and result identifiers, plus `SampleRegistry` — application-scoped, so a sample measured in VdP and then in Hall is one sample (§15). |
| `core/parameters.py` | `RunParameters` frozen base and `FourPointProbeParameters` (§14). |
| `core/units.py` | The SI convention and the boundary conversions (§54). |
| `core/thread_guard.py` | A diagnostic that records Tk variable access from a worker thread (B2). Off by default. |

`RunController._new_run_id()` now calls `identity.format_run_id()`. The
format is byte-for-byte unchanged.

**Decisions taken, so Wave 3 does not reopen them:**

- Only 4PP gets a parameter class. The other three wait for Wave 5,
  because writing them before the API has met a real experiment means
  writing three that need fixing.
- Sample identity is **application-scoped**, injected into experiments
  the way Wave 1 injects the registry and the ownership manager. Wave 3
  must add the `SampleRegistry` to `LabApp` and pass it down.
- Identifiers are readable and dated (`smp-20260808-a3f19c2b`), not raw
  UUIDs, because they end up in CSV headers and log lines.
- A decimal comma is **rejected**, not interpreted. `0,5` is a half on
  one keyboard and `1,000` is a thousand on another, and guessing is the
  §24 defect in different clothes. Underscores are rejected for the same
  reason: Python's `float()` reads `1_5` as fifteen.

**Left for Wave 3 to discover:** the parameter classes have never been
built from a real panel. Expect `_sweep_params()` to want something
`FourPointProbeParameters` does not have.

**Carried debt:** `SampleRegistry.ref()` mints under a single lock hold.
That is correct by construction, not by evidence — the check-then-act
window could not be reproduced under CPython's GIL (24 threads through a
barrier never split a sample). It starts to matter on a free-threaded
3.14 build, which is already in the CI matrix. `test_identity.py` says
so in the test that exercises it; do not strengthen that claim without
first producing a failure.

---

## Wave 3 — Pilot integration: 4PP only

**First wave that can break the app. One experiment only, deliberately.**

Wire Waves 1 and 2 into `base_experiment` and the 4PP experiment. This
is where the design meets reality; expect to discover that some of the
API from Waves 1–2 is wrong, and fix it here rather than after it has
been copied into four experiments.

**Proof:** a parameterised cancellation-boundary matrix in demo mode —
cancel before start, mid-point, between positions, during settle, after
the last point — asserting no partial data is committed and the
instrument is left safe.

### What shipped

4PP now runs entirely on the Wave 1 and 2 machinery. `measuring` and
`_stop_requested` are gone; the run owns its state, its token and its
provisional data.

| Change | Why |
|---|---|
| `_sweep_params()` returns a `FourPointProbeParameters` | §14 — the worker reads a snapshot, never a widget |
| `_do_run()` is one `begin_run()` block | the ending is owned in one place: status, discard, release, idle |
| `run.checkpoint()` before every energising step | §8's list — output-on, level change, polarity flip, commit |
| `run.expect()` + `record_error()` on a dropped reading | §7 — a short run is refused rather than fitted |
| readings staged on the run, `run.commit()` at the end | §6 — nothing is visible until it is committed |
| ownership claimed for the whole run, entered into cleanup | §12 — the transaction is the run, not the command |
| geometry in metres, `as_math_geometry()` at the boundary | §54, house rule 5 |
| `CSV_SLUG` / `CSV_TITLE` set | see below — they were missing |

**OFF is gone; Stop does the whole job.** Cancel, discard, de-energise.
The decision was that a control which stopped *without* discarding
described an operation the project had already ruled out — §8 says all
cancelled runs are discarded regardless of progress. The structural win
is bigger than the UI simplification: nothing outside the worker now
touches the instrument session, so the old race where OFF sent
`safe_output_off()` from a second thread while the worker was
mid-`measure()` on the same transport is deleted rather than managed.

### What the wiring exposed

Five things, all found by integration rather than by reading. This is
what the pilot wave is for.

1. **`RunContext` could not accept a Wave 2 snapshot.** It did
   `dict(parameters)`; a frozen dataclass is not a mapping. Now takes
   either, and copies neither more than it must. Had 4PP not gone first,
   this would have been discovered in four experiments at once.
2. **`LabApp.ui()` was not thread-safe.** It called `root.after(0, ...)`
   directly from workers. `after()` registers a Tcl command and Tcl is
   single-threaded; the app survived only because the main thread sits
   in `mainloop()`, where Tcl's own handoff covers for it. Any loop
   driven by `update()` instead raises `RuntimeError: main thread is not
   in main loop`, which is how the threaded tests found it. Workers now
   queue and the main thread drains on a 10 ms timer — see `UI_PUMP_MS`.
   **This affects all four experiments.**
3. **4PP never set `CSV_SLUG` or `CSV_TITLE`.** It was the only one. Its
   saved files were `<sample>_run.csv`, its CSV header said "Lab
   measurement suite", and since Wave 1 made the slug the run-id prefix,
   its run identifiers read `run-0001-...` and did not say which
   experiment produced them. **Saved filenames change with this fix.**
4. **The SI round trip is lossy and no arithmetic fixes it.** 180 µm to
   metres and back gave 179.99999999999997, which would reach the CSV
   header. Measured on realistic typed values — integers and one or two
   decimals — dividing by 1e6 fails to round-trip for 2.9% of entries;
   multiplying by 1e-6 fails for 28.7%. `core/units.py` now divides. The
   residue is inherent: compare converted values with a tolerance, never
   with `==`. Worth revisiting in Wave 4 when calculation inputs are
   restructured.
5. **A dropped reading now costs the whole run.** Previously a level that
   returned nothing was skipped with a console line and the fit went
   ahead on the survivors — §7's exact target. It is now an error, the
   commit gate refuses, and the data is discarded.

### Behaviour changes to expect at the bench

- Stop discards. There is no "stop and keep what we have".
- A dropped reading fails the run instead of shortening it.
- Saved 4PP files are named `<sample>_ossila_4pp.csv`.
- Progress lines lag by up to 10 ms. Invisible next to a settle delay.

### Carried forward

The other three experiments are untouched and still use their own
`measuring` flags, their own OFF buttons and `current_sample_name()`.
Wave 5 applies this pattern to Van der Pauw and Hall; the cancellation
matrix is written to be re-parameterised rather than rewritten.

---

## Wave 4 — Calculation integrity

**Done.** `core/calculation.py`, plus 4PP as the single pilot.

- Structured calculation inputs rather than reading widget strings:
  `CalculationInput` holds SI values *and the text they were typed as*.
- Mixed-sample inputs rejected, with a message naming both samples
  (§16). Matched on `sample_id`, so renaming a sample does not refuse a
  calculation on the material it names.
- `validate()` for required values, `require_set()` for §27's complete
  position/polarity sets. The latter has no caller yet — it is for Van
  der Pauw's four positions and Hall's eight combinations in Wave 5,
  built and tested here the way Wave 2 built the validators ahead of
  their first use.
- `METHODS`: one table of calculation names and versions (§28), with
  `tests/golden/` holding a known dataset per method. Changing a formula
  without bumping its version turns that red.
- `DerivedResult` carries the §17 field list — result id, sample id,
  label at calculation, source run and row ids, method, version,
  timestamp — and lands in the CSV header.
- Stale results grey out and are refused by `calculated_fields()`, so a
  number whose inputs have moved cannot reach a file (§18).

**Also fixed, found while wiring it:** `save_runs()` attached the
calculated block to the group whose *name* matched the sample box, but
the store is keyed by `SampleRef.slug`. The two disagree for any label
with punctuation in it — `film #1` — so the calculation was dropped from
the file with nothing said. Now matched on `sample_id` for experiments
whose runs carry one.

**Left deliberately:**

- Van der Pauw, Hall and the IV sweep are untouched. Their runs record
  no `run_id` or `sample_id`, so provenance built into them today would
  point at Treeview item ids. They get it in Wave 5, wired once,
  alongside their run lifecycle — not twice.
- `vdp_resistivity` is registered but has no golden file: it is computed
  inline in the VdP experiment rather than in `vdp_math`. Wave 5 moves
  it into the maths module and it gets one there.
  `tests/golden_cases.NOT_YET_COVERED` says so, and the suite fails if
  a method is added with neither cases nor a stated reason.

**Pending bench verification** (nothing here touches an instrument path,
so both are cosmetic):

- that the provenance block reads sensibly in a real saved CSV header;
- that greying on every geometry edit is not irritating in practice
  while iterating on a sample.

**Proof:** the existing notebook-parity tests must stay bit-identical —
that is the guard rail. `test_hall_math` and `test_iv_math` are the ones
to watch; they are also the tests that could never fail before Wave 0a,
so treat their green as meaningful only now. No arithmetic was touched
in this wave, so their green is structural rather than lucky.

---

## Wave 5 — Rollout, then the combined window

Split into four patches after the operator feedback that a Van der Pauw
run *always* immediately precedes a Hall measurement, on the same
mounted sample with the same contacts. That makes the two one session
rather than two programs, but the rewiring has to land first: merging
them before they are on the run lifecycle would mean touching both files
twice.

### 5a-i — Van der Pauw onto the lifecycle (**done**)

- `VanDerPauwParameters` frozen at the Run press. Position is in the
  snapshot, so clicking the spinner mid-run cannot change what the run
  claims to be.
- `_do_run(params)` inside `begin_run()`: ownership claimed before the
  first command, §8's checkpoints, `run.sleep()` so Stop during a settle
  is felt at once, provisional readings, commit gate.
- Run/Stop replaces Run/OFF. `off_pressed()` fired `safe_output_off()`
  from a second thread onto the session the worker was measuring on.
- `measuring` and `polling` deleted (A6).
- Calculation onto Wave 4's layer: `SourceRow` per position,
  `require_set()` at copy time, mixed-sample refusal, staleness gate.
- `vdp_math.resistivity()` extracted from the experiment;
  `vdp_resistivity` gets a golden file and `NOT_YET_COVERED` empties.
- `tests/test_vdp_lifecycle.py` (14) and `tests/test_vdp_calculation.py`
  (8). `stage_blocking_smu.py` gains a `second_polarity` stage: Van der
  Pauw averages its two blocks, so a cancellation that left the positive
  block behind would give an R(ave) that is not an average of anything.

**A bug this wave shipped and caught.** The calculation stored its
thickness under `thickness_m` while the staleness trace sampled
`thickness_um`. The signatures could never match, so every result read
as permanently stale and its numbers silently stopped reaching the CSV -
no error, no dialog, just a header with no Rs. `test_saving` caught it.
`core.calculation.signature_difference()` now reports a disjoint field
set as a wiring fault rather than an edit, and `stale_because()` names
which field moved. 4PP's keys happened to already agree, by luck.

### 5a-ii — Hall, same pattern (**done**)

- `HallParameters` frozen at the Run press. The **field sign** is in the
  snapshot: a Hall run is defined by the pair (position, B sign), and a
  run whose recorded sign did not match the magnet is not slightly
  wrong, it is uninterpretable.
- `_do_run(params)` inside `begin_run()`, Run/Stop replacing Run/OFF,
  `measuring` deleted. Hall was the last of the three to lose the OFF
  button.
- The four (position, sign) combinations go through `require_set()` at
  copy time. Four ticked rows fill *eight* boxes, so provenance is one
  run per pair.
- The polarities stay separate. Van der Pauw averages +I and -I into an
  R(ave); Hall must not, because the difference between them is the
  signal.
- `calculated_sample_id()` overridden — the last
  `current_sample_name()` comparison is now gone from all three ported
  experiments.
- `tests/test_hall_lifecycle.py` (13) and
  `tests/test_hall_calculation.py` (9), plus `hall_harness.py`.

**Two judgement calls worth recording.**

*Provenance is all-or-nothing per run.* Each run fills a V+ box and a
V- box. Type over one and the run is dropped as a source entirely,
rather than staying because its other box still matches. Claiming a run
against a pair of voltages it did not both produce would put a half-true
chain in the header, and a half-true chain reads exactly like a whole
one.

*`sample_type` is a watched staleness field.* Switching "Thin film" to
"Bulk" changes which carrier density is reported by a factor of the
thickness, and **none of the eight voltages move when it happens**. A
staleness rule watching only the numbers would miss it.

**Also fixed, found while wiring it.** The Wave 4 identity binding in
`save_runs()` applied as soon as the *calculation* had a `sample_id`,
regardless of whether the runs did. A store holding both kinds at once
— runs recorded before an experiment was wired up, or rows put into the
table directly — silently dropped the calculation from the file. Now
tested per group: identity where the runs carry one, name where they do
not.

### Between 5a-ii and 5b — the suite stopped scanning the network

Found from a warning count, not a failure. Every `LabApp(...)`
construction was running `VisaTransport.list_available()`, which walks
three backends and, through pyvisa-py, scans the network for TCPIP
instruments. Predates Wave 5 - `test_4pp_lifecycle` was the slowest file
in the suite - but three new app-per-test files pushed it past the point
of being noticeable.

`conftest.py` now stubs transport discovery for every test without the
`instrument_discovery` marker. The Windows GUI suite went from about
nine minutes to under two.

The speed was the symptom. The defect was that the suite's runtime
depended on the lab's network, and on CI, on GitHub's.


### Housekeeping owed, to fold into the next patch

Small, unrelated to any wave, and written down so they are not
rediscovered:

- `checkups/` into `.gitignore` — generated output from
  `tools/smu_checkup.py`, currently untracked in the working tree and
  one absent-minded `git add -A` from being committed. It has already
  wedged a `git stash -u` on Windows. Audit what else `tools/` writes
  into the tree while there.
- `--strict-markers` in `pyproject.toml`. `get_closest_marker()` returns
  None for an unregistered name, so a marker typo fails *open* -
  `instrument_discovery` misspelled in `conftest.py` would silently stub
  the one file that must not be stubbed.
- Confirm `git config status.showUntrackedFiles` is not `no` on the
  bench machine.


### 5b — the combined window (**done**)

`LabApp` hosts one experiment or several. `LabApp(root, VanDerPauwExperiment)`
still means what it meant; `LabApp(root, [VanDerPauwExperiment,
HallExperiment])` is a two-tab window, and `main.py vdp_hall` opens it.

Tabs rather than one scrollable page, decided after weighing both: Stop
must never scroll off-screen, `test_layout.py` reads `winfo_reqheight()`
and a scrolled canvas would make that assertion tautological, and
matplotlib canvases inside a scrolling Canvas eat wheel events. Nothing
here is a one-way door - a scrolled layout later is the same work.

**A single-experiment window builds no notebook.** One unclickable tab
costs about 32 px of vertical budget, and the four single windows have
none to spare. The combined window measures 1552x989 open and 843
folded, against a 1600x1000 / 860 ceiling.

| Moved to the window | Why |
|---|---|
| `TemperatureController` + its panel | two tabs meant two controllers on one COM port |
| sample name, thickness | one mounted film, two measurements |
| measurement counter, save path | one session, one folder, one counter |
| the run gate | the tabs share one SMU |

**What the merge does *not* do**, and the two are separable: the results
tables, the arithmetic, the golden files, the saved CSVs and the run
identifiers stay per experiment. Van der Pauw averages +I and -I; Hall
must not, because the difference between them is the signal. Merging
the two experiment *classes* would have fused exactly the parts that
have to stay apart, to buy sharing the window already provides. Run ids
still read `vanderpauw-0001-...` and `hall-0001-...`, so a saved file
still says which measurement produced it.

**Two declarations rather than code**, so adding or removing either is
one visible line: `USES_TEMP_STAGE` says an experiment sits on the
stage, and `SESSION_FIELDS` says which strip fields it reads. The 4PP
declares neither - its thickness belongs to a geometry that also carries
a width and a length, and a second box claiming the same quantity is a
second thing to be wrong.

**The run gate is two interlocks plus a house rule.** Each experiment
keeps its own `RunController`; `app.busy_experiment()` answers "is
anybody in this window busy". Ownership was already the guarantee - both
tabs claim the same instrument key and the second is refused - so the
gate only changes *when* the refusal lands, which is before the operator
has been sent to the switch box, and greys the other tab's Run button so
it is visible rather than merely disappointing.

**A bug this wave shipped and caught, in its own test file.** The first
version of the shared-variable guard asserted that both experiments and
the app agreed on which variable object holds the sample name. A
mutation putting a private `tk.StringVar` back into the Van der Pauw
setup panel *passed it*: rebinding `exp.app.sample_name_var` leaves all
three readers agreeing, and strands only the widget the operator types
into. The box does nothing, every reader sees `sample` forever, and
nothing raises. The guard now drives the Entry the way a finger does,
and `bound_variable()` checks every session widget in every window shape
is wired to the live variable. Identity between readers was necessary
and not sufficient.

**Also folded in, owed from 5a-ii:** `checkups/` into `.gitignore` -
`tools/smu_checkup.py --out` is the only tool that writes into the tree,
`make_goldens.py` writes `tests/golden/` which is tracked and meant to
be - and `--strict-markers` in `pyproject.toml`, so a marker typo is a
collection error rather than a rule that fails open.

`tests/test_combined_window.py` (21). Suite 470 -> 491.

**Behaviour changes to expect at the bench**

- `main.py vdp_hall` is the new default way in. The four single windows
  are unchanged and still there.
- Sample name, thickness, next number and save path are on the strip
  above the tabs, not in the measurement setup panel.
- The stage panel is a rail down the left of the window, outside the
  tabs. Switching tabs does not change what is holding the sample at
  temperature.
- Hall's results table shows seven rows rather than eight. A Hall
  calculation needs four ticked rows, so a complete set still fits; the
  row was the window's height budget.
- Starting a run on one tab greys the other tab's Run button.

**Left for 5c:** the strip carries sample and thickness but not yet the
Van der Pauw result - that is the in-memory `DerivedResult` handoff.
`app.experiment_of(cls)` was expected to be the seam; 5c-i used
`app.provider_of(quantity)` instead, for the reason recorded there.

### 5c-i — the handoff (**done**)

Rs crosses in memory as a `DerivedResult`, so Hall's resistivity names
the Van der Pauw run that supplied its sheet resistance. `vdp_result.py`
is gone with its only production caller; `test_hall_handoff.py` was
replaced by `tests/test_rs_handoff.py` rather than adapted, since it was
entirely about a file round trip that no longer happens. Its carrier-type
half moved into `test_hall_calculation.py`. `Hall.rs_source_path` became
the Van der Pauw result's `result_id` and its runs.

**The seam turned out not to be `experiment_of(cls)`.** Naming
`VanDerPauwExperiment` inside Hall would mean no Hall tab could open
without importing Van der Pauw, fusing two experiments that share a
window into one unit. So Van der Pauw declares
`PROVIDES = ("sheet_resistance",)` and Hall asks
`app.provider_of("sheet_resistance")`. The 4PP computes a sheet
resistance too; the day it shares a window with Hall it declares the same
string and nothing else changes.

**A derived value feeding another calculation needed a shape of its
own.** `UpstreamResult` sits in `CalculationInput.upstream`, not among
the `SourceRow`s: folded into `sources`, Van der Pauw's Pos1–4 would be
refused by `require_set()` as unexpected combinations, and the saved
header would claim eight Hall voltages came from twelve runs. §16 now
applies one indirection out, and `upstream_signature_items()` is called
from both the panel and the calculation so the two cannot drift on a
field name — the Wave 5a-i failure, which this wave would otherwise have
had a fresh opportunity to repeat.

**Two findings, both recorded in `PORTING_NOTES.md`.**

The sample-name warning at the transfer *could never fire*. Van der
Pauw's staleness signature includes the sample name, so renaming the
strip makes its result stale and the transfer is refused before any
mismatch check runs. Stricter than designed, and correct; the dead check
was deleted rather than left to reassure whoever reads it next.

The first mixed-sample guard passed with the new check deleted — Hall's
own runs belonged to the old sample too, so the pre-existing source-row
check refused the calculation on its own. The voltages are typed in that
test now, so the carried-over Rs is the only thing that can carry the old
sample in.

`tests/test_rs_handoff.py` (16), `test_hall_calculation.py` (9 → 11),
`test_calculation.py` (23 → 30). Suite 649 → 671.

**Behaviour changes to expect at the bench**

- `main.py vanderpauw` and `main.py hall` are gone. `vdp_hall` is how
  both are reached; `iv_sweep` and `ossila_4pp` are unchanged.
- The Rs box has **Take Rs from VdP** beside it and a line underneath
  saying where the number came from, or that it was typed.
- Pressing it before Van der Pauw has calculated, or after its inputs
  have changed, refuses and says which input moved.
- A stage-temperature difference over 1 °C warns and carries the value
  over anyway. A deliberate temperature series is that shape.
- Typing over the Rs box drops its citation; the header then says the
  value was typed rather than naming a run that did not supply it.
- Saved Hall files carry `input_sheet_resistance_from` instead of
  `Rs_source`. Neither spelling appears in both.

### 5c-ii — the summary file (**done**)

Summary file per sample, **regenerated on each save, never appended** —
accumulation across sessions would settle Wave 7's open save-semantics
decision by accident.

Written by the app rather than by either experiment: the point of it is
that it spans both measurements of one sample, and a per-experiment
writer would produce two half-summaries. Each experiment declares its
headline quantities in `SUMMARY_QUANTITIES` and the app asks every tab
what it would contribute — the same capability seam as `provide()`, so
the app never learns any experiment's result shape. A section that has
not been calculated says so explicitly rather than being absent, because
a summary that silently omits Hall looks identical to a sample that was
never Hall-measured.

**The overwrite is guarded by a pre-flight check, not by a dialog at
save time.** Every data CSV already auto-suffixes and cannot be
destroyed; the summary is the first file in the suite that can replace
itself. So at the *first Run press* for a given sample name and save
folder, if files for that sample already exist, the operator is asked
once — same sample and regenerate, or keep the old ones separate — and
the answer is remembered for the session so Save never asks again. It
re-arms if the sample name or the save folder changes.

Asking then rather than at Save is the point: after the runs are
committed they carry the sample identity they were measured under, and
renaming the box afterwards does not retroactively fix them. The check's
larger value is not overwrite protection at all — it is telling the
operator "you already have data under this name here" before twenty
minutes of measuring, which is the only moment a mistyped sample name is
cheap to fix.

A `PermissionError` writing the summary — someone has it open in Excel,
which is a Windows-specific certainty rather than a hypothetical — is a
logged warning after the CSVs are written, never an aborted save.

**Two traps found by mutation, recorded so they are not re-introduced.**

The inner all-empty guard in `write_sample_summary` was untested at
first: `save_runs` only calls the writer when its tab has a calculated
result, so the outer path never reaches the branch. The app method is
called per sample and must defend itself, so it has its own direct test
now - asked to summarise a sample nothing has calculated, it writes
nothing rather than replacing a good summary with a page of "not
calculated".

The sample-name trace fires on *every* write, including re-setting the
box to the value it already holds. Re-arming on those silently turned a
chosen overwrite back into a suffix by the time Save ran. The re-arm is
guarded against no-op writes: only a genuine change to a different
(sample, folder) clears the decision.

**Decided, so it is not reopened:** the CSV load path was deleted in
5c-i rather than kept as a fallback. There is never a Monday Van der
Pauw and a Tuesday Hall.

**Decided in Wave 4, and superseded by 5c-i's findings:**
`load_rs_from_vdp()` was to stay a *warning* on a sample mismatch rather
than a refusal. It is a refusal, because the mismatch reaches the
transfer as staleness rather than as a mismatch. The reasoning behind
the Wave 4 decision still stands — loading a value into a box is not a
calculation — it simply never gets the chance to apply.

Open question inherited from 5a-ii: whether to label negative carrier
density/mobility as n-type/p-type in the UI.

---

## Wave 6 — IV standby/sweep contract + driver traces

- The standby ↔ sweep transition contract (§19, §20): compliance set
  before output on, source function changes only in a safe state.
- Sweep worker lifecycle under cancellation.
- Per-driver command traces asserted against a fake transport, so a
  dialect change shows up as a failing trace rather than a wrong number
  at the bench.

---

## Wave 7 — Persistence and packaging

- Save semantics (§25). **Decision still open:** A snapshot / B new-only
  / C append-only. B is the recommendation, but confirm before building.
- Operational event log (§26), including the software version — which
  requires the app to know its own version.
- Schema versions on stored files.
- Resource packaging via `importlib.resources` (§42). This is where the
  question of a `src/` layout gets settled, deferred from Wave 0b.
- Python 3.14 move: update `requires-python` and the CI matrix.

---

## Open decisions

Neither blocks the next wave, but both need answering before Wave 7.

1. **Save semantics** — options A/B/C in §25.
2. **Can two instances of the app run at once?** Process-local
   instrument ownership is a very different object from cross-process
   ownership. Wave 1 assumed process-local.

---

## Working protocol

**One conversation per wave.** Start it with:

> Wave N, <name>. Repo: https://github.com/jcgutierrezg/SMUniversal_Lab_Suite,
> branch `main`. Fetch with
> `curl -sL https://codeload.github.com/jcgutierrezg/SMUniversal_Lab_Suite/tar.gz/refs/heads/main`.
> Read `WAVE_PLAN.md` for scope, and the sections of
> `LAB54_DEVELOPMENT_REVIEW_AND_WORKFLOW.md` it names. Deliver as a
> `.patch` against `main`.

**Delivery is a `.patch` file**, applied with `git apply`. A patch
expresses deletions, renames and moves; a zip cannot, which is how the
orphaned `temp_panel.py` survived Wave 0b's zip and got caught only by a
test. Confirm the base commit (`git log --oneline -1`) before generating
any patch — the one failed application in Wave 0 was an assumed base.

`.patch` files are gitignored. Do not commit them.

**Tests run with `run_tests.py`, not plain `pytest`.** See
`tests/README.md` for why.

**Windows CI is load-bearing.** It found a `ZeroDivisionError` and
15.6 ms clock quantisation that a Linux container structurally cannot
reproduce. A red Windows job is information, not noise.

**Do not delete `_retry_tk_construction` in `tests/conftest.py`** on the
grounds that it never fires. It is instrumentation for an unresolved
intermittent fault; `tests/README.md` records what has been ruled out.

**Gather evidence before proposing fixes.** Wave 0 lost several days to
theorising about an intermittent Tcl failure and shipping fixes that
made it worse. Progress came only from diagnostics that could return
facts. If a fix is being proposed for a fault that cannot be reproduced
on demand, that is the signal to build a diagnostic instead.

---

## Known technical debt

Recorded so it is not rediscovered as a surprise.

- **Order-dependent test files.** Eight files share Tk roots and
  fake-driver classes across tests via `global`, preserving the
  behaviour of the original scripts. They cannot be run in isolation and
  would break under `pytest-xdist`. Convert to module-scoped fixtures as
  each experiment is touched in Waves 3 and 5.
- **Two test styles coexist**: converted section tests using the `check`
  fixture, and wrapped collector tests. Documented in
  `tests/README.md`.
- **`core.driver_registry`** remains as a deprecation shim. Remove once
  nothing external imports it.
- **Five `int(float(...))` call sites remain in the experiments** — 4PP
  points and reversals, IV points, runs and cycles. Wave 2 built the
  validators that replace them but deliberately did not touch an
  experiment file; Waves 3 and 5 swap them over as each experiment is
  wired up. The seven in `drivers/` parse SCPI error codes and are
  correct as they are.
- **`SampleRegistry` is process-local**, like Wave 1's ownership
  manager. If the answer to "can two instances of the app run at once?"
  turns out to be yes, both need revisiting together.
- **Cancellation cannot preempt a reading in progress.** The settle
  delay is handed to the instrument with `set_source_delay()`, so it
  happens inside the driver's blocking `measure()`. The honest bound is
  one reading, and `test_4pp_lifecycle.py` measures the rest of the path
  rather than asserting it. Moving the settle into `run.sleep()` would
  make cancellation near-instant but would change *where the settle
  happens*, which is a measurement parameter and not a UI detail — it
  needs a bench comparison before it goes near real hardware.
- **`test_4pp.py` still drives `_do_run()` on the main thread.** Its
  green says nothing about threading; that is `test_4pp_lifecycle.py`'s
  job. Left as-is deliberately: churning a 434-line passing test file is
  where a real regression hides.
