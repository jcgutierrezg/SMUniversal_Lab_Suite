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
