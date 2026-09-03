---
type: fault
fault: 37
title: "A test that measured the machine instead of the code"
---

# A test that measured the machine instead of the code

## Symptom

A test that passes alone and fails when other work is running, or the
other way round: passes on a slow machine and fails on a fast one.
Re-running it clears the failure. Nothing in the diff explains it.

Two live examples, and they failed in opposite directions:

* `test_a_runaway_run_is_still_stopped_by_the_clock` asserted that a
  0.5 s run finished within 0.8 s of wall clock. Two agents saw 0.85 s
  and 0.87 s while other suites ran on the same machine. The run was
  correct; its sleeps overshot under CPU contention.
* `pump_until` in `test_link_lost_during_a_run.py` drove the Tk event
  loop 2000 times and then declared a hang. It failed
  **deterministically** on a quiet machine, and would have passed on a
  loaded one.

## Cause

Both assertions were about the host, not about the software.

The first bounded a duration. Any wall-clock upper bound includes every
other process on the machine, so it asserts "this code is correct *and*
nothing else was busy". Only the first half is the test's business.

The second is subtler and worth stating plainly: **a count of
`root.update()` calls is not a bound on anything.** `update()` returns
as soon as nothing is pending, so 2000 of them against an idle main
thread are over in a couple of milliseconds - while the thing being
waited for is a measurement on another thread, which cannot have
finished. The busier the machine, the *longer* those 2000 iterations
take, so a fast quiet machine gave up soonest. It also starved what it
was waiting for: a tight `update()` loop never yields, so the worker
thread and the app's 10 ms `after()` pump both get less time than if the
test had done nothing at all.

The comment above it said the count was "a bound on a hang, not a
schedule". It was neither.

## Why it is dangerous

Not because a run is lost - because of what an intermittent red does to
everyone who sees it.

This project's workflow says *a red Windows job is information, not
noise*, and every guard in the suite depends on that being believed. A
test that goes red for reasons unrelated to the code is the mechanism by
which it stops being believed: the first few are diagnosed, then people
learn that re-running clears it, and then a real failure is re-run too.
The cost is not the flaky test. It is every other test's credibility.

## Check

Ask what the assertion would be measuring on a machine with nothing else
running, and on one with sixteen things running. If the answers differ,
the test measures the machine.

The fix is not a looser bound - that keeps the same defect and makes it
rarer, which is worse, because a rare intermittent is the one nobody
diagnoses. The fix is to assert on a quantity the scheduler cannot
move:

* **Count the work, not the seconds.** The runaway test now bounds
  `smu.measure_calls * cost_s` - the energised time the run actually
  asked the instrument for, in the fake's own units. It is the same
  0.8 s number, derived the same way, and it still fails the mutation it
  was written against. Note which way contention pushes each form: it
  makes the wall clock longer and fails a correct run, and it makes the
  reading count *smaller*, so the instrument-side form is conservative
  under exactly the conditions that broke the other one.
* **Where a bound really is about elapsed time, make it a liveness
  bound and say so.** `pump_until` now waits on the same fact against a
  wall-clock deadline that is generous by an order of magnitude, in the
  shape `run_tests.py`'s group budget and `CLEANUP_TIMEOUT_S` already
  use. Reaching it is a finding. It also sleeps 2 ms per turn, which is
  not the sleep `tests/README.md` bans: that one hopes the worker has
  arrived, this one yields so the worker can run at all.

## Where it is guarded

Nowhere mechanically, and that is honest rather than an omission - no
test can tell a legitimate timeout from a tight one by reading it.
`tests/README.md` says *timing is not evidence*; this note is the same
rule applied to an upper bound rather than to a wait, and both fixes
carry the reasoning at the assertion.
