"""
Console panel - the scrolling log every experiment shares, and the
window-wide tooltip switch beside it.

Collapsible, because it is the one part of the window that is useful
during a run and mostly dead weight the rest of the time. On a 1080p
screen the panels alone come close to the available height, so being able
to fold away ~180 px matters more than it sounds.

Collapsing only hides the widget. Logging carries on into it, so
everything written while it was folded is there when it comes back.
"""
import tkinter as tk
from tkinter import scrolledtext, ttk

from smuniversal_lab_suite.core.gui.theme import theme_for

CONSOLE_ROW = 3


def build_console_panel(app, parent):
    """Build the log console. Sets app.console, which app.log() writes to."""
    header = ttk.Frame(parent)
    header.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    app.console_visible = tk.BooleanVar(value=True)
    ttk.Checkbutton(header, text="Console", variable=app.console_visible,
                    command=lambda: _toggle_console(app)).pack(side="left")

    # The tooltip switch rides here rather than on the session strip,
    # because this header is the one row every window has - the strip is
    # built only for the tabs that declare session fields.
    tooltips = getattr(app, "tooltips", None)
    if tooltips is not None:
        box = ttk.Checkbutton(header, text="Show tooltips",
                              variable=app.tooltips_var,
                              command=tooltips.hide)
        box.pack(side="left", padx=(12, 0))
        tooltips.attach(box, "Hover help on the panels and the fields "
                             "inside them. Off by default; it stays on "
                             "until this window closes.")

    app.console = scrolledtext.ScrolledText(parent, width=100, height=8,
                                            state="disabled",
                                            borderwidth=1, relief="solid")
    app.console.grid(row=CONSOLE_ROW, column=0, sticky="nsew", pady=(4, 0))

    # ScrolledText brings a plain `tk.Scrollbar`, which on Windows is
    # drawn by the system and ignores any colour asked of it - a white
    # bar down the side of a dark console. A ttk one follows the theme
    # like every other scrollbar in the window.
    app.console.vbar.destroy()
    bar = ttk.Scrollbar(app.console.frame, orient="vertical",
                        command=app.console.yview)
    bar.pack(side="right", fill="y")
    app.console.configure(yscrollcommand=bar.set)

    # A Text has no style, so it is repainted on every switch instead.
    theme_for(parent).on_change(lambda theme: _paint_console(app, theme),
                                widget=app.console)


def _paint_console(app, theme):
    """The console's own colours, which no ttk style reaches."""
    palette = theme.palette
    app.console.configure(background=palette.field, foreground=palette.ink,
                          insertbackground=palette.ink,
                          selectbackground=palette.rule,
                          selectforeground=palette.ink,
                          highlightbackground=palette.rule,
                          font="TkFixedFont")
    app.console.frame.configure(background=palette.bg)


def _toggle_console(app):
    """Show or hide the console.

    grid_remove() rather than grid_forget() - it remembers the row and
    options, so restoring is a bare grid() with no risk of the console
    reappearing somewhere unintended.
    """
    if app.console_visible.get():
        app.console.grid()
    else:
        app.console.grid_remove()
