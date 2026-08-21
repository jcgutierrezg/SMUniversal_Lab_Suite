---
type: fault
fault: 25
title: "A bound checked on one side only"
---

# A bound checked on one side only

## Symptom

A check confirms a reading has reached a limit, and reports a pass. The
reading is **past** the limit — sometimes far past — and that is the one
observation which proves the limit is not working.

Observed 2026-08-21 on the U2722A. Sourcing 1 µA into an open circuit
with a 1 V compliance:

```
measure() sourcing 1e-06 A into open circuit   (-2.0, -7.32e-06)
compliance reached on open circuit             pass
```

−2.0 V is the range rail, not the compliance. The 1 V limit had been
refused by the instrument for being below 10% of the active range, so
nothing was enforcing it. The check tested `abs(volts) >= limit * 0.8`
and stopped there.

The same shape appeared in the fake transports the offline tests use.
They computed `V = I × R` with no clamp, so the compliance probe's own
test file asserted against **1e6 V measured against a 1 V limit** and
passed, for the same reason: 1e6 clears a lower bound.

## Cause

"Has it reached the limit" and "is the limit in force" are different
questions, and a single `>=` answers only the first. Every value above
the threshold is treated as equally good, including values the limit
should have made impossible.

The floor and the ceiling also fail in opposite directions, which is
why one of them tends to get written and the other forgotten:

| | Missing floor | Missing ceiling |
|---|---|---|
| What it hides | the output never got there | the limit is not being enforced |
| Who notices | the check warns, someone looks | nobody |
| Cost | a wasted trip to the fixture | a measurement bounded by something nobody set |

## The rule

**A check against a limit needs both edges, and the tolerance on each is
a decision to be written down, not a number to be tuned.**

The ceiling cannot be the limit itself, because a healthy clamp
overshoots: the miniSMU settles at 1.023× its limit with the compliance
working correctly. It also cannot be generous, or it stops catching
anything. Both live edges here came from measured hardware —
`COMPLIANCE_FLOOR = 0.8`, `COMPLIANCE_CEILING = 1.25`, with 1.023× and
2.0× as the two real readings they have to separate.

This is the same lesson as [Boundary comparisons need explicit
definitions](15-limit-before-range.md) arriving in a *check* rather than
in a driver: the fix was deciding what the boundary means, not
tightening the arithmetic.

## How to check

For any threshold comparison, ask what the *other* side would look like
and whether the check would notice. If a reading twice the limit passes,
the check is measuring that a number is large, not that a mechanism
works.

And check the fake as well as the code. A bound is untestable against a
model that cannot produce a value on the wrong side of it — the fakes
here could not clamp, so no test in the file could have caught a
compliance that was not in force.
