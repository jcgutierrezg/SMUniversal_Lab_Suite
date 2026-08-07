"""
Measurement setup: source level, ranges, compliance, points, thickness,
sample naming, save path, settle delay.

Laid out as a single column of label-and-field rows rather than a grid of
side-by-side pairs. Two reasons: it reads top to bottom in the order you
fill it in, and it keeps the middle column narrow. The middle column is
the shortest of the three, so spending height here costs nothing while
saving width the results table can use.

The source-level and voltage-range dropdowns start with placeholder
values and are repopulated from the connected instrument's declared
limits in VanDerPauwExperiment.on_connected(). That's why the lists here
are short - they exist only so the widgets have something to show before
anything is plugged in.

Unlike Hall, the level dropdown is read-only: Van der Pauw wants one of
the instrument's standard ranges, not a value between them.
"""
import tkinter as tk
from tkinter import ttk

from core.gui.widgets import nplc_row, high_z_row


def _label(frame, row, text):
    """Right-aligned field label in column 0."""
    ttk.Label(frame, text=text).grid(row=row, column=0, sticky="e",
                                     padx=(0, 6), pady=2)


def build_setup_panel(exp, parent):
    """Build the setup form. Sets exp.level_var/level_combo,
    exp.volt_range_var/volt_range_combo, exp.vlim_var, exp.points_var,
    exp.thickness_entry_var, exp.sample_name_var, exp.delay_ms_var."""
    frame = ttk.LabelFrame(exp.col_mid, text="Measurement setup", padding=8)
    frame.pack(fill="x")

    ttk.Label(frame, text="Mode:").grid(row=0, column=0, sticky="e", padx=(0, 6))
    ttk.Label(frame, text="Source current, 4-wire").grid(
        row=0, column=1, columnspan=2, sticky="w")

    # --- source level: editable, with the instrument's ranges as hints ---
    _label(frame, 1, "Source current:")
    exp.level_var = tk.StringVar(value="100 µA")
    exp.level_combo = ttk.Combobox(frame, textvariable=exp.level_var,
                                   state="readonly", width=11,
                                   values=["100 µA"])
    exp.level_combo.grid(row=1, column=1, sticky="w", pady=2)

    # --- voltage range (repopulated on connect) ---
    _label(frame, 2, "Voltage range:")
    exp.volt_range_var = tk.StringVar(value="AUTO")
    exp.volt_range_combo = ttk.Combobox(frame, textvariable=exp.volt_range_var,
                                        state="readonly", width=11,
                                        values=["AUTO"])
    exp.volt_range_combo.grid(row=2, column=1, sticky="w", pady=2)


    # --- compliance and sampling ---
    _label(frame, 3, "VLIM (V):")
    exp.vlim_var = tk.StringVar(value="0.3")
    ttk.Entry(frame, textvariable=exp.vlim_var, width=13).grid(
        row=3, column=1, sticky="w", pady=2)

    _label(frame, 4, "Points:")
    exp.points_var = tk.StringVar(value="20")
    ttk.Entry(frame, textvariable=exp.points_var, width=13).grid(
        row=4, column=1, sticky="w", pady=2)

    _label(frame, 5, "Delay (ms):")
    exp.delay_ms_var = tk.StringVar(value="2000")
    ttk.Entry(frame, textvariable=exp.delay_ms_var, width=13).grid(
        row=5, column=1, sticky="w", pady=2)

    # --- integration time (shared control, see core/gui/widgets.py) ---
    exp.nplc_var, exp.nplc_combo = nplc_row(frame, 6)
    exp.high_z_var, exp.high_z_check = high_z_row(frame, 7)

    # --- sample ---
    _label(frame, 8, "Thickness (µm):")
    exp.thickness_entry_var = tk.StringVar(value="1")
    ttk.Entry(frame, textvariable=exp.thickness_entry_var, width=13).grid(
        row=8, column=1, sticky="w", pady=2)
    ttk.Button(frame, text="Set", width=5, command=exp.set_thickness).grid(
        row=8, column=2, sticky="w", padx=(4, 0), pady=2)

    _label(frame, 9, "Sample name:")
    exp.sample_name_var = tk.StringVar(value="sample")
    ttk.Entry(frame, textvariable=exp.sample_name_var, width=13).grid(
        row=9, column=1, sticky="w", pady=2)

    _label(frame, 10, "Next #:")
    exp.app.measnum_var = tk.IntVar(value=exp.app.next_meas_number)
    ttk.Entry(frame, textvariable=exp.app.measnum_var, width=6,
              state="readonly").grid(row=10, column=1, sticky="w", pady=2)

    # --- save path ---
    ttk.Separator(frame, orient="horizontal").grid(
        row=11, column=0, columnspan=3, sticky="ew", pady=(8, 6))
    ttk.Button(frame, text="Save path...", command=exp.app.select_path).grid(
        row=12, column=0, sticky="e", padx=(0, 6))
    exp.app.path_display_var = tk.StringVar(value=exp.app.storage_path)
    ttk.Entry(frame, textvariable=exp.app.path_display_var, width=22,
              state="readonly").grid(row=12, column=1, columnspan=2, sticky="w")
