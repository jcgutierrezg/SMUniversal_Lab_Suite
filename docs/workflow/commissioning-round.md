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

This now has an edge worth naming. The probe levels are no longer a
module constant applied to everybody: they are the nominal request
reconciled against each driver's declared envelope, and then raised to
whatever floor the instrument reports on the range the ranging plan
landed on. So **instruments in the same round may legitimately be probed
at different levels**, and the tier 1 *probe levels* row in every report
says which and why. Read that row before comparing a tier 3 reading
against another instrument's.

The alternative was worse and was measured: one constant meant the
U2722A was asked for a seventh of one count of its active range, which
its driver correctly refuses, so the tool was structurally unable to
pass on a working instrument. See
[fault 34](../faults/34-a-probe-the-instrument-cannot-express.md).

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

## What a checkup asks the instrument to confirm

Three settings are read back rather than assumed: the **compliance**,
the **range** on all four axes, and any applicable **power limit**. Each
answers in one of five states, and only one of them is a pass — the
vocabulary is in `core/readback.py` and the reasoning in
[fault 33](../faults/33-a-setting-never-read-back.md).

| State | In a report | What it means |
|---|---|---|
| `unsupported` | skip | this driver has no confirmed query for it |
| `unreadable` | warn | it asked, and no usable answer came back |
| `unverified` | warn | it agreed, and the readback has never been checked at the bench |
| `confirmed` | pass | it agreed, and the readback has been checked |
| `mismatched` | **fail** | the instrument is not in the state it was asked for |

Two things about that table change what a round is for.

**A `mismatched` row is a safety event, and the report says SAFETY on
it.** It is a fail whether or not the readback itself is verified: if
the readback is honest the instrument is holding a value nobody chose,
and if it is dishonest the software is steering a sample using a query
that lies. Stop and find out which before sourcing anything.

**A `warn` row is work for this round, not noise.** Every
`unverified` becomes a `confirmed` after one bench step, and the step is
always the same shape: put the instrument into a state you know
independently — a range set from the front panel, a distinctive
compliance — ask for it over the bus, and confirm the answer names it.
Then set the driver's `RANGE_READBACK_TRUSTED`,
`COMPLIANCE_READBACK_TRUSTED` or `POWER_LIMIT_READBACK_TRUSTED` and
record it in the contract ledger with the date.

The same applies to the two `sub-count ... levels` warnings each
instrument carries. They say the converter's bottom count has never been
measured on that model — which matters because below one count a
commanded level is offset residue whose sign is not the one asked for,
and that has been measured on exactly one instrument here. The step is:
command plus and minus a small fraction of a count on a wide range, and
see whether the output follows the sign. Record the answer in the
instrument note and set `SUB_COUNT_LEVELS` for that axis.

**Do not clear a warning by editing a flag.** Every one of these flags
is a claim that a physical measurement was made, and the only thing that
makes it true is the measurement.

### The two tools that produce those measurements

Both write a block to paste into the instrument note. Neither sets any
flag: they establish a fact, and a person decides what standing claim it
supports.

```bash
uv run python tools/bench_envelope.py --address <addr> --load 9958
uv run python tools/bench_readback.py --address <addr>
```

`bench_envelope.py` finds where the commanded sign stops being
commanded, on both axes by default (`--axis current|voltage|both`). It
pins the range that carries the bias and derives the compliance from the
measured load, so the control leg cannot be limited by the ceiling on
whatever fixture is to hand — a control leg that is itself limited tests
the condition it exists to rule out, and that has gone wrong here twice.
The floor it reports is a floor *for that range*; the driver stores
counts, not an absolute level.

`bench_readback.py` is the one that needs you at the front panel, and it
cannot be automated. Over the bus, a query that reads hardware and a
query that echoes the last value written to it give the same reply, so
no amount of asking separates them. A value dialled in by hand never
passes through the bus, which is what makes the answer mean something.
It puts three legs to each subject — the front-panel value, then two bus
range changes — because an echo fails the first, a constant fails the
second, and a query that latches its first answer passes both of those
and fails only the third.

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
