---
type: guide
title: "Undalogic miniSMU MS01"
---

# Undalogic miniSMU MS01

A small, portable 12 V, 180 mA source-measure unit on USB. It is quick
to set up and quick to sweep, but it has a small voltage offset that
rules it out for measurements that rest on one small voltage reading.

<!-- generated:glance undalogic-minismu -->
| At a glance | |
|---|---|
| Maximum voltage | 12 V |
| Maximum current | 180 mA |
| Power limit | up to 180 mA at 11.6 V or 175 mA at 12 V |
| Smallest current range | 1 µA |
| Smallest voltage range | 100 mV |
| Fastest reading | 6.0 ms at the OSR floor |
| Integration (NPLC) | 0.0005 to 16.384 |
| Sweep runs on | the instrument |
| Sensing | 2- or 4-wire, switchable |
| Over-voltage protection | no |
| Can disconnect when off (high-Z) | no |
| Says when it hits compliance | no |
| Connection | USB serial |
| Checked against the instrument | yes |
| Runs Van der Pauw + Hall | yes |
| Runs IV sweep | yes |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | yes |
| Choose it for | small, portable, quick; not for single-point small voltages |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Portability.** It is a small board on a USB cable, and it can travel
  with a laptop.
- **Quick IV sweeps at low voltage.** Voltage sweeps run on the board's
  own clock.
- **Anything measured from a slope**: resistances from an IV sweep, for
  example. Its offset cancels there, and 10 kΩ resistors have been
  recovered to better than 0.1%.

## Look elsewhere when

- **The result rests on one small voltage reading**: four-point probe and
  Hall voltages above all. It has an offset of roughly −1 mV that moves
  between sessions, which is often larger than the voltage you are
  after.
- **The protection limit has to be exact.** Its compliance overshoots by
  about 2%, where the others hold within 0.05%. Leave headroom below
  what the sample tolerates.
- **You need more than 12 V or 180 mA**, or a measurement below its 1 µA
  range.
- **Mains hum is a problem.** Its integration is not synchronised to the
  mains, so a given NPLC rejects hum less well than on the other
  instruments.

## At the bench

- **Use the 12 V power adapter.** On USB power alone it is limited to
  50 mA, and it cannot tell the software which supply it is on. A sweep
  that asks for more on USB power flattens at about 50 mA and looks
  like a sample hitting a compliance nobody set. If a run flattens there,
  check the barrel jack before the sample.
- **Choose miniSMU as the connection**, not Serial. Serial appears to
  work at first, then every command fails.
- **Current sweeps are stepped from the PC.** Only its voltage sweeps run
  on the board.
- **4-wire sensing uses up its second channel.**
