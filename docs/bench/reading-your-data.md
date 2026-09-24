---
type: bench
title: "Reading your data"
---

# Reading your data

## Where the files go

Saving writes **one CSV per sample name**, into the folder chosen on the
session strip. A file is never overwritten — a second save under the
same name gets a suffix — with one exception, the per-sample summary,
described at the bottom.

Nothing is written until you press Save. A run spoiled by a misaligned
sample or a badly seated contact can be deleted without ever leaving a
file behind, which is deliberate. The cost is that **an unsaved run
exists only in memory**, so a crash loses it; the app asks before
closing with unsaved work.

## The shape of a CSV

Two parts. First a header of calculated results, every line beginning
`#`:

```
# Rs_ohm_per_sq: 214.7
# result_id: res-20260813-a1b2c3d4
# method: vdp_sheet_resistance:1
```

Then a long-form table, **one row per raw reading**, with the per-run
values repeated alongside. It loads directly:

```python
df = pd.read_csv(path, comment="#")
```

into a clean numeric frame that `groupby` works on.

Lines end with `\n`, on every platform, and always did on Linux — a save
taken on Windows used to end them `\r\n` from the same code, which was
never a decision anybody made. Nothing you already have needs
converting: `pd.read_csv`, Python's own `csv` module and Excel all read
either form. A script that splits on `\r\n` by hand was already wrong
for half the files. See [the stored-file schema](../reference/schema.md).

## Columns that describe *how* the measurement was taken

These matter more than they look, because they are how two files that
disagree can be compared at all.

| Column | Why it is there |
|---|---|
| `sweep_kind` | whether the instrument swept on its own clock or the PC stepped it. Not equivalent measurements — the spacing comes from different places |
| `output_off_mode` | what happened to the sample *between* readings: driven to 0 V, or the relay opened |
| `nplc` | integration time. On the miniSMU this number orders the settings correctly but its absolute value is not a real integration time |
| `sensing` | 2-wire or 4-wire. On the U2722A it reads `4-wire (hardwired)`, because that instrument cannot be switched |
| stage temperature | recorded per row, not per file, so a run taken while the stage was still settling is visible |
| `bias_gap_s` | on a periodic IV run, the measured time the output was interrupted for a source-function change |
| `compliance_tripped` | on a Fixed source run, whether *that sample* was clamped: `yes`, `no`, or blank when the instrument cannot say. `compliance` beside it is the run's limit. Files saved before schema 3 wrote both under the name `compliance` |
| `compliance_suspected` | on every run of every experiment, `yes` when the data itself looks clamped - readings at 98 % or more of the applied compliance, or three or more readings stuck at the same value while the setpoint changed - or when the instrument reported compliance. The run is kept either way, and a dialog names it when it ends. Works on instruments with no compliance flag, because it reads the numbers rather than asking. The thresholds are starting values, set in `smuniversal_lab_suite/core/clamping.py` |

## Plotting your data

```powershell
uv run python main.py plotter
uv run python main.py plotter D:\data\filmA_iv_sweep.csv
```

or **Plot saved data (CSV plotter)** in the chooser. It opens beside a
running measurement window; it touches no instrument.

**Open files or a whole folder.** Each file is identified by its title
line, its name and its columns. If those disagree — a file renamed by
hand — it still opens, under the title's experiment, with a note saying
so under **Details**.

**Tick a run to plot it; select a row to read it.** The two are separate,
so you can overlay three runs while reading the settings of a fourth.
The first file you open is ticked for you.

**The view list follows what is ticked.** An IV file offers I–V curves,
the current's magnitude on a log axis, V/I per point and fitted
resistance by run; a Fixed
source file its trace against time, the source readback and the timing;
the 4PP, Van der Pauw and Hall files their own. Tick runs from
*different* experiments and the only view left is **Saved value by
run**: one number per run — or per file, for a calculated result — against
time, order, stage temperature or sample. That is how an IV resistance
and a 4PP resistance end up on one axis.

**Nothing is dropped without saying so.** A point that cannot be drawn —
a zero current on a log axis, a blank reading, a run without the value
you picked — is counted in the note under the plot.

**Compare** lists the ticked runs' settings side by side and marks the
rows that differ with `≠`. When two files disagree, look there first:
`nplc`, `sensing` and `sweep_kind` explain most of it.

**Checks** under **Details** are things the file itself records and
that are easy to miss: fewer points returned than asked for, a
compliance applied that is not the one requested, late samples, a run
ended early. They are never the plotter's opinion of your data.

**Drift on a held level.** On a Fixed source file, **Measured against
time** has a **Scale**: the measured value, or the % change from the
first reading or from the run's mean. A 20 nA wander on a 100 µA hold is
hard to see in amps and plain as 0.02 %, and two holds at different
levels only compare on this scale. The note under the plot says what 0 %
is for each run.

**Still measuring? Press Reload.** Each Save during a session writes a
new file (`_1`, `_2`…). **Reload** re-reads what is open and opens the
later saves of those files - not other samples in the folder. Your
ticks and the run you are reading stay put. A file that cannot be read
at that moment (a save still being written) keeps the version already
open, and you are told.

**Taking the data elsewhere.**

- **Export data...** writes every reading of the ticked runs to one CSV:
  one row per reading, with the run, sample, experiment, source file and
  `record_id` first. It opens directly in Excel, and Origin imports it as
  columns.
- **Copy table** on the **Compare** tab puts the settings side by side
  on the clipboard - paste into a spreadsheet or a lab notebook and it
  lands in cells. **Save table...** writes the same thing to a CSV.

An export is a copy for another program, not a measurement: its first
line says so, and the plotter will not open it as data. Keep the saved
files - they carry the provenance an export does not.

A run saved in two overlapping snapshots is shown once. Nothing is ever
written unless you press **Save figure...**, **Export data...** or
**Save table...**.

## Provenance, and why a result has an id

A calculated result carries a `result_id`, the sample identity, the ids
of every run and reading behind it, and the method and its version. That
is what lets a number be traced back to the readings it came from years
later, when the folder has been renamed twice.

A Hall file that used a sheet resistance from Van der Pauw records it as
a **result id**, not a file path:

```
# input_sheet_resistance_from: res-20260813-a1b2c3d4 (vdp_sheet_resistance:1, runs: ...)
```

A file with the older `# Rs_source:` line instead came from before
August 2026 and names a path rather than a measurement. Both mean what
they say; neither spelling appears in both.

## Which software wrote the file

Two lines in the `#` header, and you want the second one:

```
# app_version: 0.1.0
# build_id: 0.1.0+g5e7308eff34a
```

`app_version` is the release number, set by hand and rarely moved.
`build_id` adds the commit, which is what actually answers "is this the
same code as the file next to it?". Paste the twelve characters after
the `g` into `git show` to see exactly what ran.

Three things it can say:

- `0.1.0+g5e7308eff34a` — that commit, clean.
- `...eff34a.dirty` — that commit **plus uncommitted edits**. Someone
  was mid-change. The code that produced this file is not in the
  history and cannot be recovered from it.
- `0.1.0+unknown` — the software could not tell. A copy downloaded as a
  zip, or a packaged build shipped without its stamp.

Files saved before September 2026 have no `build_id` line at all. That
is not the same as `unknown`: it means the software of the day did not
record one.

## Identifiers got longer

Sample, record and result ids gained eight more characters, and run ids
gained a trailing block that identifies the application session:

```
smp-20260808-a3f19c2b7d4e6f81
ossila_4pp-0007-20260808T143012-3f9a1c22b7e04d61
```

The readable part is unchanged and still at the front. The extra
characters are there because two ids could previously collide — most
easily when two bench machines, or one machine restarted, began within
the same second. Old shorter ids in files you already have remain valid
and are still read.

## Stale results, and a header with nothing in it

If you change an input after calculating — a thickness, a sample name —
the result becomes **stale**, and a stale result **does not reach the
CSV header**. Raw data still saves in full.

That is intentional: a header claiming a sheet resistance computed from
inputs you have since changed is worse than no header at all. If a
header is missing numbers you expected, recalculate and save again.

## The one file that replaces itself

The per-sample summary spans both measurements of a sample and is
rebuilt from data still on disk, so it is allowed to replace a previous
version. Whether it does is asked once, at **the first run** that finds
existing files under that sample name — which is also the early warning
that you already have data under this name, before twenty minutes of
measuring rather than after.

A half-measured sample shows `not calculated` explicitly rather than a
blank, so it cannot read as a fully measured one.
