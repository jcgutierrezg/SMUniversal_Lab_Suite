"""
Results table - one row per completed run.

House button set, house order. The first button is "Copy ticked → Plot"
rather than "→ Calc", as in the IV sweep: this experiment derives no
physical quantity, so there is no calculation panel for a row to feed.

The columns are chosen to make the two things that go wrong here visible
from the table, without opening the file:

    Samples     how many landed, against the nominal count. A run that
                asked for 3600 and got 900 is a run whose interval the
                instrument could not meet.
    Interval    the *achieved* mean, not the requested one. The
                requested value is in the setup panel and in the file;
                repeating it here would tell you nothing you did not
                already type.
    Ended       duration, operator, or a read error. A run that ended
                early looks identical to a complete one in a plot.
"""
from tkinter import ttk

COLUMNS = ("dataset", "mode", "level", "samples", "interval", "ended")
HEADINGS = ["Dataset", "Mode", "Level", "Samples", "Interval (s)", "Ended"]
WIDTHS = [130, 65, 80, 90, 90, 80]


def build_results_panel(exp, parent):
    """Build the results Treeview and its buttons. Sets exp.tree."""
    frame = ttk.LabelFrame(exp.col_right, text="Results", padding=6)
    frame.pack(fill="both", expand=True)

    exp.tree = ttk.Treeview(frame, columns=COLUMNS, show="tree headings",
                            height=5)
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
    ttk.Button(buttons, text="Save snapshot → CSV",
               command=exp.save_runs).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Delete ticked",
               command=exp.delete_ticked).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Clear all",
               command=exp.clear_output).pack(side="left")

    return frame
