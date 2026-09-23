"""
The clock: how long to hold, and how often to sample.

Duration is authoritative
-------------------------
Two of {duration, interval, sample count} can be chosen; the third
follows. This panel asks for the first two, and the count is whatever
lands.

That is not an arbitrary pick. The duration is the length of time the
sample spends energised, and it is the number the operator is really
setting - the timer exists so that nobody walks away from a live
fixture. A count-authoritative run ("take 3600 samples") would run for
however long that takes on this instrument at this integration time,
which is exactly the property a timer is supposed to remove.

So the run stops when the clock says so, and how many samples fit inside
it depends on the instrument. The nominal count shown beside the
interval is arithmetic, not a promise; the achieved count and the
achieved mean interval are both recorded with the data.

There is no upper bound on the duration field. An overnight bias-stress
run is a real experiment, and a cap chosen here would be a guess about
somebody else's measurement. What there is instead is a confirmation
above `LONG_RUN_WARNING_S`, so a duration typed with an extra zero is
caught by a human rather than by a cap.
"""
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui.tooltips import HELP, tip
from smuniversal_lab_suite.core.gui.widgets import entry_row, field_label

#: Above this, the Run press asks the operator to confirm. Ten minutes:
#: long enough that a routine measurement never sees the dialog, short
#: enough that "600" typed instead of "60" does.
LONG_RUN_WARNING_S = 600.0


def build_timing_panel(exp, parent):
    """Build the timing form.

    Sets exp.duration_var, exp.interval_var, exp.dataset_var and
    exp.nominal_var.
    """
    frame = ttk.LabelFrame(exp.col_mid, text="Timing", padding=8)
    frame.pack(fill="x")
    tip(exp, frame, "How long to hold the level, and how often to read.")
    exp.duration_var = entry_row(
        frame, 0, "Duration (s):", 60, width=10, owner=exp,
        help="How long the run lasts, in seconds. Anything over ten "
             "minutes asks you to confirm when you press Run - '600' "
             "typed for '60' is an easy slip.")
    exp.interval_var = entry_row(
        frame, 1, "Sample every (s):", 0.5, width=10, owner=exp,
        help="Seconds between readings. The line below says how many "
             "that makes; an interval shorter than the instrument can "
             "manage gives fewer readings, not faster ones.")

    # Recomputed as either box is typed in, so the consequence of a
    # 10 ms interval over an hour is visible before the run rather than
    # after it.
    exp.nominal_var = tk.StringVar(value="")
    ttk.Label(frame, textvariable=exp.nominal_var,
              style="Hint.TLabel").grid(
        row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
    for var in (exp.duration_var, exp.interval_var):
        var.trace_add("write", lambda *_: exp.on_timing_changed())

    ttk.Separator(frame, orient="horizontal").grid(
        row=3, column=0, columnspan=2, sticky="ew", pady=(8, 6))

    exp.dataset_var = entry_row(frame, 4, "Dataset:", "run", owner=exp,
                                help=HELP["dataset"])

    # The sample name is the app's variable, not a new one: one sample
    # name per window, in one variable. `Experiment.sample_name_var` is
    # a read-only property, so assigning here would raise - which is the
    # point.
    field_label(frame, 5, "Sample name:", help=HELP["sample_name"],
                owner=exp)
    tip(exp, ttk.Entry(frame, textvariable=exp.app.sample_name_var, width=13),
        HELP["sample_name"]).grid(row=5, column=1, sticky="w", pady=2)

    field_label(frame, 6, "Next #:", help=HELP["next_number"], owner=exp)
    tip(exp, ttk.Entry(frame, textvariable=exp.app.measnum_var, width=6,
                       state="readonly"),
        HELP["next_number"]).grid(row=6, column=1, sticky="w", pady=2)

    ttk.Separator(frame, orient="horizontal").grid(
        row=7, column=0, columnspan=2, sticky="ew", pady=(8, 6))
    tip(exp, ttk.Button(frame, text="Save path...",
                        command=exp.app.select_path),
        HELP["save_path"]).grid(row=8, column=0, sticky="e", padx=(0, 6))
    tip(exp, ttk.Entry(frame, textvariable=exp.app.path_display_var,
                       width=22, state="readonly"),
        HELP["save_folder"]).grid(row=8, column=1, sticky="w")

    return frame
