---
type: guide
title: "Aim-TTi TSX1820P"
---

# Aim-TTi TSX1820P

A bench power supply, not a source-measure unit. It is the
[TSX3510P](aimtti-tsx3510p.md) with the output traded the other way:
up to 18 V and 20 A, in the same steps of 10 mV and 10 mA. Everything
on that page applies here.

<!-- generated:glance aimtti-tsx1820p -->
| At a glance | |
|---|---|
| Maximum voltage | 18.15 V |
| Maximum current | 20.2 A |
| Power limit | none - full V and I together |
| Smallest current range | 20.2 A |
| Smallest voltage range | 18.15 V |
| Fastest reading | 53-106 ms for a pair of readings |
| Integration (NPLC) | n/a |
| Sweep runs on | the PC |
| Sensing | set by the rear-terminal links |
| Over-voltage protection | a trip, set from the driver - no window offers it |
| Can disconnect when off (high-Z) | no |
| Says when it hits compliance | yes |
| Connection | GPIB (GPIB-USB adapter) |
| Checked against the instrument | yes |
| Runs Van der Pauw + Hall | **no** |
| Runs IV sweep | **no** |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | **no** |
| Choose it for | holding a rail or driving a heater, up to 18 V and 20 A - an auxiliary, not a measuring instrument |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **More than 10 A at a low voltage.** Otherwise the two are
  interchangeable, and the 3510 gives twice the voltage.

## Look elsewhere when

- **You are measuring a sample, need less than 10 mA, need a negative
  voltage, or need to follow something fast.** The same limits as the
  [TSX3510P](aimtti-tsx3510p.md#look-elsewhere-when), for the same
  reasons.

## At the bench

- **Use 4-wire sensing above a few amps.** A hundredth of an ohm of
  lead drops 0.2 V at 20 A. Take the two links off the rear terminal
  block and wire the sense terminals to the load.
- **The over-voltage trip is left at its widest**, 25 V on this model.
- **A run can finish with an "uncertain shutdown" warning** although
  the output switched off normally. The instrument sometimes reports an
  error that no command caused. Check the OUTPUT lamp is off, and keep
  the run.
- **The first reading after switching on can be marked as clamped.**
  Charging the supply's own output takes it through its current limit
  for a moment.
- **Everything else** is as for the
  [TSX3510P](aimtti-tsx3510p.md#at-the-bench).
- **Connection:** GPIB, through the GPIB-USB adapter.
