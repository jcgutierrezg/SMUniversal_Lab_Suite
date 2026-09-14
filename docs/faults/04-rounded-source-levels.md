---
type: fault
fault: 4
title: "Source levels rounded before sending"
---

# 4. Source levels rounded before sending

## Symptom

**21 requested points collapse to 3 distinct levels while the saved
x-axis still claims 21 evenly spaced values.**

## Cause

`round(V, 4)` quantises to 100 µV. That is invisible at ±1 V and
catastrophic at ±100 µV, where the step between requested points is
smaller than the quantum.

## Risk

The damage is invisible afterwards, because the file records what was
asked for rather than what was sourced. This fault and
[Reconstructed x-axes](09-reconstructed-x-axes.md) compound each other:
one destroys the levels, the other destroys the record of it.

## Detection

Compare the requested level list against the levels actually read back
from the instrument, at the smallest span the experiment supports rather
than at a convenient one.

## Prevention

Send the full-precision level and let the instrument round. **Every
driver rounds *up*** - checked across all of them - because rounding
down would clamp the level. Record what came back, not what went out.

## Status

Closed.

## Evidence

Found by reading the original scripts. Deviation 12, and the 2401 note.
See [Keithley 2401](../instruments/keithley-2401.md).
