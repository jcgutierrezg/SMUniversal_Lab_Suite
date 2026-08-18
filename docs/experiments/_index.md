---
type: index
title: "Experiments"
---

# Experiments

One note per folder under `experiments/`: where the measurement came
from, what it computes, how a cancelled run behaves, and what the saved
CSV holds.

An instrument is never a new experiment - that is what the driver layer
is for. The test for whether something earns a folder here is whether it
produces a different *derived quantity*; a different sweep shape is a
feature of an existing experiment, and a different box is a driver.

## The notes

- [Van der Pauw](van-der-pauw.md) - sheet resistance; supplies [Hall effect](hall.md)
- [Hall effect](hall.md) - carrier density, mobility, carrier type
- [IV sweep](iv-sweep.md) - voltage or current sweep, optional fit, optional periodic bias
- [Ossila four-point probe](ossila-4pp.md) - four-point probe sheet resistance and resistivity
- [Fixed sourcing vs time](fixed-source-vs-time.md) - hold one level, sample the other quantity against the clock

The test for a folder is stated above and the newest note is the first
one to meet it from a different direction. **Fixed sourcing vs time**
derives no physical quantity at all - it is not a different sweep shape,
it is a different independent variable, and its run record is one row
per instant rather than one per level. A sweep experiment cannot hold
that shape as an option.

## Where they came from

Every experiment here except one is a port of a single-file, globals-heavy Tkinter
script or notebook. The originals duplicated their logic per instrument
- the worst had whole function families suffixed `_2611` / `_2401`
differing only in command dialect, which is the reason the driver layer
exists at all.

The exception is [Fixed sourcing vs time](fixed-source-vs-time.md), which had no original at
all. That changes what its note is for: with no script to compare
against, every default is a decision rather than an inheritance, and the
note carries the decisions and who signed them off in place of the
deviations the others carry.

`PORTING_NOTES.md` called this archaeology, and the word is right: in
more than one case the intent had to be recovered from code that could
not run. See [Ossila four-point probe](ossila-4pp.md), where the clearest statement of what the
experiment was *for* was a loop that raised `NameError` on its first
iteration.

## The habit that runs through all of them

**A number on a screen is for a person; a number in a calculation is for
a machine; they should not be the same number.** Three separate
originals used a formatted display value as a calculation input - the
Hall notebook at `%.6g`, the 2401 script rounding source levels to four
decimals, the IV scripts reading their own display fields. Each imposed
a precision floor that no error ever reported.
