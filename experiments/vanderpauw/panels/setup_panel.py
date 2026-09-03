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

from core.gui.widgets import high_z_row, nplc_row


def _label(frame, row, text):
    """Right-aligned field label in column 0."""
    ttk.Label(frame, text=text).grid(row=row, column=0, sticky="e",
                                     padx=(0, 6), pady=2)


def build_setup_panel(exp, parent):
    """Build the setup form. Sets exp.level_var/level_combo,
    exp.volt_range_var/volt_range_combo, exp.vlim_var, exp.points_var,
    exp.delay_ms_var. Sample name and thickness live on the app-level
    session strip - see core/gui/session_strip.py."""
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

    # Sample name, thickness, the measurement counter and the save path
    # used to be four more rows here. Wave 5b moved them to the session
    # strip above the tabs: they describe the session, not this
    # measurement, and a second copy of a thickness is a second thing to
    # be wrong.
