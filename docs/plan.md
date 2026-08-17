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
| last landed | Wave 7d |
| in progress | Wave 7 |
| after Wave 7 | the numbering ends — see [Superseded](#superseded) |

`tests/test_docs.py` checks that no wave is recorded in `CHANGELOG.md`
newer than the one named on that first row, so this line cannot quietly
fall behind the work. It tracks the newest entry rather than a wave
number, because a wave lands in lettered parts and "Wave 7a is done" is
not "Wave 7 is done".

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
| 7e | packaging for a frozen executable (§42) | — |

What is left, and what each still needs answering:

- **Packaging for a frozen executable (§42) (7e).** The intended
  deployment is an `.exe`. The resource half is nearly a non-issue —
  one PNG, already loaded `__file__`-relative — but the project has no
  `[build-system]` and is not importable from another working
  directory, so §42's acceptance criterion fails at import long before
  it reaches a resource. **Undecided:** whether a `src/` layout comes
  with it, deferred here since Wave 0b.
- Packaging (§42). The intended deployment is a frozen `.exe`.

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
