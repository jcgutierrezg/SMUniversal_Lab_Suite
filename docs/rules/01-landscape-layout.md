---
type: rule
rule: 1
title: "Landscape three-column layout"
---

# 1. Landscape three-column layout

Monitors are wide and short. Before this was fixed, Hall's window was
**1333 × 1219** — taller than a 1080p desktop, so the Run button sat
below the bottom edge and **nothing reported an error.**

`Experiment.build_panels()` builds three columns. **Do not override it.**
If you need to act once the widgets exist, override `on_panels_built()`,
which it calls at the end. An override that forgot `super()` would
silently produce no columns, and every panel would fail looking for
them.

A panel picks its column by packing into the matching attribute on its
first line:

| Column | Holds | Question it answers |
|---|---|---|
| `exp.col_left` | diagram, position, temperature stage | what is the sample doing |
| `exp.col_mid` | measurement setup, Run / Stop | what am I about to run |
| `exp.col_right` | results table, calculation, plots | what came out |

Reading order is left to right in workflow order; within a column,
`PANELS` order is top to bottom.

Budget: **≤1600 × 1000 px, aspect ≥1.2**, enforced by
`tests/test_layout.py` — **add a new experiment to its `EXPERIMENTS`
list** or it is not covered.

If a column gets too wide, look at which one is *short*. The trick that
saved 350 px on both setup panels was converting side-by-side pairs into
a single column of rows: spending height in the column that had it
spare.

**The pixel budget is a tripwire, not a guard.** Wave 5c added a
reminder under the sample box that passed every test on the development
machine and failed Ubuntu CI at 1010 px against the 1000 px budget,
because the runner's fonts are larger. On a slightly *smaller* font it
would have reported nothing while the window grew. So the specific
failure has a structural guard of its own —
`test_the_session_strip_stays_one_row_tall` — which fails identically
everywhere. Use the budget for "this got a lot bigger"; it is a poor
guard for "this got slightly bigger on some machines".
