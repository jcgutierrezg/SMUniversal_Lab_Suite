"""
Run / Stop, the output lamp, and the progress line.

Why there is no separate OFF button (Wave 5a-i)
----------------------------------------------
There used to be two controls, and the split was a fiction - the same
one Wave 3 removed from the Ossila 4PP panel, for the same reasons,
which are worth stating here rather than pointing at.

`off_pressed()` ran `safe_output_off()` on a *second* background thread
while the worker was potentially mid-`measure()` on the same VISA
session. Two threads, one session, interleaved SCPI. On a Van der Pauw
run that window is wide: each polarity block sleeps for the settle
delay and then takes `points` readings back to back.

Worse, neither button did the whole job. OFF de-energised but left the
run's readings on their way to the results table, so a measurement
abandoned halfway could still be recorded and averaged into an R(ave).
Review §8 states the rule plainly - all cancelled runs are discarded
regardless of progress - so a control that de-energised without
discarding was performing an operation the project had already decided
against.

Stop now does all of it: it cancels this run's token, the worker notices
at its next checkpoint, and the worker's own cleanup puts the output
away on the thread that owns the session. The provisional readings never
reach the table.

One button also means one answer to "how do I make it stop?", which
matters more at a bench with four probes on a film than any amount of
granularity does.
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

    # Disabled while idle, because there is nothing to stop: the output
    # is only ever live inside a run.
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
