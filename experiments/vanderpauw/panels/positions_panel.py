"""
Switch-box position selector (1-4).
"""
import tkinter as tk
from tkinter import ttk


def build_positions_panel(exp, parent):
    """Radio buttons for the four measurement positions. Selecting one
    redraws the corner diagram. Sets exp.pos_var."""
    frame = ttk.LabelFrame(exp.col_left, text="Position", padding=6)
    frame.pack(fill="x", pady=(0, 6))

    ttk.Label(frame, text="Switch box set to:").pack(side="left")
    exp.pos_var = tk.IntVar(value=1)
    for i in range(1, 5):
        ttk.Radiobutton(frame, text=str(i), value=i, variable=exp.pos_var,
                        command=exp.on_pos_changed).pack(side="left", padx=4)
