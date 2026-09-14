---
type: fault
fault: 14
title: "Output state assumed across a source-function change"
---

# 14. Output state assumed across a source-function change

## Symptom

`:READ?` **blocks forever with no error, looking exactly like a dead
instrument.**

## Cause

The 2400 family drops the output when the source function changes. With
auto output-off disabled - which these drivers do, so a sweep holds its
level - the instrument is then asked to measure with the output off.

## Risk

A hang has no diagnostic. On a bench it reads as a broken cable or a
broken instrument, and the actual cause is one line of command ordering.

## Detection

Read the output state back after every source-function change rather
than tracking it locally.

## Prevention

Call `output_on()` *after* `set_source_function()`. Documented on
`BaseSMU.set_source_function` for every driver.

## Status

Closed, in the experiments and in `tools/smu_checkup.py`.

## Evidence

Found by running the finished drivers against real instruments.
Deviation 48.

Worth noting where it was found: the experiments always got this right;
`tools/smu_checkup.py` did not. See
[A diagnostic tool with the fault it diagnoses](20-a-tool-with-the-fault-it-diagnoses.md).
See [Keithley 2401](../instruments/keithley-2401.md).
