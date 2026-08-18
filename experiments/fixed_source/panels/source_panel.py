"""
What the SMU sources, and what protects the sample.

Deliberately close to the IV sweep's mode panel - same instrument, same
per-run settings, same shared widgets from `core/gui/widgets.py` - with
one field it does not have and two it does not need.

The field it does not have is **Level**. A sweep has a start and a stop;
this has one number that does not change for the whole run, which is the
entire difference between the two experiments.

The two it does not need are the linear fit and the sweep delay. There
is no line to fit here - a fixed source against time is not an IV curve,
and fitting a slope to it would be fitting drift - and the per-point
settle belongs to a sweep stepping between levels. Here the source
level never moves after the output goes on, so the only timing that
matters is the sample interval, which lives in the timing panel next
door.

Compliance is the quantity you are *not* sourcing: the current limit
when sourcing voltage, the voltage limit when sourcing current. The
label changes with the mode rather than staying generic, because
getting it backwards is how samples get cooked.
"""
import tkinter as tk
from tkinter import ttk

from core.gui.widgets import high_z_row, nplc_row

# Shown before an instrument is connected; replaced from the connected
# driver's declared limits in `on_connected()`.
FALLBACK_CURRENT_COMPLIANCE = ["1e-7", "1e-6", "1e-5", "1e-4", "1e-3",
                               "1e-2", "1e-1", "1"]
FALLBACK_VOLTAGE_COMPLIANCE = ["0.2", "2", "20", "200"]


def build_source_panel(exp, parent):
    """Build the source-function controls.

    Sets exp.mode_var, exp.level_var, exp.level_label, exp.compliance_var,
    exp.compliance_combo, exp.compliance_label, exp.nplc_var,
    exp.nplc_combo, exp.ovp_var, exp.ovp_combo, exp.ovp_label,
    exp.remote_sense_var, exp.remote_sense_check, exp.high_z_var,
    exp.high_z_check, exp.watch_compliance_var.
    """
    frame = ttk.LabelFrame(exp.col_left, text="Source", padding=8)
    frame.pack(fill="x", pady=(0, 6))

    exp.mode_var = tk.StringVar(value="voltage")
    ttk.Radiobutton(frame, text="Source voltage, measure current",
                    value="voltage", variable=exp.mode_var,
                    command=exp.on_mode_changed).grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Radiobutton(frame, text="Source current, measure voltage",
                    value="current", variable=exp.mode_var,
                    command=exp.on_mode_changed).grid(
        row=1, column=0, columnspan=2, sticky="w")

    ttk.Separator(frame, orient="horizontal").grid(
        row=2, column=0, columnspan=2, sticky="ew", pady=(8, 6))

    # Kept as an attribute so `on_mode_changed()` can retitle it.
    exp.level_label = ttk.Label(frame, text="Level (V):")
    exp.level_label.grid(row=3, column=0, sticky="e", padx=(0, 6))
    exp.level_var = tk.StringVar(value="0.1")
    ttk.Entry(frame, textvariable=exp.level_var, width=10).grid(
        row=3, column=1, sticky="w", pady=2)

    exp.compliance_label = ttk.Label(frame, text="Current compliance (A):")
    exp.compliance_label.grid(row=4, column=0, sticky="e", padx=(0, 6))
    exp.compliance_var = tk.StringVar(value="1e-3")
    exp.compliance_combo = ttk.Combobox(
        frame, textvariable=exp.compliance_var, width=10,
        values=FALLBACK_CURRENT_COMPLIANCE)
    exp.compliance_combo.grid(row=4, column=1, sticky="w", pady=2)

    ttk.Label(frame, text="Measurement range follows compliance.",
              foreground="gray").grid(row=5, column=0, columnspan=2,
                                      sticky="w", pady=(6, 0))

    exp.nplc_var, exp.nplc_combo = nplc_row(frame, 6)

    exp.ovp_label = ttk.Label(frame, text="Overvoltage protect:")
    exp.ovp_label.grid(row=7, column=0, sticky="e", padx=(0, 6), pady=(4, 0))
    exp.ovp_var = tk.StringVar(value="n/a")
    exp.ovp_combo = ttk.Combobox(
        frame, textvariable=exp.ovp_var, width=10, state="disabled",
        values=["n/a"])
    exp.ovp_combo.grid(row=7, column=1, sticky="w", pady=(4, 0))

    ttk.Separator(frame, orient="horizontal").grid(
        row=8, column=0, columnspan=2, sticky="ew", pady=(8, 6))

    exp.remote_sense_var = tk.BooleanVar(value=True)
    exp.remote_sense_check = ttk.Checkbutton(
        frame, text="4-wire (remote sense)", variable=exp.remote_sense_var)
    exp.remote_sense_check.grid(row=9, column=0, columnspan=2, sticky="w")

    exp.high_z_var, exp.high_z_check = high_z_row(frame, 10)

    # --- the compliance watch, and what it costs ---------------------
    #
    # A trip is a *state that comes and goes* on a run like this: a
    # sample that heats up can enter compliance twenty minutes in and
    # leave it again, and the readings either side look equally
    # reasonable. Asking once at the end would therefore answer a
    # question nobody asked.
    #
    # So it is asked per sample - and that is an extra round trip per
    # sample, which raises the shortest interval this experiment can
    # achieve on a slow bus. The trade is exposed rather than decided
    # here: leave it ticked for anything being held near its limit, and
    # untick it when the sample rate matters more than knowing exactly
    # when the clamp bit. Either way the run records which you chose,
    # because "no trips recorded" and "trips not watched for" are very
    # different statements about a file.
    exp.watch_compliance_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(frame, text="Watch compliance (1 extra query/sample)",
                    variable=exp.watch_compliance_var).grid(
        row=11, column=0, columnspan=2, sticky="w")

    return frame
