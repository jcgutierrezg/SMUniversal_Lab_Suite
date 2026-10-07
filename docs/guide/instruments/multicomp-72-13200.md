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
> **The software for this instrument has changed since it was last checked against it.** The code has changed since the 2026-09-16 checkup. The measurement may be fine; nobody has confirmed it. Run a checkup first - see [Running a checkup](../good-data/running-a-checkup.md).

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
| Checked against the instrument | **re-check** |
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
  far better. A cell under room light is in this group: tens of
  milliamps, and a voltage sweep on a source that weak gives points
  that are not the cell's curve.

## At the bench

- **Wire it four-wire and press SHIFT + CW.** The display shows `Comm`
  when the sense terminals are in use. Without it the voltage includes
  the drop in the force leads, and at several amps the curve comes out
  as a straight line.
- **Keep the force leads short and heavy.** They decide the lowest
  voltage a sweep can reach: the load fully on is about 43 mOhm, and
  the leads add to it. On 16 mOhm of wiring a cell at 8 A could not be
  pulled below 0.48 V.
- **Set Delay to 0.45 s or more.** A shorter one is refused: the load
  needs that long to settle and to refresh its reading.
- **"Setpoints not reached" after a run** means the load did not hold
  some of the levels, and says which way. Below what it can reach:
  start the voltage sweep where the message says. Held below the
  setpoint: the source is too weak for a voltage sweep, so sweep
  current. More current than the source gives: end the current sweep
  where the message says.
- **The current range sets the accuracy floor above.** A voltage sweep
  uses the range chosen in the window; a current sweep picks 3 A or
  30 A from its own span.
- **A run refuses anything below 0 V.** Take the reverse-bias part of the
  curve on an SMU and the high-current part here, and expect two files.
- **The open-circuit voltage (Voc) is read with the input off.** That is
  essentially open circuit, but it is not a point on the swept curve.
- **Connection:** USB serial.
