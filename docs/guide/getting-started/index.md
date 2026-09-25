---
type: guide
title: "Getting started"
---

# Getting started

From a bare Windows PC to a first measurement you can trust: install the
suite, open it, check it against a resistor, and learn the few things
that keep a sample and a person safe at the bench.

## Installing on a bench PC

<!-- generated:readme A bench PC, from nothing -->
Windows 10 or 11. About ten minutes, most of it downloads.

1. **Install Git** from <https://git-scm.com/download/win>, keeping the
   default options.

2. **Install uv.** In PowerShell:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Close PowerShell and open a new one, so `uv` is found. There is no separate
   Python to install: uv fetches the version the suite needs by itself.

3. **Install a VISA library, if this PC has a GPIB controller** - NI-VISA or
   Keysight IO Libraries Suite. GPIB goes through VISA by default. A PC with
   only USB and serial instruments can skip this step. (A PC that drives an NI
   GPIB-USB-HS adapter directly, with no NI software, has a different step:
   see [the direct GPIB-USB-HS transport](../../architecture/direct-gpib-usb-hs.md).)

4. **Get the suite.** In PowerShell, in the folder it should live in:

   ```powershell
   git clone https://github.com/jcgutierrezg/SMUniversal_Lab_Suite.git
   cd SMUniversal_Lab_Suite
   ```

5. **Install it and put it on the desktop:**

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1
   ```

   This installs everything the suite needs, then puts **SMUniversal Lab
   Suite** on the desktop. Add `-StartMenu` to put it in the Start menu too.
   If the install fails, the reason is printed here rather than discovered
   later by clicking an icon that does nothing.

6. **Check it.** Double-click the icon: the window chooser opens. Open a
   measurement window and press **Refresh** in *Instruments* - the connected
   instruments are listed by name. If one is missing, run
   `uv run tools/visa_doctor.py` in the suite's folder; it says why.

**Always start the suite from the icon**, not from a console. It opens with no
console window on purpose: closing a console kills Python before the window
can switch the instruments off. The window's own close button is the one that
puts them away.
<!-- /generated:readme -->

## Updating

<!-- generated:readme Updating -->
In the suite's folder:

```powershell
git pull
```

The next double-click runs the new code and installs anything the update
added.
<!-- /generated:readme -->

## If it will not start

<!-- generated:readme If it will not start -->
A failed launch says so in a dialog, and the details are written to
`%LOCALAPPDATA%\SMUniversal_Lab_Suite\launcher.log`. Running `uv sync` in the
suite's folder repairs an incomplete install.
<!-- /generated:readme -->

More in [Troubleshooting](../troubleshooting.md).

## Opening a window

Double-click **SMUniversal Lab Suite** on the desktop. The start-up
window shows one card per measurement: click one to open it. The cards
are described on [The windows](../windows/index.md).

Only one measurement window can hold the instruments at a time. While one
is open, the other measurement cards are greyed out; close that window
first. **Plot saved data** is always available, even during a
measurement.

## Your first measurement: a known resistor

Do this on every new setup, and whenever a result surprises you. It
takes a couple of minutes and tests the whole chain: instrument, leads,
software and analysis. Every fault this project has found produced
numbers that looked reasonable on an unknown sample and were obviously
wrong on a known one.

1. **Wire a 10 kΩ resistor** to the SMU, 4-wire if the instrument and
   leads allow it.
2. Open **IV sweep** and **Connect** the instrument (see
   [Every window](../windows/every-window.md#the-usual-order)).
3. Leave **Source voltage, measure current**. Set **Current compliance**
   to `1e-3` (1 mA), **Start** to `-1`, **Stop** to `1`, and tick **Linear
   fit**.
4. Name the sample `check-10k` and press **Run**.
5. The line should be straight through zero, with **R** within a fraction
   of a percent of 10 kΩ and **R²** very close to 1.

If it is not, stop and find out why before measuring a real sample.
[Troubleshooting](../troubleshooting.md) has the usual causes. Save the
run if you want a record that the setup was checked that day.

## Trying it without an instrument

Every window runs without hardware. In **Instruments**, set the
connection to **Demo** and press **Connect**, or choose **Run demo
instead** when a connection fails. The readings come from a simulated
1 kΩ resistor, and the status reads **DEMO - simulated** so a demo run is
never mistaken for a measurement.

## Safety at the bench

- **Close windows with their own close button.** That is what switches
  the outputs off and releases the instruments. The suite starts with no
  console for this reason: closing a console would stop the program
  before it could switch anything off.
- **Treat the fixture as live whenever the output lamp is green**, and
  check it before touching the sample.
- **Output off does not always disconnect the sample.** By default most
  instruments hold 0 V on it with some current available. Tick **High-Z
  output off** where the sample must be isolated between runs.
- **The Keithley 2611A and 2635B can put 200 V on an open fixture.** Their
  interlock is jumpered on this bench, so opening the lid does not cut the
  output. See their pages under [Instruments](../instruments/index.md).
- **Set the compliance first.** It is what protects the sample. A request
  the connected instrument cannot meet is refused before the output comes
  on, never quietly clipped.
- **Disconnect everything from the outputs before a checkup.** A checkup
  sources real levels; see
  [Running a checkup](../good-data/running-a-checkup.md).
