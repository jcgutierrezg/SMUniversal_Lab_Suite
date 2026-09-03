"""
Run / Stop, the output lamp, and the progress line.

A four-point-probe run is shorter than a periodic IV run but still long
enough to want a Stop: with reversal averaging on, eight readings per
current times thirty currents is 240 settle delays.

Why there is no separate OFF button
-----------------------------------
There used to be two controls, and the split was a fiction. Stop meant
"finish the current point and keep what we have"; OFF meant "de-energise
now". Neither did the whole job, and OFF did its half from a second
thread - sending `safe_output_off()` down the same VISA session the
worker was mid-`measure()` on.

Stop now does all of it: cancels the run, discards its data, and lets
the worker put the output away on the thread that owns the session.
The rule is plain - all cancelled runs are discarded regardless of
progress - so a control that
stopped without discarding was describing an operation the project had
already decided against.

One button also means one answer to "how do I make it stop?", which
matters more at a bench with a live probe on a film than any amount of
granularity does.
"""
import tkinter as tk
from tkinter import ttk


def build_action_panel(exp, parent):
    """Sets exp.run_btn, exp.stop_btn, exp.lamp_canvas, exp.lamp_id,
    exp.progress_var."""
    frame = ttk.Frame(exp.col_mid)
    frame.pack(fill="x", pady=(8, 0))

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")

    exp.run_btn = ttk.Button(buttons, text="Run", command=exp.run_pressed)
    exp.run_btn.pack(side="left", padx=(0, 6))

    # Stop is the only way to interrupt a run, and it de-energises.
    # Disabled while idle, because there is nothing to stop - the output
    # is only ever live inside a run, and the worker's cleanup is what
    # puts it away.
    exp.stop_btn = ttk.Button(buttons, text="Stop", command=exp.stop_pressed,
                              state="disabled")
    exp.stop_btn.pack(side="left", padx=(0, 12))

    ttk.Label(buttons, text="Output:").pack(side="left", padx=(0, 4))
    exp.lamp_canvas = tk.Canvas(buttons, width=20, height=20,
                                highlightthickness=0)
    exp.lamp_canvas.pack(side="left")
    exp.lamp_id = exp.lamp_canvas.create_oval(2, 2, 18, 18, fill="gray")

    exp.progress_var = tk.StringVar(value="Idle")
    ttk.Label(frame, textvariable=exp.progress_var, foreground="gray").pack(
        anchor="w", pady=(4, 0))

    return frame
