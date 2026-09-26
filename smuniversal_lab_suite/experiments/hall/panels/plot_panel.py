"""
The V-I plot, in the middle column under Run and Stop.

Each run is its sweep - the voltage across one diagonal against the
current through the other - with the straight line fitted through it.
The four runs a calculation takes differ only in position and field
sign, so drawn together they show a run whose sweep is noisy, clamped
or off the line before its voltages are copied.

In the middle column rather than beside the calculation, as Van der
Pauw's is: Hall's calculation is too wide to share its row, and the
middle column had the height to spare under the run controls.
"""
from smuniversal_lab_suite.core.gui.plot_panel import build_plot_panel

# Narrow enough for the middle column, and short enough that the column
# stays inside the window's height budget - see tests/test_layout.py.
FIGSIZE = (3.6, 1.8)


def build_hall_plot_panel(exp, parent):
    """The shared plot panel, under the run controls."""
    return build_plot_panel(exp, parent, figsize=FIGSIZE,
                            container=exp.col_mid, title="Hall V-I")
