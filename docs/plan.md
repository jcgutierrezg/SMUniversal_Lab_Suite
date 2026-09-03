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
| last landed | Wave 8b |
| since then | unnumbered entries, newest first in `CHANGELOG.md` |
| in progress | not recorded here — ask the remote, `git fetch --prune` |
| next | undecided — see [What is parked](#what-is-parked) |
| owed | a commissioning round — [checkup owed](open/checkup-owed.md) says which instruments and why |

`tests/test_docs.py` checks that no wave is recorded in `CHANGELOG.md`
newer than the one named on that first row, so this line cannot quietly
fall behind the work. It tracks the newest entry rather than a wave
number, because a wave lands in lettered parts and "Wave 7a is done" is
not "Wave 7 is done".

**The "in progress" row names no branch, deliberately.** It used to, and it
was wrong both times anyone checked: it described work as unmerged that had
landed, and named a branch that had since been deleted on the remote. A row
whose truth depends on a branch existing is a row that goes stale silently,
and a stale sentence is indistinguishable from a current one. Git already
answers this question and is never out of date.

**The "owed" row links rather than summarising**, for the same reason. The
generated page distinguishes a driver that is *stale* — checked once, but the
code has moved since — from one that is *unverified*, which has never been
run against its instrument at all. Prose here saying "every driver reads
stale" flattened those into one claim, and the flatter claim was false.

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

## Landed — Wave 8b: what a run does about a lost link

A run that loses its link de-energises, fails, keeps nothing, and blocks
the instrument until it is reconnected. Runs already in the table are
untouched, including their unsaved data.

Almost all of that was already true after 8a, through three mechanisms
lining up: the transport latches, `confirm_output_off()` reports the
shutdown as uncertain, and `report_uncertain_shutdown()` blocks the
instrument. Nothing pinned the combination, so any one of the three
could have been changed without a test noticing. `tests/test_link_lost_during_a_run.py`
pins it end to end, through a real experiment.

What 8b added beyond the test: `ShutdownReport.link_lost`, and an
operator message for that case which says the link stopped answering,
that this run was discarded, that other runs are untouched, and to
reconnect before starting again. The generic text said only that the
output could not be confirmed off, which left someone pressing Start
and wondering why it was refused.

## What is parked

In the order they were last discussed, not in priority order — that
ordering is a decision, not a record, and belongs in a conversation.

- ~~**A check comparing the status row against `git`.**~~ **Closed, by
  deleting the claim instead of checking it.** The row named a branch state,
  went stale twice, and the proposal was to have a test compare it against
  `git`. That would have made the repository's documentation depend on which
  refs a given checkout happens to hold — and those disagree: the same
  branch was reported present by one reader and absent by another, days
  apart, because one checkout had never been pruned. A claim that cannot be
  checked reproducibly is better removed than automated, so the row now
  points at git rather than restating it.
- **The envelope has no home in `bench/choosing-an-smu.md`.** The data
  now exists, in each instrument note. A curve does not fit a table
  cell; the intended shape is the two endpoints in the matrix — fastest
  rung and quietest rung — linking to the per-instrument table. It is a
  `tools/build_docs.py` change and wants its own wave.
- **Sub-count refusal on the drivers that do not have it.** Only the
  U2722A refuses a level it cannot express. The floors are now measured
  for the rest, so the equivalent can be written from data rather than
  by analogy — but each needs its converter count, and the floors found
  here are for one range only.
- **The miniSMU's floor is below where the probe looks.** It still
  followed the sign at 95 pA, where the walk stops after a millionfold
  descent from the bias.

Nothing is currently blocked on a decision.

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
