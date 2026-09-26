"""
Open a window maximised.

A measurement window is laid out to fit 1600 x 860, but on a laptop at
high display scaling its natural size can run past the screen's edge,
leaving controls where the operator cannot reach them. Opened maximised
it always fits the screen it is on, and the operator can still restore
it to its natural size from the title bar.

Only the launcher calls this. Tests and `tools/capture_screens.py`
build windows directly, so they keep measuring and picturing the
natural size.

Maximised, not full screen: the title bar, taskbar and other windows
stay where they are.
"""
import sys
import tkinter as tk


def maximize(root):
    """Maximise `root`. Never raises: if the window manager refuses, the
    window opens at its natural size, as it always used to."""
    try:
        if sys.platform == "win32" or sys.platform == "darwin":
            root.state("zoomed")
        else:
            root.attributes("-zoomed", True)     # X11 window managers
        return True
    except tk.TclError:
        return False
