"""
Embedded matplotlib plot, shared by any experiment that produces curves.

Why this is smaller than the original
-------------------------------------
The IV scripts gave the plot a 600x600 canvas and put it on the left,
where it was the biggest thing in the window. That worked because those
windows had nothing else in them - no results table, no temperature
stage, no console.

Here the plot sits in col_right underneath the results table, and the
window has a height budget (see tests/test_layout.py). A 600 px figure
plus an eight-row table plus the console does not fit on a 1080p screen.
So the figure is about half the original height, and the difference is
made up two ways: the navigation toolbar's zoom still works, and the
figure is redrawn on resize, so dragging the window bigger genuinely
gives the plot more room rather than stretching a fixed bitmap.

Threading
---------
Everything here touches Tk widgets, so it must run on the main thread.
Measurement code calls it through app.ui(), never directly.

Note the deliberate absence of pyplot. pyplot owns a global figure
registry and its own event loop integration; inside an existing Tk
application that is a second thing trying to be in charge. Constructing
Figure directly and handing it to FigureCanvasTkAgg leaves Tk in charge,
which is what you want. The original scripts got this right too.
"""
import tkinter as tk
from tkinter import ttk

import matplotlib

matplotlib.use("Agg")            # no separate GUI backend; Tk hosts the canvas

from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg,
    NavigationToolbar2Tk,
)
from matplotlib.figure import Figure

# Roughly half the original 6x6 inches. Tuned against the layout budget:
# raising this is the fastest way to fail tests/test_layout.py.
DEFAULT_FIGSIZE = (4.5, 2.8)
DEFAULT_DPI = 100


def build_plot_panel(exp, parent, figsize=DEFAULT_FIGSIZE, dpi=DEFAULT_DPI):
    """Build the plot into exp.col_right.

    Sets exp.plot_fig, exp.plot_ax, exp.plot_canvas, exp.plot_toolbar,
    exp.plot_title_var and exp.plot_overlap_var.
    """
    frame = ttk.LabelFrame(exp.col_right, text="Plot", padding=6)
    frame.pack(fill="both", expand=True, pady=(8, 0))

    # --- title and overlap toggle, on one row above the figure ---
    controls = ttk.Frame(frame)
    controls.pack(fill="x", pady=(0, 4))

    ttk.Label(controls, text="Title:").pack(side="left", padx=(0, 4))
    exp.plot_title_var = tk.StringVar(value="IV Measurement")
    ttk.Entry(controls, textvariable=exp.plot_title_var, width=22).pack(
        side="left", padx=(0, 10))

    # The originals had two buttons, "New Graph" and "Overlap Graph",
    # which differed only in whether previous runs stayed on the axes.
    # That is one boolean, so it is one checkbox here - and unlike the
    # buttons it shows the current state instead of only setting it.
    exp.plot_overlap_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(controls, text="Overlap runs",
                    variable=exp.plot_overlap_var,
                    command=exp.refresh_plot).pack(side="left")
    ttk.Button(controls, text="Redraw", width=8,
               command=exp.refresh_plot).pack(side="right")

    # --- the figure itself ---
    exp.plot_fig = Figure(figsize=figsize, dpi=dpi)
    exp.plot_ax = exp.plot_fig.add_subplot(111)

    exp.plot_canvas = FigureCanvasTkAgg(exp.plot_fig, master=frame)
    widget = exp.plot_canvas.get_tk_widget()
    widget.pack(fill="both", expand=True)

    # NavigationToolbar2Tk insists on packing itself into its master
    # unless told otherwise, which would fight the layout above. Giving
    # it a frame of its own and pack_toolbar=False keeps that contained.
    toolbar_frame = ttk.Frame(frame)
    toolbar_frame.pack(fill="x")
    exp.plot_toolbar = NavigationToolbar2Tk(exp.plot_canvas, toolbar_frame,
                                            pack_toolbar=False)
    exp.plot_toolbar.update()
    exp.plot_toolbar.pack(side="left", fill="x")

    draw_datasets(exp, [])
    return frame


def draw_datasets(exp, datasets, xlabel="Voltage [V]", ylabel="Current [A]",
                  show_fit=False):
    """Redraw the axes from scratch.

    `datasets` is a list of dicts with keys:
        label       legend entry
        x, y        sequences of equal length
        fit         optional (slope, intercept, r_squared)
        resistance  optional float, in ohms

    `resistance` is carried separately from `fit` rather than derived
    from the slope here, because which one it is depends on the sweep
    mode: sourcing volts and measuring amps makes it 1/slope, sourcing
    amps and measuring volts makes it the slope. The experiment knows
    which; this function shouldn't have to.

    Redrawing everything rather than appending is deliberate. An IV run
    is a handful of curves at a few hundred points each, so a full redraw
    is imperceptible, and it means the plot is a pure function of the
    stored data - there is no way for the axes and the results table to
    drift out of step.
    """
    ax = exp.plot_ax
    ax.clear()

    if not datasets:
        ax.set(title=exp.plot_title_var.get(), xlabel=xlabel, ylabel=ylabel)
        ax.text(0.5, 0.5, "No runs yet", transform=ax.transAxes,
                ha="center", va="center", color="gray", fontsize=9)
    else:
        for data in datasets:
            label = data["label"]
            fit = data.get("fit")
            if show_fit and fit:
                _, _, r_squared = fit
                label = (f"{label}  R={_ohms(data.get('resistance'))}, "
                         f"R²={r_squared:.4f}")
            ax.plot(data["x"], data["y"], "o", markersize=3, label=label)

            if show_fit and fit and len(datasets) == 1:
                slope, intercept, _ = fit
                fit_y = [slope * x + intercept for x in data["x"]]
                ax.plot(data["x"], fit_y, "-", color="red", linewidth=1,
                        label="Fit line")

        ax.set(title=exp.plot_title_var.get(), xlabel=xlabel, ylabel=ylabel)
        ax.legend(loc="upper left", fontsize=7)
        ax.grid(True, alpha=0.25)

    # tight_layout on every redraw, because the axis labels change when
    # the sweep mode flips between V-source and I-source and the old
    # margins no longer fit.
    try:
        exp.plot_fig.tight_layout()
    except Exception:
        pass
    exp.plot_canvas.draw_idle()


def _ohms(resistance):
    """Format a resistance for a legend entry, with an SI prefix."""
    try:
        value = float(resistance)
    except (TypeError, ValueError):
        return "-"
    if value == 0:
        return "-"
    magnitude = abs(value)
    if magnitude >= 1e9:
        return f"{value/1e9:.4g} GΩ"
    if magnitude >= 1e6:
        return f"{value/1e6:.4g} MΩ"
    if magnitude >= 1e3:
        return f"{value/1e3:.4g} kΩ"
    return f"{value:.4g} Ω"
