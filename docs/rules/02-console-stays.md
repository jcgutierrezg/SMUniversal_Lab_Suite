---
type: rule
rule: 2
title: "The console stays"
---

# 2. The console stays

`core/gui/console_panel.py` is built by `LabApp` for every experiment.
Nothing to do per experiment, and **do not remove it.**

It is collapsible via its checkbox, worth about 150 px on a short
screen, and `app.log()` is safe to call from any thread — see
[`app.ui()` is a queue, not a direct callback](08-ui-is-a-queue.md).
