---
type: guide
title: "TDK-Lambda Z36-24"
---

# TDK-Lambda Z36-24

A bench power supply, not a source-measure unit: up to 36 V and 24 A,
864 W, in one quadrant. Like the Aim-TTi supplies it is an auxiliary -
something to hold a rail or drive a heater while an SMU measures - and
only Fixed sourcing vs time accepts it.

<!-- generated:glance tdk-lambda-z36-24 -->
> **This instrument has never been checked against the software.** Never run against its instrument. Nothing on this page has been confirmed at a bench.

| At a glance | |
|---|---|
| Maximum voltage | 36 V |
| Maximum current | 24 A |
| Power limit | none - full V and I together |
| Smallest current range | 24 A |
| Smallest voltage range | 36 V |
| Fastest reading | 10 to 16 ms per query |
| Integration (NPLC) | n/a |
| Sweep runs on | the PC |
| Sensing | set by the rear J2 sense connector |
| Over-voltage protection | a trip, set from the driver - no window offers it |
| Can disconnect when off (high-Z) | no |
| Says when it hits compliance | yes |
| Connection | USB serial |
| Checked against the instrument | **never** |
| Runs Van der Pauw + Hall | **no** |
| Runs IV sweep | **no** |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | **no** |
| Choose it for | holding a rail or driving a heater, up to 36 V and 24 A - an auxiliary, not a measuring instrument |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Holding a voltage or a current that is large and does not need to
  be precise**: a heater, a lamp, a bias rail, up to 24 A.

## Look elsewhere when

- **You are measuring a sample.** Its current reading is specified to
  within 72 mA plus 0.1% of the reading. Van der Pauw, Hall, the IV sweep
  and four-point probe all refuse it at Connect.
- **You need negative voltage or to sink current.** It sources in one
  quadrant only.

## At the bench

- **Plug in the USB cable with the supply switched off**, then switch
  on. The manual says not to plug or unplug USB while it is running.
- **Leave the front panel at USB, SCPI, address 1.** The software
  selects the supply by address 1 before anything else; at any other
  address it hears nothing. In GEN it does not work at all.
- **It shows up as "TDK-Lambda Z36-24"** in the address list. Use the
  Serial transport.
- **If the link is lost** - the supply was switched off, or the cable
  moved - disconnect, switch the supply off, wait, switch it on, and
  connect again. That is the manual's own recovery.
- **The front panel is handed back when you disconnect.** While
  connected it is locked in remote; press REM to take it back by hand.
- **Settings survive power-off**, but the software resets them on every
  connect: output off, 0 V, 0 A, trip at 40 V.
- **Sensing is the rear J2 connector.** Local sense as shipped; for
  remote sense, remove the jumpers and run leads to the load, with the
  supply switched off. The software cannot see which.
- **Do not sample faster than about 0.2 s.** The meter only updates
  that often.
- **Connection:** USB serial.
