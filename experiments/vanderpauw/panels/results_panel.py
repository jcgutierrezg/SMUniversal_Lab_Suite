"""
Results table - one row per completed run.

Rows carry a ☑/☐ tick in the tree column; ticking exactly four (one per
position) enables copying their R(ave) values into the calculation boxes.
"""
from tkinter import ttk

COLUMNS = ("sample", "position", "Rpos", "Rneg", "Rave")
HEADINGS = ["Sample", "Position", "R(pos) [Ω]", "R(neg) [Ω]", "R(ave) [Ω]"]
WIDTHS = [140, 80, 120, 120, 120]


def build_results_panel(exp, parent):
    """Build the results Treeview and its buttons. Sets exp.tree."""
    frame = ttk.LabelFrame(exp.col_right, text="Results", padding=6)
    frame.pack(fill="both", expand=True)

    exp.tree = ttk.Treeview(frame, columns=COLUMNS, show="tree headings", height=8)
    exp.tree.heading("#0", text="")
    exp.tree.column("#0", width=32, anchor="center", stretch=False)

    for key, title, width in zip(COLUMNS, HEADINGS, WIDTHS):
        exp.tree.heading(key, text=title)
        exp.tree.column(key, width=width, anchor="center")
    exp.tree.pack(fill="both", expand=True)
    exp.tree.bind("<Button-1>", exp.toggle_row)

    # Left to right in the order they get used: pull the good runs into
    # the calculation, save what's worth keeping, discard what isn't.
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(6, 0))
    ttk.Button(buttons, text="Copy ticked → Calc",
               command=exp.copy_over).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Save → CSV",
               command=exp.save_runs).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Delete ticked",
               command=exp.delete_ticked).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Clear all",
               command=exp.clear_output).pack(side="left")
