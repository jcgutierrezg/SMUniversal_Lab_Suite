"""The desktop launch path: icon, windowless entry point, failed starts.

The shortcut runs the suite with no console, which is the point - a
console is one more thing to close, and closing it kills Python before
the window can put the instruments away. Having no console moves two
jobs elsewhere, and both are pinned here: what would have been printed
must reach a log, and a failure to start must say so in a dialog rather
than leave an icon that does nothing when clicked.
"""
import sys
import tkinter as tk
import tomllib
from pathlib import Path

import pytest
from PIL import Image

from smuniversal_lab_suite.core import launcher
from smuniversal_lab_suite.core.gui import app_icon

pytestmark = [pytest.mark.gui]

ROOT = Path(__file__).resolve().parent.parent


class DialogRecorder:
    """Stands in for `tkinter.messagebox` and remembers what it showed."""

    def __init__(self):
        self.calls = []

    def showerror(self, title, message, **_kwargs):
        self.calls.append((title, message))


def test_the_gui_script_is_declared_and_resolves(check):
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    gui = data["project"].get("gui-scripts", {})
    check("a windowless entry point is declared",
          gui.get("smu-lab-suite-gui")
          == "smuniversal_lab_suite.core.launcher:gui_main", gui)
    check("and the function it names exists",
          callable(getattr(launcher, "gui_main", None)))


def test_the_icon_carries_every_size_windows_asks_for(check):
    check("the .ico is committed", app_icon.ICON_ICO.is_file())
    check("and the PNGs Tk uses off Windows",
          app_icon.ICON_PNG.is_file() and app_icon.ICON_SMALL_PNG.is_file())
    with Image.open(app_icon.ICON_ICO) as ico:
        sizes = set(ico.info.get("sizes", ()))
    for size in (16, 24, 32, 48, 256):
        check(f"{size} px is in the .ico", (size, size) in sizes,
              sorted(sizes))


def test_the_shortcut_script_runs_the_declared_entry_point(check):
    """A rename of the entry point must not leave every bench PC's
    shortcut pointing at nothing."""
    script = (ROOT / "tools" / "make_shortcut.ps1").read_text(encoding="utf-8")
    check("the shortcut runs smu-lab-suite-gui", "smu-lab-suite-gui" in script)
    check("through uv's windowless uvw", "uvw.exe" in script)
    check("with the icon the suite ships",
          r"smuniversal_lab_suite\assets\app_icon.ico" in script)


def test_every_window_gets_the_icon(check):
    root = tk.Tk()
    root.withdraw()
    try:
        check("the icon was applied", app_icon.apply_window_icon(root))
    finally:
        root.destroy()


def test_a_failed_start_is_a_dialog_and_a_log(monkeypatch, check):
    recorder = DialogRecorder()
    monkeypatch.setattr(launcher, "messagebox", recorder)

    def broken_main():
        raise ImportError("No module named 'pyvisa'")
    monkeypatch.setattr(launcher, "main", broken_main)
    # As a GUI script starts: no console, so no stdout or stderr.
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    with pytest.raises(SystemExit) as stopped:
        launcher.gui_main()
    log = launcher.startup_log_path()
    stream = sys.stderr
    # Release the log before reading it; Windows will not share it.
    monkeypatch.setattr(sys, "stdout", sys.__stdout__)
    monkeypatch.setattr(sys, "stderr", sys.__stderr__)
    if stream is not None:
        stream.close()

    check("it exits with a failure code", stopped.value.code == 1)
    check("a dialog said so", len(recorder.calls) == 1, recorder.calls)
    if recorder.calls:
        title, message = recorder.calls[0]
        check("naming the error", "pyvisa" in message, message)
        check("and where the full report is", str(log) in message, message)
    check("the log exists", log.is_file())
    if log.is_file():
        text = log.read_text(encoding="utf-8")
        check("and holds the traceback", "ImportError" in text
              and "Traceback" in text, text[-300:])


def test_output_is_logged_when_there_is_no_console(monkeypatch, check):
    """Anything printed - an unknown window name, a Tk callback's
    traceback - reaches the log instead of vanishing."""
    def noisy_main():
        print("something worth reading")
    monkeypatch.setattr(launcher, "main", noisy_main)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    launcher.gui_main()
    stream = sys.stdout
    monkeypatch.setattr(sys, "stdout", sys.__stdout__)
    monkeypatch.setattr(sys, "stderr", sys.__stderr__)
    if stream is not None:
        stream.close()

    text = launcher.startup_log_path().read_text(encoding="utf-8")
    check("the printed line is in the log",
          "something worth reading" in text, text[-300:])
