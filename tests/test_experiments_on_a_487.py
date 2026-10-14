"""A Keithley 487 at the connection panel: what the operator is offered.

`test_experiments_on_every_driver.py` proves the runs complete or are
refused. This is the other half - the form. A voltage-only source must
not be offered a current mode, a current bias, or a compliance it cannot
hold, and the window must say the measurement range is its own.
"""
import tkinter as tk

import pytest
from test_keithley487 import Fake487

from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.ownership import InstrumentOwnership
from smuniversal_lab_suite.drivers.keithley_487 import Keithley487
from smuniversal_lab_suite.experiments.fixed_source.experiment import (
    FixedSourceExperiment,
)
from smuniversal_lab_suite.experiments.iv_sweep.experiment import (
    IVSweepExperiment,
)

pytestmark = [pytest.mark.gui]


def connected(experiment_cls, before=None):
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, experiment_cls, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    if before:
        before(app.experiment)
    app.connect_role_manual("source", Fake487(), "fake", Keithley487)
    root.update()
    return root, app, app.experiment


def close(root, app):
    app.on_close()
    try:
        root.destroy()
    except tk.TclError:
        pass


def test_iv_sweep_offers_only_what_it_can_do(check):
    def current_mode(exp):
        exp.mode_var.set("current")
        exp.on_mode_changed()
        exp.standby_var.set("Bias current")

    root, app, exp = connected(IVSweepExperiment, before=current_mode)
    try:
        check("the current radio is greyed",
              str(exp.mode_radios["current"].cget("state")) == "disabled")
        check("the voltage radio is live",
              str(exp.mode_radios["voltage"].cget("state")) == "normal")
        check("the form moved to voltage", exp.mode_var.get() == "voltage")
        check("and is labelled for it",
              exp.start_label.cget("text") == "Start voltage (V):",
              exp.start_label.cget("text"))
        standby = list(exp.standby_combo.cget("values"))
        check("no current bias offered", "Bias current" not in standby,
              f"{standby}")
        check("the bias moved off it", exp.standby_var.get() == "Remain idle")
        values = list(exp.compliance_combo.cget("values"))
        check("the compliance is the menu", values == ["2.5e-05", "0.0025"],
              f"{values}")
        check("and read-only",
              str(exp.compliance_combo.cget("state")) == "readonly")
        check("defaulting to the safer limit",
              exp.compliance_var.get() == "2.5e-05", exp.compliance_var.get())
        check("the note says the range is its own",
              "protection only" in exp.compliance_note.cget("text"),
              exp.compliance_note.cget("text"))
    finally:
        close(root, app)


def test_fixed_source_offers_only_what_it_can_do(check):
    def current_mode(exp):
        exp.mode_var.set("current")
        exp.on_mode_changed()

    root, app, exp = connected(FixedSourceExperiment, before=current_mode)
    try:
        check("the current radio is greyed",
              str(exp.mode_radios["current"].cget("state")) == "disabled")
        check("the form moved to voltage", exp.mode_var.get() == "voltage")
        check("labelled for it",
              exp.level_label.cget("text") == "Level (V):")
        values = list(exp.compliance_combo.cget("values"))
        check("the compliance is the menu", values == ["2.5e-05", "0.0025"],
              f"{values}")
        check("read-only, on the safer limit",
              str(exp.compliance_combo.cget("state")) == "readonly"
              and exp.compliance_var.get() == "2.5e-05")
        check("the note says the range is its own",
              "protection only" in exp.compliance_note.cget("text"),
              exp.compliance_note.cget("text"))
        check("sensing pinned to 2-wire",
              exp.remote_sense_var.get() is False
              and str(exp.remote_sense_check.cget("state")) == "disabled")
    finally:
        close(root, app)


@pytest.mark.parametrize("experiment_cls", [IVSweepExperiment,
                                            FixedSourceExperiment])
def test_a_current_run_is_refused_by_the_window_itself(
        check, monkeypatch, experiment_cls):
    """The radio is greyed at Connect, but a mode can still be set on the
    form. The window has to refuse it at Run on the declaration alone -
    not rely on this driver also happening to refuse a current."""
    from smuniversal_lab_suite.drivers.base_instrument import BaseInstrument
    monkeypatch.setattr(Keithley487, "validate_source_point",
                        BaseInstrument.validate_source_point)
    root, app, exp = connected(experiment_cls)
    try:
        exp.mode_var.set("current")
        if experiment_cls is IVSweepExperiment:
            params = {"mode": "current", "start": -1e-6, "stop": 1e-6,
                      "delay": 0.0, "compliance": 1.0}
        else:
            exp.level_var.set("1e-6")
            exp.compliance_var.set("1")
            params = exp._params()
        with pytest.raises(ValueError, match="cannot source current"):
            exp._check_limits(params)
    finally:
        close(root, app)
