"""Hover help for panels and the fields inside them.

Off by default, and switched on by the "Show tooltips" box beside the
Console switch, on the one header row every window has. Guidance that is
always on is in the way of the person
who has learned the panel, and the ones who need it are new to it, so
the box is where they are told to look once.

Where the words live
--------------------
Beside the widget they describe, in the panel file. A catalogue keyed by
widget name would be a second place to keep in step with the first, and
this repository has paid for that shape twice - the sample name and the
thickness both became two things claiming to be one.

What a tooltip says
-------------------
What the control does and what it costs to get it wrong, not what it is
called. "Points" is already on the label; "20 readings per polarity;
more averages down noise and lengthens the run" is not.

Panels and their fields both carry them. Entering a field hides the
panel's tooltip and shows the field's, which is the behaviour a reader
expects and falls out of Tk's enter/leave pairing for free.
"""
import tkinter as tk
from tkinter import ttk

#: How long the pointer must rest before the tooltip appears. Long
#: enough that crossing a panel on the way somewhere else shows nothing.
DELAY_MS = 600

#: Wrap width in pixels. Roughly 45 characters at the default font, which
#: is a readable line length and narrower than the narrowest column.
WRAP_PX = 320


class Tooltips:
    """One per window. Holds the on/off switch and the shown tooltip.

    The manager, rather than each tooltip, owns the visible window: two
    tooltips can never be on screen at once, and a window whose widget
    is destroyed mid-hover has one owner to take it away.
    """

    def __init__(self, root, enabled_var=None):
        self.root = root
        self.enabled_var = enabled_var or tk.BooleanVar(master=root,
                                                        value=False)
        self._window = None
        self._after = None

    @property
    def enabled(self):
        try:
            return bool(self.enabled_var.get())
        except tk.TclError:
            return False          # the window is being torn down

    def attach(self, widget, text):
        """Show `text` while the pointer rests on `widget`."""
        if widget is None or not text:
            return widget
        widget.bind("<Enter>", lambda e: self._schedule(widget, text),
                    add="+")
        widget.bind("<Leave>", lambda e: self.hide(), add="+")
        widget.bind("<ButtonPress>", lambda e: self.hide(), add="+")
        widget.bind("<Destroy>", lambda e: self.hide(), add="+")
        return widget

    def _schedule(self, widget, text):
        self.hide()
        if not self.enabled:
            return
        self._after = self.root.after(
            DELAY_MS, lambda: self._show(widget, text))

    def _show(self, widget, text):
        # Takes any tooltip already up with it, so the manager's one
        # window really is one window however this is reached. The
        # scheduled path hides first as well; this is what makes the
        # invariant hold for a direct call too.
        self.hide()
        self._after = None
        if not self.enabled:
            return
        try:
            x = widget.winfo_rootx() + 12
            y = widget.winfo_rooty() + widget.winfo_height() + 6
        except tk.TclError:
            return                # the widget went away while we waited

        window = tk.Toplevel(self.root)
        # No title bar, no taskbar entry, and never takes focus: a
        # tooltip that stole focus would eat the next keystroke typed
        # into the box it is describing.
        window.wm_overrideredirect(True)
        window.attributes("-topmost", True)
        ttk.Label(window, text=text, wraplength=WRAP_PX, justify="left",
                  relief="solid", borderwidth=1, padding=6,
                  background="#ffffe0").pack()
        window.wm_geometry(f"+{x}+{y}")
        self._window = window

    def hide(self, *_event):
        """Take the tooltip away, and cancel one that has not appeared."""
        if self._after is not None:
            try:
                self.root.after_cancel(self._after)
            except tk.TclError:
                pass              # the interpreter is gone
            self._after = None
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass              # already destroyed with its parent
            self._window = None


def tip(exp, widget, text):
    """Attach a tooltip from inside a panel builder.

    Takes the experiment rather than the manager so a panel file needs
    no import beyond this one, and does nothing at all in a window built
    without a manager - which is what a test constructing a panel in
    isolation does.
    """
    manager = getattr(getattr(exp, "app", None), "tooltips", None)
    if manager is None:
        return widget
    return manager.attach(widget, text)
