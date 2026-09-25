---
type: guide
title: "Keithley 2401"
---

# Keithley 2401

A 21 V, 1 A source-measure unit for general current-voltage work at
low voltage. It is simple and dependable, and it does nothing the others
cannot, except be free when they are busy.

<!-- generated:glance keithley-2401 -->
| At a glance | |
|---|---|
| Maximum voltage | 21 V |
| Maximum current | 1.05 A |
| Power limit | none - full V and I together |
| Smallest current range | 1 µA |
| Smallest voltage range | 200 mV |
| Fastest reading | 35.4 ms at NPLC 0.01 |
| Integration (NPLC) | 0.01 to 10 |
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
| Choose it for | general-purpose IV work up to 21 V |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Everyday IV work up to 21 V**: diodes, resistors, contacts, anything
  that stays at low voltage and above a microamp.
- **Knowing whether you hit compliance.** It reports a compliance hit
  reliably.

## Look elsewhere when

- **You need more than 21 V.** The GSM-20H10, the B2901A and the Keithley
  2611A and 2635B all go to about 200 V.
- **You need to measure below a microamp.** Its smallest current range is
  1 µA, the same as the GSM-20H10.
- **Speed matters.** It is the slowest of the GPIB instruments per
  reading, and its sweeps are stepped from the PC, so point spacing
  includes the time the PC takes to ask for each reading.

## At the bench

- **Connection:** GPIB, through a GPIB-USB adapter. On a laptop without
  National Instruments' GPIB software, see
  [Connecting a GPIB instrument from a laptop](index.md#connecting-a-gpib-instrument-from-a-laptop).
- **The first reading after a change of settings is slower** than the
  rest, by about a tenth of a second. It is not a fault.
- **Output off holds the sample at 0 V** unless **High-Z output off** is
  ticked, which opens the output relay instead.
