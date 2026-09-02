---
type: fault
fault: 32
title: "A safety margin asserted in a docstring and never computed"
---

# A safety margin asserted in a docstring and never computed

## Symptom

A design decision rests on a number nobody worked out. The number is in
a docstring, stated with the confidence of a calculation, and it is
wrong by orders of magnitude in the direction that ends the discussion.

`core/identity.py`, on the 32-bit random tail of every sample, record,
save and result identifier:

> at a few hundred samples a day that is a collision roughly every ten
> thousand years of laboratory operation

The birthday expectation for `n` draws from `N` values is about
`n²/2N`. These identifiers carry the date, so collisions are per day
and `N` is 2³²:

| draws in one day | expected collisions/day | interval |
|---|---|---|
| 300 | 1.0 × 10⁻⁵ | about **260 years** |
| 3,000 | 1.0 × 10⁻³ | about 2.6 years |
| 10,000 | 1.2 × 10⁻² | about 3 months |

Ten thousand years was out by a factor of forty at the volume quoted,
and the quoted volume was itself the wrong one: a `rec-` identifier is
minted per **run**, not per sample, and a periodic IV sweep commits one
per cycle.

The neighbouring defect had the same shape. Run identifiers were the
experiment name, a controller-local counter and a timestamp with
one-second resolution, and the docstring said the timestamp was there
because the counter restarts with the process. It does — and one second
is not enough to separate two starts, so a restart inside the same
second, or a second bench machine, produced the identical first run
identifier. `run_id` is the join key between stored measurement rows
and the operational event log, so the collision joins one run's
readings to another run's outcome.

## Cause

The claim was plausible, unfalsifiable in practice, and load-bearing.

Plausible, because 1-in-4-billion is a genuinely small number and the
sentence containing it reads like the end of an analysis. Unfalsifiable,
because a collision that happens once a century leaves no evidence
during development and no test can wait for it. Load-bearing, because
`_TAIL = 8` was chosen *by* it.

A wrong number in a comment beside working code is inert. A wrong
number that a constant was set from is the design.

## The rule

**If a constant is justified by arithmetic, the arithmetic goes in the
file and gets checked like anything else.** Write the expression, not
the conclusion — `n²/2N` with the values substituted, so the next
reader can see where the answer comes from and a wrong exponent has
somewhere visible to be wrong.

And when the margin is cheap, do not spend judgement on it. Eight more
hex characters cost nothing an operator will notice — the readable
date-and-name stem is unchanged and still first — and they move the
interval from 260 years to about 10¹². The correct question was never
"is 32 bits enough?" but "what does 64 cost?", and the answer was
nothing.

## How to check

For any width, timeout, retry count or tolerance defended by a
docstring, redo the sum. Two failure modes to look for specifically:

* **The wrong population.** The claim quoted samples per day; the
  constant is used per run, per reading and per save as well.
* **A resolution that is not a guarantee.** A one-second timestamp
  disambiguates events that are not in the same second, which is a
  weaker statement than it looks and reads as a stronger one.

Then ask what the check would be. Uniqueness at these widths cannot be
demonstrated by drawing identifiers — that is a test that passes
whatever the width is, which is
[fault 19](19-non-discriminating-probe.md). What *can* be pinned is the
width itself, on every minter, so a narrower one added later fails
rather than quietly reintroducing the margin nobody computed.
