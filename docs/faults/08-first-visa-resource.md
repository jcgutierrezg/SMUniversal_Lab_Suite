---
type: fault
fault: 8
title: "`rm.open_resource(instruments[0])`"
---

# 8. `rm.open_resource(instruments[0])`

## Symptom

Results that are inexplicable rather than wrong-looking: the right
procedure, run against a different instrument from the one intended.

## Cause

Connecting to whatever VISA happens to list first. In a room with
several SMUs the ordering is not stable and the choice is a coin toss.

## Risk

**It explains otherwise-inexplicable historical results.** A file
records the experiment, not which box on the bench answered.

## Detection

Read the address out of the connection, not out of the enumeration
order, and put it in the file.

## Prevention

The connection panel: the operator picks the address, and the run
records it. No code path opens "the first one".

## Status

Closed. Retained here because it is worth knowing when old data looks
wrong.

## Evidence

Found by reading the original scripts.
