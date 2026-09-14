---
type: fault
fault: 5
title: "Sweep completion slept rather than polled"
---

# 5. Sweep completion slept rather than polled

## Symptom

A sweep that **silently returns fewer points than requested**, on short
sweeps only.

## Cause

`sleep(round(points * delay * 1.3))` reads the buffer after a guessed
interval rather than after the instrument says it is finished.

Two details made it worse than the formula suggests. `round()` puts the
wait on a whole-second grid, so a 10-point 0.1 s sweep waited 1 s rather
than 1.3 s. And the original's `waitcomplete()` was sent with `write()`
and never read back, so it never blocked the host at all - that sleep
was the *only* thing between firing the sweep and reading the buffer.

## Risk

A partly-filled buffer reads as a complete short sweep. Nothing raises,
and the fit is computed over whatever arrived.

## Detection

Ask the instrument how many readings its buffer holds and compare
against what was requested. A timing assumption cannot be checked by
running it once on the machine it was tuned on.

## Prevention

Poll the instrument's own count, with a wall-clock deadline as a
liveness bound rather than as a schedule - see
[A test that measured the machine instead of the code](37-a-test-that-measured-the-machine.md).

## Status

Closed.

## Evidence

Found by reading the original scripts. Deviation 3.
See [IV sweep](../experiments/iv-sweep.md).
