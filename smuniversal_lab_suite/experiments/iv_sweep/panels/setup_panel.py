"""
Sweep setup: start, stop, points, delay, naming, repeats, save path.

Laid out as a single column of label-and-field rows, matching the Van der
Pauw and Hall setup panels. Same reasoning as there: it reads top to
bottom in the order it gets filled in, and it keeps the middle column
narrow so the results column can have the width.

The field labels change with the sweep mode - "Start voltage (V)" versus
"Start current (A)" - because the same four boxes drive both. The
original did this too, via set_label_text() on its LabeledEntry.

Two names, not one
------------------
The original had a single "Dataset name" that served as the plot legend
entry. Saving groups runs by sample, so this panel carries both:

    Sample name   groups runs into one CSV file, as in every other
                  experiment. Runs of the same sample belong together.
    Dataset       labels this particular sweep in the plot legend and
                  the results table.

Repeats are auto-suffixed onto the dataset name: "run (1)", "run (2)",
and "run (3-2)" for the second repeat of the third periodic cycle -
matching the original's naming exactly, so old and new files line up.
"""
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui.tooltips import HELP, tip
from smuniversal_lab_suite.core.gui.widgets import entry_row, field_label


def build_setup_panel(exp, parent):
    """Build the sweep setup form.

    Sets exp.start_var, exp.stop_var, exp.points_var, exp.delay_var,
    exp.dataset_var, exp.runs_var, exp.sample_name_var, and the
    start/stop labels so they can be relabelled on a mode change.
    """
    frame = ttk.LabelFrame(exp.col_mid, text="Sweep setup", padding=8)
    frame.pack(fill="x")
    tip(exp, frame,
        "The sweep itself: from Start to Stop in the given number of "
        "points, waiting Delay at each. The labels follow the mode - "
        "volts when sourcing voltage, amps when sourcing current. "
        "Repeats run the same sweep again under one Run press, and "
        "Dataset names each of them in the plot and the table.")

    # Kept as attributes so on_mode_changed() can retitle them.
    start_help = ("Where the sweep begins, in the unit the label shows - "
                  "volts when sourcing voltage, amps when sourcing current.")
    exp.start_label = field_label(frame, 0, "Start voltage (V):",
                                  help=start_help, owner=exp)
    exp.start_var = tk.StringVar(value="-1.0")
    tip(exp, ttk.Entry(frame, textvariable=exp.start_var, width=13),
        start_help).grid(row=0, column=1, sticky="w", pady=2)

    stop_help = ("Where the sweep ends. A Stop below Start sweeps "
                 "downwards.")
    exp.stop_label = field_label(frame, 1, "Stop voltage (V):",
                                 help=stop_help, owner=exp)
    exp.stop_var = tk.StringVar(value="1.0")
    tip(exp, ttk.Entry(frame, textvariable=exp.stop_var, width=13),
        stop_help).grid(row=1, column=1, sticky="w", pady=2)

    exp.points_var = entry_row(
        frame, 2, "Points:", 10, owner=exp,
        help="How many levels the sweep steps through, from Start to "
             "Stop. More points draw a finer curve and take longer.")
    exp.delay_var = entry_row(
        frame, 3, "Delay (s):", 0.1, owner=exp,
        help="How long to wait at each level before reading it - time "
             "for the sample and the leads to settle. Too short and a "
             "slow sample's curve lags the source.")

    ttk.Separator(frame, orient="horizontal").grid(
        row=4, column=0, columnspan=2, sticky="ew", pady=(8, 6))

    exp.dataset_var = entry_row(frame, 5, "Dataset:", "run", owner=exp,
                                help=HELP["dataset"])
    exp.runs_var = entry_row(
        frame, 6, "Repeats:", 1, width=6, owner=exp,
        help="Run the same sweep this many times under one Run press. "
             "Each becomes a row of its own.")
    # The sample name is the app's variable, not a new one.
    # `Experiment.sample_name_var` is a read-only property returning it,
    # so assigning here would raise - which is the point: one sample
    # name per window, in one variable.
    field_label(frame, 7, "Sample name:", help=HELP["sample_name"],
                owner=exp)
    tip(exp, ttk.Entry(frame, textvariable=exp.app.sample_name_var, width=13),
        HELP["sample_name"]).grid(row=7, column=1, sticky="w", pady=2)

    # "Next #" and the save path bind to the *app's* variables rather
    # than creating new ones. Before, each setup panel did
    # `exp.app.measnum_var = tk.IntVar(...)`, which quietly rebound an
    # app-level attribute from inside a panel - harmless in a
    # one-experiment window and a silent wrong readout in a window
    # hosting two. The IV sweep keeps the widgets here because it does
    # not join the combined window and has the room; Van der Pauw and
    # Hall show the same variables on the session strip instead.
    field_label(frame, 8, "Next #:", help=HELP["next_number"], owner=exp)
    tip(exp, ttk.Entry(frame, textvariable=exp.app.measnum_var, width=6,
                       state="readonly"),
        HELP["next_number"]).grid(row=8, column=1, sticky="w", pady=2)

    # --- save path ---
    ttk.Separator(frame, orient="horizontal").grid(
        row=9, column=0, columnspan=2, sticky="ew", pady=(8, 6))
    tip(exp, ttk.Button(frame, text="Save path...",
                        command=exp.app.select_path),
        HELP["save_path"]).grid(row=10, column=0, sticky="e", padx=(0, 6))
    tip(exp, ttk.Entry(frame, textvariable=exp.app.path_display_var,
                       width=22, state="readonly"),
        HELP["save_folder"]).grid(row=10, column=1, sticky="w")

    return frame
