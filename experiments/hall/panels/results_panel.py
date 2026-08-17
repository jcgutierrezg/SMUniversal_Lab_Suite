"""
Results table - one row per completed run.

Unlike Van der Pauw, which collapses each run to a single averaged
resistance, Hall keeps V+ and V- as separate columns. They are not two
estimates of one quantity: reversing the current is one of the two
reversals the eight-term average needs, so both numbers are carried
forward into the calculation individually.

Ticking exactly four rows - Pos1+, Pos1-, Pos2+, Pos2- - enables the
Copy button.
"""
from tkinter import ttk

COLUMNS = ("sample", "position", "b_pol", "current", "vplus", "vminus")
HEADINGS = ["Sample", "Position", "B pol", "I (A)", "V+ (V)", "V- (V)"]
WIDTHS = [150, 80, 60, 100, 110, 110]


def build_results_panel(exp, parent):
    """Build the results Treeview and its buttons. Sets exp.tree."""
    frame = ttk.LabelFrame(exp.col_right, text="Results", padding=6)
    frame.pack(fill="both", expand=True)

    # Seven rows, not eight, from Wave 5b. A Hall calculation needs
    # exactly four ticked rows - the four (position, B sign) pairs - so
    # seven still shows a complete set and most of a second. The row
    # bought about twenty vertical pixels, and in the combined window
    # this column is what sets the whole window's height: Hall's
    # results-plus-calculation column is the tallest thing either tab
    # contains. The table scrolls; the window does not.
    exp.tree = ttk.Treeview(frame, columns=COLUMNS, show="tree headings", height=7)
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
    ttk.Button(buttons, text="Save snapshot → CSV",
               command=exp.save_runs).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Delete ticked",
               command=exp.delete_ticked).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Clear all",
               command=exp.clear_output).pack(side="left")
