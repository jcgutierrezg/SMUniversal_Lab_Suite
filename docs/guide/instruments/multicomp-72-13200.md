---
type: guide
title: "Multicomp Pro 72-13200"
---

# Multicomp Pro 72-13200

An electronic load, not a source-measure unit. It **sinks** current from
a device that produces power, up to 30 A and 120 V, and cannot drive
anything itself. It is here for one job: IV curves of illuminated solar
cells above 3 A, where every SMU in the lab runs out of current.

<!-- generated:glance multicomp-72-13200 -->
| At a glance | |
|---|---|
| Maximum voltage | 120 V |
| Maximum current | 30 A |
| Power limit | none - full V and I together |
| Smallest current range | 3 A |
| Smallest voltage range | 18 V |
| Fastest reading | 3.5-6 ms per query |
| Integration (NPLC) | n/a |
| Sweep runs on | the PC |
| Sensing | as set at the front panel |
| Over-voltage protection | no |
| Can disconnect when off (high-Z) | no |
| Says when it hits compliance | n/a |
| Connection | USB serial |
| Checked against the instrument | yes |
| Runs Van der Pauw + Hall | **no** |
| Runs IV sweep | yes |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | **no** |
| Choose it for | illuminated solar cells above 3 A - it only sinks, it cannot source |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Solar cells and other power sources above about 3 A.** It measures
  the middle of the curve well, including the maximum power point, which
  is the region an SMU cannot reach at these currents.

## Look elsewhere when

- **Anything that needs a source.** Reverse bias, Van der Pauw, Hall and
  four-point probe all need current driven into the sample, and it is
  refused for those windows at Connect.
- **You need the short-circuit current (Isc) measured.** It cannot reach
  0 V: Isc has to be extrapolated from the low-voltage end of what it
  could measure.
- **Currents are small.** Its accuracy has a floor of 1.35 mA on its 3 A
  setting and 13.5 mA on its 30 A setting. Below a few amps, an SMU is
  far better.

## At the bench

- **Set the current ceiling on the front panel before the run.** The
  3 A or 30 A ceiling is chosen on the keypad, the software cannot see
  it, and it sets the accuracy floor above.
- **A run refuses anything below 0 V.** Take the reverse-bias part of the
  curve on an SMU and the high-current part here, and expect two files.
- **The open-circuit voltage (Voc) is read with the input off.** That is
  essentially open circuit, but it is not a point on the swept curve.
- **Sensing** is set on the front panel, not from the software.
- **Connection:** USB serial.
