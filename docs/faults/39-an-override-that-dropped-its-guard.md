---
type: fault
fault: 39
title: "An override that quietly dropped the guard it inherited"
---

# An override that quietly dropped the guard it inherited

## Symptom

Four tabs with the same Delete button. On three of them, ticking a run
and pressing Delete asks *"Discard 2 run(s) and their raw readings?"*.
On the fourth, the runs are gone.

Nothing looks different. The button, the tick boxes and the results
table are the shared ones.

## Cause

`FourPointProbeExperiment.delete_ticked()` was a full override that
never called `super()`. It had been that way since the first import, and
the base class it diverged from is where the confirmation lives.

Two behaviours were lost, and neither is visible from the call site:

* **The confirmation.** Nothing here is auto-saved (house rule 3), so a
  run in the results table exists nowhere else. Delete is irreversible
  and it was one mis-click away.
* **The provenance invalidation.** `clear_output()` two methods below
  sets `_calc_source = None` when it empties the table, with a comment
  saying why: the calculated sheet resistance points at reading ids from
  a run that no longer exists. Deleting the same runs one at a time
  reached the same state and cleared nothing, so a calculation made
  afterwards carried a source chain naming readings that had been
  discarded - which is the one claim §17 provenance exists to make true.

Found by ruff's `F841`. The override also built a list of row labels and
never used it, and that dead local was the only outward sign that this
method had been written by hand rather than derived.

## Why it is dangerous

Both halves fail towards *looking correct*.

A silent delete looks like a delete that was confirmed elsewhere. The
operator who loses a measurement to it has no way to tell whether they
were asked and clicked through, or never asked - and the run they lost
is the one they were about to save.

The stale provenance is worse in the long run, because it survives to
disk. A result whose sources name discarded readings is not merely
missing information; it is a specific, checkable claim that is false. It
reads exactly like a correctly attributed one.

## Check

When a subclass overrides a method that the base uses to enforce
something - a confirmation, a gate, a piece of bookkeeping - the
question is not "does the override do the right thing?" but "what did
the base do that this no longer does?". The three siblings here answer
it well: each calls `super().delete_ticked()` and then drops its own
plot state for the rows that actually went away.

"The rows that actually went away" is the second half. The operator may
have answered no, so an override cannot assume the deletion happened.

An unused local in a hand-written override is worth following. It is
usually the residue of a version that did more.

## Where it is guarded

`experiments/ossila_4pp/experiment.py` now goes through the base method
and drops `_run_resistance`, `_datasets` and - only when the source run
itself was among those deleted - the calculation's provenance chain.

`tests/test_4pp.py` covers all three: that Delete asks before
discarding, that answering no keeps the runs, and that deleting the run
a copied resistance came from clears the chain while deleting an
unrelated one leaves it intact. That last pair is the discriminating
one; a single test of either half would pass against code that always
cleared it, which would silently downgrade honest results to
hand-entered ones.
