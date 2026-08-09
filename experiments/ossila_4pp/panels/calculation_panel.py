"""
The calculation stage: measured resistance in, sheet resistance out.

Kept visible rather than folded into the run because the two correction
factors are the part most worth checking. A geometry factor of 0.22 and
one of 0.99 differ by more than a factor of four in the final answer,
and the difference comes entirely from numbers typed into the geometry
panel. Showing both factors means a mistyped dimension is visible as a
suspicious factor rather than only as a wrong result.

Mirrors the Van der Pauw and Hall calculation panels: ticked rows are
copied in, the button recomputes, the outputs sit underneath.
"""
import tkinter as tk
from tkinter import ttk


def build_calculation_panel(exp, parent):
    """Build the calculation block into exp.col_right."""
    frame = ttk.LabelFrame(exp.col_right, text="Calculation", padding=6)
    frame.pack(fill="x", pady=(8, 0))

    top = ttk.Frame(frame)
    top.pack(fill="x")

    exp.calc_r_var = tk.StringVar()
    ttk.Label(top, text="Measured R (Ω):", width=16, anchor="e").grid(
        row=0, column=0, sticky="e", padx=(0, 6), pady=2)
    ttk.Entry(top, textvariable=exp.calc_r_var, width=14).grid(
        row=0, column=1, sticky="w", pady=2)

    ttk.Button(top, text="Calculate", command=exp.calculate).grid(
        row=0, column=2, padx=(12, 0))

    ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(8, 6))

    outputs = ttk.Frame(frame)
    outputs.pack(fill="x")

    exp.result_vars = {}
    # Wave 4 keeps the label widgets, not only their variables. A stale
    # result is greyed rather than blanked (§18), and greying needs the
    # widget - a StringVar has no colour.
    exp.result_labels = {}
    exp.result_unit_labels = {}
    rows = [
        ("sheet", "Sheet resistance:", "Ω/□"),
        ("resistivity", "Resistivity:", "Ω·m"),
        ("conductivity", "Conductivity:", "S/m"),
        ("f_thickness", "Thickness factor:", ""),
        ("f_geometry", "Geometry factor:", ""),
    ]
    for row, (key, label, unit) in enumerate(rows):
        ttk.Label(outputs, text=label, width=18, anchor="e").grid(
            row=row, column=0, sticky="e", padx=(0, 6), pady=1)
        var = tk.StringVar(value="-")
        exp.result_vars[key] = var
        value_label = ttk.Label(outputs, textvariable=var, anchor="w")
        value_label.grid(row=row, column=1, sticky="w", pady=1)
        exp.result_labels[key] = value_label
        if unit:
            unit_label = ttk.Label(outputs, text=unit, foreground="gray")
            unit_label.grid(row=row, column=2, sticky="w", padx=(4, 0))
            exp.result_unit_labels[key] = unit_label

    # One status line, carrying two kinds of thing.
    #
    # Warnings from the correction tables - out-of-range thickness, a
    # sample too small for the geometry table - both return a usable
    # number and both make it approximate, so the warning has to sit
    # next to the result rather than only in the console where it
    # scrolls away. Wave 4 adds the result's provenance and its
    # staleness (§18) to the same line, for the same reason: the only
    # place a "this no longer follows from what is on screen" warning
    # does any good is beside the number it is about.
    #
    # **One label, not two.** A second line put the 4PP window at
    # 1005 px against the 1000 px ceiling and `test_layout.py` refused
    # it. That is the layout rule working, not an obstacle to route
    # around: this column already carries an extra panel, and the
    # landscape constraint is a house requirement. The composition
    # lives in `Ossila4PPExperiment._refresh_calc_status()`.
    exp.calc_status_var = tk.StringVar(value="")
    exp.calc_status_label = ttk.Label(
        frame, textvariable=exp.calc_status_var, foreground="#a05000",
        wraplength=380, justify="left")
    exp.calc_status_label.pack(anchor="w", pady=(6, 0))

    return frame
