"""
Sample corner diagram - the square with four labelled contacts.

Van der Pauw and Hall both draw exactly this: one square, four numbered
corners, a role letter beside each. Only the *mapping* from position to
roles differs, and that belongs to the experiment, not to the drawing.

So the geometry lives here once and each experiment supplies its own
CORNER_ROLES table. Splitting it that way is what stops a change to the
diagram's appearance from having to be made twice and getting made
differently.

Colour convention, shared by both experiments:
    current-carrying corner -> orange
    voltage-sensing corner  -> green
    unused                  -> grey
"""
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui.theme import theme_for
from smuniversal_lab_suite.core.gui.tooltips import tip

CANVAS_SIZE = 270
CORNER_RADIUS = 12
PAD = 24

#: The colour convention above is the palette's to hold, because the
#: two modes need different shades of it - see `core/gui/theme.py`.


def build_corner_diagram(exp, parent, size=CANVAS_SIZE):
    """Draw the sample square and its four corner markers.

    Sets exp.canvas, exp.corner_items, exp.role_text_items - the same
    attribute names the original scripts used, so experiment code reads
    unchanged.
    """
    frame = ttk.Frame(exp.col_left)
    frame.pack(fill="x")

    exp.canvas = tk.Canvas(frame, width=size, height=size,
                           highlightthickness=1)
    exp.canvas.pack()
    tip(exp, exp.canvas,
        "Which contact does what at the position selected below: the "
        "orange corners carry the current, the green ones sense the "
        "voltage, and the labels name each role.",
        name="Contact diagram")

    x0, y0, x1, y1 = PAD, PAD, size - PAD, size - PAD
    exp.sample_item = exp.canvas.create_rectangle(x0, y0, x1, y1, width=2)

    corners = {1: (x0, y0), 2: (x1, y0), 3: (x1, y1), 4: (x0, y1)}
    exp.corner_items = {}
    exp.role_text_items = {}

    for idx, (cx, cy) in corners.items():
        oval = exp.canvas.create_oval(cx - CORNER_RADIUS, cy - CORNER_RADIUS,
                                      cx + CORNER_RADIUS, cy + CORNER_RADIUS)
        label = exp.canvas.create_text(cx, cy, text=str(idx),
                                       font="SMUCanvasBold")
        exp.corner_items[idx] = (oval, label)

        # role text sits above the top corners, below the bottom ones
        ty = cy - 18 if idx in (1, 2) else cy + 18
        exp.role_text_items[idx] = exp.canvas.create_text(
            cx, ty, text="", font="SMUCanvas")

    # The drawing is not ttk, so it repaints itself. Re-applying the
    # roles is what does it: that restores the current position's
    # colours in the new palette rather than resetting every corner to
    # unused.
    exp.corner_roles = {}
    theme_for(frame).on_change(
        lambda theme: paint_corner_roles(exp, exp.corner_roles),
        widget=exp.canvas)

    return frame


def paint_corner_roles(exp, mapping):
    """Recolour and relabel the corners from a {corner: role} mapping.

    A role containing "I" is treated as current-carrying, one containing
    "V" as voltage-sensing. That covers both experiments' notations -
    Van der Pauw's "I,H"/"V,L" and Hall's plain "I"/"V" - without either
    having to know about the other's.
    """
    palette = theme_for(exp.canvas).palette
    # Kept so a mode switch can re-apply the roles rather than reset
    # every corner to unused.
    exp.corner_roles = dict(mapping)
    exp.canvas.configure(background=palette.bg,
                         highlightbackground=palette.rule)
    exp.canvas.itemconfig(exp.sample_item, fill=palette.diagram_body,
                          outline=palette.diagram_edge)
    for idx, (oval, label) in exp.corner_items.items():
        role = mapping.get(idx, "")
        if "I" in role:
            fill = palette.role_current
        elif "V" in role:
            fill = palette.role_voltage
        else:
            fill = palette.role_unused
        exp.canvas.itemconfig(oval, fill=fill, outline=palette.diagram_edge)
        exp.canvas.itemconfig(label, fill=palette.diagram_edge)
        exp.canvas.itemconfig(exp.role_text_items[idx], text=role,
                              fill=palette.ink2)
