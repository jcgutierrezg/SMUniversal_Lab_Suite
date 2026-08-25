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
| 6 | the 2026-08-21 round recorded; staleness derived from content, not commit dates ([A derived claim resting on something a merge rewrites](faults/24-derived-from-a-rewritable-date.md)) |
| 7 | U2722A: the compliance chooses the range, and every limit is read back (deviations 52 and 53) |
| 8 | the 2026-08-25 GSM-20H10 run recorded; the fleet is green on this branch |
| 9 | U2722A: a source level below ten counts of the active range is refused (deviation 54) |

### What triggered it

Wave 6d filled `RangePlan`'s unsourced source axis with `AUTO`. Every
instrument was checked on 2026-08-18: harmless on most, damaging on two
in opposite ways, and genuinely load-bearing on two more. The whole
account is in [A ranging command that silently resets the compliance](faults/23-autorange-resets-compliance.md); the procedure it
produced is [A commissioning round](workflow/commissioning-round.md).

### Next, in order

1. ~~**Re-run every instrument's checkup** on this branch.~~ Done
   2026-08-21. *compliance survives ranging* passes on the GSM-20H10:
   `NOT_SOURCED` confirmed against hardware rather than a fake
   transport, and confirmed again on the U2722A's voltage-sourcing half.
   The round found no new driver fault and six faults in the checkup
   tool itself, recorded as C1 and C5–C9 in
   [Known technical debt](open/technical-debt.md). The U2722A fails four
   checks — that is `D7` below, not a regression.

   **C1 and C7 landed 2026-08-21** — the compliance probe waits for the
   output to settle, and an output beyond its own limit is now a
   failure rather than a pass. Every instrument's checkup should be
   re-run against them; the U2722A is expected to report a second,
   different failure for the same underlying cause.

   **C6 landed 2026-08-21** — the reported cost per reading is the
   steady-state cost, the first read after the output comes up is its
   own line, and the published figures were re-derived from the round's
   traces rather than left overstating every instrument until the next
   session.

   **C5 landed 2026-08-21** — the GSM-20H10 reads `SOUR:FUNC?` and asks
   the complementary trip axis, as the B2901A already did and as both
   instruments' manuals describe. Unverified against hardware; the
   re-run will be the first time that query is sent to the instrument.

   **C8 and C9 landed 2026-08-21**, with the dirty flag's paths: an
   error now names the commands it could have come from, the miniSMU's
   method calls are recorded like everyone else's text, and a report
   taken from a modified tree says what was modified.

   That closes every finding from the round except **D7**, which is its
   own wave.
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

### The 2026-08-24 round

Every instrument re-run at `5f27163`. Six clean, one red, one fixed here:

| | Result |
|---|---|
| miniSMU, B2901A, 2635B, 2611A, 2401 | pass, no failures |
| U2722A | four `-222` failures — **diagnosed and fixed**, see below |
| GSM-20H10 | clean at `d332432` on 2026-08-25, **64 pass**. The 2026-08-24 run that read as a regression was a desynchronised USB stream, not a driver fault — see below |

`SOUR:FUNC?` **is verified against hardware** — it answers `VOLT` while
sourcing voltage and `CURR` after the source function changes, and the
complementary trip query follows it. That closes the C5 caveat above.
(It was briefly claimed on the strength of the 2026-08-24 run, withdrawn
when that run turned out to be desynchronised, and confirmed properly on
2026-08-25.)

**The GSM-20H10 was never broken.** Three runs in this round were lost to
an intermittent USB-TMC read timeout that leaves the reply stream one
reply behind — every query afterwards returns the previous command's
answer, and the query latency collapses from ~20 ms to ~1.3 ms because
the replies are already buffered. The driver fingerprint is identical
across the red runs and the green one. It is the only instrument in the
fleet on USB-TMC rather than Prologix, and the only one affected.

The U2722A's four failures came from two causes and are addressed by
deviations 52 and 53 in [Keysight U2722A](instruments/keysight-u2722a.md). The fix is
**unverified against hardware**: the driver changed, so its
`code_fingerprint` no longer matches the note's `bench_code`, and
[checkup-owed](open/checkup-owed.md) will say so until a session
re-runs it.

Three narrowed open items, none blocking:

- **The 2611A's 2.145 s** is one blocking query, not a slow sweep:
  `print(smu.nvbuffer1.n)` queues behind the still-running sweep script.
  So the sweep genuinely takes 429 ms per point against a 13.6 ms
  steady-state reading, and the 10 ms delay argument accounts for 2% of
  it. Deterministic across two commits and four days.
- **Compliance readback is missing on most drivers**, so the *compliance
  survives ranging* check — the one that caught this wave's fault — is
  skipped on the 2401, 2450, 2611A, 2635B, B2901A and miniSMU. On the
  TSP pair it is an attribute read symmetric with a write already in the
  code.
- **The 2401 cannot report a compliance trip either**, so a run that
  goes into compliance there produces a flat top and nothing else.

### The next wave: a desynchronised session must stop

The checkup **detects** the USB desync and warns that failures below that
point may be consequences rather than separate faults. It does not stop:
on 2026-08-25 it ran 1386 further queries against a stream it had already
declared unrecoverable, and produced a second failure that was purely a
consequence of the first.

Every one of those queries returned a real instrument response to the
*previous* question — well-formed, plausible, wrong. That is the failure
mode this repository exists to prevent, and it is currently reachable
from a cable.

`read_error()`'s docstring defends swallowing a failed queue read, on
the grounds that failing to read the queue is not evidence that a
command failed. That reasoning is right for a dropped reply and wrong
for a timeout that desynchronises the stream, and the two cases need
separating. Fleet-wide, not GSM-specific: any transport can time out.

Open before it can start: whether `viClear` on this backend can
resynchronise a stream, or whether the honest response is to end the
session and require a reconnect.

### One decision waiting

**D7 — the measure axis of the *sourced* quantity.** `for_sourcing()`
sets it to `AUTO` because it is read back from the source and is not
ours to set. On a shared-knob instrument that `AUTO` still wins the
knob: a 0.1 V sweep on the U2722A lands on the 20 V range, 1.22 mV per
count instead of 122 µV. Same shape as the fault above, different axis,
and outside what was signed off for the `NOT_SOURCED` wave.

The 2026-08-21 round changed what it costs. It is no longer only
resolution: on the U2722A a current-sourced setup takes the knob to
R120mA, the requested compliance is **refused** as below that range's
floor, and the output is bounded by the range rail instead — 2 V where
1 V was asked for — while the sourced current is quantised to 7.32 µA
steps. A sweep refuses to start; a fixed-level run does not. The same
defect is present and silent on the miniSMU, whose autorange is real,
which is the argument for fixing it in `RangePlan` rather than per
driver.

**Still open after 2026-08-24.** Deviation 52 stops the U2722A being
harmed by it — the range change is declined rather than reconciled — but
that is one driver refusing a bad plan, not `RangePlan` producing a good
one. The miniSMU is untouched.

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
