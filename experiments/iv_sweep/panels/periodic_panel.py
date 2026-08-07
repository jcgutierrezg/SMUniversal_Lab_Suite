"""
Periodic measurement - the long-bias feature.

What it does, in the original's terms: hold the sample at a standby bias
for `period` seconds, run the sweep, repeat `cycles` times. The point is
stress-over-time - watching whether an IV curve drifts while the device
sits under bias - so the bias is applied *between* sweeps, not during
them.

Three standby options, unchanged from the original:

    Bias voltage   hold a fixed voltage between sweeps
    Bias current   hold a fixed current between sweeps
    Remain idle    output off between sweeps

"Remain idle" is not the same as doing nothing. The original explicitly
switched the output off for the period and back on afterwards, which is
a real experimental condition: the device relaxes with no field across
it. It is kept as a distinct choice for that reason.

The output stays on across the sweep boundary in the two biased modes -
that is what the `alreadyOn` flag in the original's voltage_sweep() was
for. Dropping the output between a bias hold and the sweep that measures
its effect would discharge the very thing being measured.

This panel is optional in the sense the handoff describes: remove it
from PANELS and the experiment is a plain sweep tool with no other
changes needed.
"""
import tkinter as tk
from tkinter import ttk

from core.gui.widgets import entry_row, field_label

STANDBY_MODES = ["Bias voltage", "Bias current", "Remain idle"]


def build_periodic_panel(exp, parent):
    """Build the periodic-run controls.

    Sets exp.cycles_var, exp.period_var, exp.standby_var, exp.bias_var,
    exp.bias_label, exp.periodic_btn, exp.eta_var.
    """
    frame = ttk.LabelFrame(exp.col_mid, text="Periodic measurement",
                           padding=8)
    frame.pack(fill="x", pady=(8, 0))

    exp.cycles_var = entry_row(frame, 0, "Cycles:", 10, width=6)
    exp.period_var = entry_row(frame, 1, "Cycle period (s):", 10, width=6)

    field_label(frame, 2, "Between sweeps:")
    exp.standby_var = tk.StringVar(value="Remain idle")
    ttk.Combobox(frame, textvariable=exp.standby_var, state="readonly",
                 width=13, values=STANDBY_MODES).grid(
        row=2, column=1, sticky="w", pady=2)
    exp.standby_var.trace_add("write", lambda *_: exp.on_standby_changed())

    exp.bias_label = field_label(frame, 3, "Bias level:")
    exp.bias_var = tk.StringVar(value="0")
    ttk.Entry(frame, textvariable=exp.bias_var, width=13).grid(
        row=3, column=1, sticky="w", pady=2)

    ttk.Separator(frame, orient="horizontal").grid(
        row=4, column=0, columnspan=2, sticky="ew", pady=(8, 6))

    exp.periodic_btn = ttk.Button(frame, text="Run periodic",
                                  command=exp.run_periodic_pressed)
    exp.periodic_btn.grid(row=5, column=0, sticky="w")

    exp.eta_var = tk.StringVar(value="ETA: -")
    ttk.Label(frame, textvariable=exp.eta_var, foreground="gray").grid(
        row=5, column=1, sticky="w", padx=(6, 0))

    return frame
