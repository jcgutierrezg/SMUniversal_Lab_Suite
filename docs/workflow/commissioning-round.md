---
type: workflow
title: "A commissioning round"
---

# A commissioning round

Checking every instrument on the bench in one pass, rather than one at
a time as something breaks.

[Adding an SMU](adding-an-smu.md) covers a *new* driver. This covers the
other thing: a change to a shared layer has landed, and the question is
what it did to instruments nobody was thinking about when it was
written. It was learned in August 2026, expensively, and the procedure
below is most of what that cost bought.

## Why a round rather than a repair

Wave 6d gave `RangePlan` a source axis for the quantity a run is *not*
sourcing, and filled it with `AUTO`. That was checked against the
instrument in front of whoever wrote it, and it was fine there.

Nine days later a GSM-20H10 checkup had six failures. Diagnosing that
one instrument took a week and produced four wrong mechanisms — an
interlock, an auto-clear setting, an ambiguous channel suffix, a stale
buffer — each written from a plausible story rather than from a probe,
and one of them reached the instrument note as a statement of fact
before being retracted.

What ended it was checking **every** instrument. The same construct
turned out to be harmless on most, and damaging on a pair of them in
opposite directions: on one it silently reset the compliance to the
instrument's floor, on the other it made the compliance unsettable and
sweeps failed outright. On another pair the same axis was genuinely
load-bearing — it is the compliance's own range on that family — so a
fix designed from the instruments looked at first would have broken
them.

**The 2401, the B2901A and the GSM-20H10 send a byte-identical command
and only the GSM is damaged by it.** Nothing about the dialect, the
manufacturer or the command text predicts which. That is the case for
the round: a rule written from a subset turns the rest into exceptions,
and you cannot tell which subset you have until you have looked at all
of it.

## The order

**1. Land the tooling fixes first.** A commissioning tool that invents
failures teaches people to ignore it. Before the August 2026 round,
`smu_checkup.py` sent a compliance before the range that had to hold it
— the order [Limit sent before the range that has to hold it](../faults/15-limit-before-range.md) exists to prevent — which
produced a failure the application cannot produce and, on one
instrument, a cascade of four more behind it.

**2. Do not change the tool mid-round.** Instruments checked either side
of a tool change are not comparable, and comparability is the entire
product of the round.

**3. Run every instrument, including the ones you expect to be fine.**
The unharmed ones are not filler. They are what tells you whether a
behaviour is a family property, a dialect property or one instrument
being strange — and that distinction decides the shape of the fix.

```powershell
uv run tools/smu_checkup.py --address <addr> --trace
uv run tools/timing_scan.py --address <addr>
```

`--trace` is not optional. A failure reported against a *check* names
six candidate commands; a trace names the one that raised the error.

**4. Read the traces, not just the verdicts.** The most useful finding
of the August round was a pair of instruments emitting the same command
with opposite outcomes, which no pass/fail column shows.

**5. Design the fix from the whole table, then write it.**

## What a report has to say about itself

A finding is a claim about a version of the code **and** a version of
the instrument. Reports record both since 2026-08-20 — see
[core/provenance.py in the module map](../architecture/core-modules.md).

Before that they recorded neither, and comparing a clean 2026-08-06
GSM-20H10 report against a six-failure 2026-08-18 one meant bisecting
git by hand: five rounds of hypotheses for something a commit sha
answers in one line. **Look at the window before the first failure, not
just between the last two reports.** The change that caused it is in the
window nobody re-runs.

Firmware matters the same way and had not bitten yet. Every finding in
an instrument's note is a claim about the firmware it was measured on,
and upgrading invalidates the note with nothing in the staleness
machinery noticing — `checkup-owed.md` watches the code, not the
instrument.

## Clean is not the same as fine

Most of the instruments in the August round came back with zero
failures. That means **none observed**, not none.

The GSM-20H10's compliance collapse raised no error and was invisible
until an unrelated later command tripped over the collapsed value. On
an instrument where nothing downstream happens to trip, the same
collapse produces a clean report. Nothing read a compliance back.

So a round ends with a list of what was *checked*, not a list of what
passed. `compliance_readback` in the driver contract ledger records
which instruments can be asked and which have had the answer verified
against a value they were known to hold — and until both are true, that
instrument's clean checkup is still "none observed".

## The habits that actually saved time

- **Ask for the manual rather than reasoning from a plausible
  mechanism.** Four wrong mechanisms preceded the right one, and the
  manual's factory-defaults table killed the first hypothesis outright —
  it had already cost two bench runs.
- **Build a probe whose interesting answer is the correct one.** Two
  probe runs were voided because they tested the output state at 0 V,
  where output-on and output-off are physically identical on that
  instrument. A third was voided because it asserted something a helper
  guaranteed regardless.
- **Check that a query works before believing it.** `OUTP?` on the
  GSM-20H10 returns 0 with the output on and 10 V flowing. Five rounds
  of reasoning were built on it. Nothing in the suite had ever queried
  it, which is why nobody knew.
- **A control leg on every probe.** Two of the three GSM probes were
  saved from being written up as findings by a control that asked the
  same question where the answer was known.
