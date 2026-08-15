# Lab 54 Repository Review and Recommended Development Workflow

**Status:** Work in progress  
**Purpose:** Engineering handoff and ordered development plan  
**Audience:** Repository maintainers and developers  
**Scope:** Static repository review, software test observations, run-control design, data integrity, instrument safety, architecture, testing, and packaging

---

> ## Where each item stands
>
> **This document is the original review and is not edited as work is done.**
> It is the statement of the problem; rewriting it would lose the reasoning
> that justified each wave, and a review that quietly agrees with the code is
> no longer a review.
>
> Resolution status lives in two places: `WAVE_PLAN.md` for which wave took
> which item, and `PORTING_NOTES.md` for what was actually found once someone
> looked.
>
> Worth reading alongside the items closed by Wave 6, because in each case
> the review predicted the fault and the fault was real:
>
> | Item | Where it went |
> |---|---|
> | §8, §9 — cancellation and Stop | Waves 3, 5a, 6a. Stop now discards in every experiment, including the periodic IV run |
> | §19 — periodic-bias output continuity | Wave 6a. Became house rule 12 in `HANDOFF.md`: nothing is configured while the sample is energised |
> | §20 — orphaned sweep workers | Wave 6a. The fault was real and worse than described: an orphaned worker appended its points into the *next* sweep's buffer, and the result fitted a straight line without complaint |
> | §33 — driver state-transition traces | Waves 6b, 6c, 6e |
>
> One theme is worth carrying forward. Several of these were found not by
> reading the code but by *running* it and watching the wire — ordering is not
> a property of any single method, and a hand-check of three experiments
> during Wave 6a reported compliance for two that did not comply.

## 1. Executive summary

The repository already has a strong engineering foundation. Its structure, instrument abstractions, documentation, safety concepts, and test coverage are substantially better than is typical for an early-stage laboratory application.

The principal concern is not the quality of the individual instrument command dialects. The largest risks are concentrated in the orchestration layer:

- starting more than one run against the same instrument;
- cancelling a run while a worker thread is still issuing commands;
- re-enabling output after the operator has pressed **OFF**;
- retaining or exporting partial measurements;
- assigning measurements or calculations to the wrong sample;
- and allowing UI state to change the meaning of an active run.

The recommended next phase should therefore prioritize, in this order:

1. A unified run lifecycle and cancellation model.
2. Exclusive instrument ownership for the full duration of a run.
3. Provisional data buffering and atomic result commit.
4. Safe, verifiable output shutdown.
5. Immutable run parameter snapshots and correct sample provenance.
6. Correction of the IV standby-bias and sweep interaction.
7. A stricter calculation and derived-result provenance model.
8. Test-suite consolidation and cancellation race testing.
9. Connection initialization and degraded-state handling.
10. Packaging, dependency, resource, and architecture cleanup.

A core project invariant should be adopted immediately:

> A run becomes scientific data only after the complete requested sequence has finished successfully. Cancelled, failed, interrupted, or uncertain runs are discarded and must never enter the result store, calculations, or exported data files.

Operational logs may record that a run was attempted, cancelled, or failed. They should remain separate from scientific measurement data.

---

# Part I — Existing strengths

## 2. Repository structure and separation of concerns

### Finding

The repository has a deliberate separation between:

- experiments and their user interfaces;
- instrument drivers;
- communication transports;
- shared controls and panels;
- device-specific support;
- calculations and persistence;
- and tests.

The separation is not perfect, but it gives the project a credible base for continued development.

### Why this matters

Laboratory software tends to become difficult to maintain when UI controls, SCPI commands, calculations, file writing, and safety logic are all mixed into event handlers. This repository generally avoids that failure mode.

### Recommendation

Preserve the existing high-level layering while strengthening the boundary between:

- experiment orchestration;
- instrument ownership;
- UI state;
- and committed scientific results.

Do not perform a broad architectural rewrite before run control and data integrity are stable. Incremental refactoring will be safer and easier to validate.

---

## 3. Instrument-driver design

### Finding

The driver layer demonstrates good awareness of real instrument behaviour rather than assuming that all SMUs implement an idealized common dialect.

Positive elements include:

- explicit capabilities;
- driver-specific command sequences;
- fallback from hardware sweeps to software sweeps;
- handling of source-function changes;
- compliance and limit concepts;
- instrument error-queue checks;
- and shutdown cleanup.

### Why this matters

The most dangerous abstraction in measurement software is one that hides meaningful behavioural differences between instruments. The current design generally makes those differences visible.

### Recommendation

Continue using explicit capabilities, but make the driver contract stricter and add command-trace tests around state transitions, particularly:

- source-function changes;
- compliance changes;
- output enable and disable;
- hardware versus software sweeps;
- cancellation during a sweep;
- and reset or initialization failures.

---

## 4. Documentation quality

### Finding

The repository documentation is unusually useful for a WIP project. The available README, handoff notes, instrument notes, and porting notes describe both implementation and intent.

### Why this matters

Intent is essential when reviewing safety-sensitive code. Without it, developers may preserve existing behaviour without understanding whether that behaviour is deliberate, temporary, or accidental.

### Recommendation

Keep documentation close to code changes. The workflow described in this document should become a tracked repository document and be updated as milestones are completed.

For every major lifecycle change, document:

- the invariant being enforced;
- which code owns it;
- which tests prove it;
- and any remaining known limitation.

---

# Part II — Phase 1: unified run lifecycle

## 5. Adopt one run-state model across all experiments

### Finding

Run state is currently handled differently between experiments. IV and 4PP have more explicit run guards and stop flags. Van der Pauw and Hall do not provide the same level of protection.

Scattered flags such as `is_running`, `stop_requested`, and output booleans are vulnerable to inconsistent combinations and race conditions.

### Risk

Without an explicit lifecycle, the application can enter states such as:

- the UI reports idle while a worker is still active;
- output is off but a worker later turns it back on;
- cancellation is requested but a result is still committed;
- a second run starts before cleanup from the previous run finishes;
- or an exception bypasses part of the expected state transition.

### Recommendation

Define a shared state machine. A practical initial model is:

```text
IDLE
PREPARING
RUNNING
CANCELLING
COMPLETED
FAILED
CANCELLED
```

The exact names are less important than enforcing legal transitions.

Suggested transitions:

```text
IDLE -> PREPARING
PREPARING -> RUNNING
PREPARING -> FAILED
PREPARING -> CANCELLING
RUNNING -> COMPLETED
RUNNING -> FAILED
RUNNING -> CANCELLING
CANCELLING -> CANCELLED
CANCELLING -> FAILED
COMPLETED -> IDLE
FAILED -> IDLE
CANCELLED -> IDLE
```

Do not permit direct transitions that bypass cleanup. For example, `RUNNING -> IDLE` should not be legal.

### Implementation notes

Create a shared run-controller object responsible for:

- allocating a unique run ID;
- validating state transitions;
- holding the cancellation token;
- controlling whether a second run may start;
- disabling and re-enabling relevant UI controls;
- owning provisional measurements;
- recording terminal status;
- and coordinating cleanup.

The UI should observe the controller state rather than infer state from button text or worker-thread existence.

### Acceptance criteria

- Every experiment uses the same state model.
- A second run is rejected unless the previous run has reached a terminal state and completed cleanup.
- No path can commit a result from `FAILED`, `CANCELLED`, or `CANCELLING`.
- Exceptions always produce a terminal state.
- The UI returns to `IDLE` only after instrument ownership is released.

---

## 6. Treat all in-progress measurements as provisional

### Finding

Some experiment paths appear to append data during execution rather than staging the entire result privately until successful completion.

### Risk

If a run is cancelled or fails after partial acquisition, rollback becomes necessary. Rollback is difficult to make reliable when:

- UI tables are already populated;
- calculations can access the rows;
- autosave or export can see them;
- observers have received change notifications;
- or multiple data structures reference the same objects.

A partial run can then be mistaken for valid scientific data.

### Recommendation

Use a two-phase data model:

1. **Provisional acquisition:** readings exist only inside the active run context.
2. **Atomic commit:** the complete result is added to the permanent result store only after all success conditions are satisfied.

Conceptual example:

```python
run = RunContext(parameters=snapshot)

try:
    run.provisional_rows.extend(acquire_measurements(run))
    validate_complete_run(run)
    confirm_safe_shutdown(run)
    result_store.commit(run.to_completed_result())
except RunCancelled:
    run.discard()
    raise
except Exception:
    run.discard()
    raise
```

### Important rule

Do not use the visible results table as the provisional buffer. A visible progress display may show temporary values, but it must clearly indicate that they are live and uncommitted, and it must be cleared on cancellation or failure.

### Acceptance criteria

- Cancelled and failed runs leave zero committed measurement rows.
- They cannot be selected for calculations.
- They do not appear in exports.
- Cancellation immediately before commit still produces no committed result.
- A successful commit occurs once and only once.

---

## 7. Define completion as an explicit validation gate

### Finding

A run can appear to have completed its measurement sequence while still having unresolved errors, incomplete metadata, or unsuccessful output shutdown.

### Recommendation

A run should be marked `COMPLETED` only when all of the following are true:

1. The full requested sequence executed.
2. All required measurement positions, polarities, points, or repetitions are present.
3. All readings passed validation.
4. No cancellation was requested before commit.
5. No unresolved driver or instrument errors remain.
6. Required metadata is complete.
7. Output shutdown has completed according to the project’s shutdown policy.
8. The completed result can be committed atomically.

### Design decision

For this project, an inability to confirm safe shutdown should classify the run as failed and discard its measurements. The operator should receive a prominent warning because the instrument may still be energized or in an uncertain state.

### Acceptance criteria

A central function or policy object determines completion. Experiments should not independently decide that a run is successful using different criteria.

---

# Part III — Phase 2: cancellation and OFF behaviour

## 8. Make OFF a system-wide cancellation operation

### Finding

In Van der Pauw and Hall, the OFF action can turn output off without necessarily stopping the worker. The worker may continue reading, progressing through stages, or issuing later source commands.

### Risk

A worker can re-enable output after the operator pressed OFF. It may also record invalid readings taken after output was removed.

### Required behaviour

For every experiment, pressing **OFF** during a run should:

1. atomically mark the current run as cancellation requested;
2. prevent the worker from issuing further commands that energize or alter the output;
3. request immediate output-off through the active instrument session;
4. allow or force the worker to leave its current blocking operation;
5. wait for worker termination within a bounded cleanup policy;
6. discard all provisional measurements;
7. verify or report shutdown status;
8. release instrument ownership;
9. return the UI to a known idle state.

The user requirement is unambiguous: **all cancelled runs are discarded regardless of experiment or progress.**

### Race condition to prevent

```text
UI:     cancellation requested
UI:     output_off()
Worker: configure source
Worker: output_on()
```

The cancellation token must therefore be checked:

- before output-on;
- before changing source function;
- before setting a new source level;
- before changing polarity;
- before entering a hardware sweep;
- after every potentially long wait;
- and immediately before final commit.

### Acceptance criteria

- OFF never allows output to be re-enabled by an obsolete worker.
- No partial data survives.
- OFF produces a normal cancellation message, not an error traceback.
- A new run cannot start until cleanup completes.

---

## 9. Separate cancellation, failure, and emergency shutdown

### Finding

These events may currently share similar cleanup paths but they have different meanings.

### Recommendation

Model at least three concepts:

#### Operator cancellation

The operator intentionally stops a valid run.

Expected outcome:

```text
Run cancelled. No measurements were retained.
```

#### Run failure

The run terminates due to an instrument error, timeout, invalid data, communication failure, interlock state, or software exception.

Expected outcome:

```text
Run failed during <stage>. No measurements were retained.
Output shutdown was confirmed.
```

#### Emergency or uncertain shutdown

Output-off could not be performed or verified, or instrument communication was lost while output may have been active.

Expected outcome:

- the run fails and is discarded;
- instrument ownership remains logically blocked or degraded;
- the UI presents a prominent warning;
- reconnect or operator intervention is required before another run.

### Why this matters

Cancellation should not be treated as an application error, while uncertain shutdown should not be treated as a routine cancellation.

### Acceptance criteria

Terminal status and user messaging distinguish all three cases. Operational logs retain the distinction.

---

## 10. Use per-run cancellation tokens and generation IDs

### Finding

Shared stop flags and shared sweep state can be overwritten by a newer operation while an older worker remains alive.

### Risk

An obsolete worker may continue using mutable shared state or may interpret a newly cleared stop flag as permission to continue.

### Recommendation

Every run should own:

- a unique immutable run ID;
- a private cancellation event or token;
- private worker state;
- private provisional data;
- and a captured parameter snapshot.

The run ID can also act as a generation token. Before a command is issued, the controller can verify that the worker still belongs to the currently active session.

Conceptual pattern:

```python
class RunToken:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.cancel_event = threading.Event()

    def raise_if_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise RunCancelled(self.run_id)
```

Avoid one global `stop_requested` flag shared by consecutive runs.

### Acceptance criteria

An obsolete worker cannot issue commands after a new run has been allocated, even if the obsolete thread exits late.

---

## 11. Make cancellation responsive during waits

### Finding

Long `sleep()` calls delay cancellation and can make OFF appear unresponsive.

### Recommendation

Replace long sleeps with cancellation-aware waiting:

```python
if token.cancel_event.wait(timeout=settling_seconds):
    raise RunCancelled(token.run_id)
```

For longer operations, use short bounded intervals and inspect cancellation between intervals.

For VISA or serial timeouts, cancellation may require one of the following:

- reducing individual I/O timeout lengths;
- using an instrument abort command when supported;
- closing or interrupting a transport in a controlled manner;
- or allowing cleanup to continue after a bounded timeout while marking the connection degraded.

### Acceptance criteria

Cancellation latency is measured and bounded for:

- settling delays;
- software sweeps;
- hardware sweeps;
- temperature reads;
- serial communication;
- and stalled instrument queries.

---

# Part IV — Phase 3: exclusive instrument ownership

## 12. Protect complete measurement transactions, not individual commands

### Finding

A transport lock can serialize individual VISA or serial calls, but it does not prevent two workers from interleaving complete measurement sequences.

### Example risk

```text
Run A: configure voltage source
Run B: configure current source
Run A: set level
Run B: output on
Run A: measure
```

Every individual call may be thread-safe while the combined experiment is invalid.

### Recommendation

Create an instrument-session or ownership layer that grants exclusive control for the full duration of a run.

Conceptual API:

```python
with instrument_manager.claim(instrument_id, run_id) as session:
    session.configure(...)
    session.output_on()
    ...
```

Ownership should cover:

- configuration;
- source changes;
- measurements;
- sweeps;
- cancellation cleanup;
- output verification;
- and error-queue inspection.

### Policy decisions

- One physical instrument may have only one active owner.
- Manual controls must not issue commands while a run owns the instrument, except through a designated cancellation or emergency-stop path.
- Reconnect, reset, and disconnect should be disabled or routed through the controller while a run is active.
- A session is released only after cleanup is complete.

### Acceptance criteria

- Two experiment windows cannot run against the same instrument concurrently.
- A rejected second run produces a clear user message.
- Manual controls cannot silently modify an active run.
- Ownership is released after success, cancellation, and failure.

---

## 13. Decide ownership scope across application windows

### Finding

The risk is especially important if multiple experiment windows can share the same physical SMU.

### Recommendation

Instrument ownership must be application-wide, not local to an experiment panel.

The ownership key should represent the physical connection, for example:

- VISA resource address;
- serial port;
- miniSMU device identity;
- or a stable internal connection ID.

Do not use only the driver object’s Python identity if separate driver instances can point to the same resource.

### Acceptance criteria

Opening a second experiment view does not create an independent path to command the same hardware.

---

# Part V — Phase 4: immutable inputs and sample provenance

## 14. Capture an immutable run parameter snapshot

### Finding

Some worker threads read Tkinter variables directly, and sample names or other fields may be read when a run finishes rather than when it begins.

### Risks

- Tkinter access from worker threads is not reliably thread-safe.
- Changing a field during a run can alter later stages.
- A sample rename during a long run can relabel the result.
- Exported metadata may not describe the settings actually used.

### Recommendation

On Run press, validate and capture every relevant input into an immutable plain-Python data object before starting the worker.

Example:

```python
@dataclass(frozen=True)
class HallRunParameters:
    sample_id: str
    source_current_a: float
    compliance_v: float
    magnetic_field_t: float
    thickness_m: float
    settling_s: float
    repetitions: int
    temperature_mode: str
    instrument_id: str
```

The worker must use only this snapshot. It should never call `.get()` on Tk variables.

### UI policy

Disable controls that affect the active run until success, cancellation, or failure cleanup completes. Fields unrelated to the active run may remain editable if they cannot affect the worker or the current result.

### Acceptance criteria

- Changing UI fields during a run cannot change its behaviour or metadata.
- No Tk variable is accessed from a worker thread.
- The committed result retains the exact validated parameter snapshot.

---

## 15. Assign stable sample identifiers

### Finding

Sample association appears to rely heavily on the current text in a sample-name field.

### Risk

Human-readable names are editable and non-unique. They are insufficient as the sole provenance key.

### Recommendation

Use both:

- a stable internal sample ID;
- and a user-visible sample label.

A simple UUID or repository-specific identifier is sufficient. The label can remain editable, but completed results should retain the original sample ID and label captured at run start.

### Acceptance criteria

Two samples with the same display name remain distinguishable. Renaming a sample does not silently rewrite historical results unless an explicit migration operation is performed.

---

## 16. Prevent mixed-sample calculations

### Finding

Van der Pauw and Hall calculations validate selected positions or polarities, but may not require all selected data to belong to the same sample or coherent run set.

### Risk

A mathematically valid calculation can be scientifically invalid while still producing a plausible number.

### Recommendation

Calculation input validation must require:

- matching sample ID;
- completed source runs only;
- required and distinct positions or polarities;
- compatible measurement configuration;
- consistent units;
- consistent field direction and magnitude where required;
- compatible thickness assumptions;
- and no duplicate source-run use where distinct runs are expected.

### Acceptance criteria

The calculation layer rejects mixed samples before numerical calculation begins and explains the specific incompatibility.

---

## 17. Bind derived results to source-run provenance

### Finding

Derived values may be associated with whichever sample is currently shown in the UI rather than the sample and runs that produced the selected readings.

### Recommendation

Derived results should contain an immutable provenance chain.

Example:

```text
DerivedHallResult
  result_id
  sample_id
  sample_label_at_calculation
  source_run_ids
  source_row_ids
  calculation_method
  calculation_version
  magnetic_field_t
  thickness_m
  calculated_at
  software_version
```

### Why calculation version matters

If equations, correction factors, or numerical methods change later, historical derived results should remain interpretable. A calculation version permits reproducibility and controlled recalculation.

### Acceptance criteria

Every derived value can be traced to the exact completed measurements and calculation inputs used to produce it.

---

## 18. Clear or scope stale calculation inputs

### Finding

Hall calculation inputs can retain values from a previous sample or previous selection.

### Recommendation

When the active sample or selected source-run set changes:

- clear derived values;
- clear inputs that were inferred from the old sample;
- or explicitly display their provenance and require confirmation before reuse.

Prefer scoped calculation models over global form state.

### Acceptance criteria

No calculated value remains displayed as current after its source selection or sample context becomes invalid.

---

# Part VI — Phase 5: IV standby bias and sweep lifecycle

## 19. Review periodic-bias output continuity

### Finding

The periodic IV path applies a standby bias and then enters the sweep routine. The sweep can change the source function. Some drivers drop output when the source function changes. When the sweep is configured to hold output, the orchestration may assume output remains enabled and may not explicitly re-enable it.

The standby path may also not configure the full compliance, range, or NPLC state before enabling output.

### Risks

Depending on the instrument and selected source modes:

- the sweep may execute with output disabled;
- the instrument may energize with stale compliance settings;
- the intended continuous standby-to-sweep transition may not occur;
- or the output state may differ between hardware and software sweep paths.

### Recommendation

Define an explicit state-transition contract for standby and sweep modes.

Before every output-on transition, the active configuration should be complete:

1. source function;
2. measurement function;
3. compliance;
4. ranges or autorange policy;
5. integration time or NPLC;
6. terminals and sensing mode;
7. source level;
8. output enable.

Do not assume that output survives a source-function change.

### Suggested implementation approach

Create explicit orchestration methods such as:

```python
prepare_standby(parameters)
enter_standby(parameters)
prepare_sweep(parameters)
execute_sweep(parameters, token)
restore_standby(parameters)
```

Each method should define its output-state preconditions and postconditions.

### Required tests

Trace and assert exact command/state behaviour for:

- voltage standby to voltage sweep;
- voltage standby to current sweep;
- current standby to current sweep;
- current standby to voltage sweep;
- hardware sweep;
- software sweep;
- output held between cycles;
- output disabled between cycles;
- cancellation during standby;
- cancellation during source-function transition;
- and cancellation during sweep.

### Acceptance criteria

For every supported driver, the code can demonstrate whether output is on or off at each transition and can prove that compliance is configured before energization.

---

## 20. Prevent orphaned software-sweep workers

### Finding

A stopped or timed-out software sweep can remain alive in the background while the caller proceeds with output-off, reconfiguration, or a new sweep.

Shared sweep state can also be overwritten by a later sweep.

### Risk

An old worker may continue setting levels after the application believes the sweep has stopped. This can conflict with cleanup or a new measurement.

### Recommendation

Each software sweep should own:

- a private thread;
- a private cancellation token;
- private result storage;
- an explicit terminal event;
- and a non-reusable sweep ID.

Starting a new sweep should be rejected until the previous sweep thread has exited.

The caller should use a lifecycle such as:

```text
create sweep
start sweep
wait for completion or cancellation
request abort when needed
join worker
verify worker terminated
perform output cleanup
release ownership
```

Do not merely stop waiting for a worker.

### Acceptance criteria

- No software-sweep thread remains active after run cleanup.
- A second sweep cannot overwrite the first sweep’s state.
- Cancellation during a point delay or measurement exits promptly.
- Output cleanup occurs only after the sweep worker can no longer issue source commands, or the connection is explicitly placed in a degraded emergency state.

---

# Part VII — Phase 6: safe shutdown and degraded connections

## 21. Use defensive cleanup on every path

### Finding

Measurement code must remain safe under normal return, cancellation, timeout, driver error, UI closure, and unexpected exception.

### Recommendation

Use structured cleanup with nested safeguards:

```python
try:
    perform_measurement()
finally:
    try:
        instrument.output_off()
    finally:
        release_instrument_ownership()
```

Real implementation will need more nuance because output-off verification can fail, but the principle is that cleanup must not depend on a successful main path.

### Cleanup responsibilities

- prevent further worker commands;
- request or perform output-off;
- optionally query output state where supported;
- drain or inspect the instrument error queue;
- terminate or join worker threads;
- release ownership;
- update connection health;
- and move the UI to a safe terminal state.

### Acceptance criteria

Every exception-injection test confirms that output-off is attempted and ownership is released or intentionally blocked as degraded.

---

## 22. Confirm output state where possible

### Finding

Calling output-off does not prove that output is physically or logically off. Communication may fail, the command may be rejected, or the instrument may be in an unexpected state.

### Recommendation

Where supported, query output state after shutdown. Define driver capabilities such as:

```text
can_query_output_state
supports_abort
requires_output_drop_on_source_change
```

Where output-state query is unavailable, document the fallback policy and report that shutdown was commanded but not independently verified.

### UI behaviour

If shutdown cannot be confirmed:

- show a persistent warning;
- prevent another run;
- mark the connection degraded;
- instruct the operator to inspect or disable hardware output manually;
- require reset, reconnect, or explicit acknowledgement according to the project’s safety policy.

### Acceptance criteria

The application never quietly returns to a normal ready state after uncertain output shutdown.

---

## 23. Treat reset and initialization failures as connection-health failures

### Finding

Connection initialization can catch reset failures, log a warning, and still permit measurement.

### Risk

Reset or initialization may establish critical state such as:

- line frequency;
- output format;
- terminals;
- sensing mode;
- interlock handling;
- source and measurement defaults;
- or error-queue state.

A partially initialized instrument can produce invalid measurements or unsafe output behaviour.

### Recommendation

Use explicit connection states:

```text
DISCONNECTED
CONNECTING
READY
DEGRADED
FAULTED
```

A failed mandatory initialization step should prevent `READY`.

Optional initialization failures may produce `DEGRADED` only when:

- the missing feature is known;
- the affected experiments are disabled;
- and the operator receives a clear explanation.

Avoid a generic “warning but proceed” policy.

### Acceptance criteria

- Run is disabled unless the connection is ready for that experiment’s required capabilities.
- Initialization failures identify the failed step.
- Recovery is tested through reset or reconnect.

---

# Part VIII — Phase 7: validation and data behaviour

## 24. Reject non-integral values instead of truncating them

### Finding

Some integer fields use patterns equivalent to `int(float(value))`. A value such as `2.5` is silently converted to `2`.

### Risk

The user receives a different experiment than requested without a clear validation error.

### Recommendation

Parse numeric text, then explicitly verify integrality:

```python
value = float(text)
if not value.is_integer():
    raise ValidationError("Repetitions must be a whole number")
repetitions = int(value)
```

Use shared validators for:

- repetitions;
- point counts;
- averaging counts;
- selected channels;
- and any other integer-valued control.

### Acceptance criteria

Decimal values in integer fields are rejected with a field-specific message.

---

## 25. Make save semantics explicit

### Finding

Completed runs appear to remain in the in-memory store after saving. A later save may include previously saved runs again, producing duplicated data across files.

### Risk

Users may not know whether each file is:

- a complete snapshot;
- an incremental export;
- or an append to an ongoing dataset.

### Recommendation

Choose and document one primary model.

#### Option A: immutable snapshot

Each save contains the complete current dataset. File naming and UI should say “Save snapshot.” Duplicate presence across snapshot files is intentional.

#### Option B: save new completed runs only

The store tracks saved versus unsaved results. A save contains only results not previously exported.

#### Option C: append-only project dataset

The application writes completed results into one controlled data store with unique IDs and duplicate prevention.

For a laboratory WIP application, Option B is usually easiest for users to understand, while Option A is simplest technically. Whichever model is chosen, run IDs must prevent accidental duplicate rows within a single logical dataset.

### Acceptance criteria

- The UI wording matches the storage model.
- Tests verify repeated save behaviour.
- Result IDs remain stable.
- Cancelled or failed runs are never exported.

---

## 26. Separate operational logs from scientific data

### Finding

Discarding cancelled runs should not remove all evidence that a cancellation or fault occurred.

### Recommendation

Maintain an operational event log separate from measurement exports.

Suggested fields:

```text
timestamp
run_id
experiment
sample_id
instrument identity
parameter snapshot hash
terminal status
stage reached
cancellation or failure reason
exception category
shutdown command status
shutdown verification status
software version
```

### Important boundary

Do not include provisional measurement readings in the normal operational log. If engineering diagnostics require them, use an explicitly enabled debug mode, a clearly separate file, and conspicuous labeling so they cannot be mistaken for valid experiment data.

### Acceptance criteria

The project can investigate failed runs without polluting scientific datasets.

---

# Part IX — Phase 8: calculation integrity

## 27. Validate complete required measurement sets

### Finding

Domain calculations depend on complete combinations of positions, directions, polarities, or magnetic-field states.

### Recommendation

Represent required input sets explicitly rather than inferring them from UI row order.

Validation should detect:

- missing positions;
- duplicated positions;
- missing polarity;
- same polarity used twice;
- mixed current magnitudes where symmetry is required;
- incompatible field values;
- non-completed runs;
- mixed samples;
- and inconsistent units or geometry.

### Acceptance criteria

Calculation functions accept structured validated inputs rather than raw selected table rows.

---

## 28. Version equations and numerical procedures

### Finding

Laboratory calculations may evolve as correction factors, convergence methods, and conventions are refined.

### Recommendation

Assign calculation identifiers and versions, for example:

```text
vdp_resistivity:1
hall_coefficient:1
carrier_density:1
```

Store the version with every derived result. Add regression tests with known datasets and tolerances.

### Acceptance criteria

A historical derived result remains reproducible after calculation code changes.

---

# Part X — Phase 9: testing strategy

## 29. Current test observations

### Finding

The archive contains approximately 22,500 lines of Python and more test code than production code, which is a positive sign.

Twenty-five test scripts were identified during review. In a Linux virtual-display environment:

- 23 completed successfully;
- `test_layout.py` failed;
- `test_checkup.py` was not completed because its intentional stall and fault scenarios include very long waits;
- and the repository compiled successfully with `compileall`.

The layout failure affected Hall and 4PP size constraints in that environment. It may be platform- or font-dependent, but it shows that the current layout guard is either not portable or is operating too close to its threshold.

### Limitation

These observations are not a substitute for testing on the target Windows environment or against real instruments.

---

## 30. Consolidate tests under one runner

### Finding

The test suite appears to contain executable scripts and top-level test modules rather than one consistently structured test runner.

### Recommendation

Adopt a standard runner such as `pytest` and categorize tests.

Suggested markers or suites:

```text
unit
calculation
command_trace
gui
simulation
slow
fault_injection
hardware
```

Create one documented command for the fast default suite and separate commands for slow and hardware tests.

### Acceptance criteria

- One command runs all fast software tests.
- Test discovery has no side effects.
- Long intentional timeouts are marked and excluded by default.
- CI results clearly identify the test category.

---

## 31. Add cancellation tests at every meaningful boundary

### Recommendation

Inject cancellation at least at these points:

- during preparation before output-on;
- immediately after output-on;
- during settling;
- after the first reading;
- between polarity reversals;
- between Van der Pauw positions;
- between Hall field states;
- during a software sweep point delay;
- while waiting for hardware sweep completion;
- during temperature acquisition;
- immediately before final validation;
- immediately before commit;
- during output-off;
- while output-state verification fails;
- and while an instrument query is stalled.

Every cancellation test should assert:

```text
no committed run
no derived result
no exportable data
output-off attempted
worker cannot issue later commands
instrument ownership released or degraded safely
UI reaches the expected terminal state
a new run can start after valid cleanup
```

### Highest-value test

Cancellation immediately before commit is essential. It proves that the commit gate checks cancellation at the final possible boundary.

---

## 32. Add run-concurrency tests

### Recommendation

Test at least:

- pressing Run twice rapidly;
- starting two experiment types against the same resource;
- starting a manual command during a run;
- reconnecting during a run;
- closing a window during a run;
- cancellation followed immediately by Run;
- and an obsolete worker attempting to command the instrument after a new run is allocated.

### Acceptance criteria

Only one run owns a physical resource at a time, and rejected actions do not disturb the active run.

---

## 33. Add driver state-transition traces

### Recommendation

Use fake transports to record command order and simulated state. Tests should validate preconditions and postconditions, not only the presence of individual commands.

Critical traces:

- reset and initialization;
- output-on from a known off state;
- compliance configured before output-on;
- source-function change while output is active;
- hardware sweep setup and completion;
- software sweep cancellation;
- output-off and verification;
- error-queue inspection;
- and reconnect after failure.

### Acceptance criteria

A change in command order that creates an unsafe or invalid transient causes a test failure.

---

## 34. Add Windows CI and platform-aware GUI checks

### Finding

Windows is the primary deployment environment, while the reviewed software tests were run under Linux with a virtual display.

### Recommendation

At minimum, CI should include:

- supported Python version on Windows;
- fast unit and simulation tests;
- GUI import and construction tests;
- resource-loading tests from an installed package;
- and packaging or executable-build smoke tests if distribution is planned.

Layout tests should use robust constraints and tolerate known platform font differences without ignoring genuine clipping.

### Acceptance criteria

A clean Windows environment can install the package, launch all experiment windows, load resources, and run the software-only suite.

---

## 35. Establish a hardware-in-the-loop test protocol

### Recommendation

Real-instrument tests should be separate from CI and should use a controlled checklist.

For each supported instrument, test:

- identity and capability detection;
- reset and initialization;
- output-off from application start;
- source configuration;
- compliance behaviour using a safe load;
- software and hardware sweep paths as applicable;
- cancellation at low-risk operating levels;
- communication interruption;
- output-off verification;
- and recovery after reconnect.

Record:

- instrument model;
- firmware version;
- connection type;
- test load;
- application version;
- and command trace.

### Safety note

Hardware cancellation and fault tests should begin with conservative source and compliance settings and a known benign load.

---

# Part XI — Phase 10: architecture cleanup

## 36. Remove the package-level core/drivers cycle

### Finding

`core/driver_registry.py` imports every driver, while drivers import `core.limits`. This creates a package-level `core <-> drivers` dependency cycle.

### Risk

The cycle currently works but can lead to:

- fragile import order;
- difficult isolated testing;
- accidental side effects at import time;
- and an increasingly central registry module as more drivers are added.

### Recommendation

Move driver registration to the application composition root or the drivers package, for example:

```text
app/driver_registry.py
```

or:

```text
drivers/registry.py
```

The core package should contain domain-level contracts and limits without importing concrete driver implementations.

### Acceptance criteria

- Core can be imported and tested without importing all drivers.
- Concrete drivers depend on core contracts.
- Application startup composes the registry.

---

## 37. Strengthen the abstract driver contract

### Finding

Some operations that are effectively mandatory may not be declared abstract. A future driver could instantiate successfully while inheriting an unimplemented or documentation-only method.

### Recommendation

Classify driver methods into:

- mandatory abstract operations;
- optional capability-gated operations;
- and shared concrete helpers.

Mandatory operations should raise at class construction or registration time if absent.

Optional operations should be called only after checking a declared capability and should raise a clear `UnsupportedOperation` error if misused.

### Acceptance criteria

A deliberately incomplete fake driver fails registration tests before any experiment can use it.

---

## 38. Remove stale or duplicated modules

### Finding

`experiments/vanderpauw/panels/temp_panel.py` appears to duplicate a shared temperature panel and may be stale.

### Recommendation

Confirm usage with import analysis, then either:

- remove the duplicate;
- redirect imports to the shared implementation;
- or document why experiment-specific behaviour is still required.

Avoid retaining apparently unused modules because they create uncertainty for future developers.

### Acceptance criteria

There is one authoritative implementation for each shared panel unless a documented experiment-specific variant is necessary.

---

# Part XII — Phase 11: packaging and reproducibility

## 39. Correct dependency declarations

### Finding

The miniSMU dependency appears under normalized-equivalent hyphen and underscore names as both mandatory and optional. Python packaging normalizes these names, so the dependency is effectively mandatory.

### Recommendation

Choose one canonical package name and decide whether miniSMU support is:

- required for all installations;
- an optional extra;
- or a plugin installed only on relevant systems.

Example optional-extra approach:

```toml
[project.optional-dependencies]
minismu = ["minismu-py>=..."]
```

Core application imports must then tolerate the extra being absent and disable the related driver cleanly.

### Acceptance criteria

A clean install without miniSMU support succeeds and clearly reports that the driver is unavailable, if the feature is intended to be optional.

---

## 40. Improve reproducibility of dependency versions

### Finding

Open-ended `>=` constraints and the absence of a lockfile weaken reproducibility.

### Risk

A future dependency update can change GUI behaviour, VISA handling, numerical results, or packaging without a repository change.

### Recommendation

Use a controlled dependency strategy:

- minimum and maximum compatible ranges in project metadata;
- a lockfile or pinned deployment requirements for validated builds;
- and a documented process for dependency upgrades.

For released laboratory builds, record exact dependency versions in the exported operational metadata or application version report.

### Acceptance criteria

A known release can be rebuilt with the same dependency versions.

---

## 41. Remove generated files and add ignore rules

### Finding

The archive contains `__pycache__` directories and `.pyc` files, and no visible `.gitignore` was identified.

### Recommendation

Add ignore rules for at least:

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.coverage
htmlcov/
.venv/
venv/
build/
dist/
*.egg-info/
*.log
```

Add project-specific generated measurement, debug, and packaging outputs as appropriate.

### Acceptance criteria

A clean checkout has no generated Python bytecode or local environment files.

---

## 42. Package resources independently of the source-tree working directory

### Finding

Image or resource loading may depend on running directly from the source tree.

### Risk

Installed packages and frozen executables may not find resources using relative filesystem paths.

### Recommendation

Use package-resource APIs such as `importlib.resources` and declare resources in packaging metadata.

Test resource loading from:

- a source checkout;
- an installed wheel;
- and any planned frozen executable.

### Acceptance criteria

The application can launch from an arbitrary working directory after installation.

---

# Part XIII — Recommended implementation sequence

## 43. Milestone 1: lifecycle foundation

### Goal

Create shared infrastructure without changing scientific behaviour.

### Work items

- Define run states and legal transitions.
- Create per-run IDs and cancellation tokens.
- Create a run context with provisional result storage.
- Add a single atomic commit gate.
- Define terminal-status and operational-log structures.
- Add unit tests for the state machine.

### Exit criteria

The infrastructure can model success, cancellation, and failure independently of any specific experiment.

---

## 44. Milestone 2: pilot integration in one simple experiment

### Goal

Prove the lifecycle design before applying it everywhere.

### Suggested target

Use 4PP or the simplest basic IV mode. Avoid periodic-bias IV as the first integration because it has more complex output continuity and sweep behaviour.

### Work items

- Capture immutable parameters.
- Claim exclusive instrument ownership.
- Stage all readings provisionally.
- Implement OFF as cancellation.
- Commit only after complete validation and shutdown.
- Add boundary cancellation tests.

### Exit criteria

The pilot experiment cannot retain partial data or accept a second run, and it safely recovers after cancellation and injected failure.

---

## 45. Milestone 3: Van der Pauw and Hall integration

### Goal

Remove the highest known concurrency and OFF-action risks.

### Work items

- Replace local run flags with the shared controller.
- Remove Tk reads from worker threads.
- Disable duplicate Run actions.
- Make OFF cancel the run rather than only disable output.
- Stage complete polarity and position sets.
- Discard all partial sets.
- Bind calculations to completed run IDs and sample IDs.

### Exit criteria

No overlapping worker can command the same SMU, and no partial VdP or Hall data can be calculated or exported.

---

## 46. Milestone 4: IV periodic bias and sweep refactor

### Goal

Resolve output continuity and orphaned sweep-worker risks.

### Work items

- Define standby and sweep transition contracts.
- Configure compliance before every output-on.
- Handle source-function changes explicitly.
- Give each software sweep private state and cancellation.
- Join or terminate workers before cleanup completes.
- Add driver-by-driver command traces.

### Exit criteria

Output state and compliance are deterministic across all standby/sweep combinations, and no sweep worker survives cancellation.

---

## 47. Milestone 5: connection health and shutdown verification

### Goal

Prevent runs from starting with incompletely initialized or uncertain hardware.

### Work items

- Add connection states.
- Classify mandatory versus optional initialization steps.
- Block runs in degraded states lacking required capabilities.
- Query output state where supported.
- Add uncertain-shutdown UI and recovery flow.

### Exit criteria

The application cannot quietly continue after a reset failure or unconfirmed output shutdown.

---

## 48. Milestone 6: persistence and calculation provenance

### Goal

Make every scientific and derived result auditable.

### Work items

- Add stable sample, run, row, and derived-result IDs.
- Store parameter snapshots with completed results.
- Store source-run references in calculations.
- Add calculation versions.
- Choose and document save semantics.
- Separate operational logs from measurement exports.

### Exit criteria

Every exported or calculated value can be traced to a complete run, sample, parameter set, and calculation version.

---

## 49. Milestone 7: test and packaging consolidation

### Goal

Make validated builds repeatable.

### Work items

- Move tests to one runner.
- Categorize fast, slow, GUI, simulation, fault, and hardware tests.
- Add Windows CI.
- Correct dependencies and optional extras.
- Add lock or validated deployment requirements.
- Package resources correctly.
- Remove generated files and stale modules.
- Refactor the driver registry cycle.

### Exit criteria

A clean Windows environment can install, launch, and run the software-only suite using documented commands.

---

# Part XIV — Cross-cutting engineering rules

## 50. Safety first, data integrity second, convenience third

When requirements conflict, use this priority:

1. Instrument and operator safety.
2. Scientific data integrity and provenance.
3. Reproducibility and diagnosability.
4. UI responsiveness and convenience.

A discarded uncertain run is inconvenient. An incomplete run presented as valid data is much worse.

---

## 51. No hidden recovery that changes the experiment

The software should not silently:

- truncate decimal repetition counts;
- substitute a different source mode;
- reuse stale calculation inputs;
- continue after mandatory reset failure;
- relabel a run using a changed sample field;
- or retain a partial set because it is “almost complete.”

Any recovery that changes scientific meaning must be explicit and visible.

---

## 52. Make critical assumptions executable

Important assumptions should be represented by code and tests, not only comments.

Examples:

- “Only one run can own an instrument.”
- “Cancelled runs are never committed.”
- “Compliance is configured before output-on.”
- “A derived result cannot mix samples.”
- “A worker cannot command hardware after cancellation.”

Each statement should have at least one test that fails when the assumption is violated.

---

## 53. Prefer structured domain objects over UI-row dictionaries

UI tables are presentation mechanisms, not authoritative domain models.

Use structured objects for:

- run parameters;
- completed measurements;
- calculation inputs;
- calculation outputs;
- connection health;
- and operational events.

Convert these objects to UI rows and CSV records at the application boundary.

---

## 54. Preserve units explicitly

Although not identified as a specific defect in the review, unit ambiguity is a common source of laboratory errors and should be addressed while parameter and result objects are being formalized.

Recommended rules:

- store values internally in documented SI units;
- include units in field names or typed quantity objects;
- convert only at UI and export boundaries;
- record the export unit explicitly;
- and avoid passing unlabelled floats between layers.

Tests should cover common prefix conversions such as mA/A, mV/V, µm/m, and gauss/tesla where applicable.

---

## 55. Version run and file schemas

As run metadata and provenance improve, existing files may need migration.

Include a schema version in:

- run records;
- derived-result records;
- and exported file headers.

Document migrations rather than guessing file structure from available columns.

---

# Part XV — Definition of done for the upcoming workflow

## 56. Minimum release gate for a trustworthy WIP build

A development build should not be considered ready for routine laboratory use until all of the following are true:

### Run control

- One active run per physical instrument.
- Duplicate Run actions are rejected.
- OFF cancels all experiment types consistently.
- Worker threads cannot issue commands after cancellation.
- New runs wait for complete cleanup.

### Data integrity

- In-progress data is provisional.
- Cancelled and failed runs are discarded.
- Only completed runs can be calculated or exported.
- Parameter snapshots are immutable.
- Sample and run provenance is stable.

### Instrument safety

- Compliance and configuration precede output-on.
- Output-off is attempted on every terminal path.
- Shutdown is verified where supported.
- Uncertain shutdown blocks normal operation.
- Mandatory reset failure prevents measurement.

### Calculations

- Mixed samples are rejected.
- Required polarity or position sets are validated.
- Derived results reference source runs.
- Calculation versions are stored.

### Testing

- Cancellation boundary tests pass.
- Concurrency tests pass.
- Driver command traces pass.
- The software-only suite passes on Windows.
- Hardware validation is documented for each supported model.

### Packaging

- Dependencies are reproducible.
- Optional drivers are genuinely optional.
- Resources load from an installed package.
- Generated files are excluded.

---

# Part XVI — Suggested issue breakdown

## 57. Issue group A: critical safety and correctness

Create these issues first:

1. Implement shared run state machine.
2. Add per-run cancellation token and run ID.
3. Add application-wide instrument ownership.
4. Change OFF to cancel and discard across all experiments.
5. Add provisional result buffer and atomic commit.
6. Prevent obsolete workers from issuing commands.
7. Fix IV standby/sweep output transition.
8. Abort and join software-sweep workers.
9. Block runs after mandatory reset failure.
10. Add uncertain-shutdown handling.

These should be treated as blockers for adding new experiment features.

---

## 58. Issue group B: provenance and scientific integrity

1. Add immutable run parameter snapshots.
2. Remove Tk reads from worker threads.
3. Add stable sample IDs.
4. Add stable run and result IDs.
5. Bind calculations to source runs.
6. Reject mixed-sample calculations.
7. Clear stale Hall and VdP calculation state.
8. Version calculation methods.
9. Decide repeated-save semantics.
10. Separate operational and scientific data.

---

## 59. Issue group C: test infrastructure

1. Consolidate tests under one runner.
2. Add cancellation boundary tests.
3. Add cross-window ownership tests.
4. Add output-state command traces.
5. Add reset-failure and shutdown-failure tests.
6. Split slow and intentional-stall tests.
7. Add Windows CI.
8. Add installed-package resource tests.
9. Define a hardware-in-the-loop checklist.
10. Make layout tests platform-aware.

---

## 60. Issue group D: maintenance and packaging

1. Correct miniSMU dependency declaration.
2. Add validated dependency locking.
3. Add `.gitignore` and remove generated files.
4. Package resources with `importlib.resources`.
5. Move the driver registry out of core.
6. Strengthen abstract driver requirements.
7. Remove or document duplicated temperature panel code.
8. Add schema versions and migration notes.

---

# Conclusion

The project has a credible architecture and a notably strong driver and documentation foundation. The next development phase should not primarily focus on adding instruments or experiment features. It should make the execution lifecycle deterministic and auditable.

The most important design decision has already been made: cancelled runs are discarded in every experiment. Implementing that decision correctly requires more than clearing UI rows. It requires provisional data, an atomic commit boundary, per-run cancellation state, full instrument-session ownership, worker termination guarantees, and strict result provenance.

Once those mechanisms are shared across all experiments, later additions will become safer and faster. Without them, every new experiment will reproduce slightly different run-state, cancellation, and data-integrity behaviour, increasing both maintenance cost and scientific risk.
