---
type: fault
fault: 17
title: "A default that is never sent is a default nobody chose"
---

# 17. A default that is never sent is a default nobody chose

## Symptom

Slightly-wrong data rather than an error. `format.asciiprecision` resets
to 6 significant figures on every 2600B - below what the Hall
measurement needs - and **no driver in this suite had ever set it.**

## Cause

State inherited from the factory. A reset default that happens to be
acceptable is indistinguishable from a value that was chosen, right up
until a firmware revision moves it.

Distinct from
[Instrument state inherited rather than set](06-inherited-state.md),
which is state inherited from a previous *run*.

## Risk

Truncated precision propagates into every derived quantity and into the
saved file, where it looks like measurement noise.

## Detection

For each setting the measurement depends on, ask what the instrument's
reset default is and whether anything sends it. A setting nobody sends
is a setting nobody chose.

## Prevention

Where a reset default is load-bearing, send it explicitly **even when it
already has the value you want**, because firmware revisions move
defaults. Several writes in the 2635B's reset are no-ops against current
firmware and are kept for exactly that reason.

## Status

Closed. Decision D14.

## Evidence

Found while writing a driver from a manual.
See [Keithley 2611A](../instruments/keithley-2611a.md),
[Keithley 2635B](../instruments/keithley-2635b.md).
