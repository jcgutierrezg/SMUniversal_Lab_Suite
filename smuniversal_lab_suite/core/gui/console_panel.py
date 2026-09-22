"""
The log every window keeps, and the window it is read in.

The console used to be a panel at the foot of the window, folded away by
a checkbox. It is useful during a run and dead weight the rest of the
time, and on a 1080p screen it was costing ~180 px of the scarcest thing
the layout has. So it is now a window of its own, opened from the button
in the header strip.

**Nothing is lost while it is closed.** The lines are the log's, not the
widget's: `ConsoleLog` holds them, `app.log()` appends to it from any
thread, and the window - when there is one - is a view onto it. Open the
console an hour into a session and the whole hour is there. That is the
same guarantee the folded panel gave, kept deliberately, because a log
that only records while someone is watching is not a log.

The one limit is `MAX_LINES`, far above a day's logging, so that a
window left open for a week cannot grow without bound.
"""
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui.theme import set_dark_title_bar, theme_for
from smuniversal_lab_suite.core.gui.tooltips import tip

#: Lines kept. A long session logs a few thousand; this is the ceiling
#: that stops a window open for days from being a memory leak. When it
#: is hit the oldest lines go, because the recent ones are the ones
#: being read.
MAX_LINES = 20000


class ConsoleLog:
    """Every line this window has logged, and the view onto them.

    The view is optional and comes and goes; the lines do not.
    """

    def __init__(self, max_lines=MAX_LINES):
        self._lines = []
        self._max_lines = max_lines
        #: The Text of the open console window, or None.
        self.view = None

    def append(self, line):
        """Record one line, and show it if anybody is looking."""
        self._lines.append(line)
        if len(self._lines) > self._max_lines:
            del self._lines[:len(self._lines) - self._max_lines]
        if self.view is None:
            return
        try:
            self._write(self.view, line)
        except tk.TclError:
            # The window went away between the check and the write.
            self.view = None

    def text(self):
        """Everything logged, as one string."""
        return "".join(self._lines)

    def lines(self):
        return list(self._lines)

    def fill(self, widget):
        """Point a fresh Text at the whole log so far."""
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", self.text())
        widget.see("end")
        widget.configure(state="disabled")
        self.view = widget

    @staticmethod
    def _write(widget, line):
        widget.configure(state="normal")
        widget.insert("end", line)
        widget.see("end")
        widget.configure(state="disabled")


def build_console_controls(app, parent):
    """The Console button and the tooltip switch, for the header strip.

    Returns the frame. Sets `app.console_btn`.
    """
    frame = ttk.Frame(parent)

    app.console_btn = ttk.Button(frame, text="Console", width=9,
                                 command=lambda: toggle_console(app))
    app.console_btn.pack(side="left")
    tip(app.experiment, app.console_btn,
        "Open the log in its own window. It records everything this "
        "window does whether it is open or not, so opening it later "
        "still shows the whole session.")

    tooltips = getattr(app, "tooltips", None)
    if tooltips is not None:
        box = ttk.Checkbutton(frame, text="Show tooltips",
                              variable=app.tooltips_var,
                              command=tooltips.hide)
        box.pack(side="left", padx=(10, 0))
        tooltips.attach(box, "Hover help on the panels and the fields "
                             "inside them. Off by default; it stays on "
                             "until this window closes.")
    return frame


def toggle_console(app):
    """Open the console window, or close it if it is already open.

    Closing discards nothing: the lines belong to `app.console_log`.
    """
    window = getattr(app, "console_window", None)
    if window is not None and window.alive():
        window.close()
        return
    app.console_window = ConsoleWindow(app)


class ConsoleWindow:
    """The log in a window of its own."""

    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title(f"Console - {app.root.title()}")
        # Not `transient`: the console is watched *beside* the window it
        # belongs to, often on a second screen, and a transient window
        # is pinned above its parent and minimises with it.
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.geometry("900x320")

        body = ttk.Frame(self.window, padding=6)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, wrap="none", state="disabled",
                            borderwidth=1, relief="solid", height=14)
        bar = ttk.Scrollbar(body, orient="vertical",
                            command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        app.console_log.fill(self.text)
        theme_for(app.root).on_change(self._repaint, widget=self.window)

    def _repaint(self, theme):
        palette = theme.palette
        self.window.configure(background=palette.bg)
        self.text.configure(background=palette.field, foreground=palette.ink,
                            insertbackground=palette.ink,
                            selectbackground=palette.rule,
                            selectforeground=palette.ink,
                            highlightbackground=palette.rule,
                            font="TkFixedFont")
        set_dark_title_bar(self.window, theme.is_dark)

    def alive(self):
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def close(self):
        """Take the window away. The log carries on without it."""
        self.app.console_log.view = None
        self.app.console_window = None
        try:
            self.window.destroy()
        except tk.TclError:
            pass                  # already gone with its parent
