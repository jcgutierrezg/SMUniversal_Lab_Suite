---
type: guide
title: "Ossila 4-point probe"
---

# Ossila 4-point probe

Sheet resistance, resistivity and conductivity of a film, measured with
the Ossila four-point probe head. Current is driven through the outer two
probes and the voltage read across the inner two. The resistance is the
slope of the line through those readings, and it is then corrected for
the film's thickness and the size of the sample.

![The Ossila 4-point probe window after a demo run and a calculation](../../assets/screens/ossila_4pp/window-light.png#only-light)
![The Ossila 4-point probe window after a demo run and a calculation](../../assets/screens/ossila_4pp/window-dark.png#only-dark)

## What it can run on

Any SMU the suite knows. The electronic load cannot run it and is
refused at Connect. See [Instruments](../instruments/index.md).

## Before you measure: the sample's size

The corrections depend on the sample's dimensions compared with the
probe spacing, which is fixed at 1.27 mm for this head. Enter them in
**Sample geometry**:

- **W** is the **short** side and **L** the **long** side, in mm. Swapped,
  the correction is simply wrong, so a sample with L shorter than W is
  refused.
- **t** is the film thickness, in µm. It sets the thickness correction
  and turns the sheet resistance into a resistivity, so an error here
  scales both.

## Running it

1. **Connect** the SMU (see [Every window](every-window.md#the-usual-order)).
2. **Lower the probe head** onto the film, in the middle of the sample
   and along its long side.
3. **Choose the sweep shape** in **Sweep setup**:
    - **Triangular sweep** (the default) runs from 0 out to the start
      current, across to the stop current and back to 0, and keeps only
      the middle leg. It shows whether a sample that changes as it is
      driven comes back to where it began.
    - **Current list** is the quick spot check: up to eight currents,
      typed with units (`10nA`, `2.5uA`), each read once. Blank boxes are
      skipped.
4. **Set the voltage limit**, the most voltage the instrument may apply
   to push each current. A reading taken at the limit is not the
   sample's.
5. **Press Run.** The readings appear on the plot with the fitted line,
   and a row appears in **Results** with the resistance **R** and the
   corrected sheet resistance **Rs**.
6. **Tick the row, press Copy ticked → Calc, then Calculate** to see the
   corrections in full. Calculate is separate from the run: change W, L
   or t and press it again to recalculate without re-measuring, or type
   in a resistance measured elsewhere.

## Reversals per point

With the default of **1**, each current is read once. A steady offset
from the contacts (a small voltage made where two different metals
meet) then only shifts the fitted line up or down, and leaves the slope,
which is the resistance, alone.

Set it to **2, 4, 6...** when the offset drifts during a run, as when a
probe is warming up, or when the signal is only microvolts. Each current
is then read alternately at +I and −I and the pairs averaged, which
removes the offset point by point and reports its size. A large offset
usually means a warm or poorly seated probe. Odd numbers above 1 are
refused, because they would weight one polarity.

## Reading the result

- **Both correction factors are shown** beside the sheet resistance. A
  surprising factor is more likely a mistyped dimension than a strange
  sample.
- **A sample too small for the correction table** is flagged next to the
  result. The factor used then assumes a much larger sample, so the
  number is an over-estimate.
- **A spread of more than 2% between the currents' resistances** is
  flagged. It usually means self-heating or non-ohmic contacts, which a
  single fitted slope with an excellent R² can hide.

## The panels

<!-- generated:controls ossila_4pp -->
The controls every window has - in the Header strip, Instruments, Run controls, Results and Plot panels - are described once, on [Every window](every-window.md). What follows is this window's own.

### Sample geometry

![The Sample geometry panel](../../assets/screens/ossila_4pp/sample-geometry-light.png#only-light)
![The Sample geometry panel](../../assets/screens/ossila_4pp/sample-geometry-dark.png#only-dark)

The sample's size, which sets the corrections applied to the measured resistance. They are tabulated for this probe head's fixed spacing, so the dimensions are all there is to enter.

| Control | What it does |
|---|---|
| **Short side W (mm)** | The sample's shorter side, in mm. Against the probe spacing it sets the geometry correction; a sample many spacings wide needs almost none. |
| **Long side L (mm)** | The sample's longer side, in mm, measured along the probe row. Enter the same as W for a square sample. |
| **Thickness t (µm)** | The film's thickness, in µm. It sets the thickness correction and turns the sheet resistance into a resistivity, so an error here scales both. |

### Sweep setup

![The Sweep setup panel](../../assets/screens/ossila_4pp/sweep-setup-light.png#only-light)
![The Sweep setup panel](../../assets/screens/ossila_4pp/sweep-setup-dark.png#only-dark)

Which currents to drive through the outer probes; the voltage across the inner two is read at each, and the resistance is the slope of the line through them.

| Control | What it does |
|---|---|
| **Current list** | Measure at each current in the list below - the quick spot check. |
| **Triangular sweep** | Run 0 to Start to Stop and back to 0, keeping only the middle leg. Going out and returning shows whether a hysteretic sample comes back to where it began. |
| **I0 ... I7** | A current to source, with a unit: 10nA, 2.5uA, 1mA. Blank boxes are skipped. |
| **Start current** | Where the recorded middle leg begins, with a unit. Must be negative. |
| **Stop current** | Where the middle leg ends, with a unit. Must be positive. |
| **Points (middle leg)** | Readings along the middle leg, the only part recorded. |
| **Delay (s)** | How long to wait at each current before reading it. |
| **Reversals per point** | Readings per current. With 1, each current is read once: the quickest run, and a steady thermoelectric offset at the contacts only shifts the fitted line up or down - the slope, which is the resistance, is untouched. With 2, 4, 6... each current is read alternately at +I and -I and the pairs are averaged, which removes the offset point by point and reports its size. Worth it when the offset drifts during a run - a probe warming up - or the signal is only microvolts. Each reversal is another reading per current; odd numbers above 1 are refused, because they weight one polarity. |
| **Voltage limit (V)** | Compliance: the most voltage the instrument may apply to push each current. A reading taken at the limit is not the sample's. |
| **Dataset** | A label for this run, shown in the table and the plot legend and saved with it - 'dark', 'after anneal', 'probe 2'. It does not have to be unique. |
| **Sample name** | The sample on the stage. It names the saved files and identifies the sample to every check in the suite, so two different coupons must never share a name - a result from one would be carried over onto the other. |
| **Save path...** | Choose the folder to save into. A subfolder named for today's date is made inside it, so one folder holds a day's work. |
| **Save folder** | Where this session's files are being saved - today's dated folder inside the one chosen with Save path. |

### Results

![The Results panel](../../assets/screens/ossila_4pp/results-light.png#only-light)
![The Results panel](../../assets/screens/ossila_4pp/results-dark.png#only-dark)

The runs of this session, held in memory until saved. Tick a row with the box at its left; the buttons below act on the ticked rows.

Besides the controls below, it has the ones every window has - see [Results](every-window.md#results).

| Control | What it does |
|---|---|
| **Results table** | One row per run, held in memory until you save. R is the slope of the fitted V-I line; Rs is the sheet resistance after the thickness and geometry corrections. |
| **Copy ticked → Calc** | Put the ticked run's resistance into the calculation, at full precision rather than as displayed. Tick exactly one row. |

### Calculation

![The Calculation panel](../../assets/screens/ossila_4pp/calculation-light.png#only-light)
![The Calculation panel](../../assets/screens/ossila_4pp/calculation-dark.png#only-dark)

A measured resistance in, a sheet resistance out, through the published probe corrections. Both factors are shown because they come from the geometry you typed: a suspicious factor is a mistyped dimension before it is a strange sample.

| Control | What it does |
|---|---|
| **Measured R (Ω)** | The resistance to correct, V/I in ohms - put here by Copy ticked -> Calc, or typed. |
| **Calculate** | Apply the thickness and geometry corrections to the resistance in the box, using the dimensions on the left. |
| **Equations...** | Show the correction formula, its symbols, and - once a calculation is fresh - the same formula with your numbers. |
<!-- /generated:controls -->

## What this means for your data

<!-- generated:data-notes experiments/ossila-4pp.md -->
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
<!-- /generated:data-notes -->
