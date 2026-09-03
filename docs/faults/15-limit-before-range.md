---
type: fault
fault: 15
title: "A limit sent before the range that has to hold it"
---

# 15. A limit sent before the range that has to hold it

## Symptom

A sweep that runs with a compliance a hundred times lower than the one
on screen. The limit was accepted and no error was raised.

## Cause

On the U2722A a compliance value is **clamped to the range active when
it arrives**, and `*RST` leaves the smallest range selected.

## Risk

The sample is protected by a limit nobody chose, and the run is quietly
clamped rather than held where the operator asked. The file records the
requested compliance.

## Detection

Set a distinctive compliance, then read it back *after* the ranging
block rather than after the write. Checked and found absent on the
2635B, whose `source.limitY` page states the SMU always autoranges for
the limit setting.

## Prevention

Widen the range first. This is now a formal requirement of
[the ranging contract](../architecture/ranging.md) rather than a habit.

The rule is necessary and not sufficient: on the GSM-20H10 setting a
range is itself what destroys the compliance -
[A ranging command that silently resets the compliance](23-autorange-resets-compliance.md).

## Status

Closed on the U2722A. The coupling it is one half of is open in general;
see fault 23.

## Evidence

Found by running the finished drivers against real instruments.
Deviation 21.
See [Keysight U2722A](../instruments/keysight-u2722a.md).
