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

from core.gui.widgets import entry_row, field_label

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

    exp.duration_var = entry_row(frame, 0, "Duration (s):", 60, width=10)
    exp.interval_var = entry_row(frame, 1, "Sample every (s):", 0.5, width=10)

    # Recomputed as either box is typed in, so the consequence of a
    # 10 ms interval over an hour is visible before the run rather than
    # after it.
    exp.nominal_var = tk.StringVar(value="")
    ttk.Label(frame, textvariable=exp.nominal_var, foreground="gray").grid(
        row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
    for var in (exp.duration_var, exp.interval_var):
        var.trace_add("write", lambda *_: exp.on_timing_changed())

    ttk.Separator(frame, orient="horizontal").grid(
        row=3, column=0, columnspan=2, sticky="ew", pady=(8, 6))

    exp.dataset_var = entry_row(frame, 4, "Dataset:", "run")

    # The sample name is the app's variable, not a new one: one sample
    # name per window, in one variable. `Experiment.sample_name_var` is
    # a read-only property, so assigning here would raise - which is the
    # point.
    field_label(frame, 5, "Sample name:")
    ttk.Entry(frame, textvariable=exp.app.sample_name_var, width=13).grid(
        row=5, column=1, sticky="w", pady=2)

    field_label(frame, 6, "Next #:")
    ttk.Entry(frame, textvariable=exp.app.measnum_var, width=6,
              state="readonly").grid(row=6, column=1, sticky="w", pady=2)

    ttk.Separator(frame, orient="horizontal").grid(
        row=7, column=0, columnspan=2, sticky="ew", pady=(8, 6))
    ttk.Button(frame, text="Save path...", command=exp.app.select_path).grid(
        row=8, column=0, sticky="e", padx=(0, 6))
    ttk.Entry(frame, textvariable=exp.app.path_display_var, width=22,
              state="readonly").grid(row=8, column=1, sticky="w")

    return frame
