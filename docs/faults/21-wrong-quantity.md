---
type: fault
fault: 21
title: "Asking about the wrong quantity"
---

# 21. Asking about the wrong quantity

## Symptom

A compliance flag that reads `False` whatever the instrument is doing.
Not a silence - **a wrong reassurance.**

## Cause

The B2901A's `compliance_tripped()` read `:SENS:CURR:PROT:TRIP?`
unconditionally. Compliance is always on the quantity you are *not*
sourcing - source current and a voltage limit clamps you - so that
question is right only when sourcing voltage.

Sourcing current, the current protection is genuinely untripped and the
instrument answered `0` **honestly, to the wrong question.** Van der
Pauw and Hall both source current.

## Risk

A confident `False` from a safety-adjacent query, on every experiment
that sources current.

## Detection

Nothing could have caught it from the outside. The tests set a `tripped`
flag the fake returned regardless of mode, and the checkup only asked
with the output off. It took a probe on a real instrument riding a 1 V
limit into an open circuit -
[A probe asked where the answer is already known](19-non-discriminating-probe.md).

## Prevention

Read `:SOUR:FUNC:MODE?` and ask about the matching protection, rather
than tracking the mode locally. A remembered copy is one reset or one
front-panel press from being wrong, and being wrong here produces a
confident `False`.

## Status

Closed on the B2901A.

## Evidence

Found by running the finished drivers against real instruments.
Deviation 21.
See [Keysight B2901A](../instruments/keysight-b2901a.md).
