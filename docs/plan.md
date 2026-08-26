---
type: state
title: "Plan"
---

# Plan

Status, the next wave, and what is still undecided. **Short by design** —
the narrative of each completed wave is in `CHANGELOG.md`, and the
reference material it produced is in the notes. A plan that also holds
its own history stops being a plan.

## Status

Deliberately a boundary, not a list. Per-wave contents and the review
issues each one closed are in `CHANGELOG.md`; repeating them here is how
the four documents this vault replaced started disagreeing with
themselves.

| | |
|---|---|
| last landed | Wave 8a |
| in progress | nothing — `driver_checkups` merged to `main` |
| next | Wave 8b, the run-side response to a lost link |

`tests/test_docs.py` checks that no wave is recorded in `CHANGELOG.md`
newer than the one named on that first row, so this line cannot quietly
fall behind the work. It tracks the newest entry rather than a wave
number, because a wave lands in lettered parts and "Wave 7a is done" is
not "Wave 7 is done".

---

## Landed — Wave 8a: a link that stops answering stops the work

Merged. The ranging commissioning round that preceded it is in
`CHANGELOG.md`; the branch it lived on is gone.

A query whose reply never arrives leaves two separate things wrong, and
either alone is enough to stop:

1. **The correspondence is broken.** If the instrument answers late, the
   reply waits in the output buffer and the next query collects it. Every
   reading afterwards is one command out of step, and nothing about the
   numbers says so.
2. **The measurement did not happen.** A level was sourced and no reading
   came back, so the sweep has a hole in it and its point-to-point timing
   is no longer what was asked for. True even when no reply is ever
   coming.

`Transport.query()` now latches on any failed exchange and refuses to
read again until the transport reconnects. `Transport.write()` keeps
working, deliberately — a write never reads, so it cannot be one behind,
and that is what lets a poisoned session still de-energise its sample.

There is no recovery in place. `clear()` was the old one; it reported a
device-clear call not raising, which is a different question from the
stream being back in step, and on the affected backend it returned False
anyway.

## Next — Wave 8b: the run-side response

8a stops the transport lying and stops the checkup. What a *run* does
about it is not yet built:

- the operator message is the generic uncertain-shutdown text, not one
  that says the link stopped answering
- the instrument is not blocked afterwards, so the next Start will try
  the same poisoned connection. `ownership.block()` already exists for
  exactly this, and is what `_initialise_driver()` uses when a mandatory
  reset fails
- a disconnect/reconnect action is the intended way back

Runs already in the store and their unsaved data survive untouched. The
interrupted run itself is discarded, as every failed run is.

---

## Where everything else went

This file replaces `WAVE_PLAN.md`, which had grown to carry a plan, a
changelog and a reference manual at once.

| Was in `WAVE_PLAN.md` | Now |
|---|---|
| the status table | above |
| per-wave narrative | `CHANGELOG.md` |
| working protocol | [Workflow](workflow/_index.md) |
| technical debt | [Known technical debt](open/technical-debt.md) |
| open decisions | above |

---

## Superseded

The wave numbering was a plan for adopting one code review, and that
adoption finished at Wave 7. It continues from Wave 8 as a plain
sequence number for a unit of work, because the patches kept being
called waves regardless and two names for one thing is how documents
start disagreeing. It no longer tracks the review.
