---
type: fault
fault: 2
title: "Concurrent measurement never enabled"
---

# 2. Concurrent measurement never enabled

## Symptom

Source 1 V and the voltage column reads back exactly 1.000000 V - the
number that was asked for, not the number across the sample.

## Cause

With `[:SENSe]:FUNCtion:CONCurrent` off, only one function is measured
and the other field of the reply is filled from the **source setting**.

## Risk

Lead and contact drops vanish, so **a 4-wire rig silently returns a
2-wire measurement.** The data has the right shape, the right columns
and the wrong physics, and nothing in the file says which.

## Detection

Source into a known resistance and check whether the measured voltage is
*exactly* the commanded one. An exact match to six figures is the tell:
a real measurement across a real fixture does not land on the setpoint.

## Prevention

Enable concurrent measurement in the driver's configuration block, on
every run, and read back both columns.

## Status

Closed on the GSM-20H10.

## Evidence

Found by reading the original scripts. Deviation 14.
See [GW Instek GSM-20H10](../instruments/gwinstek-gsm20h10.md).
