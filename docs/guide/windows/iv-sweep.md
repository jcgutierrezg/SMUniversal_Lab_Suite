---
type: guide
title: "IV sweep"
---

# IV sweep

Steps a voltage (or a current) across the sample from a start level to a
stop level and measures the other quantity at each step. With the linear
fit on, each sweep also gives the resistance of an ohmic sample. A
periodic mode repeats the sweep on a schedule, holding the sample at a
bias or leaving it idle in between, for stress and ageing runs.

![The IV sweep window after one demo sweep](../../assets/screens/iv_sweep/window-light.png#only-light)
![The IV sweep window after one demo sweep](../../assets/screens/iv_sweep/window-dark.png#only-dark)

## What it can run on

Every SMU the suite knows, and the Multicomp electronic load, which
sinks current rather than sourcing it. What differs between them is
range and speed: the maximum voltage and current, whether the sweep runs
on the instrument's own clock or is stepped from the PC, and whether
over-voltage protection and 2-wire sensing are offered. A setting the
connected instrument cannot do reads **n/a** and is greyed out. See
[Instruments](../instruments/index.md) for the numbers.

## Wiring

**4-wire is the default**, and how the rigs are wired: two leads carry
the current, and a separate pair senses the voltage right at the sample,
so the resistance of the leads and contacts is not added to the result.
If the sample only has two leads on it, untick **4-wire (remote sense)**.
The measurement then includes the leads, which matters below about
100 Ω.

## Running a sweep

1. **Connect** the instrument in the **Instruments** panel (see
   [Every window](every-window.md#the-usual-order)).
2. **Choose what to source** in **Sweep mode**. *Source voltage, measure
   current* is the usual one.
3. **Set the compliance before anything else.** It is the most current
   (or voltage) the instrument will push through the sample, and the
   protection for it. Set it above the largest current you expect, and
   below what the sample survives.
4. **Set the sweep** in **Sweep setup**: start, stop, number of points,
   and the delay at each point. A stop below the start sweeps downwards.
5. **Give the run a dataset label** - *dark*, *after anneal* - so it can be
   told apart in the table and the plot, and check the **Sample name**.
6. **Press Run.** The output lamp goes green, the progress bar fills, and
   a row appears in **Results** when the sweep is done. The plot shows it
   with the fit line if **Linear fit** is ticked.
7. **Save** with **Save snapshot → CSV** once you are happy with what is
   in the table.

Settings are taken when you press Run. Changing a box during a sweep does
not affect that sweep.

## Reading the result

A clean ohmic sample gives a straight line through the origin, with its
resistance **R** and an **R²** close to 1 in the table.

- **A curve that goes flat at the top and bottom** has hit the
  compliance: the instrument stopped at its current limit, and the flat
  part is the limit, not the sample. Raise the compliance, or narrow the
  sweep.
- **A fit that looks convincing on a non-ohmic sample** is still not a
  resistance. A diode will return a slope and a high R². Untick
  **Linear fit** for anything that is not a resistor.
- **Noisy low currents:** raise the integration (NPLC). 1 NPLC averages
  over one mains cycle, which also cancels mains hum.

## Periodic runs

For watching a sample change under stress. **Run periodic** makes
**Cycles** sweeps, one every **Cycle period**. Between sweeps the sample
is held as **Between sweeps** says: idle with the output off, at a bias
voltage, or at a bias current (**Bias level**). Each sweep becomes its
own row in the table.

**Stop discards a periodic run entirely.** The repetitions are the
measurement, so a partial run is not kept. If you want what has been
collected so far, let the current cycle finish instead.

## The panels

<!-- generated:controls iv_sweep -->
The controls every window has - in the Header strip, Instruments, Run controls, Results and Plot panels - are described once, on [Every window](every-window.md). What follows is this window's own.

### Sweep mode

![The Sweep mode panel](../../assets/screens/iv_sweep/sweep-mode-light.png#only-light)
![The Sweep mode panel](../../assets/screens/iv_sweep/sweep-mode-dark.png#only-dark)

What the sweep drives and what protects the sample. All of it is sent to the instrument at the start of every sweep, so what is shown here is what the run used - and it is saved with it.

| Control | What it does |
|---|---|
| **Source voltage, measure current** | Hold a voltage on the sample and measure the current through it. |
| **Source current, measure voltage** | Drive a current through the sample and measure the voltage across it. |
| **Current compliance (A)** | The limit on the quantity you are not sourcing: the most current the instrument may drive when sourcing voltage, the most voltage when sourcing current. It protects the sample, and the measurement range follows it. Type any value; the list is only a starting point. |
| **Integration (NPLC)** | Integration time, in mains cycles. 1 NPLC averages over a whole cycle and rejects mains hum; 0.01 is far faster and visibly noisier. Two runs at different NPLC are not comparable, so it is recorded with the data. |
| **Overvoltage protect** | Overvoltage protection: a hard ceiling on the output, separate from compliance. It matters in 4-wire work, where a sense lead falling off makes the instrument wind its output up. Greyed on instruments without it. |
| **4-wire (remote sense)** | Measure the voltage on separate sense leads at the sample, so the resistance of the source leads and contacts drops out. Untick only for a 2-wire hookup. Greyed, and pinned to the wiring, on instruments whose sense terminals are strapped. |
| **High-Z output off** | What the instrument does to the sample between runs: open the relay (high-Z) or hold it at zero volts. High-Z leaves nothing driving the film. Greyed on instruments without the choice. |
| **Linear fit (ohmic samples only)** | Fit a straight line through each sweep and report the resistance it gives. Untick for diodes and anything non-ohmic: a line through a curve still gives a number, and it would be saved as a result. The raw points are kept either way. |

### Sweep setup

![The Sweep setup panel](../../assets/screens/iv_sweep/sweep-setup-light.png#only-light)
![The Sweep setup panel](../../assets/screens/iv_sweep/sweep-setup-dark.png#only-dark)

The sweep itself: from Start to Stop in the given number of points, waiting Delay at each. The labels follow the mode - volts when sourcing voltage, amps when sourcing current. Repeats run the same sweep again under one Run press, and Dataset names each of them in the plot and the table.

| Control | What it does |
|---|---|
| **Start voltage (V)** | Where the sweep begins, in the unit the label shows - volts when sourcing voltage, amps when sourcing current. |
| **Stop voltage (V)** | Where the sweep ends. A Stop below Start sweeps downwards. |
| **Points** | How many levels the sweep steps through, from Start to Stop. More points draw a finer curve and take longer. |
| **Delay (s)** | How long to wait at each level before reading it - time for the sample and the leads to settle. Too short and a slow sample's curve lags the source. |
| **Dataset** | A label for this run, shown in the table and the plot legend and saved with it - 'dark', 'after anneal', 'probe 2'. It does not have to be unique. |
| **Repeats** | Run the same sweep this many times under one Run press. Each becomes a row of its own. |
| **Sample name** | The sample on the stage. It names the saved files and identifies the sample to every check in the suite, so two different coupons must never share a name - a result from one would be carried over onto the other. |
| **Next #** | The number the next saved measurement will carry in its file name. It counts up by itself on every save; it is not typed. |
| **Save path...** | Choose the folder to save into. A subfolder named for today's date is made inside it, so one folder holds a day's work. |
| **Save folder** | Where this session's files are being saved - today's dated folder inside the one chosen with Save path. |

### Periodic measurement

![The Periodic measurement panel](../../assets/screens/iv_sweep/periodic-measurement-light.png#only-light)
![The Periodic measurement panel](../../assets/screens/iv_sweep/periodic-measurement-dark.png#only-dark)

Stress over time: hold the sample in the standby condition, run the sweep above, and repeat. It shows whether the IV curve drifts while the device sits under bias.

| Control | What it does |
|---|---|
| **Cycles** | How many sweeps the periodic run makes. |
| **Cycle period (s)** | How long the sample is held in the standby condition before each sweep, in seconds. |
| **Between sweeps** | What the sample sees between sweeps: a held bias voltage, a held bias current, or the output off so it relaxes with no field across it. The biased modes keep the output on into the next sweep, so what the bias did is still there to measure. |
| **Bias level (unused)** | The standby bias, in volts or amps as the label says. Unused, and labelled so, while the sample remains idle. |
| **Run periodic** | Start the periodic run: the cycles above, each a standby hold then the sweep set up above. Stop cancels it like any run. |

### Results

![The Results panel](../../assets/screens/iv_sweep/results-light.png#only-light)
![The Results panel](../../assets/screens/iv_sweep/results-dark.png#only-dark)

The runs of this session, held in memory until saved. Tick a row with the box at its left; the buttons below act on the ticked rows.

Besides the controls below, it has the ones every window has - see [Results](every-window.md#results).

| Control | What it does |
|---|---|
| **Results table** | One row per completed sweep, held in memory until you save. Tick rows to narrow the plot to them; R and R-squared are the fitted line's, so a low R-squared means the fit, not necessarily the sample, is the problem. |
| **Copy ticked → Plot** | Draw the ticked sweeps on the plot together. With nothing ticked the plot shows the newest sweep. |
| **Equations...** | Show the straight-line fit this tab computes, its symbols, and - once a sweep has been fitted - the same formula with that sweep's numbers. |
<!-- /generated:controls -->

<!-- generated:data-notes experiments/iv-sweep.md -->
## What this means for your data

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
<!-- /generated:data-notes -->
