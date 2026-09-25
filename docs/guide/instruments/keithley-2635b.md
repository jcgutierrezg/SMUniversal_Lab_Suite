---
type: guide
title: "Keithley 2635B"
---

# Keithley 2635B

A 200 V, 1.5 A source-measure unit with the lowest current ranges in the
lab. It measures down to its 100 pA range, which makes it the instrument
for high-resistance samples and sub-nanoamp currents.

<!-- generated:glance keithley-2635b -->
| At a glance | |
|---|---|
| Maximum voltage | 200 V |
| Maximum current | 1.5 A |
| Power limit | up to 1.5 A at 20 V or 100 mA at 200 V |
| Smallest current range | 100 pA measuring, 1 nA sourcing |
| Smallest voltage range | 200 mV |
| Fastest reading | 12.2 ms at NPLC 0.001 |
| Integration (NPLC) | 0.001 to 25 |
| Sweep runs on | the PC |
| Sensing | 2- or 4-wire, switchable |
| Over-voltage protection | no |
| Can disconnect when off (high-Z) | yes |
| Says when it hits compliance | yes |
| Connection | GPIB (GPIB-USB adapter) |
| Checked against the instrument | yes |
| Runs Van der Pauw + Hall | yes |
| Runs IV sweep | yes |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | yes |
| Choose it for | high-resistance samples and sub-nanoamp currents |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **High-resistance samples.** It measures to its 100 pA range, where the
  Keithley 2611A stops at 100 nA. At 200 V a 1 TΩ sample draws 200 pA,
  which only this instrument measures well.
- **Sub-nanoamp leakage**, and anything else where the current is the
  small quantity.

## Look elsewhere when

- **Speed matters.** Readings at the bottom of its range take about
  90 ms, because it searches the lowest decades as it autoranges. A
  sample that never draws less than a nanoamp is measured as well, and
  faster, on the Keithley 2611A.
- **You need to source or protect below 1 nA.** The lowest current you
  can set as a level or a compliance is 1 nA; the 100 pA range is only
  reached as a measurement.
- **You need a sweep on the instrument's own clock.** Its sweeps are
  stepped from the PC.

## At the bench

- **Connection:** GPIB, through a GPIB-USB adapter. On a laptop without
  National Instruments' GPIB software, see
  [Connecting a GPIB instrument from a laptop](index.md#connecting-a-gpib-instrument-from-a-laptop).
- **Output off does not disconnect the sample.** It holds 0 V on it, with
  1 mA available: six to nine orders of magnitude above what you are
  measuring on a high-resistance sample. **Tick High-Z output off** if
  the sample must genuinely float between runs, especially while the
  temperature stage is cycling.
- **Above about 20 V it needs its interlock line held**, as on the 2611A,
  and on this bench that line is jumpered permanently. The fixture can be
  live at 200 V with the lid open.
- **The first reading after a change of settings is noticeably slow**, at
  over half a second, the most in the fleet. It is not a fault.
