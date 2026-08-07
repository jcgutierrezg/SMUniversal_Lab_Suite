"""
Van der Pauw calculation: four position resistances in, Rs and rho out.

Values can be typed by hand or pulled from ticked rows in the results
table via the Copy button.
"""
import tkinter as tk
from tkinter import ttk


def build_calc_panel(exp, parent):
    """Build the Pos1-4 inputs and the Rh/Rv/Rs/rho readouts.
    Sets exp.pos_vars (a list of four), exp.rh_var, exp.rv_var,
    exp.rs_var, exp.rho_var."""
    frame = ttk.LabelFrame(exp.col_right, text="Calculation", padding=8)
    frame.pack(fill="x", pady=(8, 0))

    exp.pos_vars = []
    for i in range(4):
        ttk.Label(frame, text=f"Pos{i+1} (Ω):").grid(
            row=i, column=0, sticky="e", padx=(4, 6), pady=1)
        var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=var, width=14).grid(
            row=i, column=1, sticky="w", pady=1)
        exp.pos_vars.append(var)

    ttk.Button(frame, text="Calculate", command=exp.calculate_vdp).grid(
        row=4, column=0, columnspan=2, pady=(8, 6))
    ttk.Separator(frame, orient="horizontal").grid(
        row=5, column=0, columnspan=2, sticky="ew", pady=(0, 6))

    exp.rh_var = tk.StringVar(value="-")
    exp.rv_var = tk.StringVar(value="-")
    exp.rs_var = tk.StringVar(value="-")
    exp.rho_var = tk.StringVar(value="-")

    readouts = [
        ("Rh (Ω):", exp.rh_var),
        ("Rv (Ω):", exp.rv_var),
        ("Rs (Ω/□):", exp.rs_var),
        ("ρ (Ω·cm):", exp.rho_var),
    ]
    for offset, (label, var) in enumerate(readouts):
        ttk.Label(frame, text=label).grid(
            row=6 + offset, column=0, sticky="e", padx=(4, 6))
        ttk.Label(frame, textvariable=var).grid(
            row=6 + offset, column=1, sticky="w")
