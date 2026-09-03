"""
Run / Stop, the output lamp, and the progress line.

Why there is no separate OFF button
-----------------------------------
The last of the experiments to lose it, for the reasons established on
the Ossila 4PP panel and repeated on Van der
Pauw: `off_pressed()` sent `safe_output_off()` from a *second* thread
onto the same VISA session the worker was potentially mid-`measure()`
on, and it de-energised without discarding, which the run lifecycle
had already ruled out - all cancelled runs are discarded regardless
of progress.

Hall has its own reason on top of those. A run here is one half of a
pair: the calculation needs Pos1+ and Pos1-, Pos2+ and Pos2-, and it is
the *difference* between the field directions that carries the signal.
A control that stopped a run partway and kept its readings would put a
row in the table that looks like the other seven and is not comparable
with any of them. There is no safe partial Hall run.

Stop cancels this run's token; the worker notices at its next checkpoint
and puts the output away on the thread that owns the session. The
provisional readings never reach the table.
"""
import tkinter as tk
from tkinter import ttk


def build_action_panel(exp, parent):
    """Run and Stop buttons, the output lamp, and a progress line.

    Sets exp.run_btn, exp.stop_btn, exp.lamp_canvas, exp.lamp_id,
    exp.progress_var.
    """
    frame = ttk.Frame(exp.col_mid)
    frame.pack(fill="x", pady=(8, 0))

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")

    exp.run_btn = ttk.Button(buttons, text="Run", command=exp.run_pressed)
    exp.run_btn.pack(side="left", padx=(0, 6))

    # Disabled while idle: the output is only ever live inside a run.
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
