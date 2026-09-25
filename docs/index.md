---
type: index
title: "User guide"
---

# SMUniversal Lab Suite

Measurement windows for source-measure units: current-voltage sweeps,
Van der Pauw and Hall, four-point probe, and holding a level over time.
This guide is for running them. Nothing here needs you to know how the
software is built. That is in the [Developer](developer/index.md) tab,
and you can ignore it.

![The IV sweep window, mid-session](assets/screens/iv_sweep/window-light.png#only-light)
![The IV sweep window, mid-session](assets/screens/iv_sweep/window-dark.png#only-dark)

## Start here

| If you want to | Read |
|---|---|
| install it, and make a first measurement you can trust | [Getting started](guide/getting-started/index.md) |
| know what each window measures, and open one | [The windows](guide/windows/index.md) |
| learn the parts every window shares | [Every window](guide/windows/every-window.md) |
| run a current-voltage sweep | [IV sweep](guide/windows/iv-sweep.md) |
| compare the instruments, and pick one | [Instruments](guide/instruments/index.md) |
| get numbers you can trust | [Getting good measurements](guide/good-data/getting-good-measurements.md) |
| understand a saved file | [Reading your data](guide/good-data/reading-your-data.md) |
| check an instrument before trusting it | [Running a checkup](guide/good-data/running-a-checkup.md) |
| fix something that is not working | [Troubleshooting](guide/troubleshooting.md) |

Every control also explains itself: rest the pointer on it and a tooltip
says what it does. The tables in this guide are those same tooltips, so
the two never disagree.

## If you only read one thing

Measure a known resistor before you trust a session. A 10 kΩ resistor
takes two minutes and tests the whole chain: instrument, wiring,
software and analysis. Every fault this project has found produced data
that looked entirely reasonable against an unknown sample, and was
obvious against a known one.

## No instrument to hand?

Every window can run without hardware. In the **Instruments** panel,
set the connection to **Demo** and press **Connect**. The readings are
simulated from a 1 kΩ resistor, and the status says **DEMO - simulated**
so a demo run is never mistaken for a measurement. It is how the
pictures in this guide were taken.
