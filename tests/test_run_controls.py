"""The run controls behave the same on every tab.

Review A-08 found the Run/Stop/lamp panel and its four handlers copied
into all five experiments, identical but for comments and, in one, the
colour of the lamp. They are now one builder (`core/gui/run_controls.py`)
and one set of handlers on `Experiment`, and a tab that has more buttons
says so through `_idle_only_buttons` / `_run_only_buttons` rather than
by overriding the handlers. This drives that contract on every tab, so a
sixth experiment - or a seventh copy - cannot drift quietly.
"""
import tkinter as tk

import pytest

from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.gui.run_controls import LAMP_OFF, LAMP_ON
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.ownership import InstrumentOwnership
from smuniversal_lab_suite.experiments.fixed_source.experiment import (
    FixedSourceExperiment,
)
from smuniversal_lab_suite.experiments.hall.experiment import HallExperiment
from smuniversal_lab_suite.experiments.iv_sweep.experiment import (
    IVSweepExperiment,
)
from smuniversal_lab_suite.experiments.ossila_4pp.experiment import (
    Ossila4PPExperiment,
)
from smuniversal_lab_suite.experiments.vanderpauw.experiment import (
    VanDerPauwExperiment,
)

pytestmark = [pytest.mark.gui]

#: Per tab, the buttons that start a run and the ones that end one.
TABS = {
    IVSweepExperiment: (["run_btn", "periodic_btn"], ["stop_btn"]),
    VanDerPauwExperiment: (["run_btn"], ["stop_btn"]),
    HallExperiment: (["run_btn"], ["stop_btn"]),
    Ossila4PPExperiment: (["run_btn"], ["stop_btn"]),
    FixedSourceExperiment: (["run_btn"], ["finish_btn", "stop_btn"]),
}


def _state(button):
    return str(button.cget("state"))


def _lamp(exp):
    return exp.lamp_canvas.itemcget(exp.lamp_id, "fill")


@pytest.fixture
def tab(request):
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, request.param, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    root.update()
    yield app.experiment
    app.on_close()
    try:
        root.destroy()
    except tk.TclError:
        pass              # on_close() destroys the root itself


@pytest.mark.parametrize("tab", list(TABS), indirect=True,
                         ids=lambda cls: cls.__name__)
def test_the_buttons_follow_the_run(check, tab):
    starts, ends = TABS[type(tab)]
    name = type(tab).__name__

    check(f"{name}: idle, the start buttons are live",
          all(_state(getattr(tab, b)) == "normal" for b in starts))
    check(f"{name}: idle, the end buttons are not",
          all(_state(getattr(tab, b)) == "disabled" for b in ends))
    check(f"{name}: idle, the lamp is off", _lamp(tab) == LAMP_OFF,
          _lamp(tab))

    tab._enter_run_ui()
    tab.set_lamp(True)
    check(f"{name}: running, the start buttons are not",
          all(_state(getattr(tab, b)) == "disabled" for b in starts))
    check(f"{name}: running, the end buttons are live",
          all(_state(getattr(tab, b)) == "normal" for b in ends))
    check(f"{name}: running, the lamp is on", _lamp(tab) == LAMP_ON,
          _lamp(tab))

    tab._end_run()
    tab._end_run()          # queued twice by a run's cleanup: harmless
    check(f"{name}: back to idle", all(
        _state(getattr(tab, b)) == "normal" for b in starts) and all(
        _state(getattr(tab, b)) == "disabled" for b in ends))
    check(f"{name}: the lamp goes off", _lamp(tab) == LAMP_OFF, _lamp(tab))
    check(f"{name}: the progress line is reset",
          tab.progress_var.get() == "Idle", tab.progress_var.get())


def test_the_iv_tab_also_clears_its_eta(check):
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, IVSweepExperiment, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    try:
        exp = app.experiment
        exp.eta_var.set("ETA: 12 s")
        exp._end_run()
        check("the ETA is cleared", exp.eta_var.get() == "ETA: -",
              exp.eta_var.get())
    finally:
        app.on_close()


def test_stop_with_nothing_running_does_nothing(check):
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, VanDerPauwExperiment, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    try:
        exp = app.experiment
        exp.stop_pressed()
        check("no stopping message", exp.progress_var.get() == "Idle",
              exp.progress_var.get())
    finally:
        app.on_close()


def test_end_run_tolerates_teardown_and_nothing_else():
    """The five copies this replaced each swallowed every exception.

    Only a widget that is already gone may be tolerated: the cleanup
    that queues `_end_run` can land after the window has started to
    close. Any other failure is a fault, and hiding it is how a tab
    stays greyed out with no explanation.
    """
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, HallExperiment, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    exp = app.experiment
    try:
        del exp.progress_var
        with pytest.raises(AttributeError):
            exp._end_run()
    finally:
        app.on_close()

    root2 = tk.Tk()
    root2.withdraw()
    app2 = LabApp(root2, HallExperiment, ownership=InstrumentOwnership(),
                  samples=SampleRegistry())
    exp2 = app2.experiment
    app2.on_close()                 # the widgets are gone now
    exp2._end_run()                 # and this must not raise
