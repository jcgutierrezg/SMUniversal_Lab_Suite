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
| last landed | Wave 7g |
| in progress | the ranging commissioning round, on branch `driver_checkups` |
| after Wave 7 | the numbering ends — see [Superseded](#superseded) |

`tests/test_docs.py` checks that no wave is recorded in `CHANGELOG.md`
newer than the one named on that first row, so this line cannot quietly
fall behind the work. It tracks the newest entry rather than a wave
number, because a wave lands in lettered parts and "Wave 7a is done" is
not "Wave 7 is done".

---

## In progress — the ranging commissioning round

On **`driver_checkups`**, not yet merged to `main`. Four commits, each
verified by applying the chain to a clean checkout of `origin/main`:

| | Landed on the branch |
|---|---|
| 1 | `smu_checkup.py` applies ranges before limits ([Limit sent before the range that has to hold it](faults/15-limit-before-range.md)) |
| 2 | GSM-20H10 bench findings, [A ranging command that silently resets the compliance](faults/23-autorange-resets-compliance.md), first manual extracts |
| 3 | `RangePlan.NOT_SOURCED` — an axis carrying nothing is not `AUTO` |
| 4 | commit and firmware stamps on reports; `timing_scan` checks its readings |
| 5 | compliance readback, and the checkup's *compliance survives ranging* |

### What triggered it

Wave 6d filled `RangePlan`'s unsourced source axis with `AUTO`. Every
instrument was checked on 2026-08-18: harmless on most, damaging on two
in opposite ways, and genuinely load-bearing on two more. The whole
account is in [A ranging command that silently resets the compliance](faults/23-autorange-resets-compliance.md); the procedure it
produced is [A commissioning round](workflow/commissioning-round.md).

### Next, in order

1. **Re-run every instrument's checkup** on this branch. Every report now stamps
   its commit and firmware, so the set is comparable and self-dating for
   the first time. The GSM-20H10 should show *compliance survives
   ranging* passing — the first hardware evidence that `NOT_SOURCED`
   works, rather than fake-transport evidence.
2. **Re-run `timing_scan`** on the fleet. It now refuses to fit through
   failed reads and reports noise per integration time, which is the
   only thing that answers whether an instrument's NPLC integrates at
   all. The GSM-20H10's does not, so far as anyone can tell, and its
   earlier figures were taken from failed reads.
3. **GSM-20H10 firmware.** Running `V1.16`; GW Instek publish `V1.30`
   (2026-08-12) with no release notes. Capture a `V1.16` baseline
   first — every finding in that note is a claim about `V1.16` and the
   upgrade invalidates them all. Whether it fixes `OUTP?` is unknown.
4. **Then the open items** in [Known technical debt](open/technical-debt.md): the *range* half
   of `apply_ranges` reporting what it sent rather than what was
   accepted, and the compliance readback on the instruments that do not
   have one yet.

### One decision waiting

**D7 — the measure axis of the *sourced* quantity.** `for_sourcing()`
sets it to `AUTO` because it is read back from the source and is not
ours to set. On a shared-knob instrument that `AUTO` still wins the
knob: a 0.1 V sweep on the U2722A lands on the 20 V range, 1.22 mV per
count instead of 122 µV. Same shape as the fault above, different axis,
and outside what was signed off for the `NOT_SOURCED` wave.

---

## Wave 7 — Persistence and packaging

Split into five, because these are five unrelated concerns and a red
test afterwards would not say which one caused it.

| | Concern | State |
|---|---|---|
| 7a | tooling guards — doc-table lint, cross-file recorder guard | landed |
| 7b-i | run and record identity; the IV sweep's sample binding | landed |
| 7b-ii | save semantics, schema version, app version (§25) | landed |
| 7c-i | bytecode-staleness fix in the test runner | landed |
| 7c-ii | single-instance lock | landed |
| 7d | operational event log (§26) | landed |
| 7e | packaging (§42) | landed |

Wave 7 is complete, and with it the wave numbering. Later work is
recorded in `CHANGELOG.md` as entries rather than numbered waves.

**One decision this wave deliberately did not take: whether to freeze.**
7e makes the project installable, which is a prerequisite for a frozen
`.exe` and useful without one. The two deployment models differ in more
than convenience — a bench running a checkout keeps the `docs/` and
`bench/` pages in step with the code and keeps `checkup-owed.md`
meaningful, because that derives from `git log`; a bench running an
`.exe` has neither, and `app_version` becomes the only link from a
running copy back to the commit that produced it. See
[packaging](workflow/packaging.md).

**If freezing goes ahead it needs a bench session before it counts as
commissioned.** The freeze itself has never been run — everything in 7e
is verified against a built and installed *wheel*, which is not the same
artifact.

---

## Open decisions

Both of the decisions this section carried are now answered. They are
kept, answered, rather than deleted: an option that was considered and
rejected is worth more than a blank, because the next person to have the
idea gets the reasoning instead of repeating the argument.

1. **Save semantics** — **A, immutable snapshot.** Reasoning under
   Wave 7 above.
2. **Can two instances of the app run at once?** — **No.** The app must
   refuse to start a second time. Two processes driving one SMU is a
   physical hazard, not only a data one: each would believe it owns the
   output state. `SampleRegistry` and `core/ownership.py` are both
   process-local and were written on the opposite assumption, so both
   are revisited in 7c.

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

The wave numbering will run stale after Wave 7 — it was a plan for
adopting one code review, and that adoption finishes there. Whatever
guides the next phase replaces this file rather than extending it.
