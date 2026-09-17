"""
Results table - one row per completed run.

Rows carry a ☑/☐ tick in the tree column; ticking exactly four (one per
position) enables copying their R(ave) values into the calculation boxes.
Ticked rows are also what the plot draws.

R(fit) and R² are the straight line through both polarities' readings.
They sit beside R(ave) rather than replacing it: which of the two feeds
the calculation is still to be decided on the bench, and until then
R(ave) does, as it always has.
"""
from tkinter import ttk

from smuniversal_lab_suite.core.gui.tooltips import tip

COLUMNS = ("sample", "position", "Rpos", "Rneg", "Rave", "Rfit", "r2")
HEADINGS = ["Sample", "Position", "R(pos) [Ω]", "R(neg) [Ω]", "R(ave) [Ω]",
            "R(fit) [Ω]", "R²"]
WIDTHS = [110, 60, 95, 95, 95, 95, 70]


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
    tip(exp, exp.tree,
        "One row per completed run, still in memory and not yet on "
        "disk. Click the box at the left to tick a row: ticked rows are "
        "what the buttons below and the plot act on. R(ave) is the mean "
        "of the two polarities; R(fit) is the slope of the line through "
        "all their readings.")

    # Left to right in the order they get used: pull the good runs into
    # the calculation, save what's worth keeping, discard what isn't.
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(6, 0))
    tip(exp, ttk.Button(buttons, text="Copy ticked → Calc",
                        command=exp.copy_over),
        "Put the four ticked runs' R(ave) into the calculation boxes, "
        "one per position, and calculate. Exactly four rows, one per "
        "position, or it refuses - three positions still produce a "
        "number, just not this sample's sheet resistance."
        ).pack(side="left", padx=(0, 6))
    tip(exp, ttk.Button(buttons, text="Save snapshot → CSV",
                        command=exp.save_runs),
        "Write every run in the table to one CSV per sample, with the "
        "calculation in its header. Nothing reaches disk until you "
        "press this."
        ).pack(side="left", padx=(0, 6))
    tip(exp, ttk.Button(buttons, text="Delete ticked",
                        command=exp.delete_ticked),
        "Discard the ticked runs and their readings. This is why "
        "nothing saves automatically: a run spoiled by a poor contact "
        "never reaches the disk at all."
        ).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Clear all",
               command=exp.clear_output).pack(side="left")
