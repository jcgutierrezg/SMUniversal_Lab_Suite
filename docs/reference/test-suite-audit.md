---
type: reference
title: "Test suite audit, August 2026"
---

# Test suite audit, August 2026

A record of what was measured, so the next person does not spend a day
rediscovering it — and, more to the point, so they do not act on the two
reasonable-sounding instincts this audit found to be wrong.

Measured at commit `3c456c9`, on Linux, Python 3.14.4, single core,
under `xvfb-run`. Nothing in the tree was changed as a result. Windows
numbers were not taken and will differ; see
[what was not measured](#what-was-not-measured).

## The two instincts this note exists to head off

**"There are more test files than source files, so some must be
redundant."** They are not. See [what the mutations
showed](#what-the-mutations-showed).

**"We are on a newer Python now, so plain `pytest` is probably fine."**
It is not, and the reason is no longer only the Windows Tcl fault that
`run_tests.py` was written for. See [the second reason `run_tests.py` is
load-bearing](#the-second-reason-run_testspy-is-load-bearing).

## Where the runtime actually is

`uv run python run_tests.py --all` took 290 s. The distribution is not
even close to uniform:

| | measured |
|---|---|
| `test_checkup.py` | 87.6 s — 30% of the whole suite |
| `test_rs_handoff.py` | 26.0 s |
| `test_house_rule_12.py` | 20.5 s |
| `test_summary_lifecycle.py` | 17.0 s |
| `test_vdp_calculation.py` | 16.6 s |
| `test_checkup_all_drivers.py` | 13.3 s |
| every remaining non-GUI file, combined | ~10 s |

Most files run in under 0.2 s. **File count is not what costs anything**,
which is why consolidating files would buy nothing and would cost the
property that makes a red run readable: right now a failure names its own
subject.

In all six expensive files the cost is waiting, not computing:

- `test_checkup.py` and `test_checkup_all_drivers.py` are `slow`-marked
  and excluded from the default run, so the day-to-day loop never pays
  for them. Their fakes stall in real time because the checkup measures a
  real slope from real elapsed time.
- The expensive GUI files are **not** paying for Tk. Measured directly:
  `tk.Tk()` is 0.046 s and a full `make_window()` is 0.08–0.18 s. What
  they pay for is the fixed `run.sleep(0.04, ...)` pacing per reading in
  `experiments/vanderpauw/experiment.py`. Four Van der Pauw runs at five
  points is about 2.1 s, and `test_rs_handoff` does that sixteen times.

That pacing is the single highest-leverage lever on default-run time and
it was deliberately left alone. Saving ~80 s is not worth touching a
queue-drain guarantee inside the experiment that de-energises samples.

## What the mutations showed

Four rounds, each one a single deliberate change with the whole suite run
against it, counting which files went red.

| Mutation | Files red | Reading |
|---|---|---|
| 2450 `:OUTP ON` → `:OUTP 1` | `test_transition_traces` | zero duplication |
| Sign flip in `hall_voltage()` | `test_hall_math`, `test_calculation_golden`, `test_hall_calculation`, `test_hall_demo` | four questions, one formula |
| Cancellation branch removed from `RunContext.checkpoint()` | `test_run_control`, `test_iv_lifecycle`, `test_4pp_lifecycle`, `test_hall_lifecycle` | the mutation was partial — see below |
| `cancel_event.set()` → `pass` | the four above plus `test_vdp_lifecycle` | correct partitioning |

The Hall round is the one that looks like redundancy and is not. Those
four files ask four different questions about one line of arithmetic:
is this the right formula; is it still the formula that produced the
numbers on disk; does the GUI path reach it with the right eight
readings; does the whole chain still land within tolerance. A version
bump passes one and fails another. Combined cost of all four: about 6 s.

The third round is worth keeping as a cautionary example, because the
audit made this project's own most-repeated mistake. Removing the
cancellation branch from `checkpoint()` left `test_vdp_lifecycle` fully
green, which looked like a coverage hole. It was not: `RunToken.sleep()`
raises `RunCancelled` independently, and Van der Pauw cancels through the
pacing sleep rather than through a bare checkpoint. **The mutation was
not discriminating**, which is the fault described in
[05-slept-not-polled](../faults/05-slept-not-polled.md)'s neighbourhood and
warned about throughout `tests/README.md`. The fourth round, cutting
cancellation off at its source, is the discriminating version.

That fourth round is the reassuring one. If Stop silently stopped
de-energising the sample, twenty-one tests across five files go red, and
they say where:

```
- [before output on]                     outcome is CANCELLED, not an error
- [during the first reading]             outcome is CANCELLED, not an error
- [at the polarity flip]                 outcome is CANCELLED, not an error
- [after the last point, before commit]  outcome is CANCELLED, not an error
```

Four named boundaries per experiment, each an instant where a stale
worker could re-energise a sample somebody has their hands in. Three
files stayed green and were right to: `test_house_rule_12` and
`test_reconnect` never press Stop, and `test_summary_lifecycle`'s
"cancel" is the save-collision dialog button, not the run.

## The second reason `run_tests.py` is load-bearing

`tests/README.md` gives the Windows Tcl runtime as the reason. There is a
second one, it is platform-independent, and it is present now.

A single-process run on Linux, Python 3.14, produces sixteen errors that
the isolated runner does not — and saves no time doing it:

```
uv run pytest -m ""                868 passed, 29 skipped, 16 errors in 275 s
uv run python run_tests.py --all   868 passed, 29 skipped, all groups passed, 284 s
```

Every one of the sixteen is a refusal test, and every one has the same
shape — the dialog recorder is empty. The refusal happened; nobody was
watching:

```
ERROR at teardown of test_a_missing_combination_is_refused
1 check(s) failed:
  - it is refused   []
```

The cause is that many GUI test files do this at import time, over the
same shared attribute:

```python
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs
```

pytest imports every module during collection, so the **last file
imported wins**, and every earlier file's tests then assert against a
recorder nothing writes to. Proved by import order rather than inferred —
same two files, opposite order, opposite result:

```
pytest test_vdp_calculation.py test_rs_handoff.py   →  24 passed, 3 errors
pytest test_rs_handoff.py test_vdp_calculation.py   →  24 passed
```

**This mechanism is loud in one direction and silent in the other**, which
is why it belongs in this vault rather than in a commit message.
`test_rs_handoff.py` contains assertions of the *absence* of a dialog —
"no dialog on a clean transfer", "no warning", "no error". A stolen
recorder is empty, so those pass, and they pass whether or not the code
is correct. Under plain `pytest`, some of the "nothing was shown to the
operator" guards stop discriminating, go green, and say nothing about it.

Process isolation currently prevents this, whether or not the Windows
Tcl fault ever returns. The sixteen errors are the canary. **If they are
ever "fixed" by relaxing the assertions rather than by isolating the
processes, the canary dies and the absence-assertions go quiet for
real.**

## What was not measured

Said plainly, because an audit that reads as complete when it is not is
worse than no audit.

- **Nothing was run on Windows.** All figures above are Linux. Tk
  construction in particular is much slower on Windows, so the GUI split
  of the runtime may look quite different there.
- **`tests/README.md` carries two runtime figures this audit did not
  reproduce** — `test_checkup` at ~58 s (measured 87.6 s) and
  `test_4pp_lifecycle` as the slowest GUI file at ~95 s (measured ~10 s).
  They were left alone rather than corrected: they may well be Windows
  numbers, in which case they are right and the Linux numbers are the
  outliers. Someone with a Windows bench machine can settle it in one run.
- **How many absence-assertions are protected only by process isolation
  was not counted.** `test_rs_handoff` has at least three. Whether this
  is a curiosity or a real exposure needs a grep across the GUI files.

## What was left undone, and why

Recorded in [technical debt](../open/technical-debt.md) rather than acted on. The
short version: the audit set out to find redundancy to remove, found
none worth defending the removal of, and the honest recommendation was to
change nothing.
