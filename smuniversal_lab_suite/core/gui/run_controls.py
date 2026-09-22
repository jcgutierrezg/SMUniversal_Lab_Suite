"""
Run and Stop, the output lamp and the progress line - for every tab.

One builder instead of five copies. Review A-08 found the same panel in
every experiment, identical but for comments and, in one, the colour of
the lamp; a lifecycle fix to one of them had to be made five times, and
the 4PP close hook had already shown how one copy gets left behind.
The run-state handlers that drive these widgets live on
`Experiment` for the same reason.

What every tab's controls share
-------------------------------
**Stop cancels.** It discards the run's data whatever its progress and
the worker de-energises on the thread that already owns the session.
There is no separate OFF button (decision W6-2): `off_pressed()` used to
call `abort_sweep()` and `safe_output_off()` from a second thread while
the worker was mid-`measure()` on the same transport - two threads, one
session, interleaved commands.

**Stop is disabled while idle**, because the output is only ever live
inside a run, and a button that is always enabled teaches an operator
that pressing it means nothing.

**The progress line reports what actually happened** - points collected
from the instrument, not a countdown slept on the GUI thread. The bar
and the time left under it are an estimate, and say so ("about"): see
`core/progress.py`.

An experiment with more ways to end a run passes them as `extra`; the
fixed-source tab is the one that does, and its panel says why.
"""
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui.tooltips import tip

#: The lamp's two states. One definition: the 4PP tab had drifted to a
#: different green from the other four.
LAMP_ON = "green"
LAMP_OFF = "gray"


def build_run_controls(exp, parent, stop_text="Stop", extra=()):
    """Run, any `extra` buttons, Stop, the output lamp and progress text.

    Built into `exp.col_mid`, as every action panel always was; `parent`
    is accepted so this has the signature every entry in `PANELS` has.

    `extra` is a sequence of `(attribute, text, command)`. Each becomes a
    button between Run and Stop, stored on `exp` under `attribute` and,
    like Stop, disabled until a run starts.

    Sets `exp.run_btn`, `exp.stop_btn`, `exp.lamp_canvas`, `exp.lamp_id`,
    `exp.progress_var`, `exp.progress_bar`, `exp.eta_var`, and each
    extra button's attribute.
    """
    frame = ttk.Frame(exp.col_mid)
    frame.pack(fill="x", pady=(8, 0))

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")

    exp.run_btn = ttk.Button(buttons, text="Run", command=exp.run_pressed)
    exp.run_btn.pack(side="left", padx=(0, 6))
    tip(exp, exp.run_btn,
        "Take the settings as they are now and measure. Nothing typed "
        "after this press changes the run in flight, and nothing is "
        "saved to disk until you press Save.")

    for attribute, text, command in extra:
        button = ttk.Button(buttons, text=text, command=command,
                            state="disabled")
        button.pack(side="left", padx=(0, 6))
        setattr(exp, attribute, button)

    exp.stop_btn = ttk.Button(buttons, text=stop_text,
                              command=exp.stop_pressed, state="disabled")
    exp.stop_btn.pack(side="left", padx=(0, 12))
    tip(exp, exp.stop_btn,
        "Cancel the run and discard its readings. The output is taken "
        "down by the thread that owns the instrument, so it happens at "
        "the next safe point rather than instantly.")

    ttk.Label(buttons, text="Output:").pack(side="left", padx=(0, 4))
    exp.lamp_canvas = tk.Canvas(buttons, width=20, height=20,
                                highlightthickness=0)
    exp.lamp_canvas.pack(side="left")
    exp.lamp_id = exp.lamp_canvas.create_oval(2, 2, 18, 18, fill=LAMP_OFF)
    tip(exp, exp.lamp_canvas,
        "Green while the instrument's output is on and the sample is "
        "live. It follows the run, not the button.")

    exp.progress_var = tk.StringVar(value="Idle")
    ttk.Label(frame, textvariable=exp.progress_var,
              style="Hint.TLabel").pack(
        anchor="w", pady=(4, 0))

    # The bar and the time left, on one row under the progress line. Both
    # are driven by `Experiment._tick_progress()` once a second from the
    # UI thread; see `core/progress.py` for where the numbers come from.
    eta_row = ttk.Frame(frame)
    eta_row.pack(fill="x", pady=(2, 0))
    exp.progress_bar = ttk.Progressbar(eta_row, mode="determinate",
                                       maximum=1.0, length=150)
    exp.progress_bar.pack(side="left")
    tip(exp, exp.progress_bar,
        "How far through the run is, and roughly how long is left. An "
        "estimate from the settings until a few readings are in, then "
        "the pace those readings are actually arriving at.")
    exp.eta_var = tk.StringVar(value="")
    ttk.Label(eta_row, textvariable=exp.eta_var,
              style="Hint.TLabel").pack(
        side="left", padx=(8, 0))

    return frame
