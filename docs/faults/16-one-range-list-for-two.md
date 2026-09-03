---
type: fault
fault: 16
title: "One range list standing in for two"
---

# 16. One range list standing in for two

## Symptom

A derived resistance computed from a current that was never sourced. No
error, plausible number.

## Cause

A driver declares `current_ranges` and everything assumes source ranges
and measure ranges are the same set. **On the 2635B they are not:** it
measures to 100 pA and sources only to 1 nA.

Offering a measure-only range as a sourced level gets it clamped to the
nearest sourceable one.

## Risk

The clamp is silent and the arithmetic downstream is exact. Nothing in
the file distinguishes a level that was sourced from one that was
requested and clamped.

## Detection

Check both directions in the manual before declaring `LIMITS`. Ask
separately: what can this instrument *source*, and what can it
*measure*.

## Prevention

Separate source and measure axes throughout
[the ranging contract](../architecture/ranging.md). `RangePlan` carries
four axes rather than two.

## Status

Closed. Decision D15.

## Evidence

Found while writing a driver from a manual. The 2635B was the first
instrument here where the two differ, which is why the conflation went
unnoticed across every earlier driver.
See [Keithley 2635B](../instruments/keithley-2635b.md), and
[Undalogic miniSMU MS01](../instruments/undalogic-minismu.md) for the
same field holding something that is not a range list at all.
