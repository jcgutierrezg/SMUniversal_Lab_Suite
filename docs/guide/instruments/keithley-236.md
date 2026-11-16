---
type: guide
title: "Keithley 236"
---

# Keithley 236

A source-measure unit that holds up to ±110 V or ±100 mA and measures
down to femtoamps: its smallest current range is 1 nA, read to 10 fA. It
measures only the quantity it is not sourcing, so for now it runs **IV
sweeps and fixed-level traces**, and the four-contact windows refuse it.

<!-- generated:glance keithley-236 -->
> **This instrument has never been checked against the software.** Never run against its instrument. Nothing on this page has been confirmed at a bench.

| At a glance | |
|---|---|
| Maximum voltage | 110 V |
| Maximum current | 100 mA |
| Power limit | none - full V and I together |
| Smallest current range | 1 nA |
| Smallest voltage range | 1.1 V |
| Fastest reading | not measured |
| Integration (NPLC) | 0.0208 to 1 |
| Sweep runs on | the PC |
| Sensing | 2- or 4-wire, switchable |
| Over-voltage protection | no |
| Can disconnect when off (high-Z) | no |
| Says when it hits compliance | yes |
| Connection | GPIB (GPIB-USB adapter) |
| Checked against the instrument | **never** |
| Runs Van der Pauw + Hall | **no** |
| Runs IV sweep | yes |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | **no** |
| Choose it for | femtoamp-resolution IV sweeps and fixed traces up to 110 V or 100 mA - not the four-contact windows yet |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Very small currents with a real SMU.** IV sweeps on high-resistance
  samples, leakage, and anything where the 1 nA range and its default
  settling help.
- **Sourcing current and watching the voltage** up to 110 V, with remote
  sense.

## Look elsewhere when

- **You want Van der Pauw, Hall or the 4-point probe.** Those windows need
  the current measured, and the 236 reports the current it was told to
  push. They refuse it at Connect.
- **You need speed at the lowest ranges.** On the 1 nA range the
  instrument waits 360 ms before every reading to settle.

## At the bench

- **Connecting:** GPIB, through a GPIB-USB adapter. **It is not detected
  automatically** - like the 487, it predates the `*IDN?` question the
  software uses to recognise instruments. Pick its address, press
  Connect, and when the software says it does not recognise what
  answered, choose **Keithley 236** from the list. The software checks it
  really is a 236 before it sets anything.
- **Output off holds 0 V.** The output stays connected at 0 V in
  standby; it does not disconnect the sample.
- **Remote sense needs its leads.** Tick remote sense only with the sense
  leads connected: without them the output can run to the full source
  voltage.
- **Above 50 V, a run asks first.** Press Run on anything that can reach
  more than 50 V and a red **DANGER: HIGH VOLTAGE** warning comes up; the
  run starts only once you confirm the set-up is safe.
