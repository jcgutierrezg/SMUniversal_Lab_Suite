"""
Switch-box position selector: A and B, as the box labels them.
"""
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui.tooltips import tip


def build_positions_panel(exp, parent):
    """Radio buttons for the two measurement positions. Selecting one
    redraws the corner diagram. Sets exp.pos_var."""
    frame = ttk.LabelFrame(exp.col_left, text="Position", padding=6)
    frame.pack(fill="x", pady=(0, 6))
    tip(exp, frame,
        "Which pair of contacts carries the current and which pair "
        "senses the voltage, set on the switch box. Both positions are "
        "needed: A gives the horizontal resistance and B the vertical "
        "one, and the sheet resistance needs both. The diagram above "
        "shows the roles for the position selected here.")

    ttk.Label(frame, text="Switch box set to:").pack(side="left")
    exp.pos_var = tk.StringVar(value="A")
    for position in ("A", "B"):
        tip(exp, ttk.Radiobutton(frame, text=position, value=position,
                                 variable=exp.pos_var,
                                 command=exp.on_pos_changed),
            f"Switch box position {position}. Set the box to match "
            f"before pressing Run: the run is recorded against this "
            f"position, and nothing can check the box itself."
            ).pack(side="left", padx=4)
