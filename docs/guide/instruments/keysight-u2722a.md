---
type: guide
title: "Keysight U2722A"
---

# Keysight U2722A

A compact 20 V, 120 mA USB source-measure unit, wired permanently for
4-wire sensing. It is useful when the others are busy, but it works
differently from every other SMU here, because **the compliance you
choose also sets the resolution of your data**. Read the bench notes
below before using it.

<!-- generated:glance keysight-u2722a -->
| At a glance | |
|---|---|
| Maximum voltage | 20 V |
| Maximum current | 120 mA |
| Power limit | none - full V and I together |
| Smallest current range | 1 µA |
| Smallest voltage range | 2 V |
| Fastest reading | 77.0 ms at NPLC 1 |
| Integration (NPLC) | 1 to 255 |
| Sweep runs on | the PC |
| Sensing | 4-wire (hardwired) |
| Over-voltage protection | no |
| Can disconnect when off (high-Z) | no |
| Says when it hits compliance | no |
| Connection | USB serial |
| Checked against the instrument | yes |
| Runs Van der Pauw + Hall | yes |
| Runs IV sweep | yes |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | yes |
| Choose it for | when the others are busy; permanently 4-wire by wiring |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Low-voltage, low-power work when the other instruments are in use.**
- **Always-4-wire measurements.** Its sense leads are wired in, so a run
  cannot accidentally be 2-wire.

## Look elsewhere when

- **You want fine resolution and a generous compliance together.** Here
  they are the same setting (see below).
- **You need a small bias.** It cannot source below about 1.2 mV or below
  about 0.6 nA, and just above those the sign of the output is not
  reliable. For millivolt-scale bias use any other SMU.
- **You need a compliance below 100 nA, or between 10 mA and 12 mA.** It
  cannot hold either.
- **Speed matters.** Its shortest integration is one mains cycle, and each
  point needs two separate readings, so a 200-point sweep at a long
  integration time takes minutes.
- **You need more than 20 V or 120 mA.**

## At the bench

- **Your compliance picks your resolution.** On every other SMU the
  compliance protects the sample and the range sets the resolution
  separately. Here a compliance can only sit between a tenth of a range
  and its full scale, so the compliance you type *is* the range, and the
  range is what its 14-bit converter divides into 16384 steps:

    | Compliance you type | Smallest step in the data |
    |---|---|
    | 9 µA | 0.61 nA |
    | 90 µA | 6.1 nA |
    | 900 µA | 61 nA |
    | 90 mA | 7.3 µA |

    A generous compliance "to be safe" costs a decade of resolution per
    step. The console says which range each run used.

- **Pin the range if a level has to be accurate.** It has no autorange;
  left on AUTO it takes the widest range, and the same 0.1 V request can
  come out 6% different depending on which range it lands on.
- **Longer integration does not add resolution.** It is a 14-bit
  instrument whatever the NPLC. Use a smaller range instead.
- **Give it time to settle.** Into a high-resistance sample the output
  moves at about 1 V per second at 1 µA, and after a step it needs about
  a third of a second to come within 1%. Raise the delay setting if each
  point looks like the one before it.
- **The output drops for about a fifth of a second** when switching
  between sourcing voltage and sourcing current, about ten times longer
  than the Keithleys.
- **Connection:** USB serial. If it disappears from the address list,
  choose **VISA (pyvisa-py)** as the connection instead.
