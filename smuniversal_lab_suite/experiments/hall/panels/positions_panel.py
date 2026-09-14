"""
Switch-box position (1-2) and magnetic field polarity.

Van der Pauw has four positions and no field. Hall has two positions and
a field that gets reversed, giving four combinations in total: Pos1+,
Pos1-, Pos2+, Pos2-. Those four are exactly what the calculation panel
needs, which is why the Copy button insists on precisely that set.

The two groups sit on separate rows rather than one long one: they are
set together at the bench, but a single row made this the widest thing in
the left column and pushed the whole window past 1920 px.
"""
import tkinter as tk
from tkinter import ttk


def build_positions_panel(exp, parent):
    """Position radios and B-polarity radios.
    Sets exp.pos_var and exp.field_sign_var."""
    frame = ttk.LabelFrame(exp.col_left, text="Position (switch box) & B polarity",
                           padding=6)
    frame.pack(fill="x", pady=(0, 6))

    pos_row = ttk.Frame(frame)
    pos_row.pack(fill="x")
    ttk.Label(pos_row, text="Switch box:").pack(side="left")
    exp.pos_var = tk.IntVar(value=1)
    for i in (1, 2):
        ttk.Radiobutton(pos_row, text=f"Pos{i}", value=i, variable=exp.pos_var,
                        command=exp.on_pos_changed).pack(side="left", padx=4)

    field_row = ttk.Frame(frame)
    field_row.pack(fill="x", pady=(4, 0))
    ttk.Label(field_row, text="B polarity:").pack(side="left")
    exp.field_sign_var = tk.StringVar(value="+")
    for sign in ("+", "-"):
        ttk.Radiobutton(field_row, text=sign, value=sign,
                        variable=exp.field_sign_var,
                        command=exp.on_pos_changed).pack(side="left", padx=4)
