"""
Run / Stop controls, the output lamp, and the progress line.

Two differences from the Van der Pauw and Hall action panels, both
because a sweep is a long operation rather than a quick one:

  * There is a Stop button. A periodic run can be an hour of cycles;
    the original had no way to end one early short of killing the
    window, which also lost every unsaved run.
  * There is a progress label. The original wrote "Measuring... ETA: 12s"
    into a shared message label by counting down a sleep on the GUI
    thread. Here the sweep runs on a background thread and the label
    reports points actually collected from the instrument's buffer.

There is no OFF button (decision W6-2). It was removed for the
same reason it was removed from Van der Pauw, Hall and 4PP before it:
`off_pressed()` called `abort_sweep()` and `safe_output_off()` from a
*second* background thread while the worker was mid-`measure()` on the
same transport, which is the race the run lifecycle names. Stop now
cancels the
run, and the worker de-energises on the thread that already owns the
session. Cancelling also discards, so a button that stopped without
discarding described an operation the project has ruled out.
"""
import tkinter as tk
from tkinter import ttk


def build_action_panel(exp, parent):
    """Run, Stop, the output lamp, and progress text.

    Sets exp.run_btn, exp.stop_btn, exp.lamp_canvas, exp.lamp_id,
    exp.progress_var.
    """
    frame = ttk.Frame(exp.col_mid)
    frame.pack(fill="x", pady=(8, 0))

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")

    exp.run_btn = ttk.Button(buttons, text="Run", command=exp.run_pressed)
    exp.run_btn.pack(side="left", padx=(0, 6))

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
