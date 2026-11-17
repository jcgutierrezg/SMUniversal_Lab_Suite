---
type: guide
title: "Multicomp Pro MP710772"
---

# Multicomp Pro MP710772

An electronic load, not a source-measure unit. It **sinks** current from
a device that produces power, up to 40 A, 150 V and 500 W, and cannot
drive anything itself. It does the 72-13200's job with more headroom:
IV curves of illuminated solar cells above 3 A.

<!-- generated:glance multicomp-mp710772 -->
> **The software for this instrument has changed since it was last checked against it.** The code has changed since the 2026-11-17 checkup, which was failing when it ran. The measurement may be fine; nobody has confirmed it. Run a checkup first - see [Running a checkup](../good-data/running-a-checkup.md).

| At a glance | |
|---|---|
| Maximum voltage | 150 V |
| Maximum current | 40 A |
| Power limit | none - full V and I together |
| Smallest current range | 3 A |
| Smallest voltage range | 18 V |
| Fastest reading | about 10 ms per query |
| Integration (NPLC) | n/a |
| Sweep runs on | the PC |
| Sensing | as set at the front panel |
| Over-voltage protection | no |
| Can disconnect when off (high-Z) | no |
| Says when it hits compliance | n/a |
| Connection | USB serial |
| Checked against the instrument | **re-check** |
| Runs Van der Pauw + Hall | **no** |
| Runs IV sweep | yes |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | **no** |
| Choose it for | solar cells and other sources above 3 A, up to 40 A and 500 W - it only sinks, it cannot source |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Solar cells and other power sources above about 3 A**, including
  ones beyond the 72-13200's 30 A and 150 W. It also reaches lower
  voltages at a given current than the 72-13200, so more of the curve
  near Isc is measurable.

## Look elsewhere when

- **Anything that needs a source.** Reverse bias, Van der Pauw, Hall and
  four-point probe all need current driven into the sample, and it is
  refused for those windows at Connect.
- **You need the short-circuit current (Isc) measured.** It cannot reach
  0 V: Isc has to be extrapolated.
- **Currents are small.** Its accuracy has a floor of 1.35 mA on its 3 A
  setting and 18 mA on its 40 A setting. Below a few amps, an SMU is far
  better.

## At the bench

- **Wire it four-wire and switch on Remote Comp** in the Config page on
  its front panel. Without it the voltage includes the drop in the force
  leads.
- **It shows up as "Multicomp Pro 72-13200 or MP710772"** in the address
  list until you connect - the two loads report the same USB ids. After
  connecting it is named correctly.
- **Set Delay to 0.5 s or more.** A shorter one is refused: the load
  needs that long to settle.
- **A voltage sweep cannot go below 0.1 V**, and a run refuses anything
  below 0 V. Take the reverse-bias part of the curve on an SMU.
- **The open-circuit voltage (Voc) is read with the input off.**
- **Connection:** USB serial.
