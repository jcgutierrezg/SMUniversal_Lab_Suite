---
type: experiment
title: "IV sweep"
module: experiments/iv_sweep
origin: "IV_Meas_2611A_-_Basic.py, -_Development.py, -_Long_bias.py"
---

# IV sweep

A voltage or current sweep with an optional straight-line fit, and an
optional periodic mode that repeats the sweep with a bias held between
repetitions.

## Three scripts merged into one

`Basic`, `Development` (identical to a file also called `Improved`) and
`Long_bias` were additive versions of one another, so they became one
experiment with optional panels rather than three subclasses.

The only genuine difference was `alreadyOn`. With `alreadyOn=False`,
`Long_bias`'s `voltage_sweep` is **instrument-identical** to
`Development`'s — the guards wrap only the output ON and OFF writes. It
is a safe superset, so one boolean (`hold_output`) carries the whole
difference.

Two unrelated changes had crept in at the `Basic → Development` step,
and those were the interesting ones: the linear fit had been commented
out in `Long_bias` (it appended `0.0, 0.0, 0.0` instead), and the settle
wait had been rounded to whole seconds. Deviations 7 and 3.

**The bias-mode lock was dropped.** The original refused to change bias
mode without closing the program, which existed only because the
compliance dropdown was *constructed* by the lock handler. It is built
once now and repopulated on mode change, so there is nothing to protect
against. Mode changes are refused while measuring, which is the real
constraint.

## Deviations from the originals

**Deviation 3 — sweep completion is polled, not timed.** The originals
slept `round(points × delay × 1.30)` seconds. `round()` puts the wait on
a whole-second grid, so a 10-point 0.1 s sweep waited 1 s rather than
1.3 s — and `waitcomplete()` was sent with `write()` and never read
back, so it never blocked the host at all. **That sleep was the only
thing between firing the sweep and reading the buffer**, so a short
sweep could read a partly-filled buffer and silently return fewer points
than requested. Now polls until the requested count arrives.

**Deviation 4 — the x-axis is read back, not reconstructed.** The
originals rebuilt it with `np.arange(start, stop, step)`, assuming the
SMU hit every requested level exactly. The instrument is now asked what
it actually sourced, with the old reconstruction as a *logged* fallback.

This is the deviation with the widest reach. Reconstructing an x-axis
means the saved file describes the sweep that was *requested*, and every
instrument-side reason the real levels differ — the 2401's rounding, the
U2722A's range clipping, a compliance clamp — becomes invisible in the
one place you would look for it.

**Deviation 5 — single-point "sweeps" are refused.** The `Vo == Vf`
branch is dropped; one version of it crashed on a float/string
concatenation the moment anyone reached it.

**Deviation 6 — sensing is explicit and defaults to 4-wire.** The
original set `SENSE_REMOTE` inside the periodic path and nowhere else,
so a *single* sweep inherited whatever the instrument was last left in —
4-wire after a periodic run, 2-wire after a reset. **Same sample,
different reading, nothing on screen to say so.**

**Deviation 7 — the linear fit is a toggle.** One original had it
commented out because not every sample is ohmic: a diode returns a
straight-line resistance that is meaningless but looks like a result
once it is in the CSV. Per-sample now, rather than
commented-out-permanently.

## The run lifecycle, and what Stop does

Wave 6a moved this experiment onto the same run lifecycle as the other
three, and added the standby/sweep contract. Two things worth knowing:

**Stop discards all data on a periodic run**, for consistency with the
other experiments. A partial periodic run is not a shorter periodic run
— the repetitions are the measurement.

**A source-function change requiring the output to be interrupted is
allowed, with a warning dialog**, and the measured gap is recorded as
`bias_gap_s`. The gap is a real fact about what happened to the sample,
so it is written down rather than assumed to be negligible.

## Which instrument sweeps, and how

Two of the instruments sweep on their own timebase and the rest are
stepped from the host, and every run records `sweep_kind` for exactly
that reason. A hardware sweep and a software one are not equivalent
measurements: one has spacing set by the instrument's clock, the other
by host and bus latency. See [sweeps](../architecture/_index.md).

The miniSMU is the first instrument where two datasets from the *same
box* can honestly disagree, because its onboard sweep is voltage-only
and a current sweep falls back to software on the same connection.

## The per-run instrument settings

Four settings sit alongside the sweep parameters, and **all of them are
applied on every run rather than once at connect.** That is the whole point:
applied at connect, the instrument keeps whatever the last experiment left it
in, and the same sample reads differently depending on history. That is
[inherited state](../faults/06-inherited-state.md), and Deviation 6 above is
one instance of it that reached real data.

- **Sensing** — an explicit checkbox, applied on every sweep and recorded
  with the data. Defaults to 4-wire, matching how the rigs are wired.
- **Integration time (NPLC)** — how many mains cycles the ADC averages per
  reading. At 1 NPLC the mains hum on the leads completes a whole number of
  cycles inside the window and averages to zero, which is why 1 is the
  default rather than merely a middling value. Shutter speed on a camera:
  longer exposure, less grain, but nothing that moves stays sharp. Shared
  with Van der Pauw and Hall.
- **High-Z output off** — whether "output off" opens the output relay and
  disconnects the sample, or just sources 0 V into it. A light switch versus
  pulling the plug out of the wall. Defaults **off**, because the relay has a
  finite number of operations in it and a periodic run can cycle the output
  hundreds of times.
- **Overvoltage protection** — a hard ceiling on the source, separate from
  compliance. The case it earns its place for is a 4-wire sense lead falling
  off mid-run: the instrument reads 0 V at the sample, decides it is
  undershooting, and winds the output up to compensate.

Each is offered only where the connected driver *declares* it, and greys out
to `n/a` on the rest — the declaration is what the panel reads, which is why
a capability implemented but not declared stays invisible forever. All of
them land in the CSV.

## Working with the results

Each sweep is one row in the results table and one dataset in the plot. Tick
rows and press **Copy ticked → Plot** to overlay them. That is the same
button the other experiments label **Copy ticked → Calc**: a sweep's fit is
per-sweep, so there is no cross-run calculation to copy into, and the plot is
where ticked runs go instead.

## What this means for your data <!-- bench -->

**Old sweeps may contain fewer points than they claim, or the wrong
x-axis.** The originals waited a rounded number of seconds and then read
the buffer regardless, and rebuilt the x-axis from the requested levels
rather than asking what was sourced. A short sweep could return a
partly-filled buffer with no error; a clamped or rounded source level
never showed up at all. Both are fixed, and neither is recoverable from
an old file.

**Check the sensing column on old single sweeps.** The original only set
4-wire inside the periodic path, so a single sweep used whatever the
instrument was last left in. The same sample measured before and after a
periodic run could differ, with nothing recorded to say why.

**The linear fit is optional, and should stay off for anything
non-ohmic.** A diode will happily return a slope with a convincing R².
That number is not a resistance.

**Stop discards a periodic run entirely.** If you need what has been
collected so far, let the current repetition finish rather than
stopping.

## Open questions

- **The dual-SMU variant was deliberately not ported** — see
  [Keithley 2401](../instruments/keithley-2401.md) for what the script actually did and the one
  question that decides whether it is one experiment or two.
