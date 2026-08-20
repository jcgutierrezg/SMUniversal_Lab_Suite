---
type: fault
fault: 23
title: "A ranging command that silently resets the compliance"
---

# A ranging command that silently resets the compliance

## Symptom

A run configures its ranges, sets its compliance, energises, and
measures. The numbers look ordinary. But between the ranging and the
compliance, the limit protecting the sample was **five orders of
magnitude below the value on screen**, and nothing said so.

On the GSM-20H10, measured 2026-08-20:

```
*RST                        SENS:CURR:DC:PROT:LEV?  ->  +1.050000e-04
SOUR:CURR:RANG:AUTO ON      SENS:CURR:DC:PROT:LEV?  ->  +1.000000e-09
```

One command, no error, and a 105 µA compliance became 1 nA. The mirror
case is the same:

```
*RST                        SENS:VOLT:DC:PROT:LEV?  ->  +2.100000e+01
SOUR:VOLT:RANG:AUTO ON      SENS:VOLT:DC:PROT:LEV?  ->  +2.000000e-04
```

21 V became 200 µV. It is a property of the source-autorange command in
both source functions, not a quirk of one quantity, and it is
**repeatable**: setting the compliance back and issuing the command
again collapses it again. It is not a reset artefact.

## Why it is hard to see

The compliance is not refused and no error is raised. The instrument's
error queue is clean across the command that does it.

What surfaces instead is the *next* thing, wearing an unrelated name.
With the compliance sitting at 1 nA, narrowing a measurement range to
100 µA is genuinely "exceeding the compliance range", so the instrument
answers `+824 Cannot exceed compliance range` — on a line that has
nothing wrong with it. In current mode the same collapse produces
`+826 Attempt to exceed power limit`, on 1 µA into 1 V, which is a
microwatt.

Two error codes that appear unrelated, on the wrong commands, for one
cause. Diagnosing this from the error codes alone took several rounds
and produced three wrong mechanisms first — see the fault-note pattern
in [A probe asked where the answer is already known](19-non-discriminating-probe.md), which is what each of
those rounds actually was.

## Why the application currently survives it

`RangePlan.for_sourcing()` emits the source-autorange command on the
axis that means *"I am not sourcing this quantity"*. Sourcing voltage,
that is `SOUR:CURR:RANG:AUTO ON` — a command issued **only to express
indifference**, which destroys the compliance.

Runs recover because [Limit sent before the range that has to hold it](15-limit-before-range.md) puts the
compliance last: the experiment's own `set_current_limit` arrives after
the ranging block and restores the intended value. That recovery is
accidental. It holds because nothing today issues a source-autorange
command *after* `apply_ranges`, which is a property of the present call
order rather than a guarantee.

Anything that reads the compliance in between, or any path that does
not re-send it, runs a sample at 1 nA instead of the value the operator
typed.

## The general shape

A ranging command is expected to change ranging. Where it also changes
a *limit*, the two are coupled in a way no ordering rule alone can fix:

- [Limit sent before the range that has to hold it](15-limit-before-range.md) says set the range first, because on the
  U2722A a compliance sent before its range is clamped down to it.
- Here, setting a range first is what destroys the compliance.

Both are the same underlying problem — the instrument treats range and
limit as one coupled setting while the code treats them as two
independent ones. The ordering rule buys correctness at the end of a
block and guarantees nothing in the middle of it.

## What to check on a new driver

- After every ranging command, **read the compliance back**. Not the
  range: the compliance. The range usually took.
- Ask it where the answer is not already the one you want: set a
  compliance to a distinctive value first, so a reset to the
  instrument's floor is visible rather than looking like the default.
- Check both source functions. The two axes failed identically here,
  but that is a result, not an assumption.
- Where a `RangePlan` axis carries `AUTO` to mean *not sourced*, check
  what the driver actually emits for it. On the U2722A that axis wins a
  shared-knob reconciliation and costs resolution; here it costs the
  compliance. One construct, two unrelated harms, and no reason to
  think the third instrument resembles either.

## Related

- [Limit sent before the range that has to hold it](15-limit-before-range.md) — the ordering rule this
  interacts with, and which is not sufficient on its own.
- [One range list serving two different questions](16-one-range-list-for-two.md) — the earlier round of source and
  measurement ranges being conflated.
- [GW Instek GSM-20H10](../instruments/gwinstek-gsm20h10.md) — where it was measured, with the full
  bench transcript.
