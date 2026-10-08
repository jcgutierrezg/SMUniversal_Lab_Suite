---
type: guide
title: "Aim-TTi TSX3510P"
---

# Aim-TTi TSX3510P

A bench power supply, not a source-measure unit. It holds a voltage up
to 35 V or a current up to 10 A and reads both back, in steps of 10 mV
and 10 mA. It is here as an auxiliary: to hold a rail, drive a heater
or bias a lamp while another instrument does the measuring.

<!-- generated:glance aimtti-tsx3510p -->
> **The software for this instrument has changed since it was last checked against it.** The code has changed since the 2026-10-08 checkup. The measurement may be fine; nobody has confirmed it. Run a checkup first - see [Running a checkup](../good-data/running-a-checkup.md).

| At a glance | |
|---|---|
| Maximum voltage | 35.3 V |
| Maximum current | 10.2 A |
| Power limit | none - full V and I together |
| Smallest current range | 10.2 A |
| Smallest voltage range | 35.3 V |
| Fastest reading | 48 to 54 ms for a pair of readings |
| Integration (NPLC) | n/a |
| Sweep runs on | the PC |
| Sensing | set by the rear-terminal links |
| Over-voltage protection | a trip, set from the driver - no window offers it |
| Can disconnect when off (high-Z) | no |
| Says when it hits compliance | yes |
| Connection | GPIB (GPIB-USB adapter) |
| Checked against the instrument | **re-check** |
| Runs Van der Pauw + Hall | **no** |
| Runs IV sweep | **no** |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | **no** |
| Choose it for | holding a rail or driving a heater, up to 35 V and 10 A - an auxiliary, not a measuring instrument |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Power, not precision.** Anything that needs amps at tens of volts
  and where "about 2 A" is the answer you want.
- **Watching a supply rail over time.** The Fixed sourcing vs time
  window holds one level and records the voltage and current it reads
  back.

## Look elsewhere when

- **You are measuring a sample.** Van der Pauw, Hall, four-point probe
  and the IV sweep all refuse it at Connect. Its smallest step is
  10 mA, and those measurements live far below that.
- **You need less than 10 mA.** The current setting does not go lower,
  as a level or as a limit. Zero is not available either: to stop it
  driving, switch the output off.
- **The voltage has to go negative, or the instrument has to absorb
  current.** It works in one direction only. Swap the leads for the
  other polarity; use the electronic load to sink.
- **You need to follow something fast.** A reading takes about a tenth
  of a second, but the output itself takes a second or more to settle
  after a change, and longer coming down with little attached.

## At the bench

- **This unit is out of calibration: what you set is not what you
  get.** Ask it for 10 V and its own meter reads 10.39 V; set a 0.91 A
  limit and it holds 0.80 A. Until it has been checked with a
  multimeter or recalibrated, go by the readings in the file rather
  than the level you typed, and allow for the current limit being about
  a tenth lower than it says. The TSX1820P does not have this problem.
- **It starts every session at 0 V, 10 mA and output off.** The
  software resets it at Connect. Without that it would come up with
  whatever the last person set, because its settings survive being
  switched off.
- **The front panel locks while the software is talking to it.** Press
  LOCAL to get it back; it locks again at the next command.
- **Off is not disconnected.** A capacitor stays across the terminals,
  so shorting a "limited" output still gives a brief pulse. Switch the
  output off before you move a lead.
- **The compliance column says whether the limit was reached.** Holding
  a voltage, *yes* means the supply was in current limit and the
  voltage in the file is what the load allowed, not what you set. The
  first reading after switching on can say *yes* too: charging the
  supply's own output takes it through its current limit for a moment.
- **If its over-voltage protection trips, the run ends with the link
  reported lost.** The displays alternate between TRIP and a voltage,
  and the supply stops answering until the cause is gone. Its output is
  already off. Reconnect once the displays have settled.
- **Sensing** is set by the two links on the rear terminal block:
  fitted for 2-wire, removed and wired to the load for 4-wire. The
  software cannot see which, so the file records the rule.
- **The over-voltage trip is left at its widest**, 40 V. No window sets
  it yet.
- **Connection:** GPIB, through the GPIB-USB adapter. Select `488` with
  the I/F key on the front panel, and read the address with BAUD/ADDR.
