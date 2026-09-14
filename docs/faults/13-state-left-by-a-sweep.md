---
type: fault
fault: 13
title: "State left behind by a sweep"
---

# 13. State left behind by a sweep

## Symptom

The next single reading takes N times as long, and **the next level-set
is read as a sweep endpoint** - the software fallback meant to rescue a
failed sweep returned five points, no error, every one at 0 V.

## Cause

The GSM's staircase sets `TRIG:COUN` to the sweep length and puts the
source in `MODE SWE`. Neither was restored.

## Risk

The recovery path is the one that inherits the damage, so the failure
lands where the code is least exercised and least watched. A plausible
five-point trace at 0 V is data, not an error.

## Detection

After a sweep, read back the trigger count and the source mode and
compare against what they were before it.

## Prevention

**Anything a sweep changes, a sweep must put back**, on every exit path
including the failing one. See
[Sweeps and transports](../architecture/sweeps-and-transports.md).

## Status

Closed on the GSM.

## Evidence

Found by running the finished drivers against real instruments.
Deviation 44.
See [GW Instek GSM-20H10](../instruments/gwinstek-gsm20h10.md).
