"""
Measurement setup: the current sweep, ranges, compliance, points and the
settle at each point.

Laid out as a single column of label-and-field rows rather than a grid of
side-by-side pairs. Two reasons: it reads top to bottom in the order you
fill it in, and it keeps the middle column narrow. The middle column is
the shortest of the three, so spending height here costs nothing while
saving width the results table can use.

The voltage-range dropdown starts with a placeholder list and is
repopulated from the connected instrument's declared limits in
VanDerPauwExperiment.on_connected().

A run is a current sweep from Start to Stop, typed the way an IV
sweep's are: '-1u', '-1 µA', '-1e-6'. It crosses zero, and its two halves
are the two polarities the calculation needs. What the boxes accept is
checked at Run, against the connected instrument's limits.
"""
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui.tooltips import tip
from smuniversal_lab_suite.core.gui.widgets import high_z_row, nplc_row

START_HELP = (
    "Where the current sweep begins, typed with a unit: -1u, -1 uA or "
    "-1e-6. The sweep has to cross zero, so one of Start and Stop is "
    "negative. Big enough to lift the voltage clear of the noise, small "
    "enough not to heat the film.")
STOP_HELP = (
    "Where the current sweep ends, with a unit. Opposite in sign to "
    "Start: the readings at negative and at positive current are "
    "the two polarities, and averaging them cancels the contacts' "
    "thermoelectric offsets.")


def _label(frame, row, text):
    """Right-aligned field label in column 0."""
    ttk.Label(frame, text=text).grid(row=row, column=0, sticky="e",
                                     padx=(0, 6), pady=2)


def build_setup_panel(exp, parent):
    """Build the setup form. Sets exp.start_var/start_entry, exp.stop_var,
    exp.volt_range_var/volt_range_combo, exp.vlim_var, exp.points_var,
    exp.delay_ms_var. Sample name and thickness live on the app-level
    session strip - see core/gui/session_strip.py."""
    frame = ttk.LabelFrame(exp.col_mid, text="Measurement setup", padding=8)
    frame.pack(fill="x")
    tip(exp, frame,
        "What one run does: sweep the current from Start to Stop "
        "through the two contacts the selected position makes the "
        "current pair, reading the voltage across the other two at each "
        "point. The sweep crosses zero, and its negative and positive "
        "halves are averaged into one resistance for that position.")

    ttk.Label(frame, text="Mode:").grid(row=0, column=0, sticky="e", padx=(0, 6))
    ttk.Label(frame, text="Source current, 4-wire").grid(
        row=0, column=1, columnspan=2, sticky="w")

    # --- the sweep: typed, like an IV sweep's start and stop ---
    # One row, start "to" stop: the window's height is the budget
    # `tests/test_layout.py` holds it to, and a second row for Stop put
    # the combined window over it.
    _label(frame, 1, "Sweep:")
    sweep = ttk.Frame(frame)
    sweep.grid(row=1, column=1, columnspan=2, sticky="w", pady=2)
    exp.start_var = tk.StringVar(value=exp.DEFAULT_START)
    exp.start_entry = ttk.Entry(sweep, textvariable=exp.start_var, width=8)
    tip(exp, exp.start_entry, START_HELP, name="Start current")
    exp.start_entry.pack(side="left")
    ttk.Label(sweep, text="to").pack(side="left", padx=4)
    exp.stop_var = tk.StringVar(value=exp.DEFAULT_STOP)
    tip(exp, ttk.Entry(sweep, textvariable=exp.stop_var, width=8),
        STOP_HELP, name="Stop current").pack(side="left")

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
    exp.points_var = tk.StringVar(value=exp.DEFAULT_POINTS)
    tip(exp, ttk.Entry(frame, textvariable=exp.points_var, width=13),
        "How many currents the sweep steps through, from Start to Stop. "
        "Each half of the sweep is averaged, so more points beat down "
        "noise and lengthen the run in proportion.").grid(
        row=4, column=1, sticky="w", pady=2)

    _label(frame, 5, "Delay (ms):")
    exp.delay_ms_var = tk.StringVar(value=exp.DEFAULT_DELAY_MS)
    tip(exp, ttk.Entry(frame, textvariable=exp.delay_ms_var, width=13),
        "How long to wait at each current before reading it, in "
        "milliseconds - time for the sample, the leads and any "
        "thermoelectric offset to settle.").grid(
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
