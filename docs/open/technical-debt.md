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