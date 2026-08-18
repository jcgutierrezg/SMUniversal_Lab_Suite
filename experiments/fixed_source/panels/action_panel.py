"""
Run, the two ways to end a run early, the output lamp and progress.

Why this panel has three buttons when every other one has two
------------------------------------------------------------
Everywhere else in this suite, Stop means *cancel*: the run's data is
discarded whatever its progress. That rule is deliberate and it is
right for a sweep - half an IV curve is not a shorter IV curve, it is a
curve missing the part that would have told you something.

A fixed-source run is different in kind. Its readings are independent
samples of a sample's behaviour over time, so twenty minutes of a
sixty-minute run is twenty real minutes of data. Throwing that away
because the operator saw what they needed early would be discarding a
result, not a fragment.

So the two operations are separated and each gets its own verb:

    Finish and save     stop sampling now, put the output away, keep
                        what has been collected, commit it
    Stop and discard    the house Stop, unchanged - cancel, discard,
                        de-energise

Naming, not just behaviour, is the load-bearing part. "Stop" keeps the
same meaning it has on every other tab, so an operator moving between
tabs cannot lose a run by pressing the button they have pressed a
hundred times. The new operation is a new word.

Neither button talks to the instrument
--------------------------------------
Both set a flag and return. The worker notices at its next loop
boundary and de-energises **on the thread that owns the session**.

That is the whole reason the OFF buttons were removed from the other
tabs in Wave 6 (decision W6-2): `off_pressed()` used to call
`safe_output_off()` from a second thread while the worker was
mid-`measure()` on the same VISA session - two threads, one session,
interleaved SCPI. "Finish and save" is a new control, but it is not a
new race: it is a flag, exactly as Stop is.

The cost is latency. The worker notices at the top of its next sample,
so a run with a 10 s interval can take up to one reading plus the
remainder of a wait to stop. The wait itself is cancellable, so in
practice it is one reading; `tests/test_fixed_source_lifecycle.py`
measures that bound rather than asserting it.
"""
import tkinter as tk
from tkinter import ttk


def build_action_panel(exp, parent):
    """Sets exp.run_btn, exp.finish_btn, exp.stop_btn, exp.lamp_canvas,
    exp.lamp_id, exp.progress_var."""
    frame = ttk.Frame(exp.col_mid)
    frame.pack(fill="x", pady=(8, 0))

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")

    exp.run_btn = ttk.Button(buttons, text="Run", command=exp.run_pressed)
    exp.run_btn.pack(side="left", padx=(0, 6))

    # Both disabled while idle: there is nothing to finish and nothing
    # to stop, and the output is only ever live inside a run.
    exp.finish_btn = ttk.Button(buttons, text="Finish and save",
                                command=exp.finish_pressed, state="disabled")
    exp.finish_btn.pack(side="left", padx=(0, 6))

    exp.stop_btn = ttk.Button(buttons, text="Stop and discard",
                              command=exp.stop_pressed, state="disabled")
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
