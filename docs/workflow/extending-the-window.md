---
type: workflow
title: "Adding a panel, an experiment, or a shared control"
---

# Adding a panel, an experiment, or a shared control

The three smaller extensions, each a few lines once you know where they go.
Adding an instrument is a bigger procedure with its own page —
[Adding an SMU](adding-an-smu.md).

## A new panel

Write `build_x_panel(exp, parent)` under the experiment's `panels/`, pack it
into `exp.col_left`, `exp.col_mid` or `exp.col_right`, and add it to that
experiment's `PANELS` list.

**The list is order-independent.** Layout containers are built once in
`Experiment.build_panels()` before any panel function runs, so a panel cannot
be added too early. Which column it lands in is decided by the attribute it
packs into on its first line, not by a registry anybody has to keep in step.
Within a column, `PANELS` order is top-to-bottom order.

Do not override `build_panels()`. If something has to happen once the widgets
exist, override `on_panels_built()`, which it calls at the end. The reasoning,
and the pixel budget a new panel has to stay inside, are
[house rule 1](../rules/01-landscape-layout.md) — including the part that is
easy to miss: **add the experiment to `tests/test_layout.py`'s list or it is
not covered.**

## A new experiment

A folder under `experiments/` holding an `Experiment` subclass that declares
`ROLES`, `PANELS` and `run()`, plus an entry in `WINDOWS` in
`core/launcher.py`.

Read [House rules](../rules/_index.md) first. Landscape layout, the console,
and explicit save-to-CSV results handling are **requirements, not defaults to
opt into** — each of them is there because a specific failure reached real
data without it.

Two costs are collected at this point rather than later, and both are
enforced by the suite: a note under `docs/experiments/` (the bijection is a
test), and the layout list above.

Before writing the folder, check it earns one. The test is whether it
produces a different *derived quantity*: a different sweep shape is a feature
of something that already exists, and a different instrument is a driver. See
[Experiments](../experiments/_index.md), where the argument is worked through
against the case that came closest to failing it.

## A control several experiments want

Put it in `core/gui/widgets.py` as a `*_row()` builder plus `refresh_*()` and
`apply_*()` helpers, driven by a driver capability declaration. NPLC and the
high-Z checkbox both work this way, and the pattern matters more than it
looks: the builder reads the *declaration* to decide whether to offer the
control at all, so an instrument that cannot do the thing shows `n/a` rather
than a control that silently does nothing.

The alternative is what the original scripts did. Three copies of one control
is how they ended up with six drifting versions of `LabeledEntry`, and the
drift is invisible until two of them disagree about a value that reached a
measurement.
