---
type: guide
title: "GW Instek GSM-20H10"
---

# GW Instek GSM-20H10

A 210 V, 1 A source-measure unit that runs its sweeps on its own clock.
It is the instrument to reach for when a long sweep has to run
unattended, and when you need to know for certain whether a run hit its
compliance.

<!-- generated:glance gwinstek-gsm20h10 -->
| At a glance | |
|---|---|
| Maximum voltage | 210 V |
| Maximum current | 1.05 A |
| Power limit | up to 1.05 A at 21 V or 105 mA at 210 V |
| Smallest current range | 1 µA |
| Smallest voltage range | 200 mV |
| Fastest reading | 14.4 ms at NPLC 0.01 |
| Integration (NPLC) | 0.01 to 10 |
| Sweep runs on | the instrument |
| Sensing | 2- or 4-wire, switchable |
| Over-voltage protection | yes |
| Can disconnect when off (high-Z) | yes |
| Says when it hits compliance | yes |
| Connection | USB serial |
| Checked against the instrument | yes |
| Runs Van der Pauw + Hall | yes |
| Runs IV sweep | yes |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | yes |
| Choose it for | long unattended sweeps; knowing you hit compliance; over-voltage protection |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Long unattended sweeps.** Up to 2500 points run on the instrument's
  own timebase, so the spacing between points is set by the instrument
  and not by the PC.
- **Knowing whether you hit compliance.** It reports a compliance hit on
  each quantity separately, and more reliably than the rest of the
  fleet.
- **Over-voltage protection.** It is the only SMU here that offers it, as
  a hard ceiling from 20 V to 210 V that is separate from compliance.
  That matters in 4-wire work, where a sense lead coming off makes an
  instrument wind its output up.

## Look elsewhere when

- **You need to measure below a microamp.** Its smallest current range is
  1 µA. For nanoamps use the Keithley 2611A or the B2901A, and below that
  the Keithley 2635B.
- **You need more than about 1 A**, or more than 105 mA above 21 V. The
  Keysight B2901A goes to 3 A.
- **A single reading has to be quick.** The first reading after any change
  of settings takes about a quarter of a second longer than the rest.

## At the bench

- **Connection:** USB serial.
- **Output off holds the sample at 0 V** unless **High-Z output off** is
  ticked, which opens the output relay instead. Tick it if the sample
  must be isolated between runs.
