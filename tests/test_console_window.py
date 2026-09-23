"""The console records whether or not anyone is watching.

That is the whole point of moving it out of the window: the panel that
folded away kept logging while folded, and the window that replaced it
has to keep that property. If it ever stops, the symptom is silent -
an operator opens the console after something went wrong and finds the
part they needed missing.
"""
import tkinter as tk

import pytest

from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.gui.console_panel import (
    ConsoleLog,
    toggle_console,
)
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.ownership import InstrumentOwnership
from smuniversal_lab_suite.experiments.iv_sweep.experiment import (
    IVSweepExperiment,
)

pytestmark = [pytest.mark.gui]


@pytest.fixture
def app():
    root = tk.Tk()
    root.withdraw()
    application = LabApp(root, IVSweepExperiment,
                         ownership=InstrumentOwnership(),
                         samples=SampleRegistry())
    root.update()
    yield application
    application.on_close()
    try:
        root.destroy()
    except tk.TclError:
        pass              # on_close() destroys the root itself


def _console_text(app):
    return app.console_window.text.get("1.0", "end")


def test_the_log_survives_the_window(app, check):
    app.log("before the console was ever opened")
    app.drain_ui_now()
    check("a line logged with no window is kept",
          "before the console" in app.console_log.text())

    toggle_console(app)
    app.root.update()
    check("opening the console shows what was logged before it",
          "before the console" in _console_text(app))

    app.log("while the console is open")
    app.drain_ui_now()
    app.root.update()
    check("and it follows new lines live",
          "while the console is open" in _console_text(app))

    toggle_console(app)
    app.root.update()
    check("the window closes", app.console_window is None)

    app.log("while the console is closed")
    app.drain_ui_now()
    check("logging carries on into the log",
          "while the console is closed" in app.console_log.text())

    toggle_console(app)
    app.root.update()
    text = _console_text(app)
    check("reopening shows every line, in order",
          text.index("before the console")
          < text.index("while the console is open")
          < text.index("while the console is closed"), text[-200:])


def test_the_window_can_be_closed_by_its_own_button(app, check):
    toggle_console(app)
    app.root.update()
    window = app.console_window
    window.close()
    app.root.update()
    check("closing detaches the view", app.console_log.view is None)
    check("and the app forgets the window", app.console_window is None)

    app.log("after the close button")
    app.drain_ui_now()
    check("a closed console does not swallow the line",
          "after the close button" in app.console_log.text())


def test_the_log_is_bounded():
    """A console left open for a week is not a memory leak."""
    log = ConsoleLog(max_lines=10)
    for number in range(100):
        log.append(f"line {number}\n")
    lines = log.lines()
    assert len(lines) == 10
    assert lines[0] == "line 90\n"
    assert lines[-1] == "line 99\n"
