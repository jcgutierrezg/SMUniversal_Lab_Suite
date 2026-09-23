"""Choosing a window and opening it - the application's entry point.

Why this is a module in `core/` rather than the body of `main.py`
-----------------------------------------------------------------
The project is installable, and an installed project wants a
**console script**: after `uv pip install -e .` somebody types
`smu-lab-suite` from any directory and the application opens. That is
what most people actually wanted from "ship it as an `.exe`" - a thing
you run without knowing where the code lives - and it costs a line of
configuration rather than a bundled copy of the interpreter.

A console script has to name an importable function, `module:function`.
Pointing it at `main.py` would install a top-level module called `main`
into the environment's `site-packages`, where it would sit alongside
every other package's idea of what `main` means. Whoever imported second
would lose. So the logic lives here, under the package name that is
already ours, and `main.py` stays as the thin, obvious thing to run from
a checkout.

Two entry points, one body: `python main.py` and `smu-lab-suite` reach
the same `main()`.
"""
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.gui.chooser import build_cards
from smuniversal_lab_suite.core.gui.header import split_name
from smuniversal_lab_suite.core.gui.theme import theme_for
from smuniversal_lab_suite.core.single_instance import (
    AlreadyRunning,
    SingleInstance,
)
from smuniversal_lab_suite.experiments.fixed_source.experiment import (
    FixedSourceExperiment,
)
from smuniversal_lab_suite.experiments.hall.experiment import HallExperiment
from smuniversal_lab_suite.experiments.iv_sweep.experiment import (
    IVSweepExperiment,
)
from smuniversal_lab_suite.experiments.ossila_4pp.experiment import (
    Ossila4PPExperiment,
)
from smuniversal_lab_suite.experiments.vanderpauw.experiment import (
    VanDerPauwExperiment,
)

#: The CSV plotter's entry in `WINDOWS`. A name rather than a class,
#: because the plotter is not an experiment: it hosts no `LabApp`, opens
#: no instrument and is launched by `smuniversal_lab_suite.plotter`.
PLOTTER = "plotter"

#: key -> (button label, experiment class or list of them)
#:
#: Van der Pauw and Hall appear only as the combined session, and that
#: is deliberate. The sheet resistance Hall needs crosses
#: in memory from the Van der Pauw tab, so a Hall window opened on its
#: own has no way to obtain one but the keyboard - and the file path it
#: used to load one from is gone. Offering a window that cannot do the
#: measurement it is named after would be a trap, not a choice.
#:
#: The IV sweep and the 4PP stay standalone: different instruments,
#: different sample mounting, nothing carried across.
WINDOWS = {
    "vdp_hall": ("Van der Pauw + Hall (one session)",
                 [VanDerPauwExperiment, HallExperiment]),
    "iv_sweep": (IVSweepExperiment.NAME, IVSweepExperiment),
    # Standalone, like the IV sweep, and for the same reason: it derives
    # no quantity another tab wants and shares nothing across a window.
    # It is not folded into the IV sweep despite both holding a bias,
    # because the sequences genuinely fork - one measures *between*
    # holds, the other measures *during* one - and a red test after a
    # shared change would not say which measurement broke.
    "fixed_source": (FixedSourceExperiment.NAME, FixedSourceExperiment),
    "ossila_4pp": (Ossila4PPExperiment.NAME, Ossila4PPExperiment),
    # One window for every experiment's files, rather than a plot tab in
    # each: comparing an IV run with a 4PP run, or a Fixed source run
    # from last week with today's, is exactly what a per-experiment tab
    # cannot do. It detects which experiment a file came from itself.
    PLOTTER: ("Plot saved data (CSV plotter)", PLOTTER),
}

#: What each window is for, in one sentence: shown on its card in the
#: chooser, under its name. Keyed like `WINDOWS`, and a window without a
#: sentence fails `tests/test_chooser.py` - the card would otherwise say
#: nothing to the operator who needs it most, the one who has not used
#: that window before.
DESCRIPTIONS = {
    "vdp_hall": "Sheet resistance from four corner contacts, then carrier "
                "density and mobility in a field - one mounted sample, one "
                "session.",
    "iv_sweep": "Current-voltage sweeps of a device, once or repeated on a "
                "schedule, with a linear fit for ohmic samples.",
    "fixed_source": "Hold one voltage or current and log the response "
                    "over time.",
    "ossila_4pp": "Sheet resistance and resistivity through the Ossila "
                  "four-point probe head, corrected for sample geometry.",
    PLOTTER: "Open files saved by any experiment to plot them, compare "
             "their settings and export the data.",
}

#: The card title, where the experiment's own name will not do: a pair
#: of experiments has no single name, and the plotter is not one.
TITLES = {
    "vdp_hall": "Van der Pauw + Hall",
    PLOTTER: "CSV plotter",
}


def window_keys(spec):
    """The emblem and colour keys a window wears: one per experiment it
    hosts, or the neutral one for the plotter."""
    if spec == PLOTTER:
        return ["neutral"]
    classes = [spec] if isinstance(spec, type) else list(spec)
    return [cls.THEME_KEY for cls in classes]


def window_title(key, spec):
    """A card's title: the experiment's name without its subtitle."""
    if key in TITLES:
        return TITLES[key]
    return split_name(spec.NAME)[0]


#: Kept because notes and scripts refer to it. Single experiments only -
#: a combination is not an experiment class and cannot be constructed
#: like one.
EXPERIMENTS = {key: spec for key, (_label, spec) in WINDOWS.items()
               if isinstance(spec, type)}


def needs_instrument_lock(spec):
    """Whether opening `spec` must hold the single-instance lock.

    The lock exists so two copies never command the same instrument.
    The plotter reads files and nothing else, so it neither needs the
    lock nor should keep it: holding it would stop a measurement window
    opening while old data is on screen, which is when it is most
    wanted.
    """
    return spec != PLOTTER


def launch(spec, paths=()):
    """Open a window hosting `spec` - one experiment class, a list of
    them, or the plotter (with any files named after it)."""
    if spec == PLOTTER:
        # Imported here so a measurement window does not build the
        # plotter's module graph it never uses.
        from smuniversal_lab_suite.plotter.window import main as plotter

        plotter(paths)
        return
    root = tk.Tk()
    LabApp(root, spec)
    root.mainloop()


def pick_window(measurements_available=True):
    """Small chooser shown when nothing is named on the command line.
    Closes itself once a choice is made, then hands off to the real
    window.

    With `measurements_available` false - another copy holds the lock -
    the measurement windows are shown greyed with the reason, and only
    the plotter can be chosen. Refusing outright would also refuse the
    one window that is safe to open beside a running measurement.
    """
    chooser = tk.Tk()
    chooser.title("SMUniversal Lab Suite")
    chooser.resizable(False, False)
    # The chooser is the first window of the session, so it is also
    # where the operator first sees which mode they left the suite in.
    theme_for(chooser)
    chosen = {}

    def choose(spec):
        chosen["spec"] = spec
        chooser.destroy()

    def entry(key, spec, enabled=True):
        return {"title": window_title(key, spec),
                "description": DESCRIPTIONS[key],
                "keys": window_keys(spec), "value": spec,
                "enabled": enabled}

    page = ttk.Frame(chooser, padding=(18, 16, 18, 18))
    page.pack(fill="both", expand=True)

    ttk.Label(page, text="Which measurement?",
              style="Title.TLabel").pack(anchor="w", padx=6)
    ttk.Label(page, style="Hint.TLabel",
              text="Each opens in a window of its own.").pack(
        anchor="w", padx=6, pady=(0, 8))

    measurements = [entry(key, spec, measurements_available)
                    for key, (_label, spec) in WINDOWS.items()
                    if needs_instrument_lock(spec)]
    grid, _cards = build_cards(page, measurements, choose)
    grid.pack(fill="x")
    if not measurements_available:
        ttk.Label(page, style="Warn.TLabel", wraplength=560,
                  justify="left",
                  text="A measurement window is already open on this "
                       "machine, so another cannot start. Saved data "
                       "can still be plotted.").pack(anchor="w", padx=6,
                                                    pady=(4, 0))

    ttk.Label(page, text="Or look at saved data",
              style="Hint.TLabel").pack(anchor="w", padx=6, pady=(14, 0))
    saved = [entry(key, spec) for key, (_label, spec) in WINDOWS.items()
             if not needs_instrument_lock(spec)]
    grid, _cards = build_cards(page, saved, choose)
    grid.pack(fill="x")

    chooser.mainloop()
    return chosen.get("spec")


def refuse_second_instance():
    """Tell the operator why nothing opened, then leave.

    A dialog rather than a printed line: launched from a shortcut or a
    frozen `.exe` there is no console to print to, and an application
    that exits silently reads as a broken install.

    It needs its own `Tk` root because the real window is never built -
    withdrawn, so the only thing on screen is the message.
    """
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Already running",
        "SMUniversal Lab Suite is already running on this machine.\n\n"
        "Only one copy may run at a time: two copies would each open the "
        "same instruments, and each would believe it controlled the "
        "output state.\n\n"
        "Switch to the window that is already open. If you are sure "
        "nothing is running, the previous copy may still be shutting "
        "down - wait a moment and try again.")
    root.destroy()


def main():
    """Open the application, or refuse if another copy is running."""
    # Taken before any window is built and held for the life of the
    # process. Released by the operating system when this process ends,
    # however it ends - see `core/single_instance.py` for why that is
    # the whole design rather than an implementation detail.
    #
    # Attempted rather than required here: whether a missing lock is
    # fatal depends on what is opened, and the plotter opens nothing.
    lock = SingleInstance()
    try:
        _lock = lock.acquire()
    except AlreadyRunning:
        _lock = None

    paths = []
    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name not in WINDOWS:
            print(f"Unknown window '{name}'. Available: {', '.join(WINDOWS)}")
            sys.exit(1)
        spec = WINDOWS[name][1]
        paths = sys.argv[2:]
    else:
        spec = pick_window(measurements_available=_lock is not None)
        if spec is None:
            return

    if needs_instrument_lock(spec):
        if _lock is None:
            refuse_second_instance()
            sys.exit(1)
    else:
        # Not kept for the plotter, so a measurement window can still
        # start while it is open.
        lock.release()
    launch(spec, paths)
