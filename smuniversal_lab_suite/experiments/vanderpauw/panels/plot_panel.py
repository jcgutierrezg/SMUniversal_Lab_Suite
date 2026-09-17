"""
The V-I plot, beside the calculation under the results table.

Each run is two clusters of points - the +I block and the -I block -
with the straight line fitted through both. The slope is the run's
resistance and the intercept is the offset voltage the polarity
reversal cancels, so a run whose line misses a cluster, or whose
clusters are smeared along the current axis, is visible before its
number is copied into the calculation.

The plot shares a row with the calculation rather than stacking under
it. The calculation is a narrow form, the width beside it was empty,
and the window's height is the budget `tests/test_layout.py` holds it
to; the width is not the scarce side.
"""
from tkinter import ttk

from smuniversal_lab_suite.core.gui.plot_panel import build_plot_panel

# Shorter than the shared default, so the row stays about as tall as the
# calculation beside it.
FIGSIZE = (4.0, 2.3)


def build_output_row(exp, parent):
    """The row under the results table that the calculation and the
    plot share. Sets exp.output_row."""
    exp.output_row = ttk.Frame(exp.col_right)
    exp.output_row.pack(fill="both", expand=True)


def build_vdp_plot_panel(exp, parent):
    """The shared plot panel, to the left of the calculation."""
    return build_plot_panel(exp, parent, figsize=FIGSIZE,
                            container=exp.output_row,
                            title="Van der Pauw V-I")
