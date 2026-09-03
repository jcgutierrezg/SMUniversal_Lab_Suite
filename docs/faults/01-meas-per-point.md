---
type: fault
fault: 1
title: "`MEAS?` used per point"
---

# 1. `MEAS?` used per point

## Symptom

A sweep whose ranging and compliance are configured once, at the top,
and then quietly are not. On the GSM-20H10 the output also comes on by
itself.

## Cause

On the 2400 family and its relatives, `MEAS?` is `:CONFigure` followed
by `:READ?`. It resets ranging and compliance to `*RST` values on
**every point**, undoing whatever was set beforehand.

Not universal. The B2901A's `:MEAS?` is documented as measuring with the
conditions already set, and is used deliberately there - partly because
`:READ` and `:INIT` are the two commands that trigger its automatic
output-on.

## Risk

Every point after the first is taken under conditions nobody chose, and
the file records the conditions that were requested. The compliance
protecting the sample is the reset default rather than the operator's.

## Detection

Read the command reference for what the composite query expands to,
rather than for what it returns. Then set a distinctive compliance,
issue one `MEAS?`, and read the compliance back.

## Prevention

Use `:READ?` against the configuration already in place. Reserve the
composite form for instruments whose manual states it measures under
existing conditions, and say so in the driver.

## Status

Closed. All drivers use `:READ?` except the B2901A, deliberately.

## Evidence

Found by reading the original scripts, in the 2401 original and again in
the 20H10 one. Deviation 11.
See [GW Instek GSM-20H10](../instruments/gwinstek-gsm20h10.md),
[Keithley 2401](../instruments/keithley-2401.md),
[Keysight B2901A](../instruments/keysight-b2901a.md).
