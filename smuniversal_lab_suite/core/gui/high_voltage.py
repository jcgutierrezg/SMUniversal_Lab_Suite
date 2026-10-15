"""
The warning shown before a run puts a dangerous voltage on the terminals.

An instrument declares the level above which this is asked -
`BaseInstrument.HAZARDOUS_ABOVE_V` - and an experiment asks it through
`Experiment.confirm_terminal_voltage()` after Run, with the highest
voltage the run can reach. Only the Keithley 487 declares one today: it
sources up to 505 V, and in this lab it is used without its interlock
cable, so nothing switches it off if someone touches the terminals or
opens the fixture. The decision, 2026-10-15, was to allow such runs and
to make starting one a deliberate act.

Deliberately not a yes/no box. Those are clicked through, and the
default button of one is a single Enter away. Here the run starts only
after a box is ticked and a button naming the voltage is pressed; Cancel
has the focus, and Escape or closing the window cancels.
"""
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui.theme import theme_for

#: The banner, the same in either look: it is a warning, not a theme.
BANNER_BG = "#b00020"
BANNER_INK = "#ffffff"

#: Said in the dialog, and again on the console for the length of the
#: run once it has been accepted.
STAY_CLEAR = ("While the run is taking place, stay clear of the sample and "
              "the probes. Do not touch or adjust anything until the run "
              "has ended and the output is off.")


class HighVoltageDialog:
    """The dialog, built and live. `result` is True only for Apply."""

    def __init__(self, parent, instrument, volts, threshold):
        self.result = False
        palette = theme_for(parent).palette
        self.window = window = tk.Toplevel(parent)
        window.title("DANGER - HIGH VOLTAGE")
        window.transient(parent)
        window.configure(bg=palette.bg)
        window.resizable(False, False)

        banner = tk.Frame(window, bg=BANNER_BG)
        banner.pack(fill="x")
        tk.Label(banner, text="⚠  DANGER: HIGH VOLTAGE  ⚠",
                 bg=BANNER_BG, fg=BANNER_INK,
                 font=("TkDefaultFont", 20, "bold")).pack(padx=24,
                                                          pady=(16, 4))
        tk.Label(banner, text=f"Up to {volts:g} V",
                 bg=BANNER_BG, fg=BANNER_INK,
                 font=("TkDefaultFont", 28, "bold")).pack(padx=24,
                                                          pady=(0, 16))

        body = ttk.Frame(window, padding=18)
        body.pack(fill="both")
        ttk.Label(body, wraplength=520, justify="left", text=(
            f"This run will put up to {volts:g} V on the {instrument}'s "
            f"source terminals - and through them on the sample, the "
            f"cables and the fixture.\n\n"
            f"There is NO interlock. Nothing will switch the voltage off "
            f"if someone touches a terminal, a lead or the sample, or "
            f"opens the fixture. Above {threshold:g} V that can injure "
            f"or kill.")).pack(anchor="w")
        ttk.Label(body, style="Bold.TLabel", text="Before you go on:").pack(
            anchor="w", pady=(14, 4))
        for line in (
                "Every conductor carrying the source is insulated, covered "
                "or out of reach.",
                "No one will touch the sample, the probes, the leads or the "
                "fixture until the run has ended and the output is off.",
                f"The sample and everything wired to it can withstand "
                f"{volts:g} V."):
            ttk.Label(body, wraplength=500, justify="left",
                      text=f"•  {line}").pack(anchor="w", padx=(8, 0))

        # Its own line, in the theme's error colour - readable in either
        # look, where the banner's red is not on the dark one: the one
        # instruction that holds for the whole run, not just the set-up.
        tk.Label(body, text=STAY_CLEAR, fg=palette.bad, bg=palette.bg,
                 wraplength=520, justify="left",
                 font=("TkDefaultFont", 11, "bold")).pack(anchor="w",
                                                          pady=(14, 0))

        self.checked = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            body, variable=self.checked, command=self._sync,
            # Broken by hand: a ttk checkbox does not wrap, and one long
            # line would stretch the whole window.
            text=f"I have made the set-up safe for {volts:g} V, and I and "
                 f"everyone near it\nwill stay clear of the sample and the "
                 f"probes until the output is off.").pack(
            anchor="w", pady=(12, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(18, 0))
        self.cancel_btn = ttk.Button(buttons, text="Cancel",
                                     command=self.cancel)
        self.cancel_btn.pack(side="right")
        self.apply_btn = ttk.Button(buttons, text=f"Apply {volts:g} V",
                                    command=self.apply, state="disabled")
        self.apply_btn.pack(side="right", padx=(0, 8))

        window.protocol("WM_DELETE_WINDOW", self.cancel)
        window.bind("<Escape>", lambda _event: self.cancel())
        self.cancel_btn.focus_set()

    def _sync(self):
        self.apply_btn.config(
            state="normal" if self.checked.get() else "disabled")

    def apply(self):
        if not self.checked.get():
            return
        self.result = True
        self.window.destroy()

    def cancel(self):
        self.result = False
        self.window.destroy()


def confirm_high_voltage(parent, instrument, volts, threshold):
    """Show the warning and wait. True only if the operator applied it."""
    dialog = HighVoltageDialog(parent, instrument, volts, threshold)
    dialog.window.grab_set()
    parent.wait_window(dialog.window)
    return dialog.result
