---
type: fault
fault: 7
title: "Line frequency never set"
---

# 7. Line frequency never set

## Symptom

An integration time that does not reject mains hum as well as its NPLC
setting implies.

## Cause

NPLC only cancels mains hum if the instrument knows the mains period, so
an integration time set without `:SYSTem:LFRequency` is worth less than
it looks.

The 2611A carries the opposite trap: writing `linefreq` explicitly
**disables automatic detection permanently**, in nonvolatile memory.

## Risk

Quiet degradation of every reading, in a way that looks like sample
noise rather than like a configuration error.

## Detection

Read the line-frequency setting back at connect and compare it against
the bench's actual supply.

## Prevention

Set it in the driver's reset block. On the 2611A, read first and write
only on disagreement, so automatic detection is not destroyed on an
instrument that already had it right.

## Status

Closed.

## Evidence

Found by reading the original scripts. Deviation 16.
