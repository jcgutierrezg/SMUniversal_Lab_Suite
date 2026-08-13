"""
Hall calculation: eight measured voltages in, V_H / n_s / mu / rho out.

Layout mirrors the original: a P column and an N column of four voltages
each, a computed delta column beside them, then the four inputs the
physics needs but the measurement doesn't supply (B, R_s, I, sample
type).

B, R_s and I are typed by the user and are deliberately *never*
overwritten by the Copy button. B comes off the magnet, R_s comes from a
separate Van der Pauw run, and I may differ from the instrument's
nominal level. Having Copy silently replace them would lose numbers that
took another measurement to obtain - which is why copy_over() touches
only the eight voltage boxes.
"""
import tkinter as tk
from tkinter import ttk

# (label, attribute name) for the two voltage columns
P_FIELDS = [("V13,P (V):", "v13p_var"), ("V31,P (V):", "v31p_var"),
            ("V24,P (V):", "v24p_var"), ("V42,P (V):", "v42p_var")]
N_FIELDS = [("V13,N (V):", "v13n_var"), ("V31,N (V):", "v31n_var"),
            ("V24,N (V):", "v24n_var"), ("V42,N (V):", "v42n_var")]
DELTA_FIELDS = [("Δ13 (V):", "dv13_var"), ("Δ31 (V):", "dv31_var"),
                ("Δ24 (V):", "dv24_var"), ("Δ42 (V):", "dv42_var")]


def build_calc_panel(exp, parent):
    """Build the calculation panel.

    Sets the eight voltage vars, the four delta vars, exp.calc_B_var,
    exp.calc_Rs_var, exp.calc_I_var, exp.sample_type_var, and the
    readouts exp.vh_var, exp.ns_var, exp.mu_var, exp.rho_var.
    """
    frame = ttk.LabelFrame(exp.col_right, text="Calculation", padding=8)
    frame.pack(fill="x", pady=(8, 0))

    # --- the eight measured voltages ---
    for row, (label, attr) in enumerate(P_FIELDS):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="e",
                                          padx=(4, 6), pady=1)
        var = tk.StringVar(value="")
        setattr(exp, attr, var)
        ttk.Entry(frame, textvariable=var, width=12).grid(
            row=row, column=1, sticky="w", pady=1)

    for row, (label, attr) in enumerate(N_FIELDS):
        ttk.Label(frame, text=label).grid(row=row, column=2, sticky="e",
                                          padx=(10, 6), pady=1)
        var = tk.StringVar(value="")
        setattr(exp, attr, var)
        ttk.Entry(frame, textvariable=var, width=12).grid(
            row=row, column=3, sticky="w", pady=1)

    # --- P minus N, shown for eyeballing ---
    # Not used by the calculation. It's a sanity display: the four deltas
    # should be of comparable size, and one wildly out of line usually
    # means a contact problem rather than an interesting sample.
    for row, (label, attr) in enumerate(DELTA_FIELDS):
        ttk.Label(frame, text=label).grid(row=row, column=4, sticky="e",
                                          padx=(12, 6), pady=1)
        var = tk.StringVar(value="-")
        setattr(exp, attr, var)
        ttk.Label(frame, textvariable=var).grid(row=row, column=5,
                                                sticky="w", pady=1)

    # --- inputs the measurement can't supply ---
    ttk.Label(frame, text="B (T):").grid(row=4, column=0, sticky="e",
                                         padx=(4, 6), pady=(8, 0))
    exp.calc_B_var = tk.StringVar(value="0.82")
    ttk.Entry(frame, textvariable=exp.calc_B_var, width=12).grid(
        row=4, column=1, sticky="w", pady=(8, 0))

    ttk.Label(frame, text="Rs (Ω/□):").grid(row=4, column=2, sticky="e",
                                            padx=(10, 6), pady=(8, 0))
    exp.calc_Rs_var = tk.StringVar(value="")
    ttk.Entry(frame, textvariable=exp.calc_Rs_var, width=12).grid(
        row=4, column=3, sticky="w", pady=(8, 0))
    # Rs comes from a Van der Pauw run on the same mounted sample, so it
    # is carried over from that tab's result rather than retyped. The
    # button is disabled in a window with no Van der Pauw tab - see
    # `HallExperiment.on_panels_built`.
    exp.rs_take_btn = ttk.Button(frame, text="Take Rs from VdP", width=17,
                                 command=exp.take_rs_from_vdp)
    exp.rs_take_btn.grid(row=4, column=4, columnspan=2, sticky="w",
                         padx=(12, 0), pady=(8, 0))

    # Where the number in the Rs box came from. Worth a line of its own:
    # the box looks identical whether the value was measured next door
    # or typed from memory, and those two are not equally trustworthy.
    exp.rs_source_var = tk.StringVar(value="")
    ttk.Label(frame, textvariable=exp.rs_source_var,
              foreground="#777777").grid(
        row=5, column=4, columnspan=2, sticky="w", padx=(12, 0), pady=(2, 0))

    ttk.Label(frame, text="I (A):").grid(row=5, column=0, sticky="e",
                                         padx=(4, 6), pady=(2, 0))
    exp.calc_I_var = tk.StringVar(value="")
    ttk.Entry(frame, textvariable=exp.calc_I_var, width=12).grid(
        row=5, column=1, sticky="w", pady=(2, 0))

    ttk.Label(frame, text="Sample type:").grid(row=5, column=2, sticky="e",
                                               padx=(10, 6), pady=(2, 0))
    exp.sample_type_var = tk.StringVar(value="Thin film")
    ttk.Combobox(frame, textvariable=exp.sample_type_var,
                 values=["Thin film", "Bulk"], state="readonly",
                 width=12).grid(row=5, column=3, sticky="w", pady=(2, 0))

    ttk.Button(frame, text="Calculate", command=exp.calculate_hall).grid(
        row=6, column=0, columnspan=6, pady=(10, 6))
    ttk.Separator(frame, orient="horizontal").grid(
        row=7, column=0, columnspan=6, sticky="ew", pady=(0, 6))

    # --- results ---
    exp.vh_var = tk.StringVar(value="-")
    exp.ns_var = tk.StringVar(value="-")
    exp.mu_var = tk.StringVar(value="-")
    exp.rho_var = tk.StringVar(value="-")

    exp.carrier_type_var = tk.StringVar(value="-")

    readouts = [
        ("V_H (V):", exp.vh_var, None),
        ("Carrier type:", exp.carrier_type_var, "bold"),
        ("Carrier density:", exp.ns_var, None),
        ("Mobility:", exp.mu_var, None),
        ("Resistivity:", exp.rho_var, None),
    ]
    # Wave 5a-ii keeps the label widgets, not only their variables: a
    # stale result is greyed rather than blanked (§18), and greying
    # needs the widget - a StringVar has no colour.
    exp.calc_result_labels = {}
    for offset, (label, var, weight) in enumerate(readouts):
        ttk.Label(frame, text=label).grid(row=8 + offset, column=0,
                                          sticky="e", padx=(4, 6))
        widget = ttk.Label(frame, textvariable=var)
        if weight == "bold":
            widget.configure(font=("TkDefaultFont", 10, "bold"))
            exp.carrier_type_label = widget
        widget.grid(row=8 + offset, column=1, columnspan=3, sticky="w")
        exp.calc_result_labels[label] = widget

    # Provenance and staleness share the caveat's column, one row above
    # it. One label rather than a second block: Wave 4 learned on the
    # 4PP panel that an extra line can push a window past the 1000 px
    # ceiling `test_layout.py` enforces, and this column is the tallest
    # in the app.
    exp.calc_status_var = tk.StringVar(value="")
    # Wrapped at 600 rather than 380 from Wave 5b: the column is 660 px
    # wide, so the narrower wrap was spending vertical budget - the
    # scarce one - to leave horizontal space unused.
    exp.calc_status_label = ttk.Label(
        frame, textvariable=exp.calc_status_var, foreground="#777777",
        wraplength=600, justify="left")
    exp.calc_status_label.grid(row=14, column=0, columnspan=6, sticky="w",
                               padx=(4, 0), pady=(6, 0))

    # The caveat sits next to the answer, not in a manual nobody reads.
    # Carrier type is the one output here that software cannot verify:
    # a p-type sample wired backwards is numerically identical to an
    # n-type sample wired correctly.
    ttk.Label(frame, foreground="#777", wraplength=600, justify="left",
              text=("Carrier type is read from the sign of V_H, which "
                    "depends on the contact numbering, the field "
                    "direction and the current polarity. Confirm it once "
                    "against a sample of known type; after that it can "
                    "be trusted.")).grid(
        row=13, column=0, columnspan=6, sticky="w", padx=(4, 0), pady=(8, 0))
