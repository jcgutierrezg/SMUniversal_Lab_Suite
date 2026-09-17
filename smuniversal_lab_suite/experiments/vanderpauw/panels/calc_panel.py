"""
Van der Pauw calculation: four position resistances in, Rs and rho out.

Values can be typed by hand or pulled from ticked rows in the results
table via the Copy button. Sits on the right of the row it shares with
the V-I plot - see panels/plot_panel.py.
"""
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui.tooltips import tip


def build_calc_panel(exp, parent):
    """Build the Pos1-4 inputs and the Rh/Rv/Rs/rho readouts.
    Sets exp.pos_vars (a list of four), exp.rh_var, exp.rv_var,
    exp.rs_var, exp.rho_var."""
    # On the right of the row it shares with the plot. Packed before the
    # plot, so the plot takes whatever width is left.
    frame = ttk.LabelFrame(exp.output_row, text="Calculation", padding=8)
    frame.pack(side="right", fill="y", pady=(8, 0), padx=(8, 0))
    tip(exp, frame,
        "The four position resistances go in, the sheet resistance "
        "comes out. Values copied from ticked runs carry those runs "
        "with them into the saved header; typed values do not, and the "
        "status line at the bottom says which you have.")

    exp.pos_vars = []
    for i in range(4):
        ttk.Label(frame, text=f"Pos{i+1} (Ω):").grid(
            row=i, column=0, sticky="e", padx=(4, 6), pady=1)
        var = tk.StringVar(value="")
        entry = ttk.Entry(frame, textvariable=var, width=14)
        entry.grid(row=i, column=1, sticky="w", pady=1)
        tip(exp, entry,
            "The resistance measured at this switch-box position, in "
            "ohms. Pos1 and Pos2 average into Rh, Pos3 and Pos4 into "
            "Rv. Editing a copied value drops the run behind it, since "
            "the number is no longer that run's.")
        exp.pos_vars.append(var)

    buttons = ttk.Frame(frame)
    buttons.grid(row=4, column=0, columnspan=2, pady=(8, 6))
    tip(exp, ttk.Button(buttons, text="Calculate",
                        command=exp.calculate_vdp),
        "Solve the Van der Pauw equation for the sheet resistance, and "
        "multiply by the thickness for the resistivity. The result "
        "records which runs it came from and goes stale if any input "
        "changes underneath it."
        ).pack(side="left", padx=(0, 6))
    tip(exp, ttk.Button(buttons, text="Equations...",
                        command=exp.show_equations),
        "Show the formulas this tab uses, with their symbols named - "
        "and, once a calculation is fresh, the same formulas with your "
        "numbers in them."
        ).pack(side="left")
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
    # Keep the label widgets, not only their variables: a stale
    # result is greyed rather than blanked, and greying
    # needs the widget - a StringVar has no colour.
    exp.calc_result_labels = {}
    for offset, (label, var) in enumerate(readouts):
        ttk.Label(frame, text=label).grid(
            row=6 + offset, column=0, sticky="e", padx=(4, 6))
        value_label = ttk.Label(frame, textvariable=var)
        value_label.grid(row=6 + offset, column=1, sticky="w")
        exp.calc_result_labels[label] = value_label

    # One status line, carrying the result's provenance, its staleness,
    # and any note from the solver. One label rather than several: the
    # 4PP panel showed that a second line can push a window
    # past the 1000 px ceiling `test_layout.py` enforces, and this
    # column already carries a table above it.
    exp.calc_status_var = tk.StringVar(value="")
    exp.calc_status_label = ttk.Label(
        frame, textvariable=exp.calc_status_var, foreground="#777777",
        wraplength=300, justify="left")
    exp.calc_status_label.grid(row=10, column=0, columnspan=2, sticky="w",
                               pady=(6, 0))

    return frame
