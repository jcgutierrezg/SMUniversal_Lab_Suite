"""
Run / OFF controls and the output indicator lamp.
"""
import tkinter as tk
from tkinter import ttk


def build_action_panel(exp, parent):
    """Run and OFF buttons plus the output lamp.
    Sets exp.run_btn, exp.off_btn, exp.lamp_canvas, exp.lamp_id."""
    frame = ttk.Frame(exp.col_mid)
    frame.pack(fill="x", pady=(8, 0))

    exp.run_btn = ttk.Button(frame, text="Run", command=exp.run_pressed)
    exp.run_btn.pack(side="left", padx=(0, 6))

    exp.off_btn = ttk.Button(frame, text="OFF", command=exp.off_pressed,
                             state="disabled")
    exp.off_btn.pack(side="left", padx=(0, 12))

    ttk.Label(frame, text="Output:").pack(side="left", padx=(0, 4))
    exp.lamp_canvas = tk.Canvas(frame, width=20, height=20,
                                highlightthickness=0)
    exp.lamp_canvas.pack(side="left")
    exp.lamp_id = exp.lamp_canvas.create_oval(2, 2, 18, 18, fill="gray")
