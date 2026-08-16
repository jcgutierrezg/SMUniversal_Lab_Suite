---
type: index
title: "At the bench"
---

# At the bench

For anyone taking a measurement with this suite. No knowledge of how the
software works is assumed, and nothing here requires reading the code.

| Page | Answers |
|---|---|
| [[choosing-an-smu]] | which instrument for this sample, and has it been checked recently |
| [[getting-good-measurements]] | the five settings that decide whether your numbers are right |
| [[running-a-checkup]] | how to confirm an instrument before trusting it |
| [[reading-your-data]] | what every column in the saved CSV means |
| `instruments/` | one page per SMU: what it gets wrong, and what that does to your data |
| `experiments/` | one page per measurement: what changed from the old scripts, and what it means for old files |

## Some of these pages are generated

`choosing-an-smu.md` and everything under `instruments/` and
`experiments/` is built from the developer notes in `docs/`, so the two
cannot drift apart. **Do not edit those** — the next build overwrites
them, and the test suite fails before that. Each one says so in its
first line.

The other three pages have no developer-facing counterpart and are
written by hand.

To change a generated page, edit the matching note under `docs/` and
run:

```powershell
uv run python tools/build_docs.py
```

## If you only read one thing

Measure a known resistor before you trust a session. A 10 kΩ resistor
takes two minutes and tests the whole chain — instrument, wiring,
driver, analysis. Every fault this project has found produced data that
looked entirely reasonable against an unknown sample, and was obvious
against a known one.
