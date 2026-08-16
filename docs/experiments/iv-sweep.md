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
by host and bus latency. See [[../architecture/_index|sweeps]].

The miniSMU is the first instrument where two datasets from the *same
box* can honestly disagree, because its onboard sweep is voltage-only
and a current sweep falls back to software on the same connection.

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
  [[keithley-2401]] for what the script actually did and the one
  question that decides whether it is one experiment or two.
