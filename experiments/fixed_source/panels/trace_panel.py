"""
What the plot shows - one checkbox, under the figure.

The measured quantity is always drawn. The sourced one is optional and
off by default, and both halves of that are deliberate.

It is *available* because a fixed source is only fixed in the sense that
the instrument was asked to hold it. A compliance clamp, a range limit
or a lead falling off all show up as the sourced quantity moving, and if
the plot cannot show that, the first sign of it is a measured trace that
does something inexplicable.

It is *off* because it needs a second y-axis - amps and volts do not
share a scale - and a second axis on a figure this size costs
readability on every run where the source did exactly what it was told,
which is most of them.

A separate strip rather than a control inside the plot panel: that panel
is shared with the IV sweep and the 4PP, and neither of them has a
second quantity to draw. Adding a checkbox there for one experiment's
benefit would put a dead control on two others.
"""
import tkinter as tk
from tkinter import ttk


def build_trace_panel(exp, parent):
    """Sets exp.show_source_var."""
    frame = ttk.Frame(exp.col_right)
    frame.pack(fill="x", pady=(4, 0))

    exp.show_source_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(frame, text="Also plot the sourced level (right axis)",
                    variable=exp.show_source_var,
                    command=exp.refresh_plot).pack(side="left")

    return frame
