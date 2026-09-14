---
type: fault
fault: 3
title: "NAN and overflow sentinels treated as data"
---

# 3. NAN and overflow sentinels treated as data

## Symptom

A least-squares fit that runs to one distant point while still reporting
a healthy R².

## Cause

"No reading" comes back as a *number*: `+9.91e37` for NAN, `+9.9e37` for
over-range. Nothing raises, and nothing in the reply distinguishes it
from a measurement.

## Risk

One of these in a sweep dominates the sum of squares entirely. The fit
is not merely wrong; it is confidently wrong, and its goodness-of-fit
statistic is computed against the same corrupted set.

## Detection

Compare every returned value against the instrument's documented
sentinels before anything numerical touches it. A magnitude near 1e37 in
a milliamp measurement is not a reading.

## Prevention

`BaseSMU.drop_sentinel()`, which replaces **in place** rather than
filtering. Dropping a value by omission shifts every later column left
and promotes the current into the voltage's position.

`tests/test_sentinel_handling.py` discovers drivers from the registry,
so a new driver cannot quietly opt out.

## Status

Closed, fleet-wide and enforced by a registry-driven test.

## Evidence

Found by reading the original scripts. Deviation 17.
See [GW Instek GSM-20H10](../instruments/gwinstek-gsm20h10.md),
[Keithley 2635B](../instruments/keithley-2635b.md).
