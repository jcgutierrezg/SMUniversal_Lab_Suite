---
type: guide
title: "Keithley 2400"
---

# Keithley 2400

A 210 V, 1 A source-measure unit: the Keithley 2401 with a 200 V range.
It runs every experiment in the suite.

<!-- generated:glance keithley-2400 -->
> **This instrument has never been checked against the software.** Never run against its instrument. Nothing on this page has been confirmed at a bench.

| At a glance | |
|---|---|
| Maximum voltage | 210 V |
| Maximum current | 1.05 A |
| Power limit | up to 1.05 A at 21 V or 105 mA at 210 V |
| Smallest current range | 1 µA |
| Smallest voltage range | 200 mV |
| Fastest reading | not measured |
| Integration (NPLC) | 0.01 to 10 |
| Sweep runs on | the PC |
| Sensing | 2- or 4-wire, switchable |
| Over-voltage protection | no |
| Can disconnect when off (high-Z) | yes |
| Says when it hits compliance | yes |
| Connection | not known |
| Checked against the instrument | **never** |
| Runs Van der Pauw + Hall | yes |
| Runs IV sweep | yes |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | yes |
| Choose it for | general-purpose IV and four-contact work up to 210 V, or 1 A up to 21 V |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **IV work past 21 V** where you would otherwise reach for the
  GSM-20H10, the B2901A or the 2611A/2635B.
- **Up to an amp at low voltage**, like the 2401.
- **Knowing whether you hit compliance.** It reports a compliance hit.

## Look elsewhere when

- **You need high current and high voltage together.** Above 21 V it
  gives at most 105 mA.
- **You need to measure below a microamp.** Its smallest current range
  is 1 µA, like the 2401's.
- **Speed matters.** Its sweeps are stepped from the PC, like the 2401's.

## At the bench

- **Not checked against the instrument yet.** Run a checkup before
  trusting a result from it.
- **Connection:** GPIB or RS-232. If the 2401 is on the same GPIB bus,
  give the 2400 a different address from its front panel: both leave
  the factory on 24.
- **Above 50 V the run asks first.** The terminals can carry a
  dangerous voltage.
- **Output off holds the sample at 0 V** unless **High-Z output off** is
  ticked, which opens the output relay instead.
