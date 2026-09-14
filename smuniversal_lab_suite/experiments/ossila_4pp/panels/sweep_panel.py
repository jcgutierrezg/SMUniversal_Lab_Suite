"""
What to source: the current list, or a triangular sweep.

The original had both and used neither cleanly. The GUI showed eight
current entry boxes, while the buffer-reading code sliced out "the
middle sweep" - which only makes sense for the triangular shape built by
`generate_triangular_sweep_string()`, a function that was written and
never called. Both are offered here, switched explicitly, so the slicing
matches what was actually sourced.

*Current list* is the spot check: pick a handful of currents, measure
the voltage at each, fit a line.

*Triangular* runs 0 -> -I -> +I -> 0 and keeps only the middle leg. The
outer legs bring the sample to the start and back to zero; going out and
returning shows whether a hysteretic sample comes back to where it
began.
"""
import tkinter as tk
from tkinter import ttk

# The eight defaults from the original. Kept because they are a sensible
# starting decade for a thin film and because anyone who used the old
# script will recognise them.
DEFAULT_CURRENTS = ["10nA", "20nA", "30nA", "40nA",
                    "50nA", "60nA", "70nA", "80nA"]

MAX_CURRENTS = 30          # the original's stated ceiling


def build_sweep_panel(exp, parent):
    """Build the sweep controls into exp.col_mid."""
    frame = ttk.LabelFrame(exp.col_mid, text="Sweep setup", padding=6)
    frame.pack(fill="x")

    # --- mode ---
    exp.sweep_mode_var = tk.StringVar(value="list")
    ttk.Radiobutton(frame, text="Current list", value="list",
                    variable=exp.sweep_mode_var,
                    command=exp.on_sweep_mode_changed).grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Radiobutton(frame, text="Triangular sweep", value="triangular",
                    variable=exp.sweep_mode_var,
                    command=exp.on_sweep_mode_changed).grid(
        row=1, column=0, columnspan=2, sticky="w")

    ttk.Separator(frame, orient="horizontal").grid(
        row=2, column=0, columnspan=2, sticky="ew", pady=(6, 6))

    # --- the two mode-specific blocks, stacked in the same cell ---
    # Only one is ever mapped; on_sweep_mode_changed swaps them. Building
    # both up front keeps their values when switching back and forth,
    # which matters if someone flips modes to compare.
    holder = ttk.Frame(frame)
    holder.grid(row=3, column=0, columnspan=2, sticky="ew")

    exp.list_frame = _build_list_frame(exp, holder)
    exp.triangular_frame = _build_triangular_frame(exp, holder)

    ttk.Separator(frame, orient="horizontal").grid(
        row=4, column=0, columnspan=2, sticky="ew", pady=(6, 6))

    # --- shared settings ---
    shared = ttk.Frame(frame)
    shared.grid(row=5, column=0, columnspan=2, sticky="ew")

    exp.delay_var = tk.StringVar(value="0.1")
    exp.reversals_var = tk.StringVar(value="8")
    exp.compliance_var = tk.StringVar(value="2")
    exp.dataset_var = tk.StringVar(value="run")

    rows = [
        ("Delay (s):", exp.delay_var),
        ("Reversals per point:", exp.reversals_var),
        ("Voltage limit (V):", exp.compliance_var),
        ("Dataset:", exp.dataset_var),
        # The app's variable, not a new one - see
        # core/gui/session_strip.py. 4PP does not take the strip's
        # thickness box: its thickness is part of a geometry that also
        # carries a width and a length, and lives in that panel.
        ("Sample name:", exp.app.sample_name_var),
    ]
    for row, (label, var) in enumerate(rows):
        ttk.Label(shared, text=label, width=20, anchor="e").grid(
            row=row, column=0, sticky="e", padx=(0, 6), pady=2)
        ttk.Entry(shared, textvariable=var, width=12).grid(
            row=row, column=1, sticky="w", pady=2)

    # Reversal averaging is the thing most worth explaining on screen,
    # because switching it off changes the numbers rather than just the
    # speed, and the reason is not obvious from the label.
    ttk.Label(frame,
              text="Reversals alternate ±I and average, cancelling\n"
                   "thermoelectric offsets at the contacts. Set 1 to\n"
                   "disable. Even numbers only.",
              foreground="gray", justify="left").grid(
        row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))

    exp.on_sweep_mode_changed()

    # Binds the *app's* path variable rather than creating one (Wave
    # 5b). The old `exp.app.path_display_var = tk.StringVar(...)` here
    # rebound an app-level attribute from inside a panel, which is
    # harmless in a one-experiment window and a silently stale readout
    # in a window hosting two.
    path_row = ttk.Frame(frame)
    path_row.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    ttk.Button(path_row, text="Save path...",
               command=exp.app.select_path).pack(side="left", padx=(0, 6))
    ttk.Entry(path_row, textvariable=exp.app.path_display_var, width=22,
              state="readonly").pack(side="left", fill="x", expand=True)
    return frame


def _build_list_frame(exp, parent):
    """The eight (or more) explicit current entries."""
    frame = ttk.Frame(parent)

    exp.current_vars = []
    for index, value in enumerate(DEFAULT_CURRENTS):
        var = tk.StringVar(value=value)
        exp.current_vars.append(var)
        row, column = divmod(index, 2)
        cell = ttk.Frame(frame)
        cell.grid(row=row, column=column, sticky="w", padx=(0, 8))
        ttk.Label(cell, text=f"I{index}:", width=4, anchor="e").pack(
            side="left")
        ttk.Entry(cell, textvariable=var, width=9).pack(side="left")

    ttk.Label(frame,
              text="Units: A, mA, uA, nA. Blank entries are skipped.",
              foreground="gray").grid(row=4, column=0, columnspan=2,
                                      sticky="w", pady=(4, 0))
    return frame


def _build_triangular_frame(exp, parent):
    """Start / stop / points for the 0 -> -I -> +I -> 0 shape."""
    frame = ttk.Frame(parent)

    exp.tri_start_var = tk.StringVar(value="-80nA")
    exp.tri_stop_var = tk.StringVar(value="80nA")
    exp.tri_points_var = tk.StringVar(value="21")

    rows = [
        ("Start current:", exp.tri_start_var),
        ("Stop current:", exp.tri_stop_var),
        ("Points (middle leg):", exp.tri_points_var),
    ]
    for row, (label, var) in enumerate(rows):
        ttk.Label(frame, text=label, width=20, anchor="e").grid(
            row=row, column=0, sticky="e", padx=(0, 6), pady=2)
        ttk.Entry(frame, textvariable=var, width=12).grid(
            row=row, column=1, sticky="w", pady=2)

    ttk.Label(frame,
              text="Start must be negative, stop positive.\n"
                   "Only the middle leg is recorded.",
              foreground="gray", justify="left").grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
    return frame
