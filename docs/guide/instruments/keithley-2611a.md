---
type: guide
title: "Keithley 2611A"
---

# Keithley 2611A

A 200 V, 1.5 A source-measure unit that reads voltage and current in one
conversion and runs its sweeps on its own clock. It is the best choice
here for Hall measurements, and a good general-purpose instrument when a
sample needs high voltage.

<!-- generated:glance keithley-2611a -->
| At a glance | |
|---|---|
| Maximum voltage | 200 V |
| Maximum current | 1.5 A |
| Power limit | up to 1.5 A at 20 V or 100 mA at 200 V |
| Smallest current range | 100 nA |
| Smallest voltage range | 200 mV |
| Fastest reading | 13.6 ms at NPLC 0.001 |
| Integration (NPLC) | 0.001 to 25 |
| Sweep runs on | the instrument |
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
| Choose it for | matched V and I in one conversion; fast hardware sweeps |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Hall effect.** Voltage and current are read in one matched
  conversion, so both describe the same instant. That matters most where
  the result is a small difference between two large readings, which is
  what a Hall voltage is.
- **Fast sweeps on the instrument's own clock**, with integration times
  down to a thousandth of a mains cycle.
- **High voltage.** Up to 200 V, at up to 100 mA.

## Look elsewhere when

- **You need to measure below about 100 nA.** Its smallest range is
  100 nA. The Keithley 2635B goes three decades lower.
- **You need more than 1.5 A.** The Keysight B2901A goes to 3 A.
- **You need over-voltage protection.** Only the GSM-20H10 has it.

## At the bench

- **Connection:** GPIB, through a GPIB-USB adapter. On a laptop without
  National Instruments' GPIB software, see
  [Connecting a GPIB instrument from a laptop](index.md#connecting-a-gpib-instrument-from-a-laptop).
- **Above about 20 V it needs its interlock line held.** Without it, the
  output will not turn on on the 200 V range, and opening a fixture lid
  turns the output off and keeps it off.
- **On this bench the interlock is jumpered permanently.** The lid cutout
  is therefore **not** in circuit, so 200 V at up to 100 mA can stay live
  on an open fixture. Treat the fixture as live whenever the output lamp
  is green.
- **Output off does not disconnect the sample.** It holds 0 V on it, with
  1 mA available. Tick **High-Z output off** if the sample must actually
  be isolated. That opens the output relay, which has a limited life, so
  it is not ticked by default.
- **The first reading after a change of settings is slower** than the
  rest. On a PC-stepped sweep or a bias hold it shows as one slow point
  at the start.
