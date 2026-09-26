"""
The header strip: which experiment this window is, and the mode button.

One row, at the top left, beside the Instruments panel rather than above
it - the connection row never filled the width, and the window's height
budget has no spare row in it (see `tests/test_layout.py`).

It carries four things:

* an **emblem**, drawn on a canvas: the sample setup this experiment
  measures, in its own colour;
* the **name** and, under it, what the experiment measures - both split
  from the experiment's own `NAME`, so there is one place to change it;
* the **mode button**, which switches dark and light in place.

In the Van der Pauw + Hall window the strip follows the tab in front:
the accent, the emblem and the name all change with it, because those
two tabs are two measurements sharing one window rather than two views
of the same one.
"""
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui.help_link import help_button
from smuniversal_lab_suite.core.gui.theme import theme_for
from smuniversal_lab_suite.core.gui.tooltips import tip

#: The emblem's drawing area, in pixels. Square, and small enough that
#: the strip stays shorter than the connection panel beside it.
EMBLEM_SIZE = 40


def split_name(name):
    """`NAME` as (title, what it measures).

    Every experiment already names itself as "Van der Pauw - sheet
    resistance", so the subtitle is not a new thing to write and keep in
    step - it is the half of the name the tab strip throws away.
    """
    title, separator, subtitle = name.partition(" - ")
    return (title, subtitle) if separator else (name, "")


def build_header(app, parent):
    """Build the strip. Sets app.header_*; returns the frame."""
    frame = ttk.Frame(parent, style="Header.TFrame", padding=(10, 6))

    # The accent bar: down the left in dark, under the strip in light.
    # Two modes, two conventions - `_place_bar` moves it on a switch.
    app.header_bar = ttk.Frame(frame, style="AccentBar.TFrame")

    app.header_emblem = tk.Canvas(frame, width=EMBLEM_SIZE,
                                  height=EMBLEM_SIZE, highlightthickness=0)
    app.header_emblem.grid(row=0, column=1, rowspan=2, padx=(6, 10))
    tip(app.experiment, app.header_emblem,
        "Which measurement this window makes. Its colour runs through "
        "the window - panel titles, Run, the progress bar - so windows "
        "side by side are told apart at a glance.",
        name="Window emblem")

    app.header_title_var = tk.StringVar(value="")
    ttk.Label(frame, textvariable=app.header_title_var,
              style="Title.Header.TLabel").grid(row=0, column=2, sticky="w")

    app.header_subtitle_var = tk.StringVar(value="")
    ttk.Label(frame, textvariable=app.header_subtitle_var,
              style="Sub.Header.TLabel", wraplength=200,
              justify="left").grid(row=1, column=2, sticky="w")

    app.header_mode_btn = ttk.Button(frame, width=7,
                                     command=lambda: _toggle(app))
    # Light/Dark over [?], stacked rather than side by side: the strip
    # already has two rows, and a third button across would widen the
    # top row every window is budgeted on.
    app.header_mode_btn.grid(row=0, column=3, sticky="w", padx=(14, 0))
    tip(app.experiment, app.header_mode_btn,
        "Switch between the dark and light look. It changes this window "
        "as it stands - nothing is restarted, a run in progress is not "
        "disturbed - and the choice is remembered for next time.",
        name="Light / Dark")

    # The guide page of whichever tab is in front, asked at the press.
    app.header_help_btn = help_button(
        frame, lambda: app.experiment.GUIDE_PAGE, owner=app.experiment,
        log=app.log)
    app.header_help_btn.grid(row=1, column=3, sticky="w", padx=(14, 0),
                             pady=(2, 0))

    theme_for(parent).on_change(lambda theme: _repaint(app, theme),
                               widget=frame)
    return frame


def _toggle(app):
    theme_for(app.root).toggle()


def _repaint(app, theme):
    """Redraw the strip for the mode and the experiment in front."""
    _place_bar(app, theme)
    app.header_mode_btn.configure(text="Light" if theme.is_dark else "Dark")
    app.header_emblem.configure(background=theme.palette.header)
    refresh_header(app)


def _place_bar(app, theme):
    """The accent bar, where each mode puts it.

    Dark wears it as a stripe down the left edge, like the coloured band
    on a rack instrument. Light rules it under the strip, the way a
    heading is underlined on paper.
    """
    bar = app.header_bar
    bar.grid_forget()
    if theme.is_dark:
        bar.configure(width=5)
        bar.grid(row=0, column=0, rowspan=2, sticky="ns")
    else:
        bar.configure(height=3)
        bar.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))


def refresh_header(app):
    """Point the strip at the experiment in front.

    Called on a tab change as well as on a switch, because in the
    Van der Pauw + Hall window the two tabs are different experiments.
    """
    experiment = app.experiment
    theme = theme_for(app.root)
    theme.set_accent(experiment.THEME_KEY)
    title, subtitle = split_name(experiment.NAME)
    app.header_title_var.set(title)
    app.header_subtitle_var.set(subtitle)
    draw_emblem(app.header_emblem, experiment.THEME_KEY, theme)


# --- the emblems ---------------------------------------------------------
#
# Each is the sample setup its experiment measures, drawn rather than
# shipped as an image: a canvas follows the theme, takes the window's
# scaling, and needs no asset to keep in step with the palette. The
# coordinates below are on a 48x48 grid, scaled to the canvas.

def draw_emblem(canvas, key, theme):
    """Draw `key`'s emblem in the accent colour, replacing any before."""
    canvas.delete("all")
    accent = theme.accent_of(key)
    scale = int(canvas.cget("width")) / 48.0

    def xy(*points):
        return [value * scale for value in points]

    def line(*points, width=2.2, smooth=False):
        canvas.create_line(*xy(*points), fill=accent, width=width * scale,
                           smooth=smooth, capstyle="round")

    def oval(x0, y0, x1, y1, fill=None, width=2.0):
        canvas.create_oval(*xy(x0, y0, x1, y1), outline=accent,
                           fill=fill or "", width=width * scale)

    drawing = _EMBLEMS.get(key, _EMBLEMS["neutral"])
    drawing(line, oval, accent, canvas, xy, scale)


def _iv(line, oval, accent, canvas, xy, scale):
    """A diode's I-V curve against its axes."""
    canvas.create_line(*xy(4, 30, 44, 30), fill=accent, width=scale)
    canvas.create_line(*xy(16, 44, 16, 4), fill=accent, width=scale)
    line(4, 31, 14, 31, 22, 30, 28, 24, 32, 12, 36, 5,
         width=2.6, smooth=True)


def _vanderpauw(line, oval, accent, canvas, xy, scale):
    """A square sample with a contact at each corner."""
    canvas.create_rectangle(*xy(12, 12, 36, 36), outline=accent,
                            width=2.2 * scale)
    for cx, cy in ((12, 12), (36, 12), (36, 36), (12, 36)):
        oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=accent)


def _hall(line, oval, accent, canvas, xy, scale):
    """A field through the sample, and the carriers pushed sideways."""
    canvas.create_rectangle(*xy(6, 12, 42, 36), outline=accent,
                            width=2.2 * scale)
    oval(28, 15, 37, 24, width=1.4)
    oval(31.5, 18.5, 33.5, 20.5, fill=accent, width=1.0)
    line(10, 31, 18, 31, 24, 31, 27, 25, width=2.2, smooth=True)
    line(23, 26, 27, 25, 28, 29, width=2.0)


def _ossila_4pp(line, oval, accent, canvas, xy, scale):
    """Four probes in a line, touching down on the sample."""
    canvas.create_line(*xy(4, 38, 44, 38), fill=accent, width=2.2 * scale)
    for x in (12, 20, 28, 36):
        line(x, 8, x, 32, width=2.4)
        canvas.create_polygon(*xy(x - 2, 32, x + 2, 32, x, 37),
                              fill=accent, outline=accent)


def _fixed_source(line, oval, accent, canvas, xy, scale):
    """A level held flat over time."""
    canvas.create_line(*xy(6, 6, 6, 42, 44, 42), fill=accent, width=scale)
    line(8, 36, 13, 36, 13, 16, 44, 16, width=2.6)


def _neutral(line, oval, accent, canvas, xy, scale):
    """The launcher and the plotter: axes and a trace, no experiment."""
    canvas.create_line(*xy(8, 8, 8, 40, 42, 40), fill=accent, width=scale)
    line(10, 34, 20, 22, 28, 28, 40, 12, width=2.4)


def tab_dot(widget, colour, size=10):
    """A small square of `colour`, for a notebook tab's label.

    ttk cannot colour one tab differently from another, so the tab's
    own accent is shown as an image beside its text - which is also
    what tells the operator that the tab they are *not* on has an
    identity of its own.
    """
    image = tk.PhotoImage(master=widget, width=size, height=size)
    image.put(colour, to=(0, 0, size, size))
    return image


def refresh_tab_dots(app, theme):
    """Give every tab a dot in its own experiment's colour."""
    notebook = getattr(app, "notebook", None)
    if notebook is None:
        return
    # Held on the app: Tk keeps no reference of its own, and an image
    # that is garbage collected silently blanks.
    app._tab_dots = [tab_dot(notebook, theme.accent_of(exp.THEME_KEY))
                     for exp in app.experiments]
    for index, image in enumerate(app._tab_dots):
        notebook.tab(index, image=image, compound="left")


_EMBLEMS = {
    "iv_sweep": _iv,
    "vanderpauw": _vanderpauw,
    "hall": _hall,
    "ossila_4pp": _ossila_4pp,
    "fixed_source": _fixed_source,
    "neutral": _neutral,
}
