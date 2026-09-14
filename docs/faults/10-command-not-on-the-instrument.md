---
type: fault
fault: 10
title: "A command in the manual but not on the instrument"
---

# 10. A command in the manual but not on the instrument

## Symptom

A setting that never takes, with no error and no failed call.

## Cause

SCPI instruments log unrecognised commands to an error queue and carry
on. Nothing raises, and **the previous setting stays in force.**

## Risk

The code believes it configured the instrument. The instrument is in
whatever state it was in before. Every reading afterwards is taken under
conditions nobody chose and the file records the requested ones.

## Detection

Where a spelling is inferred rather than documented, send it and then
read `SYST:ERR?`. See the GSM's `_probe_sweep_support()`.

## Prevention

Probe once at connect and cache what the instrument accepted, rather
than assuming the manual. A guessed *query* is worse than a guessed
command - it is never answered, times out, and latches the transport -
so an unconfirmed query is not sent at all.

## Status

Closed on the GSM. The general rule is
[A setting reported from the command that was sent](33-a-setting-never-read-back.md).

## Evidence

Found by reading the original scripts. Confirmed on the bench: `:ABOR`
exists on the 2400 family and is rejected by the GSM with
`-113 Undefined header`.
