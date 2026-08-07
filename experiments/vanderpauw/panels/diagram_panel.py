"""
Van der Pauw corner diagram.

The drawing itself is shared with the Hall experiment and lives in
core/gui/corner_diagram.py. All that's left here is the wiring, kept as
its own panel so the PANELS list stays a readable list of panels.
"""
from core.gui.corner_diagram import build_corner_diagram


def build_diagram_panel(exp, parent):
    """Draw the sample square and its four corner markers.
    Sets exp.canvas, exp.corner_items, exp.role_text_items."""
    return build_corner_diagram(exp, parent)
