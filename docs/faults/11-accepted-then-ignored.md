---
type: fault
fault: 11
title: "A command the instrument accepts and then ignores"
---

# 11. A command the instrument accepts and then ignores

## Symptom

A configuration command that raises nothing, queues no error, reads back
as applied, and has not been applied.

## Cause

The GSM accepts `FORM:ELEM VOLT,CURR`, queues no error, and keeps
sending three columns - **and answers `FORM:ELEM?` with the list it was
given rather than the one it sends.** Neither the command nor the
read-back described reality.

## Risk

Worse than
[A command in the manual but not on the instrument](10-command-not-on-the-instrument.md),
because the error queue stays clean. There is no artefact anywhere that
says the setting did not take, and a reply parsed at the wrong stride
turns currents into voltages.

## Detection

**Where the shape of a reply matters, count what arrived.** What cannot
lie is arithmetic: `read_sweep()` asks how many readings the buffer
holds, counts the numbers that came back, and takes the ratio as the
stride.

## Prevention

Derive the reply layout from the reply itself rather than from the
requested format. A readback is evidence only where the readback itself
has been checked - see
[A setting reported from the command that was sent](33-a-setting-never-read-back.md).

## Status

Closed on the GSM.

## Evidence

Found by running the finished drivers against real instruments.
Deviation 50.
See [GW Instek GSM-20H10](../instruments/gwinstek-gsm20h10.md).
