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

- [[van-der-pauw]] - sheet resistance; supplies [[hall]]
- [[hall]] - carrier density, mobility, carrier type
- [[iv-sweep]] - voltage or current sweep, optional fit, optional periodic bias
- [[ossila-4pp]] - four-point probe sheet resistance and resistivity

## Where they came from

Every experiment here is a port of a single-file, globals-heavy Tkinter
script or notebook. The originals duplicated their logic per instrument
- the worst had whole function families suffixed `_2611` / `_2401`
differing only in command dialect, which is the reason the driver layer
exists at all.

`PORTING_NOTES.md` called this archaeology, and the word is right: in
more than one case the intent had to be recovered from code that could
not run. See [[ossila-4pp]], where the clearest statement of what the
experiment was *for* was a loop that raised `NameError` on its first
iteration.

## The habit that runs through all of them

**A number on a screen is for a person; a number in a calculation is for
a machine; they should not be the same number.** Three separate
originals used a formatted display value as a calculation input - the
Hall notebook at `%.6g`, the 2401 script rounding source levels to four
decimals, the IV scripts reading their own display fields. Each imposed
a precision floor that no error ever reported.
