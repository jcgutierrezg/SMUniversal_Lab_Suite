#!/usr/bin/env python3
"""
Launcher.

Pick a window by name, or pass one on the command line:

    python main.py                 # shows the picker
    python main.py vdp_hall        # Van der Pauw and Hall in one window
    python main.py iv_sweep        # one experiment

Once the project is installed (`uv pip install -e .`) the same thing is
reachable from any directory as `smu-lab-suite`, with the same
arguments.

This file is deliberately thin. Everything it used to hold moved to
`core/launcher.py` in Wave 7e, because a console script has to name an
importable function and pointing one at `main.py` would install a
top-level `main` module into the environment - a name every other
package also thinks is theirs. See that module for the reasoning.

Both routes run the same `main()`. Adding an experiment or a window is
still a one-line edit, now to `WINDOWS` in `core/launcher.py`.
"""
from core.launcher import EXPERIMENTS, WINDOWS, main  # noqa: F401

if __name__ == "__main__":
    main()
