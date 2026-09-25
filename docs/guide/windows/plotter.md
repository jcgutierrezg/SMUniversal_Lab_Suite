---
type: guide
title: "Plot saved data"
---

# Plot saved data

A window for looking at files you have already saved, from any
measurement window: plot runs together, compare the settings they were
taken with, and export the numbers. It never talks to an instrument, so
it opens even while a measurement window is running. Choose **Plot saved
data** from the start-up window.

![The plotter with two IV sweeps open and their settings compared](../../assets/screens/plotter/window-light.png#only-light)
![The plotter with two IV sweeps open and their settings compared](../../assets/screens/plotter/window-dark.png#only-dark)

## Opening files

Press **Open files...** or **Open folder...**. The plotter works out
which window saved each file on its own, so opening is the whole of the
setup. The first file's runs are plotted straight away. Files from
different windows can be open together.

A file that cannot be read is listed with the reason, and the rest still
open.

**Following a session still in progress.** Each save in a measurement
window writes a new numbered file. Press **Reload** to read the open
files again and pick up any newer saves of them.

## Plotting and comparing

- **The box beside a run** puts it on the plot. **Selecting a row** shows
  that run in the panel on the right. The two are separate on purpose, so
  you can plot three runs while reading the settings of a fourth.
- **View** chooses how the ticked runs are drawn. Only views that suit
  every ticked run are offered, and the line under it says what the view
  shows. Some views add options of their own beside it.
- **Rest the pointer on a point** to read its values. The toolbar under
  the plot zooms and pans.
- **Notes under the plot** say what a view left out, and why.

The panel on the right has three tabs:

| Tab | Shows |
|---|---|
| **Details** | everything recorded about the selected run: its settings, its results, and anything flagged |
| **Compare** | the ticked runs' settings side by side. Settings that differ are marked ≠ and shaded, and **Only settings that differ** hides the rest |
| **Data** | the selected run's readings |

**Compare is the first place to look when two runs disagree.** A
different integration time, sensing mode or compliance explains more
surprising results than the sample does.

## Getting things out

Nothing is written unless you ask, and each of these asks where:

- **Save figure...** saves the plot as an image.
- **Export data...** writes the ticked runs' readings to one CSV, for a
  spreadsheet or another program.
- **Save table...** / **Copy table** save or copy the Compare table.

An export can never overwrite one of the open measurement files.

## The panels

<!-- generated:controls plotter -->
### Toolbar

![The Toolbar panel](../../assets/screens/plotter/toolbar-light.png#only-light)
![The Toolbar panel](../../assets/screens/plotter/toolbar-dark.png#only-dark)

| Control | What it does |
|---|---|
| **Open files...** | Choose saved CSV files to open. Files from any window can be open together; the first file's runs are plotted straight away. |
| **Open folder...** | Open every CSV in a folder at once - a day's work, for example. |
| **Close file** | Close the file selected in the list. The file on disk is not touched. |
| **Close all** | Close every open file. Nothing on disk is touched. |
| **Reload** | Read the open files again, and open any newer saves of them. A session still measuring saves a new numbered file each time, so this keeps up with it. |
| **Save figure...** | Save the plot as an image. It asks where; nothing is written otherwise. |
| **Light / Dark** | Switch between the dark and light look. The plot stays on white paper either way, as it will be saved. |
| **Export data...** | Write the ticked runs' readings to one CSV, for a spreadsheet or another program. It asks where; the measurement files are never overwritten. |

### Files and runs

![The Files and runs panel](../../assets/screens/plotter/files-and-runs-light.png#only-light)
![The Files and runs panel](../../assets/screens/plotter/files-and-runs-dark.png#only-dark)

Every open file, and the runs inside it. The box beside a run puts it on the plot; selecting a row shows its settings in Details and its readings in Data.

| Control | What it does |
|---|---|
| **File list** | Click a run's box, or press Space, to plot it; click a row to read it. Points is how many readings the run has; Key value is its headline result - a resistance, a sheet resistance. |
| **Tick file's runs** | Plot every run in the selected file. |
| **Untick all** | Take every run off the plot. |

### Plot

![The Plot panel](../../assets/screens/plotter/plot-light.png#only-light)
![The Plot panel](../../assets/screens/plotter/plot-dark.png#only-dark)

The ticked runs, drawn in the chosen view. Notes under the plot say what was left out of it, and why.

| Control | What it does |
|---|---|
| **View** | How the ticked runs are drawn. Only views that suit every ticked run are offered, and the line under it says what the view shows. |
| **Plot** | Rest the pointer near a point to read its values. Zoom and pan with the toolbar below; its home button puts the view back. |

### Details, Compare and Data

![The Details, Compare and Data panel](../../assets/screens/plotter/details-compare-and-data-light.png#only-light)
![The Details, Compare and Data panel](../../assets/screens/plotter/details-compare-and-data-dark.png#only-dark)

| Control | What it does |
|---|---|
| **Tabs** | Details: everything recorded about the selected run. Compare: the ticked runs' settings side by side. Data: the selected run's readings. |
| **Details** | Everything recorded about the selected run: the settings it was taken with, its results, and anything flagged about it. |
| **Only settings that differ** | Hide the settings every ticked run shares, leaving the ones that could explain a difference between them. |
| **Copy table** | Copy the comparison to the clipboard, ready to paste into a spreadsheet. |
| **Save table...** | Save the comparison as a CSV. It asks where. |
| **Comparison table** | The ticked runs' settings side by side, one column per run. A setting that differs between them is marked ≠ and shaded. |
| **Readings table** | The selected run's readings - the first 2000 rows. Every row is in the file, and in Export data. |
<!-- /generated:controls -->
