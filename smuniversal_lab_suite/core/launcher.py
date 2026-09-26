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
from smuniversal_lab_suite.core.gui.app_icon import (
    apply_window_icon,
    declare_app_id,
)
from smuniversal_lab_suite.core.gui.chooser import build_cards
from smuniversal_lab_suite.core.gui.header import split_name
from smuniversal_lab_suite.core.gui.maximize import maximize
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
    apply_window_icon(root)
    LabApp(root, spec)
    maximize(root)
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
    apply_window_icon(chooser)
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
    apply_window_icon(root)
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
    # Before any window: the taskbar reads it when the first appears.
    declare_app_id()
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


# ---------------------------------------------------------------------------
# The desktop shortcut's entry point
# ---------------------------------------------------------------------------

#: Kept beside the single-instance lock. Trimmed when it passes this
#: size, so a machine that has launched the suite for a year does not
#: carry a year of it.
STARTUP_LOG_LIMIT = 1_000_000


def startup_log_path():
    """Where a windowless launch writes what it would have printed."""
    from smuniversal_lab_suite.core.single_instance import lock_directory
    return lock_directory() / "launcher.log"


def gui_main():
    """Open the application with no console window - the desktop icon.

    Installed as the `smu-lab-suite-gui` GUI script, which Windows runs
    without a console. That matters for safety, not only for looks: a
    console beside the window is one more thing to close, and closing it
    kills Python outright - the window's own close path never runs, so
    the output is never switched off and the stage never put away. With
    no console, the window's close button is the only way out, and it is
    the one that puts the instruments away.

    The cost of having no console is that nothing it would have shown is
    seen, so two things replace it:

    * **What would have been printed goes to a log** - `launcher.log`
      beside the single-instance lock - including a traceback from a
      Tk callback that raises, which Tk reports on stderr.
    * **A failure to start is a dialog**, naming the error and the log,
      rather than an icon that is clicked and does nothing.
    """
    path = startup_log_path()
    stream = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > STARTUP_LOG_LIMIT:
            path.unlink()
        stream = open(path, "a", encoding="utf-8", buffering=1)
        stream.write(f"\n--- started {_now()} ---\n")
    except OSError:
        stream = None             # no log: still better than no window
    # A GUI script has no console, and Python leaves stdout and stderr
    # as None. Anything written there would be lost; send it to the log.
    if stream is not None:
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream

    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:
        import traceback
        if stream is not None:
            traceback.print_exc(file=stream)
        _startup_failed(exc, path if stream is not None else None)
        raise SystemExit(1) from exc


def _now():
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


def _startup_failed(exc, log_path):
    """Say that the suite could not start, and where to look."""
    detail = f"{type(exc).__name__}: {exc}"
    where = (f"\n\nThe full report is in:\n{log_path}" if log_path
             else "")
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "SMUniversal Lab Suite could not start",
            f"The suite stopped before its window opened.\n\n{detail}"
            f"{where}\n\nIf this follows an update, the suite's "
            f"packages probably need installing again - see Install in "
            f"its README.")
        root.destroy()
    except Exception:
        pass                      # no display at all: the log has it
