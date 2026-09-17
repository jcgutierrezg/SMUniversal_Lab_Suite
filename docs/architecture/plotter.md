---
type: reference
title: "The CSV plotter"
---

# The CSV plotter

`smuniversal_lab_suite/plotter/` is one window for every experiment's
saved files. It is offered by the launcher as a choice of its own —
`python main.py plotter [files...]` — and it works out which experiment
wrote each file itself, so opening a file is the whole of the setup.

It reads files and nothing else. No instrument, no `LabApp`, no run
lifecycle, and nothing written unless **Save figure...**, **Export
data...** or **Save table...** is pressed - each of which asks where.

## The modules

| Module | Holds | Tk? | Without it |
|---|---|---|---|
| `plotter/reader.py` | `parse()`/`load()`: the `#` header split into file details and the calculated block, the table grouped back into runs by `record_id`, each column filed as a run setting or a reading | no | nothing to plot. Checked by mypy with the other boundaries |
| `plotter/detect.py` | `ExperimentKind` per experiment, `detect()` | no | a file opens as columns with no idea what they mean. Checked by mypy |
| `plotter/session.py` | open files, ticked runs, colour slots, duplicate runs across overlapping snapshots | no | a run saved twice is drawn twice, and colours jump when a run is unticked |
| `plotter/views.py` | `View`, `Option`, `Choice`, one drawing function per view, `VIEWS` | no | the plot |
| `plotter/describe.py` | curated settings per experiment, checks, the side-by-side comparison, unit lookup | no | the details beside the plot are a dump of column names |
| `plotter/style.py` | palette, chrome, line and marker specs | no | every view picks its own colours |
| `plotter/export.py` | the readings export and the settings table, as text; `write_text()` through a temporary file | no | the data stays in the plotter, and gets retyped into whatever is used next |
| `plotter/window.py` | `PlotterWindow`, `main()` | yes | there is no window |

Everything above the window runs headless, which is why the tests can
draw every view onto a bare `Figure` and read back what was drawn.

## Detection: three clues, all evaluated

The title line (`CSV_TITLE`), the file name (`<sample>_<CSV_SLUG>.csv`,
with or without a `_1` save suffix) and a column signature. The
strongest clue that matches decides, and **every other clue is still
checked**: a Hall file renamed `_iv_sweep.csv` opens as Hall with a note
saying the name disagrees. A plotter that stopped at the first match
would draw IV curves from Hall data and say nothing.

The titles and slugs are copies rather than imports, because importing
the experiment classes would build Tk panels and the driver registry to
read five strings. The copies are pinned instead:

- `tests/test_plotter_detect.py` fails if a copy stops matching the
  experiment's `CSV_TITLE` or `CSV_SLUG`, or if a window in `WINDOWS`
  hosts an experiment the plotter has no kind for;
- `tests/test_plotter_real_files.py` (slow) saves a file from every
  experiment in demo mode and checks the column signature and the
  declared reading columns against it, and that no column name repeats.

## Settings and readings

A column is a **reading** if the experiment declares it as one, or if
its value changes within any run. Either rule alone is wrong: a column
the plotter has never heard of is only found by variation, and a
declared one that happens to hold one value throughout — every sample
unclamped — is only found by declaration.

An empty cell is NaN **in its own position**, never dropped; see
[Sentinels read as data](../faults/03-sentinels-as-data.md). Repeated
column names are kept apart as `name#2` and reported, which is how
[One column name written twice](../faults/47-one-column-name-written-twice.md)
was found.

## Which files it reads

Schema 2 onwards. Saved data is taken to start at 2026-09-16, so there
is no fallback for a file without `schema` or `record_id`; such a file
is refused with the reason, rather than half-read. A newer schema is
read with a warning. See [the stored-file schema](../reference/schema.md#stored-file-schema).

## The lock

The plotter neither needs nor keeps the single-instance lock
(`core/launcher.py`, `needs_instrument_lock()`). The lock exists so two
copies never command one instrument, and holding it would stop a
measurement window opening while old data is on screen — which is when
the plotter is most wanted. With another copy running, the chooser
greys the measurement windows, says why, and still offers the plotter.

## Reloading a session that is still saving

Every Save writes the whole store to a new file - `filmA_iv_sweep.csv`,
then `_1`, `_2` - so a plotter opened at lunchtime shows the lunchtime
file. **Reload** (`Session.reload()`) re-reads every open file and opens
the *later* saves of each one.

What it deliberately does not do:

- **Open every CSV in the folder.** Other samples live there too, and
  nobody asked for them. The match is the save's base name plus a
  higher `_N` than the one open.
- **Reopen an older save.** If `_2` is open, `_1` stayed closed on
  purpose.
- **Drop a file it could not re-read.** A save caught half-written, or a
  file moved away, keeps the copy already open and is reported. Losing
  it would untick runs and redraw the plot because a read failed.

Ticks, colours and the selected run survive, because all of them are
keyed on `record_id` and a later snapshot carries the same ids. A run
that is gone from every open file is unticked.

## Exports

**Export data...** (`export.build_readings_csv`) writes every reading of
the ticked runs, one row per reading, with the run's name, sample,
experiment, source file and `record_id` in front: long form, the same
shape the suite saves, so it filters and pivots without reshaping.
Numbers keep full precision and a missing reading stays a blank cell.

**Copy table** and **Save table...** (`export.build_compare_table`) are
the Compare tab: settings down, runs across, and a `differs` column in
words. Tab-separated on the clipboard so a paste lands in cells;
comma-separated in a file.

An export is **not a saved measurement**, and cannot pass for one. Its
header says `CSV plotter export - not a saved measurement` and names the
files it came from, and it has no `schema` line, so the plotter refuses
to open it as data. Choosing an open data file as the destination is
refused: an export in place of the file it came from would destroy the
only copy with the full header and provenance.

## Rules the views keep

- **One y-scale per panel.** Different units get stacked panels sharing
  the x-axis; there is no second y-axis anywhere.
- **Nothing is dropped silently.** A zero current on a log axis, a blank
  reading, a run without the chosen value — each is counted in a note
  under the plot.
- **Identity is never colour alone.** Two or more runs get a legend;
  polarity is a filled or open marker; a compliance trip is a cross in
  the status colour with its own legend entry.
- **Colour follows the run.** A run keeps its palette slot while ticked.
  Past eight runs there is no ninth hue: every curve is coloured by time
  on a single-hue ramp, which is what that many curves are for.
- **A rescaled axis states its reference.** The Fixed source trace as a
  percentage change says under the plot what 0 % is for each run, and a
  zero or missing reference draws nothing rather than a percentage of
  nothing. Only the measured trace rescales; the source readback does
  not, because its job is to show the absolute level held.
- **Checks state what the file records.** Fewer points returned than
  requested, a compliance applied that differs from the one requested,
  late samples. Never a threshold of the plotter's own.

## Adding an experiment

The suite makes the plotter part of the cost, at the time it is cheap:

1. an `ExperimentKind` in `detect.py`, with its title, slug, a column
   signature no other kind's columns contain, and its reading columns;
2. its curated settings in `describe.CURATED`;
3. at least one `View` in `views.VIEWS`. The comparison view covers it
   from the start, so a first version can be small;
4. a case in `tests/test_plotter_real_files.py` and fixtures in
   `tests/plotter_files.py`.
