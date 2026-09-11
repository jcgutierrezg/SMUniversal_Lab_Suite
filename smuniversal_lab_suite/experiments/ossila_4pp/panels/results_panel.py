"""
Results table - one row per completed run, plus the derived quantities.

House button set, house order. The first button is "Copy ticked → Calc"
here rather than the IV sweep's "→ Plot", because unlike a plain IV
sweep this experiment *does* have a calculation stage: the fitted
resistance still has to go through the geometry and thickness
corrections before it means anything. So the ticked row feeds the
calculation panel, exactly as it does in Van der Pauw and Hall.
"""
from tkinter import ttk

COLUMNS = ("dataset", "mode", "points", "resistance", "r2", "rs")
HEADINGS = ["Dataset", "Mode", "Pts", "R (Ω)", "R²", "Rs (Ω/□)"]
WIDTHS = [140, 80, 45, 95, 70, 95]


def build_results_panel(exp, parent):
    """Build the results Treeview and its buttons. Sets exp.tree."""
    frame = ttk.LabelFrame(exp.col_right, text="Results", padding=6)
    frame.pack(fill="both", expand=True)

    # Four rows, not the six the other experiments use. This column
    # carries three panels rather than two - results, calculation and
    # plot - and height is the scarce dimension. The table scrolls.
    exp.tree = ttk.Treeview(frame, columns=COLUMNS, show="tree headings",
                            height=4)
    exp.tree.heading("#0", text="")
    exp.tree.column("#0", width=32, anchor="center", stretch=False)

    for key, title, width in zip(COLUMNS, HEADINGS, WIDTHS):
        exp.tree.heading(key, text=title)
        exp.tree.column(key, width=width, anchor="center")
    exp.tree.pack(fill="both", expand=True)
    exp.tree.bind("<Button-1>", exp.toggle_row)

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(6, 0))
    ttk.Button(buttons, text="Copy ticked → Calc",
               command=exp.copy_over).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Save snapshot → CSV",
               command=exp.save_runs).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Delete ticked",
               command=exp.delete_ticked).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Clear all",
               command=exp.clear_output).pack(side="left")

    return frame
