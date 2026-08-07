"""
Hall corner diagram.

Shares the drawing with Van der Pauw (core/gui/corner_diagram.py); only
the role mapping differs, and that lives in experiment.py.
"""
from core.gui.corner_diagram import build_corner_diagram


def build_diagram_panel(exp, parent):
    """Draw the sample square and its four corner markers.
    Sets exp.canvas, exp.corner_items, exp.role_text_items."""
    return build_corner_diagram(exp, parent)
