---
type: fault
fault: 9
title: "Reconstructed x-axes"
---

# 9. Reconstructed x-axes

## Symptom

A saved file that describes the sweep that was *requested* rather than
the one that happened, and looks identical to one that does not.

## Cause

`np.arange(start, stop, step)` assumes the instrument hit every
requested level exactly.

## Risk

This is the fault with the widest reach. Every instrument-side reason
the real levels differ - rounding, range clipping, a compliance clamp -
becomes invisible in the one place anybody would look for it. It hides
[Source levels rounded before sending](04-rounded-source-levels.md) and
every fault of that shape.

## Detection

Compare the saved x-axis against a readback of what was sourced. If the
file's x column is exactly arithmetic, it was computed rather than
measured.

## Prevention

Read back what the instrument actually sourced and store that. The
software sweep reads back every level it sources for this reason.

## Status

Closed.

## Evidence

Found by reading the original scripts. Deviation 4.
See [IV sweep](../experiments/iv-sweep.md).
