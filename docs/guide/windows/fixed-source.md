---
type: guide
title: "Fixed sourcing vs time"
---

# Fixed sourcing vs time

Holds one voltage (or one current) on the sample and records the other
quantity against the clock: leakage, bias stress, relaxation, self-heating,
anything whose interesting axis is time rather than level. You choose how
long the level is held and how often to read; the number of readings
follows from those.

![The Fixed sourcing window after a demo run](../../assets/screens/fixed_source/window-light.png#only-light)
![The Fixed sourcing window after a demo run](../../assets/screens/fixed_source/window-dark.png#only-dark)

## What it can run on

Every SMU the suite knows, and the Multicomp electronic load. See
[Instruments](../instruments/index.md). Every run is stepped from the PC,
so how fast it can read depends on the instrument and the integration
time. Asking for readings faster than that gives fewer readings, not
faster ones.

## Running it

1. **Connect** the instrument (see
   [Every window](every-window.md#the-usual-order)).
2. **Choose what to hold** in **Source**, and type the **Level**.
3. **Set the compliance.** It protects the sample for the whole hold,
   which may be hours.
4. **Set the timing:** **Duration** is how long the sample is held
   energised, and **Sample every** is the gap between readings. The line
   under them says how many readings that makes. A duration over ten
   minutes asks you to confirm, to catch a mistyped extra zero.
5. **Press Run.** The output lamp goes green, and the plot fills in as
   readings arrive. The output is switched off when the duration is up,
   every time.

## Ending a run early: two buttons

This is the one window where there are two ways to stop, and **they do
opposite things with your data**:

- **Finish and save** stops now and **keeps** what has been collected, as
  a run in the table. Twenty minutes of an hour's hold is twenty real
  minutes of data.
- **Stop and discard** cancels and **throws the readings away**, like
  Stop in every other window.

Both switch the output off first. Closing the window cancels, like Stop.

## Reading the result

- **Time is measured, not assumed.** Each reading records when it was
  actually taken. If the instrument could not keep up, the gaps in the
  time column show it, and the file's header records the achieved
  interval beside the one you asked for.
- **The first readings include the turn-on.** Time zero is the moment
  the output comes on, with no settling wait, so the first few rows show
  the sample responding to the level arriving. Discard them if you want
  the steady state.
- **Also plot the sourced level** draws what the instrument actually
  sourced on a second axis, to check the source held steady while the
  measured quantity moved.
- **Compliance is watched on every reading** unless you untick **Watch
  compliance**. A trip that comes and goes mid-run is recorded against
  the readings it affected.

## The panels

<!-- generated:controls fixed_source -->
The controls every window has - in the Header strip, Instruments, Run controls, Results and Plot panels - are described once, on [Every window](every-window.md). What follows is this window's own.

### Sample and saving

![The Sample and saving panel](../../assets/screens/fixed_source/sample-and-saving-light.png#only-light)
![The Sample and saving panel](../../assets/screens/fixed_source/sample-and-saving-dark.png#only-dark)

| Control | What it does |
|---|---|
| **Sample name** | The sample on the stage. It names the saved files and identifies the sample to every check in the suite, so two different coupons must never share a name - a result from one would be carried over onto the other. |
| **Next #** | The number the next saved measurement will carry in its file name. It counts up by itself on every save; it is not typed. |
| **Save path...** | Choose the folder to save into. A subfolder named for today's date is made inside it, so one folder holds a day's work. |
| **Save folder** | Where this session's files are being saved - today's dated folder inside the one chosen with Save path. |

### Source

![The Source panel](../../assets/screens/fixed_source/source-light.png#only-light)
![The Source panel](../../assets/screens/fixed_source/source-dark.png#only-dark)

The one level held on the sample for the whole run, and what protects it. All of it is sent at the start of the run and saved with it.

| Control | What it does |
|---|---|
| **Source voltage, measure current** | Hold a voltage on the sample and measure the current through it. |
| **Source current, measure voltage** | Drive a current through the sample and measure the voltage across it. |
| **Level (V)** | The level held for the whole run, in volts or amps as the label says. It does not move once the output is on. |
| **Current compliance (A)** | The limit on the quantity you are not sourcing: the most current the instrument may drive when sourcing voltage, the most voltage when sourcing current. It protects the sample, and the measurement range follows it. Type any value; the list is only a starting point. |
| **Integration (NPLC)** | Integration time, in mains cycles. 1 NPLC averages over a whole cycle and rejects mains hum; 0.01 is far faster and visibly noisier. Two runs at different NPLC are not comparable, so it is recorded with the data. |
| **Overvoltage protect** | Overvoltage protection: a hard ceiling on the output, separate from compliance. It matters in 4-wire work, where a sense lead falling off makes the instrument wind its output up. Greyed on instruments without it. |
| **4-wire (remote sense)** | Measure the voltage on separate sense leads at the sample, so the resistance of the source leads and contacts drops out. Untick only for a 2-wire hookup. Greyed, and pinned to the wiring, on instruments whose sense terminals are strapped. |
| **High-Z output off** | What the instrument does to the sample between runs: open the relay (high-Z) or hold it at zero volts. High-Z leaves nothing driving the film. Greyed on instruments without the choice. |
| **Watch compliance (1 extra query/sample)** | Ask after every sample whether the instrument was clamped, so a trip that comes and goes mid-run is recorded against the readings it affected. It costs one extra query per sample, which slows the fastest possible interval; untick when rate matters more. The file records which you chose. |

### Timing

![The Timing panel](../../assets/screens/fixed_source/timing-light.png#only-light)
![The Timing panel](../../assets/screens/fixed_source/timing-dark.png#only-dark)

How long to hold the level, and how often to read.

| Control | What it does |
|---|---|
| **Duration (s)** | How long the run lasts, in seconds. Anything over ten minutes asks you to confirm when you press Run - '600' typed for '60' is an easy slip. |
| **Sample every (s)** | Seconds between readings. The line below says how many that makes; an interval shorter than the instrument can manage gives fewer readings, not faster ones. |
| **Dataset** | A label for this run, shown in the table and the plot legend and saved with it - 'dark', 'after anneal', 'probe 2'. It does not have to be unique. |
| **Sample name** | The sample on the stage. It names the saved files and identifies the sample to every check in the suite, so two different coupons must never share a name - a result from one would be carried over onto the other. |
| **Next #** | The number the next saved measurement will carry in its file name. It counts up by itself on every save; it is not typed. |
| **Save path...** | Choose the folder to save into. A subfolder named for today's date is made inside it, so one folder holds a day's work. |
| **Save folder** | Where this session's files are being saved - today's dated folder inside the one chosen with Save path. |

### Run controls

![The Run controls panel](../../assets/screens/fixed_source/run-controls-light.png#only-light)
![The Run controls panel](../../assets/screens/fixed_source/run-controls-dark.png#only-dark)

Besides the controls below, it has the ones every window has - see [Run controls](every-window.md#run-controls).

| Control | What it does |
|---|---|
| **Finish and save** | End the run now and keep what has been collected, as a run in the table. Unlike Stop and discard nothing is thrown away: twenty minutes of an hour's hold is twenty real minutes. The output is put away first. |
| **Stop and discard** | Cancel the run and discard its readings. The output is taken down by the thread that owns the instrument, so it happens at the next safe point rather than instantly. |

### Results

![The Results panel](../../assets/screens/fixed_source/results-light.png#only-light)
![The Results panel](../../assets/screens/fixed_source/results-dark.png#only-dark)

The runs of this session, held in memory until saved. Tick a row with the box at its left; the buttons below act on the ticked rows.

Besides the controls below, it has the ones every window has - see [Results](every-window.md#results).

| Control | What it does |
|---|---|
| **Results table** | One row per run, held in memory until you save. Tick rows to plot them together; with none ticked the newest is drawn. |
| **Copy ticked → Plot** | Draw the ticked runs on the plot together. With nothing ticked the plot shows the newest run. |

### Also plot the sourced level (right axis)

![The Also plot the sourced level (right axis) panel](../../assets/screens/fixed_source/also-plot-the-sourced-level-right-axis-light.png#only-light)
![The Also plot the sourced level (right axis) panel](../../assets/screens/fixed_source/also-plot-the-sourced-level-right-axis-dark.png#only-dark)

| Control | What it does |
|---|---|
| **Also plot the sourced level (right axis)** | Draw the level the instrument actually sourced, dashed, on a second axis on the right - to see whether the source held steady while the measured quantity moved. |
<!-- /generated:controls -->

## What this means for your data

<!-- generated:data-notes experiments/fixed-source-vs-time.md -->
**The time column is what happened, not what was asked for.** If the
instrument could not keep up, the gaps in `time_s` say so and
`interval_achieved_s` in the header says so more compactly. Compare it
against `interval_requested_s` before trusting any rate you derive.

**A run that ended early says how.** `ended_by` is `duration`,
`operator` or `read_error`. A trace that stops early looks identical to
a complete one on a plot, so check that column before concluding
anything from the length of a run.

**"Finish and save" keeps your data; "Stop and discard" does not.** The
two buttons sit next to each other. On every other tab in this suite,
Stop discards — that is deliberate and unchanged, and it is why the
button that keeps your data is called something else.

**Compliance is watched per sample unless you switched it off.**
`compliance_watched` records which you chose. A blank `compliance_tripped` column
with watching on means the instrument cannot report a trip at all —
which is not the same as no trip, and must not be read as one.

**A blank reading is a blank cell, never a missing row.** Sample indices
stay contiguous, so a gap in the trace is visible rather than closing up
and shifting everything after it earlier in time.

**The turn-on transient is inside the data.** t = 0 is the output-on
instant and there is no settle before the first sample, so the first few
rows include whatever the sample did as the level arrived. That is
deliberate; discard them if you want the steady state.

**A run can overshoot its duration by up to one sample interval.** The
timer is a ceiling with a small, bounded grace, not a hard cut — the
alternative was dropping the sample due at exactly the duration.

**This has never been run against hardware.** Everything above is
verified against the simulated instrument and the test suite. The first
bench session is expected to find something — commissioning a new path
always has.
<!-- /generated:data-notes -->
