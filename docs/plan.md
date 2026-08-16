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

| Wave | Contents | Review issues | State |
|

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
