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

## What the envelope answers

Not "how long does a reading take" — the per-reading figure in
[choosing an SMU](choosing-an-smu.md) already says that. It answers the
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

Only that instrument refuses such a level today. The pass halves the
commanded level down from the bias and asks, at each step, whether
`+X` and `-X` still read differently. Where they stop differing is the
floor for that instrument on that range.

**Read the crossing against the envelope's noise before believing it.**
Below the reading noise the sign is undetectable whatever the source is
doing, so a crossing there is a statement about the measurement rather
than the converter. If the two coincide, the answer is "needs quieter
integration", not "here is the count".

## Safety

Both phases energise the fixture. The bias is 100 µA with a 2 V
compliance, so into 10 k the worst case on any range is 200 µA and
0.4 mW — bounded by the compliance rather than by the commanded level,
which is what makes the sub-count phase safe even though it deliberately
drives levels the instrument may not honour.

The output goes off between phases, on any exception, and on Ctrl-C.
Nothing runs without an explicit `--load`.

Paste both outputs back whole rather than summarising them. What gets
recorded in the instrument note is what was measured.
