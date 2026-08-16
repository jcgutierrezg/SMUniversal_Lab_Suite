---
type: experiment
title: "Van der Pauw"
module: experiments/vanderpauw
origin: "VdP_v*.ipynb"
supplies: sheet_resistance
---

# Van der Pauw

Sheet resistance of an arbitrarily-shaped thin film from eight
four-terminal readings. Ported from a Jupyter notebook that existed in
several versions.

## What it measures, and why eight readings

Van der Pauw's theorem needs two resistances — one "horizontal", one
"vertical" — measured on a sample with four peripheral contacts. Each is
measured in both current polarities and both contact orderings, so the
eight readings collapse to two averaged resistances with the
thermoelectric offsets cancelled.

The offsets are not a rounding detail. A junction between two dissimilar
metals on a stage that is being heated produces a DC voltage that has
nothing to do with the sample, and it is often comparable to the signal.
Reversing the current reverses the sample's contribution and leaves the
offset alone, so the difference isolates one and the average isolates
the other.

## The solver

`solve_vdp_sheet_resistance(Rh, Rv)` solves the transcendental Van der
Pauw equation numerically — there is no closed form except when
`Rh == Rv`. Guarded by `tests/golden/vdp_sheet_resistance.json`, so a
change to the solver that alters an answer has to be a deliberate act
with a regenerated golden file.

## Deviations from the original

**Deviation 1 — delay units corrected.** The notebook mixed seconds and
milliseconds in the settle delay. Nothing errored; the settle was simply
a thousand times shorter or longer than intended depending on the path.

**Deviation 2 — voltage precision raised from 6 to 9 significant
figures.** This one matters more here than it looks, and matters most
next door in [[hall]]. See the shared habit below.

## A habit the originals had

**Precision floors.** The notebooks wrote measured voltages at `%.6g`
into both the results table and the calculation boxes — that is, the
displayed value *was* the calculation input. Six significant figures on
a raw reading is fine for a resistance recovered from a slope. It is not
fine for a quantity recovered by subtracting two nearly-equal numbers,
which is what both this experiment's offset cancellation and Hall's
voltage extraction do. `VOLTAGE_FIGURES = 9` now.

The same class of mistake appears in the 2401's four-decimal source
rounding and in the IV scripts using six-figure display values as
calculation inputs. Three separate scripts, one idea: *a number on a
screen is for a person, and a number in a calculation is for a machine,
and they should not be the same number.*

**Background `:READ?` pollers.** Both notebooks ran a thread issuing
`:READ?` while the measurement loop was also issuing `:READ?`, throwing
the result away. Not corrupting — the socket lock made each read atomic
— but it doubled the instrument's work and made point-to-point timing
unpredictable. Dropped from every port.

## What it supplies downstream

`SUMMARY_QUANTITIES` declares `sheet_resistance`, which is what makes
this experiment a *provider*: `LabApp.provider_of("sheet_resistance")`
finds it, and [[hall]] consumes it in memory. See [[hall#The handoff]]
for what that changed and what it cost.

The declaration is the seam. Nothing is keyed on the experiment's class
name or on a string typed in two places — an experiment that supplies a
quantity says so once, and the GUI and the file output follow.

## What this means for your data <!-- bench -->

**Sheet resistance is computed from eight readings, not two.** If a run
reports fewer, something interrupted it and the result is refused rather
than computed from what arrived.

**Voltages are now recorded to nine significant figures**, not six.
Results from the original notebook carry a precision floor of about 0.1%
on anything derived from a difference of two readings. Sheet resistance
itself is largely unaffected; the Hall numbers taken alongside it are
not.

**A sheet resistance can only be handed to a Hall run in the same
session.** That is deliberate — see [[hall]].

## Open questions

- **One sample label covering two physical coupons defeats the mixing
  guard entirely.** The label typed on the session strip is what
  `core/identity.py` mints a sample identifier from, so two coupons
  measured under one name are one sample as far as every check in the
  suite is concerned — and a sheet resistance from the first carries
  silently onto the second with every number looking right.
  `SampleRegistry.new(label)` exists for exactly this and nothing calls
  it. The decision was that bench labelling practice is disciplined
  enough; that is a judgement about people, not about software, and it
  is the kind that stops being true quietly. The fix, if a result is
  ever suspected of belonging to the wrong coupon, is a "New sample"
  button calling `samples.new()` — not more wording.
