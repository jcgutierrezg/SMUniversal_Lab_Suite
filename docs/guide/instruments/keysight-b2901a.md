---
type: guide
title: "Keysight B2901A"
---

# Keysight B2901A

A 210 V, 3 A source-measure unit: the only one here above 1.5 A, with
the shortest integration time in the fleet and a dependable compliance
report.

<!-- generated:glance keysight-b2901a -->
| At a glance | |
|---|---|
| Maximum voltage | 210 V |
| Maximum current | 3.03 A |
| Power limit | up to 3.03 A at 6 V or 1.515 A at 21 V or 105 mA at 210 V |
| Smallest current range | 100 nA |
| Smallest voltage range | 200 mV |
| Fastest reading | 5.7 ms at NPLC 0.0004 |
| Integration (NPLC) | 0.0004 to 100 |
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
| Choose it for | currents above 1.5 A, to 3 A; the shortest integration time |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Currents above 1.5 A**, up to 3 A at up to 6 V. Nothing else here
  that can source goes past 1.5 A.
- **Fast readings.** Its shortest integration time is the shortest in the
  fleet.
- **Compliance-critical work.** It reports a compliance hit reliably;
  after the GSM-20H10, it is the next choice when that matters.
- **A wide span in one instrument**: from its 100 nA range up to 3 A, and
  up to 210 V.

## Look elsewhere when

- **You need to measure below about 100 nA.** The Keithley 2635B goes
  three decades lower.
- **You need a sweep on the instrument's own clock.** Its sweeps are
  stepped from the PC; the GSM-20H10 and the Keithley 2611A run theirs on
  the instrument.
- **You need over-voltage protection.** Only the GSM-20H10 has it.

## At the bench

- **Connection:** GPIB, through a GPIB-USB adapter. On a laptop without
  National Instruments' GPIB software, see
  [Connecting a GPIB instrument from a laptop](index.md#connecting-a-gpib-instrument-from-a-laptop).
- **High current is only available at low voltage.** It is 3 A up to
  6 V, 1.5 A up to 21 V, and 105 mA up to 210 V. A request outside those
  limits is refused before the output comes on.
- **Output off holds the sample at 0 V** unless **High-Z output off** is
  ticked, which opens the output relay instead.
