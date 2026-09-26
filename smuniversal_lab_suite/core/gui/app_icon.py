"""
The application's icon, on every window and on the taskbar.

The icon itself is drawn by `tools/make_icon.py` and committed under
`smuniversal_lab_suite/assets/`. This module only puts it where Windows
and Tk look for one.

Two things are needed for it to show on Windows, and either alone falls
short:

* **The window icon.** `iconbitmap(default=...)` with the multi-size
  .ico gives every window this process opens the icon in its title bar
  and in Alt-Tab, each drawn from the size Windows asks for rather than
  one scaled image. Off Windows, `iconphoto` does the same job.
* **An application id.** Without one, Windows groups the windows on the
  taskbar under the program that is running them - `pythonw.exe` - and
  shows Python's icon there, whatever the windows themselves carry.
  Declaring an id of our own makes the taskbar group this suite's
  windows as one application with its own icon.

Neither is allowed to stop a window opening: a missing or unreadable
icon file costs the icon, never the measurement.
"""
import pathlib
import sys
import tkinter as tk

ASSETS = pathlib.Path(__file__).resolve().parent.parent.parent / "assets"
ICON_ICO = ASSETS / "app_icon.ico"
ICON_PNG = ASSETS / "app_icon.png"
ICON_SMALL_PNG = ASSETS / "app_icon_32.png"

#: What Windows groups this suite's windows under on the taskbar.
APP_ID = "SMUniversal.LabSuite"


def declare_app_id():
    """Give this process its own identity on the Windows taskbar.

    Must run before the first window is created: the taskbar reads it
    when a window first appears. Returns whether it was set.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        return True
    except Exception:
        return False              # an old Windows, or no shell32: no id


def apply_window_icon(root):
    """Make the suite's icon the default for every window of `root`'s
    interpreter - the root itself and every Toplevel opened after it."""
    try:
        if sys.platform == "win32" and ICON_ICO.is_file():
            root.iconbitmap(default=str(ICON_ICO))
            return True
        photos = [tk.PhotoImage(master=root, file=str(path))
                  for path in (ICON_PNG, ICON_SMALL_PNG) if path.is_file()]
        if not photos:
            return False
        root.iconphoto(True, *photos)
        # Tk keeps no reference of its own, and a garbage-collected
        # image silently blanks.
        root._smu_icon_photos = photos
        return True
    except tk.TclError:
        return False
