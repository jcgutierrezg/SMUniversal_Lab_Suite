---
type: index
title: "Manual extracts"
---

# Manual extracts

Command summary tables and per-attribute reset-default tables,
transcribed from the instrument manuals into Markdown.

## What is here

- [GSM-20H10 reset defaults](gsm-20h10-reset-defaults.md) — the Factory Settings
  table, pp. 160–164, confirmed against the instrument.
- [GSM-20H10 output and source commands](gsm-20h10-output-and-source.md) — `:OUTPut`,
  `:SOURce:CLEar`, `:INITiate`, `:ROUTe:TERMinals`.

The rest arrive as each driver's note is written.

## Why transcribe at all

The PDFs are not in the repository (see `manuals/README.md`), and even
where they are on disk, a PDF cannot be grepped, diffed, or linked to
from a driver note. These two tables are the parts every driver here was
actually written from.

The reset-default table is the one that keeps earning its place: every
driver written from a manual so far has had at least one setting whose
reset value had to be overridden, and in the worst cases there was no
command in the log to trace the behaviour back to. Read the *Affected
by* column — a setting that reset does not touch needs the opposite
treatment from one it does.

## The honest cost

A table transcribed by hand is a table that can be transcribed wrong,
and a wrong reset default produces a driver that is confidently
incorrect. So each one is checked against the PDF once, at the point of
writing, and thereafter it is the reference. Where a value could not be
read with confidence it is recorded as unknown rather than guessed —
the same rule the frontmatter applies to `*IDN?` strings.
