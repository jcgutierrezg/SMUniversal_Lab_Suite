"""Switching mode repaints a live window.

The switch is the whole point of the feature: an operator halfway
through a session presses one button and the window changes without
being rebuilt. So what is checked here is that a *live* theme reaches
all three kinds of widget - ttk styles, the plain-Tk widgets that
registered a callback, and the saved preference - and that a listener
whose widget has been destroyed stops being called, because that is the
leak that would otherwise grow with every closed tab.
"""
import tkinter as tk
from tkinter import ttk

import pytest

from smuniversal_lab_suite.core.gui import theme as theme_module
from smuniversal_lab_suite.core.gui.theme import (
    DARK,
    LIGHT,
    PALETTES,
    Theme,
    load_mode,
    theme_for,
)

pytestmark = [pytest.mark.gui]


@pytest.fixture
def root():
    window = tk.Tk()
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass


def test_a_root_has_one_theme(root, check):
    first = theme_for(root)
    check("the same root gives the same theme", theme_for(root) is first)
    child = ttk.Frame(root)
    check("a widget finds its window's theme", theme_for(child) is first)


def test_the_styles_follow_the_mode(root, check):
    theme = Theme(root, mode=DARK)
    dark_ink = theme.style.lookup("TLabel", "foreground")
    check("dark text is the dark palette's ink",
          dark_ink == PALETTES[DARK].ink, dark_ink)

    theme.set_mode(LIGHT)
    light_ink = theme.style.lookup("TLabel", "foreground")
    check("light text is the light palette's ink",
          light_ink == PALETTES[LIGHT].ink, light_ink)
    check("the ground changed too",
          theme.style.lookup("TFrame", "background") == PALETTES[LIGHT].bg)


def test_the_accent_follows_the_experiment(root, check):
    theme = Theme(root, mode=DARK)
    theme.set_accent("hall")
    hall = theme.style.lookup("Run.TButton", "background")
    theme.set_accent("iv_sweep")
    iv = theme.style.lookup("Run.TButton", "background")
    check("Run wears the experiment's colour", hall != iv, f"{hall} {iv}")
    check("a tab can be asked for another tab's colour",
          theme.accent_of("hall") == hall)
    check("an unknown key falls back rather than raising",
          theme.accent_of("nonesuch") == theme_module.ACCENTS["neutral"][DARK])


def test_plain_tk_widgets_are_called_on_every_switch(root, check):
    theme = Theme(root, mode=DARK)
    canvas = tk.Canvas(root)
    seen = []
    theme.on_change(lambda t: seen.append(t.mode), widget=canvas)
    check("the callback runs once when it registers", seen == [DARK], seen)

    theme.set_mode(LIGHT)
    check("and again on a switch", seen == [DARK, LIGHT], seen)

    canvas.destroy()
    theme.set_mode(DARK)
    check("a destroyed widget's callback is dropped",
          seen == [DARK, LIGHT], seen)
    check("and it is not kept in the list", theme._listeners == [],
          theme._listeners)


def test_switching_is_remembered(root, check):
    theme = Theme(root, mode=DARK)
    theme.toggle()
    check("toggling dark gives light", theme.mode == LIGHT, theme.mode)
    check("and it is saved for next launch", load_mode() == LIGHT)
    theme.toggle()
    check("toggling back gives dark", theme.mode == DARK, theme.mode)
    check("and that is saved too", load_mode() == DARK)


def test_an_unknown_mode_is_refused(root):
    theme = Theme(root, mode=DARK)
    with pytest.raises(ValueError):
        theme.set_mode("sepia")


def test_the_window_is_built_in_the_saved_mode(check):
    """A window opens in the mode the operator left it in."""
    theme_module.save_mode(LIGHT)
    root = tk.Tk()
    root.withdraw()
    try:
        check("the new window is light", theme_for(root).mode == LIGHT)
    finally:
        root.destroy()
