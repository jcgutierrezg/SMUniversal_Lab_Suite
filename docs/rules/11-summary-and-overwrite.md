---
type: rule
rule: 11
title: "The per-sample summary, and its one overwrite"
---

# 11. The per-sample summary, and its one overwrite

Two things under one heading because they are one decision: a summary
file spanning both measurements of a sample, and the only place in the
suite where a file may replace itself.

**The summary is written by the app, from each experiment's
declaration.** An experiment lists its headline quantities in
`SUMMARY_QUANTITIES` — `(result-key, label, unit)` — and the base
`summary_contribution(sample_id)` turns them into rows, or `None` when
nothing is calculated. `write_sample_summary` asks every hosted
experiment and lays out whatever comes back. Same capability pattern as
`provide()`, and for the same reason: **the app must not know the shape
of any experiment's result.** A per-experiment writer was rejected — it
would produce two half-summaries, one clobbering the other, because each
tab saves separately.

- **A missing half is a row, not a gap.** `not calculated` is written
  explicitly, so a part-finished sample cannot read as a fully measured
  one. That is the whole reason the file is structured rather than free
  text.
- **Stale reads as not-calculated for free**, because
  `summary_contribution` goes through `calculated_fields()`. The summary
  inherits the staleness gate with no second copy of the logic.
- **A `PermissionError` is swallowed, not raised.** The summary is
  written after the data CSVs and outside their `try`. On Windows a
  summary open in Excel makes `os.replace` raise, and that must degrade
  to a logged warning: the measurement data is already safe, and a stale
  convenience file must never turn a good save into a reported failure.

**The overwrite.** Every data CSV auto-suffixes through
`unique_filename` and cannot be lost; the summary is derived from files
still on disk, so it may replace itself. Whether it does is decided once
by `summary_collision_decision` at the **first run** — not the first
save — that finds files already under the sample's name. Run rather than
save, because by save time the runs already carry the identity they were
measured under, and the check's real value is the early "you already
have data under this name" warning *before* twenty minutes of measuring.

The decision is keyed by `(sample, folder)` and re-armed when either
changes. The sample-name trace fires on every write **including
re-setting the box to its current value**, so `note_sample_context_changed`
compares against the last pair it acted on and returns early when
nothing moved. Without that, a chosen overwrite silently turned back
into a suffix before Save ran — a real trap found by mutation, not a
hypothetical.
