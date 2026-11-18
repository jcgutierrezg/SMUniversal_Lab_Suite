---
type: guide
title: "Keysight B2987A"
---

# Keysight B2987A

An electrometer: it holds a voltage and measures the current that
results, down to a few femtoamps. Up to ±21 V on its own, or ±1000 V
with an interlock fixture. It cannot source a current and it does not
measure voltage at the sample, so it runs **IV sweeps in voltage mode
and fixed-voltage traces**, and nothing else.

<!-- generated:glance keysight-b2987a -->
> **The software for this instrument has changed since it was last checked against it.** The code has changed since the 2026-11-18 checkup. The measurement may be fine; nobody has confirmed it. Run a checkup first - see [Running a checkup](../good-data/running-a-checkup.md).

| At a glance | |
|---|---|
| Maximum voltage | 1 kV |
| Maximum current | 20 mA |
| Power limit | none - full V and I together |
| Smallest current range | 2 pA |
| Smallest voltage range | 21 V |
| Fastest reading | about 34 ms per reading at 1 PLC on 50 Hz mains |
| Integration (NPLC) | 0.0006 to 100 |
| Sweep runs on | the PC |
| Sensing | 2-wire |
| Over-voltage protection | no |
| Can disconnect when off (high-Z) | always - off opens the relay |
| Says when it hits compliance | yes |
| Connection | USB (USB-TMC) |
| Checked against the instrument | **re-check** |
| Runs Van der Pauw + Hall | **no** |
| Runs IV sweep | yes |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | **no** |
| Choose it for | femtoamp currents and very high resistance, sourcing up to 21 V, or 1000 V with the interlock fixture - IV sweeps and fixed-voltage traces only |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Very small currents and very high resistance**: insulators, thin
  films, leakage, anything in the picoamp range and below.
- **Voltages beyond what an SMU gives**, up to 1000 V, with the sample in
  an interlocked fixture.

## Look elsewhere when

- **You need Van der Pauw, Hall or four-point probe.** It cannot source
  a current; those tabs refuse it at Connect.
- **You need a compliance of your choosing.** The current limit is fixed
  by the range: 20 mA up to 21 V, 1 mA beyond. The compliance menu
  offers those two and nothing else.

## At the bench

- **Wiring:** Voltage Source HI to one side of the sample, the other
  side to the ammeter input's centre conductor (triax). Leave the low
  terminal as the software sets it - common - or no current comes back.
- **Above 21 V the interlock must be closed** - the fixture lid shut.
  Open, the run is refused before anything is energised, and a lid
  opened during a run stops it.
- **Above 21 V choose the 1 mA compliance**, and up to 21 V the 20 mA.
  The run says which if the other is chosen.
- **A sweep through zero beyond 21 V** (−100 V to +100 V, say) switches
  range at 0 V: the output opens for a moment at 0 V and closes again.
  The point list is not affected.
- **Above 50 V the high-voltage warning** has to be acknowledged, as on
  every instrument here that can reach it.
- **It shows up as "Keysight B2987A"** in the address list.
- **Connection:** USB.
