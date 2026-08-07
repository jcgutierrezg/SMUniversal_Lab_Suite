"""
Results table - one row per completed sweep.

A sweep is a whole run: the row is the sweep, and its hundreds of raw
points are the readings behind it. So the row shows what identifies the
sweep and what came out of it, not the data itself - that is what the
plot beside it and the saved CSV are for.

The tree is short (six rows) on purpose. It shares the right-hand column
with the plot, and height is the scarce dimension in this layout; the
table scrolls, the plot can't usefully shrink further.

The four buttons are the house set, in the house order. "Copy ticked →
Plot" is this experiment's version of the copy action: Van der Pauw and
Hall copy ticked rows into a calculation grid, and the equivalent here
is putting them on the axes, since the fit is computed per sweep and
there is no separate calculation to feed.
"""
from tkinter import ttk

COLUMNS = ("dataset", "mode", "span", "points", "resistance", "r2")
HEADINGS = ["Dataset", "Mode", "Start → Stop", "Pts", "R (Ω)", "R²"]
WIDTHS = [150, 60, 130, 45, 100, 75]


def build_results_panel(exp, parent):
    """Build the results Treeview and its buttons. Sets exp.tree."""
    frame = ttk.LabelFrame(exp.col_right, text="Results", padding=6)
    frame.pack(fill="both", expand=True)

    exp.tree = ttk.Treeview(frame, columns=COLUMNS, show="tree headings",
                            height=6)
    exp.tree.heading("#0", text="")
    exp.tree.column("#0", width=32, anchor="center", stretch=False)

    for key, title, width in zip(COLUMNS, HEADINGS, WIDTHS):
        exp.tree.heading(key, text=title)
        exp.tree.column(key, width=width, anchor="center")
    exp.tree.pack(fill="both", expand=True)
    exp.tree.bind("<Button-1>", exp.toggle_row)

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(6, 0))
    ttk.Button(buttons, text="Copy ticked → Plot",
               command=exp.copy_over).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Save → CSV",
               command=exp.save_runs).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Delete ticked",
               command=exp.delete_ticked).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Clear all",
               command=exp.clear_output).pack(side="left")
