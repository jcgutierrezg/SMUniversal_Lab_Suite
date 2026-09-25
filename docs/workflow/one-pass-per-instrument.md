---
type: bench
title: "One pass per instrument"
---

# One pass per instrument

Everything the fleet currently owes, in one sitting per instrument, on
one fixture. Doing these separately costs three sessions and gives
answers that cannot be compared, because the load and the bias differ
between them.

## What you need

A resistor across the terminals, its value measured and written down.
The bench standard is a 10 k; the one in use measures **9958 Ω**.

That value is measured with one of these instruments, so it is not a
traceable reference — using it to judge the same instruments is
circular. Nothing here depends on it being right. The noise figures are
relative, and the sub-count test keys off whether the commanded sign
comes through, which needs no calibration at all.

## The order, and why

```powershell
uv run tools/smu_checkup.py --address <addr> --trace
uv run tools/bench_envelope.py --address <addr> --load 9958
```

The checkup first, because it is the one that must pass before anything
else means anything, and because it leaves the commissioning stamp the
whole fleet is currently owed. Copy `last_bench`, `bench_code` and
`bench_result` from its report header into the instrument's note and
rebuild the generated pages.

Then the envelope pass, on the same connection and the same fixture.

`tools/bench_readback.py` is separate and needs someone at the front
panel for the ranges; the compliance checks at its end run unattended.
Instruments with no front panel have nothing for its range legs to do.
See [the tools](../architecture/tools.md).

## What the envelope answers

Not "how long does a reading take" — the per-reading figure in
[choosing an SMU](../guide/instruments/index.md) already says that. It answers the
question that one cannot:

> After the first read, how fast can I poll while keeping the noise I
> can live with?

One row per rung of the instrument's NPLC ladder, each with the achieved
sample rate and the relative standard deviation of the readings. The
useful output is the shape: where the curve turns over is where more
integration stops buying quiet.

The ladders differ enormously. The B2901A spans 4×10⁻⁴ to 100 PLC. The
**U2722A's floor is 1 PLC**, which at 50 Hz is 20 ms of integration
before any overhead — so it cannot poll faster than about 50 Hz however
much noise you are willing to accept. That is a ceiling, not a
trade-off.

## What the sub-count pass answers

Below one converter count there is no signal, only offset residue, and
its polarity is not commanded. On the U2722A `-1 µA` and `+1 µA`
produced the same output, and during a commissioning run the residue
pointed the wrong way and walked the output to the range rail.

The pass halves the commanded level down from the bias and asks, at
each step, whether `+X` and `-X` still read differently — on the current
axis and then the voltage axis. Where they stop is the floor for that
instrument on that range.

**On most instruments that floor is the output's zero offset, not a
converter count.** The legs straddle zero exactly while the level is
larger than the offset, and each row records the offset as the midpoint
of its two legs. The offset drifts between sessions, so one day's
crossing is not a property of the model; and it is only the part of the
offset the instrument's own readings can see. A halving walk makes every
level the range over a power of two, so a crossing always "matches" some
count — that match is not evidence about the converter.

### What the 2026-08-28 run changed

Run across the bench on 2026-08-28, the first version of this pass
produced one usable sub-count result. <!-- lint-ok --> Four instruments
failed their control leg, one crashed, and the GSM reported twenty-one
consecutive "sign follows" rows down to 95 pA on readings that never
moved. Every one of those faults was in the tool:

- it pinned the **widest** range, so the 100 uA control was itself
  sub-count — the condition the control exists to rule out. It now pins
  the range that suits the bias. The compliance settles this
  independently: 2 V into 10 k caps the current at 200 uA, so no level
  on a wide range could be honoured anyway.
- it asked for a 1 A range, which the miniSMU's 180 mA ladder refuses
  outright.
- its verdict required only that the readings separate by more than the
  commanded level. That threshold shrinks as the level does, so a fixed
  offset clears it more easily the smaller the request gets. It now
  requires the separation to be *about* twice the level, bounded from
  both sides.
- every instrument reported `RSD 0.000%` at its upper rungs. That is
  quantisation, not quiet: all twenty readings land on one converter
  code. Those rungs are now named as quantised rather than reported as
  perfect.

### Two more, from the second run

**Both legs must land on opposite sides of zero.** Commanding a negative
level and reading positive is not a commanded sign, whatever the
separation. The GSM tracked its command beautifully down to about 1.5 nA
and then froze at +1.28 nA / +0.40 nA - both positive - and four more
rows were still reported as following, because a fixed offset kept
sitting inside a window that shrank with the level. The floor came out
nearly ten times too low.

**The envelope pins the same range as the sub-count phase.** It used to
put the level onto whatever range `reset()` left active. The B2901A then
read a mean of 4.3e-7 A against a commanded 1e-4 at every rung - and the
run before that reported `RSD 0.000%` for the same instrument, with no
mean column to contradict it.

**A fixed offset and a real signal are indistinguishable at one
level.** The GSM's +144 uA against +20 uA is a plausible response to a
commanded +/-100 uA, and the guard does not catch it at the control. It
catches it within a few halvings, when the expected separation has
shrunk past the offset and the readings have not moved. Read the whole
column, not the verdict on one row.

**Read the crossing against the envelope's noise before believing it.**
Below the reading noise the sign is undetectable whatever the source is
doing, so a crossing there is a statement about the measurement rather
than the converter. If the two coincide, the answer is "needs quieter
integration", not "here is the count".

### What the 2026-09-11 run changed

The first run with a voltage axis, across the fleet. Every fault it
found was in the tool again:

- **the walk ran at the envelope's last NPLC rung** — the slowest, up to
  10 s a reading. It now sets 1 PLC itself.
- **it read straight after each step.** At 1 PLC the U2722A had covered
  71% of the step, and the separation window passed it. Readings after
  every step are now discarded, as many as the control level shows the
  output needs, and the control must read within 5% of the command.
- **a level whose halving changed nothing still passed.** The 2401 read
  the same output at 3.05 nA as at 6.1 nA, on two separate days, and the
  lower level was reported as the floor. Such a level now fails.
- **the second axis inherited the first axis's ranges.** The miniSMU's
  1 V control came out at 10 mV on a 1 µA range, and the 2635B's current
  measurement autoranged into its pA decades until a reading timed out.
  Each axis now sets every range through `RangePlan.for_sourcing`.

The midpoint is the offset only where it is flat across rows. On the
miniSMU it grows with the level at the top — a small gain difference
between polarities — so read the offset from the low rows.

## Safety

Both phases energise the fixture. The current axis biases at 100 µA
and the voltage axis at 1 V, each with a compliance of twice what the
bias reaches on the measured load — about 2 V or 200 µA into 10 k, so
0.4 mW at worst on any range. Bounded by the compliance rather than by
the commanded level, which is what makes the sub-count phase safe even
though it deliberately drives levels the instrument may not honour.

The output goes off between phases, on any exception, and on Ctrl-C.
Nothing runs without an explicit `--load`.

Paste both outputs back whole rather than summarising them. What gets
recorded in the instrument note is what was measured.
