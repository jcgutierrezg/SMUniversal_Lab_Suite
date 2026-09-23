"""Hover help and the Equations window, in a real window.

Two properties matter more than the wording:

* **tooltips are off until asked for**, because guidance that cannot be
  turned off is in the way of everyone who has learned the panel;
* **the numbers are withheld while a result is stale**, for the same
  reason `calculated_fields()` withholds them from the file. A formula
  filled in from inputs that have since moved is self-consistent and
  wrong, which is the hardest kind of wrong to notice.
"""
import pytest

pytestmark = [pytest.mark.gui]

import sys
import tkinter as tk

from vdp_harness import run_vdp

import smuniversal_lab_suite.experiments.iv_sweep.experiment as iv
from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.ownership import InstrumentOwnership
from smuniversal_lab_suite.core.transports.null_transport import NullTransport
from smuniversal_lab_suite.experiments.fixed_source.experiment import (
    FixedSourceExperiment,
)
from smuniversal_lab_suite.experiments.hall.experiment import HallExperiment
from smuniversal_lab_suite.experiments.ossila_4pp.experiment import (
    Ossila4PPExperiment,
)
from smuniversal_lab_suite.experiments.vanderpauw.experiment import (
    VanDerPauwExperiment,
)

EXPERIMENTS = [VanDerPauwExperiment, HallExperiment, iv.IVSweepExperiment,
               Ossila4PPExperiment, FixedSourceExperiment]


class DialogLog:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(title="", message="", **kwargs):
            self.calls.append((name, title))
            return True
        return call


DIALOGS = DialogLog()


@pytest.fixture(autouse=True)
def _no_dialogs(monkeypatch):
    DIALOGS.calls.clear()
    for name, module in list(sys.modules.items()):
        if (name.startswith(("smuniversal_lab_suite.core.",
                             "smuniversal_lab_suite.experiments."))
                and module is not None and hasattr(module, "messagebox")):
            monkeypatch.setattr(module, "messagebox", DIALOGS)


def _app(experiment_cls):
    root = tk.Tk()
    app = LabApp(root, experiment_cls, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    root.update()
    return root, app


def _alive(window):
    """True while `window` is still a real window on screen."""
    try:
        return bool(window is not None and window.winfo_exists())
    except tk.TclError:
        return False


def _close(root, app):
    try:
        app.on_close()
    except Exception:
        pass
    try:
        root.destroy()
    except tk.TclError:
        pass


# ------------------------------------------------------------------
# tooltips
# ------------------------------------------------------------------
@pytest.mark.parametrize("experiment_cls", EXPERIMENTS,
                         ids=[c.__name__ for c in EXPERIMENTS])
def test_every_window_has_the_switch_and_starts_with_it_on(experiment_cls):
    root, app = _app(experiment_cls)
    try:
        assert app.tooltips is not None
        assert app.tooltips_var.get() is True
        assert app.tooltips.enabled is True
    finally:
        _close(root, app)


def test_a_tooltip_shows_only_while_the_switch_is_on(check):
    root, app = _app(VanDerPauwExperiment)
    try:
        tooltips = app.tooltips
        widget = app.experiment.level_entry

        # On by default now, so switch it off to test the off state.
        app.tooltips_var.set(False)
        tooltips._show(widget, "the source current")
        check("nothing appears while it is off", tooltips._window is None)

        app.tooltips_var.set(True)
        tooltips._show(widget, "the source current")
        check("it appears once it is on", tooltips._window is not None)
        if tooltips._window is not None:
            texts = [w.cget("text")
                     for w in tooltips._window.winfo_children()]
            check("with the text it was given",
                  "the source current" in texts, str(texts))

        tooltips.hide()
        check("and goes away again", tooltips._window is None)
    finally:
        _close(root, app)


def test_one_tooltip_at_a_time(check):
    root, app = _app(VanDerPauwExperiment)
    try:
        app.tooltips_var.set(True)
        app.tooltips._show(app.experiment.level_entry, "first")
        first = app.tooltips._window
        app.tooltips._show(app.experiment.tree, "second")
        root.update()
        check("the first one was taken away",
              app.tooltips._window is not first)
        check("the first one is gone from the screen", not _alive(first))
        check("and the second one is on it", _alive(app.tooltips._window))
    finally:
        _close(root, app)


# ------------------------------------------------------------------
# the Equations window
# ------------------------------------------------------------------
def test_a_tab_with_no_result_shows_the_formulas_and_says_so(check):
    root, app = _app(HallExperiment)
    try:
        exp = app.experiment
        window = exp.show_equations()
        check("it opened", window is not None)
        values, note = exp.equation_values()
        check("no numbers yet", values == {}, str(values))
        check("and it says why", "No result yet" in note, note)
        check("the values box is unavailable",
              str(window.values_check.cget("state")) == "disabled")
        check("every formula is on show",
              len(window.body.winfo_children()) == len(exp.EQUATIONS),
              str(len(window.body.winfo_children())))
        window.close()
    finally:
        _close(root, app)


def test_the_numbers_appear_once_calculated_and_vanish_when_stale(check):
    root, app = _app(VanDerPauwExperiment)
    try:
        exp = app.experiment
        app.connect_role("source", NullTransport(), "demo")
        exp.sample_name_var.set("wafer_A")
        exp.thickness_entry_var.set("180 nm")
        for position in (1, 2, 3, 4):
            run_vdp(exp, root, position, points=4)
        for item in exp.tree.get_children():
            exp.tree.item(item, text="☑")
        exp.copy_over()
        root.update()

        values, note = exp.equation_values()
        check("both formulas have numbers",
              set(values) == {"vdp_sheet_resistance", "vdp_resistivity"},
              str(sorted(values)))
        check("and the note names the result",
              exp._calc_result.result_id in note, note)
        check("the sheet resistance appears in its own formula",
              "R_s" in values["vdp_sheet_resistance"])

        window = exp.show_equations()
        check("the values box is now available",
              str(window.values_check.cget("state")) == "normal")

        exp.thickness_entry_var.set("900 nm")
        root.update()
        stale_values, stale_note = exp.equation_values()
        check("a stale result shows no numbers", stale_values == {},
              str(stale_values))
        check("and says the calculation is out of date",
              "out of date" in stale_note, stale_note)

        window.refresh()
        check("the window's values box follows it back to unavailable",
              str(window.values_check.cget("state")) == "disabled")
        check("and it stops claiming to show them",
              window.with_values.get() is False)
        window.close()
    finally:
        _close(root, app)


def test_reopening_reuses_the_one_window(check):
    root, app = _app(Ossila4PPExperiment)
    try:
        exp = app.experiment
        first = exp.show_equations()
        second = exp.show_equations()
        check("the same window comes back", first is second)
        first.close()
    finally:
        _close(root, app)


def test_a_tab_with_no_formulas_offers_no_window(check):
    root, app = _app(FixedSourceExperiment)
    try:
        exp = app.experiment
        check("Fixed source declares none", exp.EQUATIONS == ())
        check("so nothing opens", exp.show_equations() is None)
    finally:
        _close(root, app)
