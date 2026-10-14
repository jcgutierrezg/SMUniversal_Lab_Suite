---
type: guide
title: "Keithley 487"
---

# Keithley 487

A picoammeter with a voltage source beside it: it holds up to ±505 V
and measures the current that results, from 10 fA to 2 mA. It cannot
source a current and it does not measure voltage, so it runs **IV sweeps
in voltage mode and fixed-voltage traces**, and nothing else.

<!-- generated:glance keithley-487 -->
> **This instrument fails its own checkup.** At 94628971e22b, one run of three passed whole and the other two each lost a reading at the sweep's first point, with no flag left behind. the cause is not yet known; tools/bench_487_trigger.py is the next step. Treat any measurement it produces as unconfirmed.

| At a glance | |
|---|---|
| Maximum voltage | 505 V |
| Maximum current | 2.5 mA |
| Power limit | none - full V and I together |
| Smallest current range | 2 nA |
| Smallest voltage range | 50.5 V |
| Fastest reading | about 52 ms per reading at fast integration |
| Integration (NPLC) | 0.1 to 1 |
| Sweep runs on | the PC |
| Sensing | 2-wire |
| Over-voltage protection | no |
| Can disconnect when off (high-Z) | always - off opens the relay |
| Says when it hits compliance | yes |
| Connection | GPIB (GPIB-USB adapter) |
| Checked against the instrument | **fails** |
| Runs Van der Pauw + Hall | **no** |
| Runs IV sweep | yes |
| Runs Fixed sourcing vs time | yes |
| Runs Ossila 4-point probe | **no** |
| Choose it for | picoamp currents and high resistance, sourcing up to 505 V - IV sweeps and fixed-voltage traces only |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Picoamp currents.** Its smallest range is 2 nA with 10 fA
  resolution - fifty times below the lowest range anywhere else in the
  lab.
- **High voltage on a high-resistance sample.** Insulators, leakage and
  dielectrics: 500 V across 1 TΩ is 500 pA, which it measures well.

## Look elsewhere when

- **You need to source a current.** It has no current source, so Van der
  Pauw, Hall and the 4-point probe refuse it at Connect.
- **The sample needs protecting below 25 µA.** The current limit is
  25 µA or 2.5 mA and nothing else.
- **You need speed.** It returns about twelve to sixteen readings a
  second, one at a time.

## At the bench

- **Connecting:** GPIB, through a GPIB-USB adapter. **It is not detected
  automatically** - it predates the `*IDN?` question the software uses
  to recognise instruments. Pick its address, press Connect, and when
  the software says it does not recognise what answered, choose
  **Keithley 487** from the list. The software then checks it really is
  a 487 before it sets anything.
- **Wiring is two circuits, not one.** The voltage comes out of the
  binding posts on the back; the current goes in through the triax
  input. The sample sits between the source HI and the triax centre,
  with the two LOs joined.
- **The compliance is a choice of two:** 25 µA, which the form starts
  on, or 2.5 mA. It protects the sample only - **the measurement range
  is picked by the instrument**, so a 25 µA limit still measures
  picoamps.
- **Output off disconnects the sample.** The software takes the source
  to 0 V first, then opens the relay. There is no "High-Z" box to tick
  because there is no other kind of off.
- **With the interlock cable fitted, the source will not turn on while
  the fixture lid is open**, and a run stops if the lid opens during
  it.
- **Warm it up.** Keithley specify two hours to rated accuracy.
