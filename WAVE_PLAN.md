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
| **3** | Pilot integration: 4PP only | A4, A6, A8 in situ | next |
| **4** | Calculation integrity | B5–B8, §16–18, §27–28 | |
| **5** | Rollout: Van der Pauw + Hall | Milestone 3 | |
| **6** | IV standby/sweep contract + driver command traces | A7, A8, §19, §20, §33, C4 | |
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

---

## Wave 4 — Calculation integrity

- Structured calculation inputs rather than reading widget strings.
- Reject mixed-sample inputs (§16).
- Validate the required set is present before calculating (§17).
- Calculation version tags, so a stored result records which formula
  produced it.
- Provenance: a derived result names the rows it came from.
- Clear stale outputs when inputs change (§28).

**Proof:** the existing notebook-parity tests must stay bit-identical —
that is the guard rail. `test_hall_math` and `test_iv_math` are the ones
to watch; they are also the tests that could never fail before Wave 0a,
so treat their green as meaningful only now.

---

## Wave 5 — Rollout: Van der Pauw + Hall

Apply the Wave 3 pattern to the other two ported experiments. The
cancellation matrix from Wave 3 becomes a shared parameterised table
rather than three copies.

Open questions from earlier work that belong here: whether to label
negative carrier density/mobility as n-type/p-type in the UI, and
whether a VdP run should auto-carry `Rs` into Hall.

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
