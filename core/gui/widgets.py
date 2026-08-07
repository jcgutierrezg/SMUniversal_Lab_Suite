"""
Small shared widgets.

The original scripts each carried their own copy of a `LabeledEntry`
class - six copies with slow drift between them, which is how one script
ended up with a label-width parameter the others didn't have. The ported
panels don't need a custom class: a right-aligned label plus a widget in
the next grid column does the same job in two lines. What they *were*
duplicating is that pair, so that is what lives here.

Van der Pauw and Hall each still define a private `_label()` doing this;
they were written before this module existed and are left alone rather
than churned. New panels should use these.
"""
import tkinter as tk
from tkinter import ttk


def field_label(frame, row, text, column=0):
    """Right-aligned field label. Returns the label."""
    label = ttk.Label(frame, text=text)
    label.grid(row=row, column=column, sticky="e", padx=(0, 6), pady=2)
    return label


def entry_row(frame, row, text, initial="", width=13, column=0):
    """A labelled Entry on one grid row.

    Returns the StringVar holding its value - the caller almost always
    wants the variable rather than the widget, and returning it directly
    keeps panel code to one line per field.
    """
    field_label(frame, row, text, column=column)
    var = tk.StringVar(value=str(initial))
    ttk.Entry(frame, textvariable=var, width=width).grid(
        row=row, column=column + 1, sticky="w", pady=2)
    return var


def combo_row(frame, row, text, values, initial=None, width=11,
              column=0, readonly=True):
    """A labelled Combobox on one grid row.

    Returns (variable, widget). The widget comes back too because range
    dropdowns get repopulated from the connected instrument's declared
    limits in on_connected().
    """
    field_label(frame, row, text, column=column)
    var = tk.StringVar(value=initial if initial is not None
                       else (values[0] if values else ""))
    combo = ttk.Combobox(frame, textvariable=var, width=width,
                         state="readonly" if readonly else "normal",
                         values=list(values))
    combo.grid(row=row, column=column + 1, sticky="w", pady=2)
    return var, combo


def readout_row(frame, row, text, initial="-", column=0, bold=False):
    """A labelled read-only value that gets updated later.

    Returns the StringVar to write results into.
    """
    field_label(frame, row, text, column=column)
    var = tk.StringVar(value=initial)
    style = {"font": ("TkDefaultFont", 9, "bold")} if bold else {}
    ttk.Label(frame, textvariable=var, **style).grid(
        row=row, column=column + 1, sticky="w")
    return var


# ---------------------------------------------------------------
# Integration time (NPLC)
# ---------------------------------------------------------------
#
# Three experiments want this control and they want it to behave
# identically, so it lives here rather than in three panels. That is the
# same reasoning that moved the corner diagram and the temperature panel
# into this package - and the lesson from the six drifting copies of
# LabeledEntry described at the top of this file.
#
# NPLC is how many mains cycles the ADC integrates over per reading. At
# 1 NPLC the mains hum on the leads completes a whole number of cycles
# inside the measurement window and averages to zero, which is why 1 is
# the sensible default rather than merely a middling one. 10 is quieter
# and slower; 0.01 is fast and noisy.
#
# Shutter speed on a camera: longer exposure, less grain, but nothing
# that moves stays sharp.

NPLC_PRESETS = (0.01, 0.1, 1, 10, 25)


def nplc_row(frame, row, text="Integration (NPLC):", initial="1",
             column=0, width=11):
    """A labelled, editable NPLC dropdown.

    Editable rather than read-only: the presets cover the useful cases
    but instruments accept anything in their range, and a sweep that
    wants 2.5 shouldn't need a code change.

    Returns (variable, widget). Pass the widget to refresh_nplc() from
    on_connected() so it can be populated or greyed out.
    """
    field_label(frame, row, text, column=column)
    var = tk.StringVar(value=str(initial))
    combo = ttk.Combobox(frame, textvariable=var, width=width,
                         values=[f"{v:g}" for v in NPLC_PRESETS])
    combo.grid(row=row, column=column + 1, sticky="w", pady=2)
    return var, combo


def refresh_nplc(combo, var, driver, log=None):
    """Populate or grey out an NPLC control for the connected driver.

    Greying out rather than hiding: a control that vanishes leaves the
    operator wondering whether they imagined it, whereas a disabled one
    reading "n/a" says plainly that this instrument has no such setting.

    The offered presets are filtered to the driver's declared range, so
    a 2611A shows 25 and the SCPI instruments don't offer a value they
    would silently clamp.
    """
    if driver is None or not driver.supports_nplc():
        combo.config(state="disabled")
        var.set("n/a")
        return

    low, high = driver.NPLC_RANGE
    combo.config(state="normal")
    combo["values"] = [f"{v:g}" for v in NPLC_PRESETS if low <= v <= high]
    if var.get().lower() in ("", "n/a"):
        var.set("1")
    if log:
        log(f"NPLC range {low:g} to {high:g}")


def parse_nplc(var):
    """Read an NPLC field, returning a float or None.

    None means "leave the instrument alone" - either the control is
    greyed out, or it is empty. That is deliberately different from
    sending a default, which would overwrite whatever the operator set
    on the front panel.
    """
    text = (var.get() or "").strip()
    if not text or text.lower() == "n/a":
        return None
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"Integration time (NPLC) must be a number, "
                         f"not {text!r}.")
    if value <= 0:
        raise ValueError("Integration time (NPLC) must be positive.")
    return value


def apply_nplc(smu, nplc, log=None):
    """Send an NPLC to an instrument, clamping and reporting.

    Returns the value actually applied, or None if nothing was sent.
    Clamping rather than raising: an out-of-range NPLC is a speed
    preference, not a safety matter, and losing a run over one would be
    disproportionate.
    """
    if nplc is None or not smu.supports_nplc():
        return None
    applied = smu.clamp_nplc(nplc)
    smu.set_nplc(applied)
    if log and abs(applied - nplc) > 1e-9:
        log(f"NPLC {nplc:g} is outside this instrument's range; "
            f"using {applied:g}")
    return applied


# ---------------------------------------------------------------
# Output-off mode (high impedance)
# ---------------------------------------------------------------
#
# What "output off" physically means. Normal off leaves the instrument
# connected and sourcing 0 V into the sample - a low-impedance path.
# High-Z opens the output relay instead, disconnecting it entirely.
#
# Light switch versus pulling the plug out of the wall. The switch is
# fine most of the time and wears nothing out; pulling the plug is what
# you want when the thing must genuinely be isolated, and it wears the
# socket.
#
# Defaults OFF. High-Z matters for particular measurements, but the
# relay has a finite number of operations in it and a periodic IV run
# can cycle the output hundreds of times unattended - so the setting
# that costs hardware is the one you opt into, not the one you inherit.


def high_z_row(frame, row, text="High-Z output off", column=0, columnspan=2):
    """A checkbox for the output-off mode.

    Returns (variable, widget). The widget comes back so on_connected()
    can disable it for instruments that have no such control.
    """
    var = tk.BooleanVar(value=False)
    check = ttk.Checkbutton(frame, text=text, variable=var)
    check.grid(row=row, column=column, columnspan=columnspan, sticky="w",
               pady=2)
    return var, check


def refresh_high_z(check, var, driver, log=None):
    """Enable or grey out the high-Z checkbox for the connected driver."""
    if driver is None or not driver.supports_high_z_off():
        check.config(state="disabled")
        var.set(False)
        return
    check.config(state="normal")


def apply_high_z(smu, high_z, log=None):
    """Send the output-off mode, returning what was applied or None.

    Sent every run rather than once at connect, for the same reason as
    remote sense and NPLC: otherwise the instrument keeps whatever the
    last experiment left it in.
    """
    if not smu.supports_high_z_off():
        return None
    smu.set_output_off_mode(bool(high_z))
    if log and high_z:
        log("Output-off mode: high impedance (output relay opens)")
    return bool(high_z)


# ---------------------------------------------------------------
# Sensing (2-wire / 4-wire)
# ---------------------------------------------------------------
#
# Most SMUs switch between local and remote sensing over the bus, so
# the experiment offers a checkbox and sets it on every run. The
# Keysight U2722A does not: it has no remote-sense command at all, and
# whether it is 2-wire or 4-wire is decided by how the SENSE terminals
# are strapped.
#
# That is an unusual shape for a capability - not "this instrument
# lacks a feature" but "this instrument has the feature and software
# cannot see or change it". So the control is greyed out *and forced to
# the wiring's actual state*, rather than greyed out at some default.
# The alternative - leaving the checkbox live and letting it do nothing -
# would write a sensing mode into the CSV that the measurement did not
# use, which is worse than having no control, because a wrong number
# reads exactly like a right one.


def refresh_remote_sense(check, var, driver, log=None):
    """Enable, or grey out and pin, the sensing checkbox.

    On an instrument that cannot switch, the box is forced to match the
    wiring and disabled, and the console says what the wiring is - so
    the operator knows the measurement is 4-wire rather than assuming
    the greyed-out tick is a leftover default.
    """
    if driver is None or driver.supports_remote_sense_control():
        check.config(state="normal")
        return

    fixed = driver.fixed_sense() or ""
    var.set("2-wire" not in fixed.lower())
    check.config(state="disabled")
    if log:
        log(f"Sensing is set by wiring on {driver.DISPLAY_NAME}: "
            f"{fixed or 'unknown'}. The control is disabled.")


def apply_remote_sense(smu, on, log=None):
    """Set sensing for this run and return what to record in the CSV.

    Returns the description that belongs in the data: "4-wire",
    "2-wire", or the instrument's fixed wiring where software has no
    say. Returning the string rather than a bool is the point - the
    file should describe the measurement, not the checkbox.
    """
    if not smu.supports_remote_sense_control():
        return smu.fixed_sense() or "fixed (unknown)"
    smu.set_remote_sense(bool(on))
    return "4-wire" if on else "2-wire"
