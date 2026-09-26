"""
The plotter against files the experiments really save.

`test_plotter_detect.py` pins each experiment's title and slug, but the
column signatures and the declared reading columns are claims about what
the experiment *writes*, and only a real save can check those. So every
experiment runs once in demo mode, saves through its own `save_runs()`,
and the file is read back.

Each file is checked three ways: detected with all clues agreeing,
detected by its columns alone, and every column the plotter declares as
a reading actually present - so renaming a reading key in an experiment
fails here rather than leaving a plot that quietly draws nothing.
"""
import pytest

pytestmark = [pytest.mark.gui, pytest.mark.slow]

import os
import tkinter as tk

from hall_harness import run_hall
from vdp_harness import run_vdp

import smuniversal_lab_suite.core.base_app as base_app
import smuniversal_lab_suite.experiments.base_experiment as base_experiment
import smuniversal_lab_suite.experiments.four_contact as four_contact
import smuniversal_lab_suite.experiments.iv_sweep.experiment as iv_experiment
from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.transports.null_transport import NullTransport
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
from smuniversal_lab_suite.plotter.detect import (
    FIXED_SOURCE,
    HALL,
    IV_SWEEP,
    OSSILA_4PP,
    VAN_DER_PAUW,
    _by_columns,
)
from smuniversal_lab_suite.plotter.reader import load


class Dialogs:
    """Answers yes to everything, so a headless save never blocks."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: True


@pytest.fixture(autouse=True)
def _no_dialogs(monkeypatch):
    # Every module that imports `messagebox` on its own, not just the
    # experiment's: `LabApp.on_close()` asks through `base_app`'s.
    for module in (base_app, base_experiment, four_contact, iv_experiment):
        monkeypatch.setattr(module, "messagebox", Dialogs())
    monkeypatch.setattr(iv_experiment, "PRE_SWEEP_SETTLE_S", 0.01)


def _drain(root, app):
    app.drain_ui_now()
    for _ in range(40):
        root.update()
    app.drain_ui_now()


def _save(tmp_path, experiment_cls, measure):
    """Open `experiment_cls` on the demo instrument, measure, save, and
    return the one data file it wrote."""
    root = tk.Tk()
    app = LabApp(root, experiment_cls)
    try:
        app.connect_role("source", NullTransport(), "demo")
        app.storage_path = str(tmp_path)
        exp = app.experiment
        exp.sample_name_var.set("film")
        root.update()
        measure(root, app, exp)
        _drain(root, app)
        exp.save_runs()
    finally:
        _drain(root, app)
        app.on_close()
    slug = f"_{experiment_cls.CSV_SLUG}.csv"
    written = [name for name in os.listdir(tmp_path) if name.endswith(slug)]
    assert len(written) == 1, os.listdir(tmp_path)
    return str(tmp_path / written[0])


def _iv(root, app, exp):
    exp.mode_var.set("voltage")
    exp.on_mode_changed()
    exp.start_var.set("-0.5")
    exp.stop_var.set("0.5")
    exp.points_var.set("11")
    exp.delay_var.set("0.001")
    exp.compliance_var.set("0.01")
    params = exp._sweep_params()
    exp._check_limits(params)
    exp._do_single(params)


def _fixed_source(root, app, exp):
    exp.mode_var.set("voltage")
    exp.on_mode_changed()
    exp.level_var.set("0.1")
    exp.compliance_var.set("0.01")
    exp.duration_var.set("0.6")
    exp.interval_var.set("0.2")
    exp._watch_compliance = True
    params = exp._params()
    app.guard_run(lambda: exp._do_run(params))()


def _four_pp(root, app, exp):
    params = exp._sweep_params()
    exp._check_limits(params)
    exp._do_run(params)


def _vdp(root, app, exp):
    for position in ("A", "B"):
        run_vdp(exp, root, position, points=2)


def _hall(root, app, exp):
    for sign in ("+", "-"):
        run_hall(exp, root, "C", field_sign=sign, points=2)


CASES = [
    (IV_SWEEP, IVSweepExperiment, _iv),
    (FIXED_SOURCE, FixedSourceExperiment, _fixed_source),
    (OSSILA_4PP, Ossila4PPExperiment, _four_pp),
    (VAN_DER_PAUW, VanDerPauwExperiment, _vdp),
    (HALL, HallExperiment, _hall),
]


@pytest.mark.parametrize("kind, experiment_cls, measure", CASES,
                         ids=[kind.key for kind, _, _ in CASES])
def test_a_real_save_is_recognised_and_read(check, tmp_path, kind,
                                            experiment_cls, measure):
    stored = load(_save(tmp_path, experiment_cls, measure))

    check("detected", stored.kind is kind, stored.kind.key)
    check("by its title", stored.detection.method == "title",
          stored.detection.method)
    check("with every clue agreeing", stored.detection.notes == (),
          stored.detection.notes)
    check("the columns alone identify it", _by_columns(stored.columns) is kind,
          stored.columns)
    check("runs were read", stored.runs and all(len(r) for r in stored.runs),
          [len(r) for r in stored.runs])

    # `compliance#2` is how the reader names the trip flag in a schema 2
    # file; a save made now writes `compliance_tripped`. `stage_temp_C`
    # is only written while a stage is connected.
    declared = kind.reading_columns - {"compliance#2", "stage_temp_C"}
    missing = sorted(declared - set(stored.columns))
    repeated = [w for w in stored.warnings if "appears" in w]
    check("no column name is written twice", not repeated, repeated)
    check("every declared reading column is written", not missing, missing)
    for run in stored.runs:
        stray = sorted(c for c in run.readings if c not in kind.reading_columns)
        check(f"{run.label}: no undeclared column varies within a run",
              not stray, stray)
