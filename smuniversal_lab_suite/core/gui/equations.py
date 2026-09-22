"""The Equations window: what a tab computes, written out.

One window per tab, opened from a button beside Calculate. It shows each
formula the tab uses, typeset, with its symbols named and their units,
and - once there is a result - the same formula with that result's own
numbers in it.

Why typeset rather than plain text
----------------------------------
`n_s = I*B/(q*V_H)` is readable; the Van der Pauw equation and the
eight-term Hall average are not, and those are the two this exists for.
Matplotlib is already a dependency and its mathtext engine needs no TeX
installation, so the cost is one figure per formula, rendered once and
cached.

Why the numbers are optional rather than always shown
-----------------------------------------------------
The symbolic form answers "what is this tab doing"; the substituted form
answers "where did that number come from", which is the question asked
when a result looks wrong. They are different questions and the second
one needs a result that is still true - so the values are offered only
when the calculation is fresh, and the window says which of the two it
is showing.
"""
import base64
import io
import tkinter as tk
from tkinter import ttk

from matplotlib.figure import Figure

from smuniversal_lab_suite.core.gui.theme import (
    set_dark_title_bar,
    theme_for,
)

#: Rendered-image cache, keyed by the mathtext string and its size. A
#: window reopened, or its values toggled back and forth, re-renders
#: nothing. Images are small and the set is bounded by the number of
#: formulas in the suite.
_CACHE = {}

#: Point size of the typeset formulas, and the dots per inch they are
#: rasterised at. 13 pt at 110 dpi matches the surrounding text closely
#: enough that the window does not read as two documents.
FONT_SIZE = 13
DPI = 110

#: Widest a rendered formula may be, in pixels. A formula with the
#: numbers in it is far longer than the same formula in symbols - the
#: eight-term Hall average becomes eight decimals - and one wider than
#: the window would simply be cut off at the edge with nothing to say
#: so. Over-wide formulas are re-rendered smaller instead.
MAX_WIDTH_PX = 520

#: Never shrink past this, however long the formula. Below it the
#: digits stop being readable and a smaller picture of an unreadable
#: line is no use.
MIN_FONT_SIZE = 7


def render(master, latex, fontsize=FONT_SIZE, colour="#202020"):
    """One mathtext string as a Tk image, or None if it will not parse.

    A formula that cannot be parsed must not take the window down with
    it: the caller falls back to showing the source text, which is still
    more use than an error dialog.
    """
    key = (latex, fontsize, colour)
    if key in _CACHE:
        image = _CACHE[key]
    else:
        figure = Figure(figsize=(0.01, 0.01), dpi=DPI)
        figure.patch.set_alpha(0.0)
        figure.text(0, 0, f"${latex}$", fontsize=fontsize, color=colour)
        buffer = io.BytesIO()
        try:
            figure.savefig(buffer, format="png", dpi=DPI,
                           bbox_inches="tight", pad_inches=0.05,
                           transparent=True)
        except (ValueError, RuntimeError):
            return None           # unparseable mathtext; caller shows text
        image = base64.b64encode(buffer.getvalue())
        _CACHE[key] = image
    # Built per call rather than cached: a PhotoImage belongs to the
    # interpreter that made it, and this window outlives none of them.
    return tk.PhotoImage(master=master, data=image)


def number(value, figures=4):
    """A number as mathtext: `0.0816`, or `1.80\\times10^{-5}`.

    Plain `%g` would put `1.8e-05` inside a typeset formula, which reads
    as a programming language rather than as physics next to the symbols
    around it.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if value == 0:
        return "0"
    text = f"{value:.{figures}g}"
    if "e" not in text:
        return text
    mantissa, exponent = text.split("e")
    return rf"{mantissa}\times10^{{{int(exponent)}}}"


class EquationsWindow:
    """The window itself. One per tab, reused if it is already open."""

    def __init__(self, parent, title, equations, values_provider):
        self.parent = parent
        self.equations = tuple(equations)
        self.values_provider = values_provider
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.transient(parent)

        self.with_values = tk.BooleanVar(master=self.window, value=False)
        header = ttk.Frame(self.window, padding=(10, 8, 10, 0))
        header.pack(fill="x")
        self.values_check = ttk.Checkbutton(
            header, text="Show the last calculation's values",
            variable=self.with_values, command=self.refresh)
        self.values_check.pack(side="left")
        ttk.Button(header, text="Close",
                   command=self.close).pack(side="right")

        self.note_var = tk.StringVar(value="")
        ttk.Label(self.window, textvariable=self.note_var,
                  style="Warn.TLabel", wraplength=520, justify="left",
                  padding=(10, 4)).pack(fill="x")

        # A canvas so a tab with five formulas scrolls rather than
        # growing past the screen.
        outer = ttk.Frame(self.window)
        outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(outer, highlightthickness=0, width=580,
                                height=460)
        scroll = ttk.Scrollbar(outer, orient="vertical",
                               command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas, padding=10)
        self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")))

        # Held so Tk does not garbage-collect the images out of the
        # labels showing them - the oldest Tkinter footgun there is.
        self._images = []
        # Formulas are pictures: matplotlib renders them in one ink, so
        # a mode switch has to draw them again. `refresh()` already
        # rebuilds the whole body, which is exactly that.
        theme_for(self.window).on_change(self._repaint, widget=self.window)

    def _repaint(self, theme):
        """Follow a mode switch: the window's own ground, then a redraw
        of every formula in the new ink."""
        try:
            self.canvas.configure(background=theme.palette.bg)
        except tk.TclError:
            return
        set_dark_title_bar(self.window, theme.is_dark)
        self.refresh()

    def refresh(self):
        """Redraw every formula, with or without the numbers."""
        for child in list(self.body.winfo_children()):
            child.destroy()
        self._images.clear()

        values, note = self.values_provider()
        self.values_check.configure(
            state="normal" if values else "disabled")
        if not values:
            self.with_values.set(False)
        self.note_var.set(note)

        for row, equation in enumerate(self.equations):
            block = ttk.LabelFrame(self.body, text=equation.title, padding=8)
            block.pack(fill="x", pady=(0 if row == 0 else 8, 0))
            theme = theme_for(self.window)
            self._formula(block, equation.latex, colour=theme.palette.ink)
            if self.with_values.get() and values.get(equation.method):
                # The same formula with this calculation's numbers in
                # it, in the tab's own colour so the two readings of one
                # equation are told apart at a glance.
                self._formula(block, values[equation.method],
                              colour=theme.accent)
            for symbol, meaning in equation.symbols:
                ttk.Label(block, text=f"{symbol} - {meaning}",
                          wraplength=460, justify="left",
                          style="Hint.TLabel").pack(anchor="w")
            if equation.note:
                ttk.Label(block, text=equation.note, wraplength=460,
                          justify="left", style="Hint.TLabel").pack(
                    anchor="w", pady=(4, 0))
            ttk.Label(block, text=f"method: {equation.method}",
                      style="Stale.Hint.TLabel").pack(anchor="w",
                                                      pady=(4, 0))

    def _formula(self, parent, latex, colour="#202020"):
        """One formula as a picture, in `colour`."""
        image = render(self.window, latex, colour=colour)
        if image is None:
            ttk.Label(parent, text=latex, wraplength=460,
                      justify="left").pack(anchor="w", pady=2)
            return
        # Shrink a formula too wide for the window rather than letting
        # the right-hand end disappear off it.
        size = FONT_SIZE
        while image.width() > MAX_WIDTH_PX and size > MIN_FONT_SIZE:
            size = max(MIN_FONT_SIZE, int(size * MAX_WIDTH_PX
                                          / image.width()))
            image = render(self.window, latex, fontsize=size, colour=colour)
        self._images.append(image)
        ttk.Label(parent, image=image).pack(anchor="w", pady=2)

    def close(self):
        try:
            self.window.destroy()
        except tk.TclError:
            pass                  # already gone with its parent


def show(exp, equations, values_provider):
    """Open, or raise, the Equations window for one experiment."""
    existing = getattr(exp, "_equations_window", None)
    if existing is not None:
        try:
            existing.window.deiconify()
            existing.window.lift()
            existing.refresh()
            return existing
        except tk.TclError:
            pass                  # it was closed; build a new one
    window = EquationsWindow(exp.app.root, f"{exp.NAME} - equations",
                             equations, values_provider)
    exp._equations_window = window
    return window
