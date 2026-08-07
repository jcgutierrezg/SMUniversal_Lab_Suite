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

CANVAS_SIZE = 270
CORNER_RADIUS = 12
PAD = 24

CURRENT_FILL = "#ffcc99"
VOLTAGE_FILL = "#ccffcc"
UNUSED_FILL = "#ddd"


def build_corner_diagram(exp, parent, size=CANVAS_SIZE):
    """Draw the sample square and its four corner markers.

    Sets exp.canvas, exp.corner_items, exp.role_text_items - the same
    attribute names the original scripts used, so experiment code reads
    unchanged.
    """
    frame = ttk.Frame(exp.col_left)
    frame.pack(fill="x")

    exp.canvas = tk.Canvas(frame, width=size, height=size,
                           bg="white", highlightthickness=1,
                           highlightbackground="#ccc")
    exp.canvas.pack()

    x0, y0, x1, y1 = PAD, PAD, size - PAD, size - PAD
    exp.canvas.create_rectangle(x0, y0, x1, y1, fill="#f8f8f8",
                                outline="#333", width=2)

    corners = {1: (x0, y0), 2: (x1, y0), 3: (x1, y1), 4: (x0, y1)}
    exp.corner_items = {}
    exp.role_text_items = {}

    for idx, (cx, cy) in corners.items():
        oval = exp.canvas.create_oval(cx - CORNER_RADIUS, cy - CORNER_RADIUS,
                                      cx + CORNER_RADIUS, cy + CORNER_RADIUS,
                                      fill=UNUSED_FILL, outline="#555")
        label = exp.canvas.create_text(cx, cy, text=str(idx),
                                       font=("Helvetica", 10, "bold"))
        exp.corner_items[idx] = (oval, label)

        # role text sits above the top corners, below the bottom ones
        ty = cy - 18 if idx in (1, 2) else cy + 18
        exp.role_text_items[idx] = exp.canvas.create_text(
            cx, ty, text="", font=("Helvetica", 9), fill="#1155aa")

    return frame


def paint_corner_roles(exp, mapping):
    """Recolour and relabel the corners from a {corner: role} mapping.

    A role containing "I" is treated as current-carrying, one containing
    "V" as voltage-sensing. That covers both experiments' notations -
    Van der Pauw's "I,H"/"V,L" and Hall's plain "I"/"V" - without either
    having to know about the other's.
    """
    for idx, (oval, _label) in exp.corner_items.items():
        role = mapping.get(idx, "")
        if "I" in role:
            fill = CURRENT_FILL
        elif "V" in role:
            fill = VOLTAGE_FILL
        else:
            fill = UNUSED_FILL
        exp.canvas.itemconfig(oval, fill=fill)
        exp.canvas.itemconfig(exp.role_text_items[idx], text=role)
