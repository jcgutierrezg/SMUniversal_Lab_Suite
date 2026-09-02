---
type: fault
fault: 34
title: "A test level the instrument cannot express"
---

# A test level the instrument cannot express

## Symptom

A commissioning tool reports a failure against a working instrument,
every time it is run, and the failure is the tool's own request rather
than the instrument's answer.

Measured on the U2722A. `tools/smu_checkup.py` sourced a module-wide
`PROBE_CURRENT = 1e-6` at every instrument in the registry. That model
has no autorange, so the checkup's all-`AUTO` current axis lands on
R120mA, where one count is 7.32 µA — and 1 µA is a seventh of a count.
Below one count the output is offset residue whose *sign is not
commanded*: `-1 µA` and `+1 µA` produced the same output at the bench on
2026-08-25, and during the commissioning round the residue pointed the
wrong way and walked the output to the −2 V range rail.

The driver refuses that level, correctly, before energising anything.
So the checkup was **structurally unable to pass** on an instrument that
was working exactly as specified, and the 2026-08-25 bench report
carries that failure as accepted-and-explained.

## Cause

One constant standing in for a property that differs by instrument, and
differs *by range within* an instrument. 1 µA is eleven counts on the
U2722A's R1uA range and a seventh of a count on its R120mA range. There
is no number that is right on both, so a module-level constant is not a
conservative choice — it is a choice that happens to be right on the
instruments it was written against.

The second half of the cause is *when* the question can be answered. The
floor depends on the range the ranging plan lands on, which is not known
until the plan has been carried out. A floor derived from the model
alone would be right on one range and wrong on the rest, which is the
same defect one level up.

## The rule

**A diagnostic sources levels the instrument can express, taken from
that instrument, at the moment the range is known.**

The nominal constants remain, as a starting request. Reconciling them is
two steps:

- before anything is sent, clamp into what the model declares (`LIMITS`)
  — a probe above the widest declared range is a request the instrument
  cannot carry out, and every check downstream would then be measuring
  the clamp;
- after the ranging plan has been applied and before the output comes
  up, ask the driver what its floor is *on the range that is now
  active* (`source_level_floor()`), and raise the level to it.

And the report says which level was actually sourced and why. A report
that quotes 1e-06 A while the instrument was handed 73 µA is a report
somebody will quote later.

## How to check

A tool that cannot pass on a working instrument is on the same footing
as one that invents failures — both teach people to read past the
output, and this project has now had one of each. Ask of any fixed
diagnostic level: *what makes this the right number on the instrument
with the coarsest converter and the narrowest envelope in the fleet?*
If the answer is that it was chosen against a different instrument, it
is a constant waiting to become a failure report.

Where a floor cannot be derived, say so rather than proceeding quietly.
Most drivers here declare their sub-count behaviour `unmeasured` — the
contract ledger in `tests/test_driver_contract.py` records which — and
the checkup raises a warning on each. One bench measurement per
instrument closes it, and until then a clean report on those models
still means *none observed*.

Related: [A probe asked where the answer is already known](19-non-discriminating-probe.md) and
[A diagnostic tool with the fault it diagnoses](20-a-tool-with-the-fault-it-diagnoses.md).
