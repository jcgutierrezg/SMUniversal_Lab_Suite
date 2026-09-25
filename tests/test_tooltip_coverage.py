"""Every control in every window says what it does, beside the pointer.

Two properties. Coverage: every control an operator can press, type
into, tick or read a table from carries a tooltip, in every window the
suite opens - including the stage's own window. A panel added without
them fails here, so "hover help on every panel" stays true rather than
being true once. And placement: a tooltip appears at the pointer, not at
a fixed spot under the widget, and does not run off the screen.
"""
import tkinter as tk

import pytest

from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.gui import tooltips as tooltips_module
from smuniversal_lab_suite.core.gui.temp_panel import open_stage_window
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.launcher import PLOTTER, WINDOWS
from smuniversal_lab_suite.core.ownership import InstrumentOwnership

pytestmark = [pytest.mark.gui]

#: The widget classes an operator acts on or reads a result from. Labels
#: are not here: a field's label carries its field's words where the
#: row builders make that easy, but a label is not a control.
CONTROLS = {"TEntry", "TCombobox", "TButton", "TCheckbutton",
            "TRadiobutton", "Treeview", "TLabelframe", "Canvas",
            "TSpinbox", "TNotebook"}


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _is_matplotlib(widget):
    """The navigation toolbar's own buttons are matplotlib's, with its
    own labels; they are not ours to describe."""
    return "navigationtoolbar" in str(widget).lower()


@pytest.mark.parametrize("key", [k for k, (_l, spec) in WINDOWS.items()
                                 if spec != PLOTTER])
def test_every_control_has_a_tooltip(key, check):
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, WINDOWS[key][1], ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    try:
        # The stage's controls are built on demand; build them so they
        # are checked too.
        if getattr(app, "temp_btn", None) is not None:
            open_stage_window(app)
        root.update_idletasks()
        missing = [f"{w.winfo_class()} {w}" for w in _walk(root)
                   if w.winfo_class() in CONTROLS
                   and not _is_matplotlib(w)
                   and not app.tooltips.text_for(w)]
        check(f"{key}: every control has a tooltip", not missing,
              "\n  " + "\n  ".join(missing[:15]))
    finally:
        app.on_close()


def test_every_plotter_control_has_a_tooltip(tmp_path, check):
    """The plotter too, with files open - its view options are built
    from what is on the plot, so an empty window would not show them."""
    from plotter_files import IV_TITLE, iv_run, write

    from smuniversal_lab_suite.plotter.window import PlotterWindow

    iv = write(tmp_path, "film_iv_sweep.csv", [iv_run(), iv_run("rev")],
               title=IV_TITLE)
    root = tk.Tk()
    root.withdraw()
    try:
        window = PlotterWindow(root, [iv])
        root.update_idletasks()
        missing = [f"{w.winfo_class()} {w}" for w in _walk(root)
                   if w.winfo_class() in CONTROLS
                   and not _is_matplotlib(w)
                   and not window.tooltips.text_for(w)]
        check("plotter: every control has a tooltip", not missing,
              "\n  " + "\n  ".join(missing[:15]))
    finally:
        root.destroy()


def test_a_field_label_carries_its_fields_words(check):
    """Hovering the words beside a box is as good as hovering the box."""
    from smuniversal_lab_suite.experiments.iv_sweep.experiment import (
        IVSweepExperiment,
    )
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, IVSweepExperiment, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    try:
        exp = app.experiment
        text = app.tooltips.text_for(exp.start_label)
        check("the Start label has a tooltip", bool(text))
        entry = [w for w in exp.start_label.master.grid_slaves(row=0,
                                                               column=1)]
        check("and it is the same as its box's",
              entry and app.tooltips.text_for(entry[0]) == text)
    finally:
        app.on_close()


# ---------------------------------------------------------------- placement

@pytest.fixture
def shown():
    """A tooltip manager with a tooltip on screen, and a way to place it."""
    root = tk.Tk()
    root.withdraw()
    manager = tooltips_module.Tooltips(root)
    manager.enabled_var.set(True)
    widget = tk.Frame(root)
    yield root, manager, widget
    manager.hide()
    root.destroy()


def _position(window):
    window.update_idletasks()
    _size, x, y = window.wm_geometry().split("+")    # "WxH+X+Y"
    return int(x), int(y)


def test_it_appears_beside_the_pointer(shown, check):
    root, manager, widget = shown
    manager._pointer = (200, 150)
    manager._show(widget, "words")
    x, y = _position(manager._window)
    check("to the right of the pointer",
          x == 200 + tooltips_module.OFFSET_X, x)
    check("and below it", y == 150 + tooltips_module.OFFSET_Y, y)


def test_it_follows_the_pointer(shown, check):
    root, manager, widget = shown
    manager._pointer = (200, 150)
    manager._show(widget, "words")

    class Motion:
        x_root, y_root = 260, 190
    manager._moved(widget, "words", Motion)
    x, y = _position(manager._window)
    check("it moved with the pointer",
          (x, y) == (260 + tooltips_module.OFFSET_X,
                     190 + tooltips_module.OFFSET_Y), (x, y))


def test_it_does_not_run_off_the_screen(shown, check):
    root, manager, widget = shown
    width, height = root.winfo_screenwidth(), root.winfo_screenheight()
    manager._pointer = (width - 5, height - 5)
    manager._show(widget, "a tooltip long enough to have some width")
    window = manager._window
    x, y = _position(window)
    check("it flips left of a pointer at the right edge",
          x + window.winfo_reqwidth() <= width, (x, width))
    check("and above a pointer at the bottom edge",
          y + window.winfo_reqheight() <= height, (y, height))


def test_resting_waits_and_moving_restarts_the_wait(shown, check):
    """It appears where the pointer rests, so crossing a panel on the
    way somewhere else shows nothing."""
    root, manager, widget = shown

    class At:
        x_root, y_root = 100, 100
    manager._arrive(widget, "words", At)
    first = manager._after
    check("arriving schedules it", first is not None)
    check("nothing is shown yet", manager._window is None)
    manager._moved(widget, "words", At)
    check("moving before it appears restarts the wait",
          manager._after is not None and manager._after != first)
