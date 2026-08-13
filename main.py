#!/usr/bin/env python3
"""
Launcher.

Pick a window by name, or pass one on the command line:

    python main.py                 # shows the picker
    python main.py vdp_hall        # Van der Pauw and Hall in one window
    python main.py iv_sweep        # one experiment

A window is one or more experiments. Wave 5b made the second form
possible, after the operator note that a Van der Pauw run *always*
immediately precedes a Hall measurement on the same mounted sample with
the same contacts - one session, not two programs.

Adding an experiment: write the folder under experiments/, then add one
line to WINDOWS below. Adding a *combination* is a line holding a list.
"""
import sys
import tkinter as tk
from tkinter import ttk

from core.base_app import LabApp
from experiments.vanderpauw.experiment import VanDerPauwExperiment
from experiments.hall.experiment import HallExperiment
from experiments.iv_sweep.experiment import IVSweepExperiment
from experiments.ossila_4pp.experiment import Ossila4PPExperiment

#: key -> (button label, experiment class or list of them)
#:
#: Van der Pauw and Hall appear only as the combined session, and that
#: is deliberate as of Wave 5c. The sheet resistance Hall needs crosses
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
    "ossila_4pp": (Ossila4PPExperiment.NAME, Ossila4PPExperiment),
}

#: Kept because notes and scripts refer to it. Single experiments only -
#: a combination is not an experiment class and cannot be constructed
#: like one.
EXPERIMENTS = {key: spec for key, (_label, spec) in WINDOWS.items()
               if isinstance(spec, type)}


def launch(spec):
    """Open a window hosting `spec` - one experiment class, or a list."""
    root = tk.Tk()
    LabApp(root, spec)
    root.mainloop()


def pick_window():
    """Small chooser shown when nothing is named on the command line.
    Closes itself once a choice is made, then hands off to the real
    window."""
    chooser = tk.Tk()
    chooser.title("Choose measurement")
    chosen = {}

    ttk.Label(chooser, text="Which measurement?", padding=12).pack()
    for _key, (label, spec) in WINDOWS.items():
        def select(s=spec):
            chosen["spec"] = s
            chooser.destroy()
        ttk.Button(chooser, text=label, width=40,
                   command=select).pack(padx=12, pady=3)
    ttk.Frame(chooser, height=8).pack()

    chooser.mainloop()
    return chosen.get("spec")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name not in WINDOWS:
            print(f"Unknown window '{name}'. Available: {', '.join(WINDOWS)}")
            sys.exit(1)
        launch(WINDOWS[name][1])
    else:
        spec = pick_window()
        if spec is not None:
            launch(spec)
