---
type: rule
rule: 2
title: "The console stays"
---

# 2. The console stays

`smuniversal_lab_suite/core/gui/console_panel.py` is built by `LabApp` for every
experiment. Nothing to do per experiment, and **do not remove it.**

It is a window of its own, opened from the Console button in the header
strip. It used to be a panel at the foot of every window, folded away by
a checkbox; that cost ~180 px of the scarcest thing the layout has for
something read during a run and ignored the rest of the time.

**What the rule protects is the log, not the panel.** The lines belong
to `app.console_log`, not to the widget: `app.log()` appends to it from
any thread — see [`app.ui()` is a queue, not a direct
callback](08-ui-is-a-queue.md) — and the window, when there is one, is a
view onto it. Open the console an hour into a session and the whole hour
is there. A log that only records while somebody is watching is not a
log, and that is the property to keep whatever the console looks like
next.

The one bound is `MAX_LINES`, far above a day's logging, so a console
left open for a week cannot grow without limit.

The console is a display. The record that has to survive an
investigation is the operational log in `core/event_log.py`, which is
written separately and does not come through here.
