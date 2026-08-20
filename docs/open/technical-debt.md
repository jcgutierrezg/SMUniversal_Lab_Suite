---
type: state
title: "Known technical debt"
---

# Known technical debt

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
- **GUI test files patch `messagebox` on shared modules at import
  time**, so in one pytest process the last file imported wins and the
  others assert against a recorder nothing writes to. `run_tests.py`
  hides this by giving each GUI file its own process. The fix is a
  fixture that patches and restores per test, the way
  `_no_instrument_discovery` already does in `conftest.py` — a
  shared-layer change across every GUI file, so it wants a wave of its
  own and must not ride along with an unverified instrument. It buys no
  speed; it is a correctness change. Deferred deliberately: the hazard
  only fires under plain `pytest`, which is not how this suite is run.
  Measured in [the test suite audit](../reference/test-suite-audit.md).
- **A guard for the above now exists; the fix still does not.**
  `_dialog_recorder_belongs_to_this_file` in `tests/conftest.py` fails
  any GUI test whose dialog seam is owned by another test file, so a
  hand-run `pytest tests/` reports the contamination instead of a
  meaningless green. It does not make those files independent — that is
  still per-test patch-and-restore in each of them.

  The guard as originally proposed was **wrong**, and worth recording:
  "fail if more than one GUI module is imported into this process" would
  have failed `run_tests.py`'s own non-GUI pass, because
  `pytest -m "not gui"` imports every module it collects before
  deselecting any of them. The correct command imports all of them every
  time. What the guard checks instead is ownership by identity at the
  moment a GUI test runs. Two files that install their recorder inside a
  fixture rather than at import are not covered, and do not need to be.
- **The Keithley 2450 has no dedicated driver test file**, alone among
  the text-dialect drivers, and is covered only by the registry-driven
  contract files. A mutation confirmed the practical effect: changing one
  of its output spellings turned exactly one generic test red. Not
  urgent, and not obviously wrong given the contract files — but it
  should be a decision rather than an accident, and it belongs to
  whichever wave next touches that driver.
- **`test_4pp.py` still drives `_do_run()` on the main thread.** Its
  green says nothing about threading; that is `test_4pp_lifecycle.py`'s
  job. Left as-is deliberately: churning a 434-line passing test file is
  where a real regression hides.
- **A stale `.pyc` can mask or persist a mutation.** Found during Wave
  7b while mutation-testing the version check: the source read `0.1.0`
  and the imported module reported `0.2.0`. The two strings are the same
  byte length and the edit landed inside one mtime tick, so CPython's
  bytecode cache validator - which compares source mtime and size -
  saw no change and served the old `.pyc`.

  It fooled three mutation rounds before it was caught, and it fails in
  both directions: a mutation can persist after it is reverted, or be
  masked so a test that would have caught it appears not to. "Mutate
  your own code to prove each test can fail" is the discipline most of
  this project's real defects were found by, so a hazard that quietly
  invalidates it matters more than its size suggests.

  **Fixed in Wave 7c-i**: `run_tests.py` now passes
  `PYTHONDONTWRITEBYTECODE=1` to every pytest subprocess, and
  `tests/test_bytecode_staleness.py` demonstrates the mechanism. Note
  that this protects the *suite*; a bare `python -c` or a hand-run
  script still caches, so clear `__pycache__` when mutating outside
  the runner.

- **The generated indices record `file:line`.** `deviation-index.md` and
  `review-index.md` cite source line numbers, so *any* edit that shifts
  a line makes them stale and fails `test_generated_pages_match_a_fresh_build`.
  `uv run python tools/build_docs.py` therefore belongs in every patch
  that touches code, not only in documentation patches.

  Related, and mildly misleading when it happens: that test writes the
  fresh build before asserting, so a failure leaves the working tree
  dirty and an isolated re-run passes against the files the failed run
  just regenerated. It looks like order-dependence and is not. Restoring
  on failure would make the second run tell the truth.

- **The operational log transcribes `metadata` verbatim**, by design -
  an operator note belongs in the log. Nothing in `core/event_log.py`
  can stop a caller putting a measurement value in it, so §26's
  boundary holds there by convention rather than by construction.
  `experiments/base_experiment.py` passes `context.metadata`, which
  today holds parameters and notes and never readings. Worth a
  narrowing rule - an allowed key list, or a numeric-value refusal - if
  a future experiment starts putting richer things in metadata.

- **`RangePlan`'s `AUTO` meant two different things.** Closed
  2026-08-20 by a distinct `NOT_SOURCED` value; see
  [A ranging command that silently resets the compliance](../faults/23-autorange-resets-compliance.md) for the fleet table and the
  design. Recorded here rather than deleted because the *reason* it took
  a whole commissioning round is worth keeping: the harm differed per
  instrument in ways nothing about the dialect predicted, and a fix
  designed from the instruments looked at first would have broken the
  2611A and 2635B, where that axis is the compliance's own range.

- **`apply_ranges` still reports what it sent, not what was accepted.**
  Partly addressed 2026-08-20: `verify_compliance()` and the checkup's
  *compliance survives ranging* check cover the **limit**, which is the
  half that can hurt a sample. The **range** half is still open — the
  GSM-20H10 will refuse a measurement range and silently leave a
  narrower one in force (`SENS:CURR:DC:RANG?` reading `1.050000E-05`
  after `1E-4` was asked for), and nothing notices.

  Left open deliberately rather than bundled in. Reading a range back
  needs its own per-driver spelling and its own bench verification, and
  the compliance readback already showed why that matters: on the
  GSM-20H10 `OUTP?` answers dishonestly, so a readback is only worth
  having where somebody has checked it against a value the instrument
  was known to hold.

- **Most compliance readbacks are unimplemented, and the U2722A's is
  unverified.** `compliance_readback` in the contract
  ledger records which. Until a driver both implements it *and* has it
  checked at the bench, the checkup's new check reports `skip` or
  `unverified` rather than `pass` — so a clean checkup on those
  instruments still means *none observed*, not *none*. Closing this is
  one bench session per instrument: set a distinctive compliance, read
  it back, confirm it agrees.

- **`tools/timing_scan.py` did not check that its readings were
  readings.** Closed 2026-08-20. It called `driver.measure()`,
  discarded the result and timed it, so a `(None, None)` was timed
  exactly like a real measurement - which is how it reported 10.3 ms
  flat across a thousandfold NPLC change on the GSM-20H10, fitted a
  confident straight line through it, and concluded the driver's
  declared aperture was "6493x too long", from a run where every read
  had failed. It now counts blanks, refuses to fit if any turned up,
  and reports the **noise** at each integration time alongside the
  timing - which is the only thing that distinguishes an instrument
  that integrates from one that ignores the request, since a
  free-running conversion returns in the same time either way.

- **Checkup reports did not record the commit or the firmware.** Closed
  2026-08-20 by `core/provenance.py`; both the JSON and the Markdown
  header carry them now. The commit gap cost five rounds of hypotheses
  when a clean 2026-08-06 GSM-20H10 report had to be compared against a
  six-failure 2026-08-18 one. The firmware gap has not cost anything
  yet, and is about to: every finding in that instrument's note is a
  claim about `V1.16`, GW Instek publish `V1.30`, and nothing in the
  staleness machinery watches the instrument rather than the code.
