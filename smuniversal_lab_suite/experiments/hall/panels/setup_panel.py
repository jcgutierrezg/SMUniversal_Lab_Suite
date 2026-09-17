"""
Measurement setup: source level, ranges, compliance, points, thickness,
sample naming, save path, settle delay.

Laid out as a single column of label-and-field rows rather than a grid of
side-by-side pairs. Two reasons: it reads top to bottom in the order you
fill it in, and it keeps the middle column narrow. The middle column is
the shortest of the three, so spending height here costs nothing while
saving width the results table can use.

The source current is a plain entry box, as on Van der Pauw, typed the
way an IV sweep's start and stop are: '47u', '47 µA', '4.7e-5'. Hall
often wants a level between the instrument's range steps. A box that
cannot be read is refused rather than replaced with a default, and the
limit gate in run_pressed() refuses a level the instrument cannot reach.
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
        "What one run does: source the current below through one "
        "diagonal, measure the voltage across the other, at both "
        "current polarities. One run is one (position, field polarity) "
        "pair; four of them - both positions at both field signs - make "
        "the eight voltages the calculation needs.")

    ttk.Label(frame, text="Mode:").grid(row=0, column=0, sticky="e", padx=(0, 6))
    ttk.Label(frame, text="Source current, 4-wire").grid(
        row=0, column=1, columnspan=2, sticky="w")

    # --- source level: typed, like a sweep's start and stop ---
    _label(frame, 1, "Source current:")
    exp.level_var = tk.StringVar(value="100 µA")
    exp.level_entry = ttk.Entry(frame, textvariable=exp.level_var, width=13)
    exp.level_entry.grid(row=1, column=1, sticky="w", pady=2)
    tip(exp, exp.level_entry,
        "The current through the sample, typed with a unit: 47u, 47 uA "
        "or 4.7e-5. It appears in the carrier density directly, so the "
        "value used by the calculation is the one in the I box there - "
        "which may differ from this if compliance clamped the source.")
    exp.level_entry.bind("<Return>", lambda _e: exp.on_set_level())
    ttk.Button(frame, text="Set level", width=9, command=exp.on_set_level).grid(
        row=1, column=2, sticky="w", padx=(4, 0), pady=2)

    # --- voltage range (repopulated on connect) ---
    _label(frame, 2, "Voltage range:")
    exp.volt_range_var = tk.StringVar(value="AUTO")
    exp.volt_range_combo = ttk.Combobox(frame, textvariable=exp.volt_range_var,
                                        state="readonly", width=11,
                                        values=["AUTO"])
    exp.volt_range_combo.grid(row=2, column=1, sticky="w", pady=2)
    exp.volt_range_combo.bind("<<ComboboxSelected>>",
                              lambda _e: exp.on_volt_range_changed())

    # --- compliance and sampling ---
    _label(frame, 3, "VLIM (V):")
    exp.vlim_var = tk.StringVar(value="0.3")
    tip(exp, ttk.Entry(frame, textvariable=exp.vlim_var, width=13),
        "Compliance: the highest voltage the instrument will apply to "
        "push the current you asked for. Clamping here is worse than "
        "elsewhere - the Hall voltage is a small difference between "
        "large readings, and a clamped reading is not the sample's.").grid(
        row=3, column=1, sticky="w", pady=2)

    _label(frame, 4, "Points:")
    exp.points_var = tk.StringVar(value="200")
    tip(exp, ttk.Entry(frame, textvariable=exp.points_var, width=13),
        "Readings per polarity, averaged. The Hall voltage is recovered "
        "by subtracting nearly equal numbers, so averaging is what "
        "makes it measurable at all - this is why the default is much "
        "higher than Van der Pauw's.").grid(
        row=4, column=1, sticky="w", pady=2)

    _label(frame, 5, "Delay (ms):")
    exp.delay_ms_var = tk.StringVar(value="2000")
    ttk.Entry(frame, textvariable=exp.delay_ms_var, width=13).grid(
        row=5, column=1, sticky="w", pady=2)

    # --- integration time (shared control, see core/gui/widgets.py) ---
    exp.nplc_var, exp.nplc_combo = nplc_row(frame, 6)
    tip(exp, exp.nplc_combo,
        "Integration time, in mains cycles. Longer rejects mains hum "
        "and costs time; it is recorded with the data because two runs "
        "at different NPLC have visibly different scatter.")
    exp.high_z_var, exp.high_z_check = high_z_row(frame, 7)
    tip(exp, exp.high_z_check,
        "What the instrument does to the sample between runs: open the "
        "relay (high-Z) or hold it at zero volts.")

    # Sample name, thickness, the measurement counter and the save path
    # used to be four more rows here. They live on the session
    # strip above the tabs: they describe the session, not this
    # measurement, and a second copy of a thickness is a second thing to
    # be wrong.
