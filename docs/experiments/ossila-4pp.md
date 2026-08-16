---
type: experiment
title: "Ossila four-point probe"
module: experiments/ossila_4pp
origin: "Ossila_4PP_2611A.py (+ a _Triangular_sine variant)"
---

# Ossila four-point probe

Sheet resistance, resistivity and conductivity from an in-line
four-point probe head, with thickness and geometry corrections.

**The most heavily reconstructed port in the suite.** The file first
supplied could not run at all, so as much of this experiment came from
reading intent as from reading code.

## The first file supplied was mid-edit

Two independent crashes sat on the Run path:

1. `run_func()` tested `if points <= 30:`, but `points` was a (70, 2)
   geometry meshgrid at module scope, not a sweep-point count. Comparing
   an array raises `ValueError` before any measurement starts.
2. `current_sweep()` opened with a loop calling `set_current()`,
   `measure_voltage()` and `save_data_point()` — none of which was
   defined anywhere in the file. `NameError` on the first iteration.

Both look like one accident: a local name shadowed by a module-level
one, and a block of intended helpers left unwritten.

**That dead loop was also the clearest surviving statement of intent.**
It alternated each current's polarity eight times, which is
thermoelectric-offset cancellation, and it is implemented properly now.
The code that could not run said more about what the experiment was for
than the code that could.

A third inconsistency: the buffer read sliced out "the middle sweep",
which only makes sense against a triangular shape produced by a
generator function that was written and never called. The visible GUI
sourced eight flat current entries with no leg structure, so that slice
would have taken the wrong region. **Both shapes are offered now, chosen
explicitly, and the slicing follows the choice.**

## The later versions, reviewed

- The **triangular/sine variant** is the one with a working fit, and it
  confirms the middle-leg slice: its `start_index = floor(points/2) + 1`
  matches this port's `len(down_leg)` exactly, for odd and even point
  counts. It still reconstructs the x-axis with `np.arange` and rounds
  resistance to three decimals before storing — both avoided here.
- The **revised list version** restructured the measurement so each
  current became its own block of eight alternating readings and its own
  dataset. Its `regresion_mem` is still never appended to, so its plot
  and calculate paths raise `IndexError`: it collects raw data only.
  **If anyone is still running it, their Plot and Calculate buttons do
  not work.**
- Its per-block fit is **mathematically identical** to the reversal
  averaging used here — verified numerically, not assumed. Both recover
  R exactly and return the offset as the intercept.
- `arr_flag`, `sample_number` and `time_between_avg` in the sine variant
  are vestigial: declared global, never used.

**What was worth taking was its output shape.** One fit per current
shows whether R depends on drive level; a single slope across all
currents hides that inside its R². Each reading now carries
`resistance_at_point_ohm`, and a spread above 2% logs a warning about
self-heating or non-ohmic contacts.

## Deviations from the original

**Deviation 8 — the thickness correction no longer raises at the top of
its table.** The original's `else` branch printed a message and left the
factor unassigned, so the next line raised `NameError` for any sample
with t/s > 2. The top of the table is held instead, with a warning next
to the result.

**Deviation 9 — out-of-table geometry is flagged, not silent.** The
original substituted 1.0 without comment. 1.0 means "effectively
infinite sample", which for a sample too *small* for the table is
backwards — it over-reports sheet resistance. Same substitution, but it
says so now.

**Deviation 10 — resistivity is in Ω·m, not Ω·mm.** The original
computed `Rs × t` with t in millimetres and labelled the result `mΩ/m`,
which is neither what it computed nor a unit of resistivity. Its
conductivity was right, because the `×1000` converted the same figure to
S/m.

## Probe spacing is fixed at 1.27 mm

Not a parameter that happens to have a default. Both correction tables
are indexed by t/s and W/s, so the spacing is **baked into them**: a
different probe head needs different tables, not a different number. It
is shown on screen as a note for exactly that reason.

## What this means for your data <!-- bench -->

**Old saved files differ by 1000× on the resistivity column.** The
original computed sheet resistance times a thickness in millimetres and
labelled it `mΩ/m`. Sheet resistance and conductivity in those files are
unchanged and correct; only resistivity is affected. If you have
published or plotted a resistivity from an old 4PP file, check the
factor.

**A sample too small for the geometry table used to be silently
over-reported.** The original substituted a correction factor of 1.0,
which means "effectively infinite sample" — the opposite of the truth
for a small coupon. The substitution still happens, but it is flagged
next to the result now.

**A sample thicker than twice the probe spacing used to crash.** If a
run never produced a result on a thick sample, that is why.

**Watch the per-current resistance spread.** Each reading carries its
own `resistance_at_point_ohm`, and a spread above 2% is flagged. That
usually means self-heating or non-ohmic contacts, and it is invisible in
a single slope fitted across all currents — the R² can look excellent
while the sample's resistance is drifting with drive level.

**The probe spacing is not adjustable**, because the correction tables
are indexed in units of it. A different probe head is a different set of
tables.

## Open questions

None recorded. The reconstruction questions were closed by the later
script versions, and the mathematical equivalence of the two fitting
approaches was checked numerically rather than argued.
