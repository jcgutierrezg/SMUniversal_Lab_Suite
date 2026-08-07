"""
Console panel - the scrolling log every experiment shares.

Collapsible, because it is the one part of the window that is useful
during a run and mostly dead weight the rest of the time. On a 1080p
screen the panels alone come close to the available height, so being able
to fold away ~180 px matters more than it sounds.

Collapsing only hides the widget. Logging carries on into it, so
everything written while it was folded is there when it comes back.
"""
import tkinter as tk
from tkinter import ttk, scrolledtext

CONSOLE_ROW = 3


def build_console_panel(app, parent):
    """Build the log console. Sets app.console, which app.log() writes to."""
    header = ttk.Frame(parent)
    header.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    app.console_visible = tk.BooleanVar(value=True)
    ttk.Checkbutton(header, text="Console", variable=app.console_visible,
                    command=lambda: _toggle_console(app)).pack(side="left")

    app.console = scrolledtext.ScrolledText(parent, width=100, height=8,
                                            state="disabled")
    app.console.grid(row=CONSOLE_ROW, column=0, sticky="nsew", pady=(4, 0))


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
