---
type: reference
title: "The look, and how it switches"
---

# The look, and how it switches

`smuniversal_lab_suite/core/gui/theme.py` holds every colour and font the
windows use, in two modes. Dark is the default and looks like the bench
instruments beside the screen. Light is the lab notebook, and reuses the
CSV plotter's paper, ink and gridline colours so a window and its figures
read as one thing.

The button that switches them is in the header strip, top left of every
measurement window, and in the plotter's toolbar. It changes the window
as it stands: no rebuild, no restart, no interruption to a run in
progress. The choice is saved next to the single-instance lock, so the
next launch opens in it.

## One switch, three kinds of widget

A mode change reaches the window by three different routes, because Tk
offers no single one.

| Kind | How it follows | Examples |
|---|---|---|
| ttk widgets | named styles; reconfiguring a style repaints everything using it | every panel, button, entry, table |
| plain Tk widgets | a callback registered with `Theme.on_change()` | the console, the corner diagram, the lamp's ground, tooltips, the Equations window, the 4PP drawing |
| matplotlib figures | redrawn; `style_axes()` reads the palette on every redraw | the live plot on each tab |

This is why **a panel never passes a literal colour**. It names what a
label *is* - `Hint`, `Warn`, `Good`, `Bad`, `Stale`, `NType` - and the
palette decides what that looks like in each mode. `tests/test_theme.py`
fails if a literal colour appears anywhere but the three files that are
allowed one.

A plot is styled on *every* redraw rather than once, because
`Axes.clear()` resets the face, the spines and the tick colours, and
every redraw starts with one.

## What the mode must never change

The safety cues. Stop is red, the output lamp is green while the output
is live, a connection is green when made and red when not - in both
modes and on every tab. An operator who learnt "green lamp means live"
on one window must not have to relearn it on another, and that is worth
more than a consistent palette.

The lamp is the one widget outside `theme.py` allowed to name its own
colours, for exactly this reason.

## The accent is identity, not status

Each experiment owns a colour: it fills the header strip's bar, the
panel titles, the focus ring, Run, the progress bar and a ticked box. It
says *which measurement this window is*, and nothing else. Plot lines
keep the plotter's categorical palette, so an accent never stands for a
run.

In the Van der Pauw + Hall window the accent follows the tab in front,
because those tabs are two measurements sharing a session rather than
two views of one. Each tab also carries a dot in its own colour, which
is the only way ttk will let one tab look different from another.

A sixth experiment picks its colour by setting `THEME_KEY` and adding an
entry to `ACCENTS`; `tests/test_theme.py` fails until it does.

## Constraints worth knowing before changing this

**Legibility is a test, not a judgement.** Every text colour is checked
against WCAG AA on every ground it can sit on, in both modes, and each
accent is checked twice: as text, and as a fill under white or near-black
text. The light 4PP orange is `#b4481a` rather than the mockup's
`#c24f1d` because the lighter one missed by 0.2.

**The height budget is the binding constraint.** `tests/test_layout.py`
gives 4PP twenty spare pixels. That is why the header strip shares a row
with the Instruments panel, why light-mode headings are Cambria at 9
rather than 11, and why table rows are two pixels above the font's line
height rather than five - eight rows of a table multiply.

**Fonts must exist.** Only faces that ship with Windows 11 are named -
Segoe UI, Cambria, Bahnschrift, Cascadia Mono - each with fallbacks,
because CI also runs on Linux where none of them do. `resolve_family()`
picks the first installed.

**`clam`, not the native theme.** The Windows `vista` theme draws its
own widgets and ignores background colours, so there is no dark mode on
it.

**What Tk cannot do**: small caps (light-mode panel titles are Cambria,
not the small caps of the mockup); coloured tabs (hence the dots);
and the system dialogs - message boxes and file pickers - which Windows
draws in its own colours whatever the window does.

## The plotter is a deliberate exception

Its chrome follows the mode. Its figures do not: they stay on paper in
both modes, because they are the plotter's output - what gets saved and
put in a report - and the palette they use was checked for colour vision
on that ground. A dark copy would be a palette nobody has validated. See
[The CSV plotter](plotter.md).
