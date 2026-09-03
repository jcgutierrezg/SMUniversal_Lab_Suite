"""
Sweep mode and compliance - what the SMU sources, and what protects the
sample.

This replaces two controls from the original: the "V Bias"/"I Bias"
toggle button and the "OK" lock beside it. In the original, pressing OK
built the compliance dropdown for the chosen mode and then disabled the
toggle permanently - the window carried a label reading "Close the
program to change bias mode".

That lock is dropped here. It existed because the compliance dropdown
was *constructed* by the lock handler, so changing mode afterwards would
have left a dropdown listing amps while the instrument sourced amps. The
dropdown is built once now and simply repopulated when the mode changes,
so there is nothing to protect against. Mode changes are refused while a
measurement is running, which is the real constraint.

Compliance is the current limit when sourcing voltage, and the voltage
limit when sourcing current - always the quantity you are *not*
controlling. Getting it backwards is how samples get cooked, so the
label text changes with the mode rather than staying generic.
"""
import tkinter as tk
from tkinter import ttk

from core.gui.widgets import high_z_row, nplc_row

# Fallback lists, shown before an instrument is connected. Replaced from
# the connected driver's declared limits in on_connected().
FALLBACK_CURRENT_COMPLIANCE = ["1e-7", "1e-6", "1e-5", "1e-4", "1e-3",
                               "1e-2", "1e-1", "1"]
FALLBACK_VOLTAGE_COMPLIANCE = ["0.2", "2", "20", "200"]


def build_mode_panel(exp, parent):
    """Source-function radio buttons and the compliance dropdown.

    Sets exp.mode_var, exp.compliance_var, exp.compliance_combo,
    exp.compliance_label.
    """
    frame = ttk.LabelFrame(exp.col_left, text="Sweep mode", padding=8)
    frame.pack(fill="x", pady=(0, 6))

    exp.mode_var = tk.StringVar(value="voltage")
    ttk.Radiobutton(frame, text="Source voltage, measure current",
                    value="voltage", variable=exp.mode_var,
                    command=exp.on_mode_changed).grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Radiobutton(frame, text="Source current, measure voltage",
                    value="current", variable=exp.mode_var,
                    command=exp.on_mode_changed).grid(
        row=1, column=0, columnspan=2, sticky="w")

    ttk.Separator(frame, orient="horizontal").grid(
        row=2, column=0, columnspan=2, sticky="ew", pady=(8, 6))

    exp.compliance_label = ttk.Label(frame, text="Current compliance (A):")
    exp.compliance_label.grid(row=3, column=0, sticky="e", padx=(0, 6))

    exp.compliance_var = tk.StringVar(value="1e-3")
    exp.compliance_combo = ttk.Combobox(
        frame, textvariable=exp.compliance_var, width=10,
        values=FALLBACK_CURRENT_COMPLIANCE)
    exp.compliance_combo.grid(row=3, column=1, sticky="w")

    # Editable rather than readonly: the original offered decade steps
    # only, but compliance is a safety setting and an operator may well
    # want 5 mA rather than 1 mA or 10 mA. The dropdown stays as a set
    # of sensible starting points.

    ttk.Label(frame, text="Measurement range follows compliance.",
              foreground="gray").grid(row=4, column=0, columnspan=2,
                                      sticky="w", pady=(6, 0))

    # --- integration time ---
    # Shared control, defined once in core/gui/widgets.py and used here,
    # in Van der Pauw and in Hall. See that module for what NPLC is and
    # why 1 is the default rather than merely a middling value.
    exp.nplc_var, exp.nplc_combo = nplc_row(frame, 5)

    # --- overvoltage protection -------------------------------------
    # A hard ceiling on the source, separate from compliance. The case
    # it earns its place for: in 4-wire sensing a sense lead falling off
    # reads as 0 V at the sample, so the instrument decides it is
    # undershooting and winds the output up to compensate. OVP stops
    # that at a chosen level instead of at the instrument's maximum.
    #
    # `IV_Meas_20H10.py` pinned this at MIN with a higher setting
    # commented out beside it, so MIN stays the default here and doing
    # nothing reproduces the original. Populated from the connected
    # driver's OVP_CHOICES; disabled for instruments that have no such
    # control, which is currently every model but the GSM-20H10.
    exp.ovp_label = ttk.Label(frame, text="Overvoltage protect:")
    exp.ovp_label.grid(row=6, column=0, sticky="e", padx=(0, 6), pady=(4, 0))
    exp.ovp_var = tk.StringVar(value="n/a")
    exp.ovp_combo = ttk.Combobox(
        frame, textvariable=exp.ovp_var, width=10, state="disabled",
        values=["n/a"])
    exp.ovp_combo.grid(row=6, column=1, sticky="w", pady=(4, 0))

    ttk.Separator(frame, orient="horizontal").grid(
        row=7, column=0, columnspan=2, sticky="ew", pady=(8, 6))

    # --- sensing ---------------------------------------------------
    # The originals were inconsistent here.               # DEVIATION 6
    #
    # Long bias sent `smu.sense = smu.SENSE_REMOTE` (4-wire) inside
    # periodic_run() and nowhere else. The single-run path never set
    # sensing at all, so a single sweep used whatever the instrument
    # happened to be left in - 4-wire if a periodic run had just
    # finished, 2-wire after a reset. The same sample could read
    # differently depending on what was run before it, with nothing on
    # screen to say so.
    #
    # Now set explicitly on every sweep, and defaulted to 4-wire
    # because that is how the rigs are physically wired. Unticking it
    # is left available deliberately - probe-station work and quick
    # continuity checks sometimes want 2-wire - and the choice is
    # recorded in the saved data either way.
    #
    # The widget is kept on the experiment, not discarded, because some
    # instruments have no remote-sense command at all - on the U2722A
    # the SENSE terminals are strapped and software gets no say - and
    # on_connected() has to grey this out and pin it to the wiring.
    exp.remote_sense_var = tk.BooleanVar(value=True)
    exp.remote_sense_check = ttk.Checkbutton(
        frame, text="4-wire (remote sense)",
        variable=exp.remote_sense_var)
    exp.remote_sense_check.grid(row=8, column=0, columnspan=2, sticky="w")

    # Sits with the other per-run instrument settings rather than in
    # the mode block: it changes what the hardware does between sweeps,
    # not what is measured.
    exp.high_z_var, exp.high_z_check = high_z_row(frame, 9)

    # --- fit -------------------------------------------------------
    # Off for diodes and anything else non-ohmic.        # DEVIATION 7
    # A straight-line fit
    # through a rectifying curve returns a number, and that number is
    # meaningless - worse than absent, because it looks like a result
    # and lands in the CSV as one. Long bias had the fit commented out
    # rather than switched off, which is the same judgement made
    # permanent; this makes it per-sample and visible.
    #
    # The raw points are stored identically either way. Only the fitted
    # columns change, so a sweep taken with the fit off can still be
    # re-examined later.
    exp.do_fit_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(frame, text="Linear fit (ohmic samples only)",
                    variable=exp.do_fit_var).grid(
        row=10, column=0, columnspan=2, sticky="w")
    return frame
