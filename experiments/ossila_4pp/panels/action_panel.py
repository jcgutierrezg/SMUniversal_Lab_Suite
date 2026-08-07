"""
Run / Stop / OFF, the output lamp, and the progress line.

Same shape as the IV sweep's action panel. A four-point-probe run is
shorter than a periodic IV run but still long enough to want a Stop:
with reversal averaging on, eight readings per current times thirty
currents is 240 settle delays.
"""
import tkinter as tk
from tkinter import ttk


def build_action_panel(exp, parent):
    """Sets exp.run_btn, exp.stop_btn, exp.off_btn, exp.lamp_canvas,
    exp.lamp_id, exp.progress_var."""
    frame = ttk.Frame(exp.col_mid)
    frame.pack(fill="x", pady=(8, 0))

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")

    exp.run_btn = ttk.Button(buttons, text="Run", command=exp.run_pressed)
    exp.run_btn.pack(side="left", padx=(0, 6))

    exp.stop_btn = ttk.Button(buttons, text="Stop", command=exp.stop_pressed,
                              state="disabled")
    exp.stop_btn.pack(side="left", padx=(0, 6))

    exp.off_btn = ttk.Button(buttons, text="OFF", command=exp.off_pressed,
                             state="disabled")
    exp.off_btn.pack(side="left", padx=(0, 12))

    ttk.Label(buttons, text="Output:").pack(side="left", padx=(0, 4))
    exp.lamp_canvas = tk.Canvas(buttons, width=20, height=20,
                                highlightthickness=0)
    exp.lamp_canvas.pack(side="left")
    exp.lamp_id = exp.lamp_canvas.create_oval(2, 2, 18, 18, fill="gray")

    exp.progress_var = tk.StringVar(value="Idle")
    ttk.Label(frame, textvariable=exp.progress_var, foreground="gray").pack(
        anchor="w", pady=(4, 0))

    return frame
