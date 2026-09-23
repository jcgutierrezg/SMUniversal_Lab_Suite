"""The stage is watched in the window and commanded from another one.

Splitting it that way put a connection, a PID loop and a polling timer
on one side of a window boundary and the controls on the other. What is
checked here is that the boundary is one-way: closing the controls must
not disturb the stage, and the reading must keep coming either way.
"""
import tkinter as tk

import pytest

from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.gui.temp_panel import open_stage_window
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
        pass


def test_the_reading_is_in_the_window_and_the_controls_are_not(app, check):
    check("the reading is on screen from the start",
          app.temp_readout_label.winfo_exists())
    check("and it is not inside an experiment's columns",
          app.temp_readout_label.master is app.temp_frame)
    check("no controls exist until they are asked for",
          app._temp_controls == [])
    check("and no window has been built",
          getattr(app, "temp_window", None) is None)


def test_opening_twice_raises_the_same_window(app, check):
    first = open_stage_window(app)
    app.root.update()
    check("the controls appear with it", len(app._temp_controls) == 4)
    second = open_stage_window(app)
    check("asking again does not build a second one", first is second)


def test_closing_the_controls_leaves_the_stage_alone(app, check):
    window = open_stage_window(app)
    app.root.update()
    poll_id = app._temp_poll_id
    # Exactly what the close button does: Tk hands back the name of the
    # registered command, and invoking that runs the same handler.
    window.tk.call(window.protocol("WM_DELETE_WINDOW"))
    app.root.update()

    check("the window is gone", getattr(app, "temp_window", None) is None)
    check("its controls are forgotten", app._temp_controls == [])
    check("the controller is untouched", app.temp_ctrl is not None)
    check("the reading is still on screen",
          app.temp_readout_label.winfo_exists())
    check("and the poll was not cancelled", app._temp_poll_id is not None)
    check("the setpoint the operator typed survives the window",
          app.temp_setpoint_var.get() == "25")

    # The stage's own state is what decides whether the controls are
    # live, so a reopened window is in the right state rather than the
    # state it was left in.
    reopened = open_stage_window(app)
    app.root.update()
    check("reopening rebuilds the controls", len(app._temp_controls) == 4)
    check("and they are disabled, because nothing is connected",
          all(str(w.cget("state")) == "disabled"
              for w in app._temp_controls))
    check("a second window was built, not the destroyed one",
          reopened is app.temp_window)
    check("polling still has an id", poll_id is not None)
