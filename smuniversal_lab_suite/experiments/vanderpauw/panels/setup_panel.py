"""
Measurement setup: source level, ranges, compliance, points, thickness,
sample naming, save path, settle delay.

Laid out as a single column of label-and-field rows rather than a grid of
side-by-side pairs. Two reasons: it reads top to bottom in the order you
fill it in, and it keeps the middle column narrow. The middle column is
the shortest of the three, so spending height here costs nothing while
saving width the results table can use.

The voltage-range dropdown starts with a placeholder list and is
repopulated from the connected instrument's declared limits in
VanDerPauwExperiment.on_connected().

The source current is a plain entry box, typed the way an IV sweep's
start and stop are: '100u', '100 µA', '1e-4'. It used to be a locked
dropdown of the instrument's ranges, which ruled out any level between
two range steps. What the box accepts is checked at Run, against the
connected instrument's limits.
"""
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui.tooltips import tip
from smuniversal_lab_suite.core.gui.widgets import high_z_row, nplc_row


def _label(frame, row, text):
    """Right-aligned field label in column 0."""
    ttk.Label(frame, text=text).grid(row=row, column=0, sticky="e",
                                     padx=(0, 6), pady=2)


def build_setup_panel(exp, parent):
    """Build the setup form. Sets exp.level_var/level_entry,
    exp.volt_range_var/volt_range_combo, exp.vlim_var, exp.points_var,
    exp.delay_ms_var. Sample name and thickness live on the app-level
    session strip - see core/gui/session_strip.py."""
    frame = ttk.LabelFrame(exp.col_mid, text="Measurement setup", padding=8)
    frame.pack(fill="x")
    tip(exp, frame,
        "What one run does: source the current below through the two "
        "contacts the selected position makes the current pair, measure "
        "the voltage across the other two, then repeat with the current "
        "reversed. The two blocks are averaged into one resistance for "
        "that position.")

    ttk.Label(frame, text="Mode:").grid(row=0, column=0, sticky="e", padx=(0, 6))
    ttk.Label(frame, text="Source current, 4-wire").grid(
        row=0, column=1, columnspan=2, sticky="w")

    # --- source level: typed, like a sweep's start and stop ---
    _label(frame, 1, "Source current:")
    exp.level_var = tk.StringVar(value="100 µA")
    exp.level_entry = ttk.Entry(frame, textvariable=exp.level_var, width=13)
    exp.level_entry.grid(row=1, column=1, sticky="w", pady=2)
    tip(exp, exp.level_entry,
        "The current driven through the sample, typed with a unit: "
        "100u, 100 uA or 1e-4. Both polarities of it are measured. Big "
        "enough to lift the voltage clear of the noise, small enough "
        "not to heat the film - a bad guess shows up as a resistance "
        "that drifts with the level.")

    # --- voltage range (repopulated on connect) ---
    _label(frame, 2, "Voltage range:")
    exp.volt_range_var = tk.StringVar(value="AUTO")
    exp.volt_range_combo = ttk.Combobox(frame, textvariable=exp.volt_range_var,
                                        state="readonly", width=11,
                                        values=["AUTO"])
    exp.volt_range_combo.grid(row=2, column=1, sticky="w", pady=2)
    tip(exp, exp.volt_range_combo,
        "The range the voltage is measured on, from what the connected "
        "instrument declares. AUTO lets it choose. A range far larger "
        "than the reading costs resolution; one too small clips it.")


    # --- compliance and sampling ---
    _label(frame, 3, "VLIM (V):")
    exp.vlim_var = tk.StringVar(value="0.3")
    tip(exp, ttk.Entry(frame, textvariable=exp.vlim_var, width=13),
        "Compliance: the highest voltage the instrument will put across "
        "the sample to push the current you asked for. Reach it and it "
        "stops being a current source - the run is flagged and you are "
        "told when it ends.").grid(row=3, column=1, sticky="w", pady=2)

    _label(frame, 4, "Points:")
    exp.points_var = tk.StringVar(value="20")
    tip(exp, ttk.Entry(frame, textvariable=exp.points_var, width=13),
        "Readings per polarity. They are averaged, so more of them "
        "beats down noise and lengthens the run in proportion.").grid(
        row=4, column=1, sticky="w", pady=2)

    _label(frame, 5, "Delay (ms):")
    exp.delay_ms_var = tk.StringVar(value="2000")
    tip(exp, ttk.Entry(frame, textvariable=exp.delay_ms_var, width=13),
        "How long to wait after each polarity change before reading. "
        "This is what lets the thermoelectric offsets settle; too short "
        "and the two polarities do not cancel.").grid(
        row=5, column=1, sticky="w", pady=2)

    # --- integration time (shared control, see core/gui/widgets.py) ---
    exp.nplc_var, exp.nplc_combo = nplc_row(frame, 6)
    tip(exp, exp.nplc_combo,
        "Integration time, in mains cycles. 1 NPLC averages over a "
        "whole cycle and rejects mains hum; 0.01 is twenty times "
        "faster and visibly noisier. Two runs at different NPLC are "
        "not comparable, so it is recorded with the data.")
    exp.high_z_var, exp.high_z_check = high_z_row(frame, 7)
    tip(exp, exp.high_z_check,
        "What the instrument does to the sample between runs: open the "
        "relay (high-Z) or hold it at zero volts. High-Z leaves nothing "
        "driving the film.")

    # Sample name, thickness, the measurement counter and the save path
    # used to be four more rows here. They live on the session
    # strip above the tabs: they describe the session, not this
    # measurement, and a second copy of a thickness is a second thing to
    # be wrong.
