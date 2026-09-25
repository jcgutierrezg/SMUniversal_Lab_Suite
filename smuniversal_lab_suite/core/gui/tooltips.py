"""Hover help for panels and the fields inside them.

On by default, and switched off by the "Show tooltips" box beside the
Console button, top right of every window. A tooltip waits for the
pointer to rest before it appears, so it stays out of the way of an
operator who knows the panel and is moving through it; one who does not
finds the help where they are already pointing, without having to know
there is a box to tick first.

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

Where it appears
----------------
At the pointer, and it follows the pointer while it stays on the widget.
A tooltip placed under the widget - where it used to go - lands on a
different spot for every widget, often across the next field down; one
at the pointer is where the reader is already looking. It waits for the
pointer to *rest*, not merely to arrive, so sweeping across a panel
shows nothing, and it flips to the other side of the pointer rather than
run off the edge of the screen.

Every tooltip is recorded against its widget (`text_for`), which is what
lets `tests/test_tooltip_coverage.py` check that every control in every
window says what it does.
"""
import tkinter as tk
from tkinter import ttk

#: How long the pointer must rest before the tooltip appears. Long
#: enough that crossing a panel on the way somewhere else shows nothing.
DELAY_MS = 600

#: Wrap width in pixels. Roughly 45 characters at the default font, which
#: is a readable line length and narrower than the narrowest column.
WRAP_PX = 320

#: Where the tooltip sits relative to the pointer, in pixels: right of
#: and below it, clear of the cursor's own arrow so it hides nothing the
#: pointer is on.
OFFSET_X = 16
OFFSET_Y = 20

#: Kept between a tooltip and the edge of the screen.
SCREEN_MARGIN = 8


#: Help for controls that are the same control in every experiment -
#: the same base-class method behind the button, the same app variable
#: behind the box. Written once here rather than copied into five panel
#: files, because five copies of one sentence drift apart the first time
#: the behaviour changes. Controls that differ per experiment keep their
#: words in their own panel, beside the widget.
HELP = {
    "sample_name":
        "The sample on the stage. It names the saved files and identifies "
        "the sample to every check in the suite, so two different coupons "
        "must never share a name - a result from one would be carried "
        "over onto the other.",
    "dataset":
        "A label for this run, shown in the table and the plot legend "
        "and saved with it - 'dark', 'after anneal', 'probe 2'. It does "
        "not have to be unique.",
    "next_number":
        "The number the next saved measurement will carry in its file "
        "name. It counts up by itself on every save; it is not typed.",
    "save_path":
        "Choose the folder to save into. A subfolder named for today's "
        "date is made inside it, so one folder holds a day's work.",
    "save_folder":
        "Where this session's files are being saved - today's dated "
        "folder inside the one chosen with Save path.",
    "nplc":
        "Integration time, in mains cycles. 1 NPLC averages over a whole "
        "cycle and rejects mains hum; 0.01 is far faster and visibly "
        "noisier. Two runs at different NPLC are not comparable, so it "
        "is recorded with the data.",
    "high_z":
        "What the instrument does to the sample between runs: open the "
        "relay (high-Z) or hold it at zero volts. High-Z leaves nothing "
        "driving the film. Greyed on instruments without the choice.",
    "voltage_range":
        "The range the voltage is measured on, from what the connected "
        "instrument declares. AUTO lets it choose. A range far larger "
        "than the reading costs resolution; one too small clips it.",
    "remote_sense":
        "Measure the voltage on separate sense leads at the sample, so "
        "the resistance of the source leads and contacts drops out. "
        "Untick only for a 2-wire hookup. Greyed, and pinned to the "
        "wiring, on instruments whose sense terminals are strapped.",
    "compliance":
        "The limit on the quantity you are not sourcing: the most "
        "current the instrument may drive when sourcing voltage, the "
        "most voltage when sourcing current. It protects the sample, "
        "and the measurement range follows it. Type any value; the list "
        "is only a starting point.",
    "ovp":
        "Overvoltage protection: a hard ceiling on the output, separate "
        "from compliance. It matters in 4-wire work, where a sense lead "
        "falling off makes the instrument wind its output up. Greyed on "
        "instruments without it.",
    "source_voltage":
        "Hold a voltage on the sample and measure the current through "
        "it.",
    "source_current":
        "Drive a current through the sample and measure the voltage "
        "across it.",
    "save_snapshot":
        "Write every run in the table to CSV, one file per sample. "
        "Nothing reaches disk until you press this; the table can be "
        "saved again as it grows.",
    "delete_ticked":
        "Discard the ticked runs and their readings. This is why nothing "
        "saves automatically: a run spoiled by a poor contact never "
        "reaches the disk at all.",
    "clear_all":
        "Empty the table and the plot. If anything in it has not been "
        "saved you are asked first.",
    "results_frame":
        "The runs of this session, held in memory until saved. Tick a "
        "row with the box at its left; the buttons below act on the "
        "ticked rows.",
    "plot_canvas":
        "The ticked runs, or the newest one when none is ticked. Zoom or "
        "pan with the toolbar below; Redraw puts it back.",
}


class Tooltips:
    """One per window. Holds the on/off switch and the shown tooltip.

    The manager, rather than each tooltip, owns the visible window: two
    tooltips can never be on screen at once, and a window whose widget
    is destroyed mid-hover has one owner to take it away.
    """

    def __init__(self, root, enabled_var=None):
        self.root = root
        self.enabled_var = enabled_var or tk.BooleanVar(master=root,
                                                        value=True)
        self._window = None
        self._after = None
        # Where the pointer was last seen over a widget with a tooltip,
        # in screen coordinates - where the next tooltip is placed.
        self._pointer = None
        #: str(widget) -> its tooltip. See `text_for`.
        self.texts = {}
        #: str(widget) -> what the user guide calls it, for a control
        #: with no label of its own. See `name_for`.
        self.names = {}

    @property
    def enabled(self):
        try:
            return bool(self.enabled_var.get())
        except tk.TclError:
            return False          # the window is being torn down

    def attach(self, widget, text, name=None):
        """Show `text` while the pointer rests on `widget`.

        `name` is for a control that has no words on it - a lamp, a
        plot, a box with no label beside it. Nothing on screen shows
        it; the user guide's control tables use it for the row.
        """
        if widget is None or not text:
            return widget
        self.texts[str(widget)] = text
        if name:
            self.names[str(widget)] = name
        widget.bind("<Enter>", lambda e: self._arrive(widget, text, e),
                    add="+")
        widget.bind("<Motion>", lambda e: self._moved(widget, text, e),
                    add="+")
        widget.bind("<Leave>", lambda e: self.hide(), add="+")
        widget.bind("<ButtonPress>", lambda e: self.hide(), add="+")
        widget.bind("<Destroy>", lambda e: self.hide(), add="+")
        return widget

    def text_for(self, widget):
        """The tooltip attached to `widget`, or None."""
        return self.texts.get(str(widget))

    def name_for(self, widget):
        """The name given to an unlabelled `widget`, or None."""
        return self.names.get(str(widget))

    def _arrive(self, widget, text, event):
        self._pointer = (event.x_root, event.y_root)
        self._schedule(widget, text)

    def _moved(self, widget, text, event):
        """Follow the pointer if the tooltip is up; otherwise start the
        wait again, because a tooltip appears where the pointer rests."""
        self._pointer = (event.x_root, event.y_root)
        if self._window is not None:
            self._place(*self._pointer)
            return
        self._schedule(widget, text)

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
            # Where the pointer is now - or, called directly with no
            # pointer seen yet, where it is on the screen.
            pointer = self._pointer or widget.winfo_pointerxy()
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
                  style="Tooltip.TLabel").pack()
        self._window = window
        self._place(*pointer)

    def _place(self, x_root, y_root):
        """Put the tooltip beside the pointer, on the side that fits.

        Right of and below the pointer by default; to the left of it or
        above it when that side would run off the screen. Only the
        primary screen is measured, so on a second monitor the tooltip
        keeps to the default side rather than guessing at its size.
        """
        window = self._window
        if window is None:
            return
        try:
            window.update_idletasks()
            width, height = window.winfo_reqwidth(), window.winfo_reqheight()
            screen_w = window.winfo_screenwidth()
            screen_h = window.winfo_screenheight()
        except tk.TclError:
            return
        x, y = x_root + OFFSET_X, y_root + OFFSET_Y
        on_primary_x = 0 <= x_root <= screen_w
        on_primary_y = 0 <= y_root <= screen_h
        if on_primary_x and x + width > screen_w - SCREEN_MARGIN:
            x = max(0, x_root - width - OFFSET_X // 2)
        if on_primary_y and y + height > screen_h - SCREEN_MARGIN:
            y = max(0, y_root - height - OFFSET_X // 2)
        try:
            # "+-40" is how Tk spells a negative position - a monitor
            # left of or above the primary one.
            window.wm_geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

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


def results_help(exp, frame, buttons, copy_help):
    """Help for a Results panel: the frame, and its row of buttons.

    Every experiment's Results panel has the same four buttons calling
    the same base-class methods, so three of them take the shared words
    in `HELP`. The first - "Copy ticked" - does something different on
    each tab, so its words are passed in. Buttons are found by their
    label; one that already has a tooltip keeps it.
    """
    tip(exp, frame, HELP["results_frame"])
    shared = {"Save snapshot → CSV": HELP["save_snapshot"],
              "Delete ticked": HELP["delete_ticked"],
              "Clear all": HELP["clear_all"]}
    manager = getattr(getattr(exp, "app", None), "tooltips", None)
    for button in buttons.winfo_children():
        try:
            label = str(button.cget("text"))
        except Exception:
            continue          # not a button
        words = copy_help if label.startswith("Copy ticked") \
            else shared.get(label)
        if not words:
            continue
        if manager is not None and manager.text_for(button):
            continue
        tip(exp, button, words)


def tip(exp, widget, text, name=None):
    """Attach a tooltip from inside a panel builder.

    Takes the experiment rather than the manager so a panel file needs
    no import beyond this one, and does nothing at all in a window built
    without a manager - which is what a test constructing a panel in
    isolation does.
    """
    manager = getattr(getattr(exp, "app", None), "tooltips", None)
    if manager is None:
        return widget
    return manager.attach(widget, text, name=name)
