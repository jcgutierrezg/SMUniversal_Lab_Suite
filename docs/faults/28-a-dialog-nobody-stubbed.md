---
type: fault
fault: 28
title: "A dialog nobody stubbed, on a machine that never showed it"
---

# A dialog nobody stubbed, on a machine that never showed it

## Symptom

A GUI test that passes quickly on one machine, hangs forever on
another, and shows a modal window on a third. No assertion changes
between them and neither does the code.

The hang has no output at all. Under CI it consumes the job's whole time
budget and reports a cancellation, which names nothing.

## Cause

A dialog raised on a seam the test never replaced.

Dialogs from a run do not reach `messagebox` directly. `LabApp.ui()`
puts the call on a queue and the main thread drains it from a
`root.after(UI_PUMP_MS, ...)` timer. A test drives the loop itself, so
whether a queued dialog is ever executed depends on whether the test's
pumping happens to span the timer's period in **wall-clock** time.

That makes the outcome a property of the machine:

- pumping spans the period — `messagebox.showwarning` opens a window and
  runs its own event loop until someone clicks it, which under a virtual
  display nobody ever will;
- pumping does not — the call sits in the queue until `root.destroy()`
  discards it, and the test passes having asserted nothing about it.

A test that pumps a fixed number of times rather than waiting on a fact
sits on whichever side of that line the hardware puts it.

## Why it is dangerous

The hang is the loud half and the cheap half. The quiet half is that the
message is thrown away and the suite reports green.

In the case this was found in, the discarded message was the one telling
an operator that a sample may still be energised after the link to the
instrument stopped answering. The test asserted that the instrument was
blocked, which was true, and never asked whether anybody had been told.
A green run meant less than it appeared to, in the one ending that
concerns a person reaching into a fixture.

It also breaks the symmetry that makes a suite worth running: the
machine where it hangs is not the machine where the fault is, so the
report arrives somewhere nobody can reproduce it.

## Check

Two questions, and a call-time check alone answers only the first:

- did anything reach the real dialog module during this test?
- was anything still sitting in the UI queue when the test ended?

The second is the one that fails on a fast machine, where nothing was
ever called because the pump never fired.

Waiting on a fact rather than on a count removes the machine-dependence
underneath both. Drain the queue explicitly — `LabApp.drain_ui_now()`
exists for this — rather than pumping the event loop and hoping the
timer fires.

## Where it is guarded

`_a_gui_test_never_reaches_a_real_dialog` in `tests/conftest.py` fails
any `gui`-marked test that leaves a dialog on an unclaimed seam, whether
it was shown or merely queued. It stands a recorder on seams no test has
patched, so an unstubbed dialog returns and is reported instead of
blocking.

It is the counterpart of `_dialog_recorder_belongs_to_this_file`, which
catches a recorder *stolen* by another test file. That one cannot catch
this: with nobody owning the seam there is no owner to disagree with.
