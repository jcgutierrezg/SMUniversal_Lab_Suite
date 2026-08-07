"""
Sample geometry: the W/L diagram, the dimensions, and the fixed probe
spacing.

The diagram is the point of this panel. W and L are only meaningful
relative to each other and to where the probe head sits, and "short
side" versus "long side" is exactly the sort of thing that gets swapped
at the keyboard. Showing the picture next to the boxes removes the
ambiguity in a way a label cannot.

Lives in col_left, where Van der Pauw and Hall put their contact
diagrams - same idea, same place: this column is what the sample *is*,
the middle column is what to do to it.

No temperature panel here, unlike the other experiments. A four-point
probe measurement is a spot check on the bench, not a stage run.
"""
import os
import tkinter as tk
from tkinter import ttk

from ..fourpp_math import PROBE_SPACING_MM

ASSET_PATH = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "assets", "WL.png")

# The source image is 848x261. Scaled to fit col_left without forcing
# the window wider - see tests/test_layout.py.
DIAGRAM_WIDTH = 300


def build_geometry_panel(exp, parent):
    """Build the diagram and the W/L/t entries into exp.col_left."""
    frame = ttk.LabelFrame(exp.col_left, text="Sample geometry", padding=6)
    frame.pack(fill="x")

    _add_diagram(exp, frame)

    entries = ttk.Frame(frame)
    entries.pack(fill="x", pady=(6, 0))

    exp.width_var = tk.StringVar(value="10")
    exp.length_var = tk.StringVar(value="10")
    exp.thickness_var = tk.StringVar(value="180")

    for row, (label, var) in enumerate([
            ("Short side W (mm):", exp.width_var),
            ("Long side L (mm):", exp.length_var),
            ("Thickness t (µm):", exp.thickness_var)]):
        ttk.Label(entries, text=label, width=18, anchor="e").grid(
            row=row, column=0, sticky="e", padx=(0, 6), pady=2)
        entry = ttk.Entry(entries, textvariable=var, width=10)
        entry.grid(row=row, column=1, sticky="w", pady=2)
        if var is exp.width_var:
            exp.width_entry = entry

    ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(8, 6))

    # Fixed, and worth saying why on screen rather than only in the
    # source: the correction tables are indexed by t/s and W/s, so the
    # spacing is baked into them. Someone with a different probe head
    # needs different tables, not a different number here.
    ttk.Label(frame,
              text=f"Probe spacing s = {PROBE_SPACING_MM} mm (fixed)",
              foreground="gray").pack(anchor="w")
    ttk.Label(frame,
              text="Correction tables are indexed by t/s and W/s,\n"
                   "so they only hold for this probe head.",
              foreground="gray", justify="left").pack(anchor="w")
    return frame


def _add_diagram(exp, parent):
    """Place the W/L diagram, or a text fallback if it can't be loaded.

    A missing or unreadable image must not stop a measurement, so every
    failure here degrades to a label. The reference is stashed on the
    experiment because Tk does not hold one itself - a PhotoImage that
    goes out of scope is garbage collected and the image silently
    blanks, which is the classic Tk image bug.
    """
    try:
        from PIL import Image, ImageTk

        image = Image.open(ASSET_PATH)
        ratio = DIAGRAM_WIDTH / image.width
        resized = image.resize(
            (DIAGRAM_WIDTH, max(1, int(image.height * ratio))),
            Image.LANCZOS)
        exp._wl_diagram = ImageTk.PhotoImage(resized)
        ttk.Label(parent, image=exp._wl_diagram).pack()
        return
    except Exception as exc:                      # noqa: BLE001 - see docstring
        message = f"(W/L diagram unavailable: {exc.__class__.__name__})"

    ttk.Label(parent, text=message, foreground="gray").pack()
    ttk.Label(parent,
              text="W is the short side, L the long side.",
              foreground="gray").pack(anchor="w")
