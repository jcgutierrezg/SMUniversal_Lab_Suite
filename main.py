#!/usr/bin/env python3
"""
Launcher.

Pick an experiment by name, or pass one on the command line:

    python main.py                 # shows the picker
    python main.py vanderpauw      # launches straight into it

Adding an experiment: write the folder under experiments/, then add one
line to EXPERIMENTS below.
"""
import sys
import tkinter as tk
from tkinter import ttk

from core.base_app import LabApp
from experiments.vanderpauw.experiment import VanDerPauwExperiment
from experiments.hall.experiment import HallExperiment
from experiments.iv_sweep.experiment import IVSweepExperiment
from experiments.ossila_4pp.experiment import Ossila4PPExperiment

EXPERIMENTS = {
    "vanderpauw": VanDerPauwExperiment,
    "hall": HallExperiment,
    "iv_sweep": IVSweepExperiment,
    "ossila_4pp": Ossila4PPExperiment,
    # "four_point_probe": FourPointProbe,
}


def launch(experiment_cls):
    """Open the main window for one experiment."""
    root = tk.Tk()
    LabApp(root, experiment_cls)
    root.mainloop()


def pick_experiment():
    """Small chooser shown when no experiment is named on the command
    line. Closes itself once a choice is made, then hands off to the
    real window."""
    chooser = tk.Tk()
    chooser.title("Choose experiment")
    chosen = {}

    ttk.Label(chooser, text="Which measurement?", padding=12).pack()
    for key, cls in EXPERIMENTS.items():
        def select(c=cls):
            chosen["cls"] = c
            chooser.destroy()
        ttk.Button(chooser, text=cls.NAME, width=34,
                   command=select).pack(padx=12, pady=3)
    ttk.Frame(chooser, height=8).pack()

    chooser.mainloop()
    return chosen.get("cls")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name not in EXPERIMENTS:
            print(f"Unknown experiment '{name}'. Available: {', '.join(EXPERIMENTS)}")
            sys.exit(1)
        launch(EXPERIMENTS[name])
    else:
        cls = pick_experiment()
        if cls is not None:
            launch(cls)
