---
type: guide
title: "Every window"
---

# Every window

Every measurement window is built the same way: a header strip across
the top, an **Instruments** panel to connect with, the measurement's own
settings on the left, **Run** and **Stop** under them, and the results
table and plot on the right. This page covers the parts they share. Each
window's own page covers the rest.

The pictures are of the IV sweep window. The others differ only in their
colour and in what their panels hold.

## The usual order

1. **Connect.** In **Instruments**, pick how the instrument is attached
   (usually **VISA**), pick it from the address list, and press
   **Connect**. The status turns to the instrument's name. If the list is
   empty, press **Refresh** after switching the instrument on.
2. **Name the sample.** The sample name goes into every saved file's name
   and into the file itself.
3. **Set up** the measurement in the window's own panels, then press
   **Run**. The output lamp is green while the sample is live.
4. **Look** at the result in the table and the plot. Runs stay in the
   table until you save or discard them, so a spoiled run can be deleted
   before anything is written.
5. **Save.** Press **Save snapshot → CSV**. Nothing reaches the disk until
   you do.

<!-- generated:controls shared -->
## Header strip

![The Header strip panel](../../assets/screens/shared/header-strip-light.png#only-light)
![The Header strip panel](../../assets/screens/shared/header-strip-dark.png#only-dark)

| Control | What it does |
|---|---|
| **Window emblem** | Which measurement this window makes. Its colour runs through the window - panel titles, Run, the progress bar - so windows side by side are told apart at a glance. |
| **Light / Dark** | Switch between the dark and light look. It changes this window as it stands - nothing is restarted, a run in progress is not disturbed - and the choice is remembered for next time. |
| **Stage...** | The stage's controls - port, Connect, setpoint and PID - in a window of its own. The reading beside this button is live whether that window is open or not. |
| **Console** | Open the log in its own window. It records everything this window does whether it is open or not, so opening it later still shows the whole session. |
| **Show tooltips** | Hover help on the panels and the fields inside them. On by default; switched off, it stays off until this window closes. |

## Instruments

![The Instruments panel](../../assets/screens/shared/instruments-light.png#only-light)
![The Instruments panel](../../assets/screens/shared/instruments-dark.png#only-dark)

The instrument this window measures with. Pick how it is attached, pick its address, and Connect - the model is recognised from its own reply, and a model this tab cannot use is refused rather than connected.

| Control | What it does |
|---|---|
| **Connection** | How the instrument is attached: VISA for GPIB, USB and LAN instruments; NI GPIB-HS to drive an NI GPIB-USB-HS adapter directly; Serial for RS-232; miniSMU for the Undalogic board; Demo for a simulated sample. Changing it rescans for addresses. |
| **Address** | Where the instrument answers. The list shows this bench's instruments by name; you can also type an address, which is opened exactly as written. Tick All addresses to see everything the scan found. |
| **Refresh** | Scan again for instruments on the chosen connection - after plugging one in or switching one on. The console lists what was found, per backend. |
| **Connect** | Open the address, identify the model and take charge of it. Once connected this becomes Disconnect, which switches the output off before releasing the instrument. |
| **All addresses** | Off: only this bench's instruments - every GPIB address, and the USB and serial devices that are instruments. On: every address the scan returned, including ports that are not instruments at all. |

## Run controls

![The Run controls panel](../../assets/screens/shared/run-controls-light.png#only-light)
![The Run controls panel](../../assets/screens/shared/run-controls-dark.png#only-dark)

| Control | What it does |
|---|---|
| **Run** | Take the settings as they are now and measure. Nothing typed after this press changes the run in flight, and nothing is saved to disk until you press Save. |
| **Stop** | Cancel the run and discard its readings. The output is taken down by the thread that owns the instrument, so it happens at the next safe point rather than instantly. |
| **Output lamp** | Green while the instrument's output is on and the sample is live. It follows the run, not the button. |
| **Progress bar** | How far through the run is, and roughly how long is left. An estimate from the settings until a few readings are in, then the pace those readings are actually arriving at. |

## Results

![The Results panel](../../assets/screens/shared/results-light.png#only-light)
![The Results panel](../../assets/screens/shared/results-dark.png#only-dark)

The runs of this session, held in memory until saved. Tick a row with the box at its left; the buttons below act on the ticked rows.

| Control | What it does |
|---|---|
| **Delete ticked** | Discard the ticked runs and their readings. This is why nothing saves automatically: a run spoiled by a poor contact never reaches the disk at all. |
| **Clear all** | Empty the table and the plot. If anything in it has not been saved you are asked first. |
| **Save snapshot → CSV** | Write every run in the table to CSV, one file per sample. Nothing reaches disk until you press this; the table can be saved again as it grows. |

## Plot

![The Plot panel](../../assets/screens/shared/plot-light.png#only-light)
![The Plot panel](../../assets/screens/shared/plot-dark.png#only-dark)

The runs ticked in the table above, or the newest run when none is ticked. The toolbar zooms and pans, and saves the figure as an image - the data itself is saved from the table.

| Control | What it does |
|---|---|
| **Plot title** | The heading drawn over the plot, and on the image when the figure is saved from the toolbar. Press Redraw to apply it. |
| **Overlap runs** | Ticked: every run you have ticked in the table shares the axes. Unticked: only the newest of them is drawn. |
| **Redraw** | Draw the plot again from the table - after changing the title, or to reset a zoom. |
| **Plot** | The ticked runs, or the newest one when none is ticked. Zoom or pan with the toolbar below; Redraw puts it back. |
<!-- /generated:controls -->
