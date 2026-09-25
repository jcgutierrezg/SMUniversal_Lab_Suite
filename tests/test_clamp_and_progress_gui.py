"""The compliance warning, the Sample column and the progress bar, on
every experiment, against the dummy instrument.

The dummy models a 1 kΩ sample and clamps at its compliance, so a limit
below what the sample needs produces a genuinely clamped run through the
real run path. Each experiment is run twice: once inside its limit,
where nothing may be said, and once clamped, where exactly one dialog
must name the run and the run must be saved as suspected.

The detector's rules are tested on synthetic data in `test_clamping.py`;
this file is about the wiring.
"""
import pytest

pytestmark = [pytest.mark.gui]

import sys
import tkinter as tk

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


class DialogLog:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(title="", message="", **kwargs):
            self.calls.append((name, title, message or ""))
            return True
        return call

    def warnings(self):
        return [c for c in self.calls
                if c[0] == "showwarning" and c[1] == "Compliance limit reached"]


#: Module-level so the conftest guard can see which test file owns it.
DIALOGS = DialogLog()


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    DIALOGS.calls.clear()
    for name, module in list(sys.modules.items()):
        if (name.startswith(("smuniversal_lab_suite.core.",
                             "smuniversal_lab_suite.experiments."))
                and module is not None and hasattr(module, "messagebox")):
            monkeypatch.setattr(module, "messagebox", DIALOGS)
    monkeypatch.setattr(iv, "PRE_SWEEP_SETTLE_S", 0.0)


# ---------------------------------------------------------------
# one clean and one clamped setup per experiment
# ---------------------------------------------------------------
def _vdp(limit):
    def setup(exp):
        exp.thickness_entry_var.set("180 nm")
        exp.pos_var.set("A")
        exp.points_var.set("6")
        # Up to 0.1 V across 1 kΩ at the ends of the sweep.
        exp.start_var.set("-100 µA")
        exp.stop_var.set("100 µA")
        exp.vlim_var.set(limit)
        exp.delay_ms_var.set("0")
        return exp._run_params()
    return VanDerPauwExperiment, setup, "_do_run"


def _hall(limit):
    def setup(exp):
        exp.thickness_entry_var.set("180 nm")
        exp.pos_var.set("C")
        exp.field_sign_var.set("+")
        exp.points_var.set("6")
        exp.start_var.set("-100 µA")
        exp.stop_var.set("100 µA")
        exp.vlim_var.set(limit)
        exp.delay_ms_var.set("0")
        return exp._run_params()
    return HallExperiment, setup, "_do_run"


def _iv(limit):
    def setup(exp):
        exp.mode_var.set("voltage")
        exp.on_mode_changed()
        exp.start_var.set("-1")                # up to 1 mA across 1 kΩ
        exp.stop_var.set("1")
        exp.points_var.set("21")
        exp.delay_var.set("0")
        exp.runs_var.set("1")
        exp.compliance_var.set(limit)
        exp.standby_var.set("Remain idle")
        exp.on_standby_changed()
        params = exp._sweep_params()
        exp._check_limits(params)
        exp._run_estimate_s = exp._estimate_single(params)
        return params
    return iv.IVSweepExperiment, setup, "_do_single"


def _fourpp(limit):
    def setup(exp):
        exp.dataset_var.set("list")
        exp.reversals_var.set("2")
        exp.delay_var.set("0")
        exp.width_var.set("10")
        exp.length_var.set("27")
        exp.thickness_var.set("180")
        exp.compliance_var.set(limit)
        exp.sweep_mode_var.set("list")
        exp.on_sweep_mode_changed()
        for index, var in enumerate(exp.current_vars):
            var.set(f"{(index + 1) * 1e-4:g}" if index < 4 else "")
        params = exp._sweep_params()
        exp._check_limits(params)
        return params
    return Ossila4PPExperiment, setup, "_do_run"


def _fixed(limit):
    def setup(exp):
        exp.mode_var.set("voltage")
        exp.on_mode_changed()
        exp.level_var.set("0.1")               # 100 µA across 1 kΩ
        exp.compliance_var.set(limit)
        exp.duration_var.set("0.3")
        exp.interval_var.set("0.1")
        exp.dataset_var.set("trace")
        exp.watch_compliance_var.set(False)
        exp._watch_compliance = False
        params = exp._params()
        exp._check_limits(params)
        return params
    return FixedSourceExperiment, setup, "_do_run"


CASES = {
    "Van der Pauw": (_vdp("1"), _vdp("0.05")),
    "Hall": (_hall("1"), _hall("0.05")),
    "IV sweep": (_iv("0.01"), _iv("0.0005")),
    "4PP": (_fourpp("2"), _fourpp("0.05")),
    "Fixed source": (_fixed("0.01"), _fixed("0.00005")),
}


def _run(case, sample="wafer_A"):
    experiment_cls, setup, method = case
    root = tk.Tk()
    app = LabApp(root, experiment_cls, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    app.connect_role("source", NullTransport(), "demo")
    root.update()
    exp = app.experiment
    exp.sample_name_var.set(sample)
    params = setup(exp)
    app.guard_run(lambda: getattr(exp, method)(params))()
    app.drain_ui_now()
    for _ in range(30):
        root.update()
    app.drain_ui_now()
    return root, app, exp


def _close(root, app):
    try:
        app.on_close()
    except Exception:
        pass
    try:
        root.destroy()
    except tk.TclError:
        pass


def _stored(exp):
    return [exp.run_store.get(i) for i in exp.tree.get_children()]


@pytest.mark.parametrize("name", list(CASES))
def test_a_run_inside_its_limit_says_nothing(check, name):
    root, app, exp = _run(CASES[name][0])
    try:
        runs = _stored(exp)
        check("the run was kept", len(runs) >= 1, str(len(runs)))
        check("no compliance warning", not DIALOGS.warnings(),
              str(DIALOGS.calls))
        for record in runs:
            check("recorded as not suspected",
                  record.metadata.get("compliance_suspected") == "no",
                  repr(record.metadata.get("compliance_suspected")))
        first = exp.tree.item(exp.tree.get_children()[0], "values")
        check("the table names the sample", first[0] == "wafer_A",
              str(first))
    finally:
        _close(root, app)


@pytest.mark.parametrize("name", list(CASES))
def test_a_clamped_run_is_kept_flagged_and_warned_about_once(check, name):
    root, app, exp = _run(CASES[name][1])
    try:
        runs = _stored(exp)
        check("the run was kept", len(runs) >= 1, str(len(runs)))
        warnings = DIALOGS.warnings()
        check("exactly one warning", len(warnings) == 1, str(DIALOGS.calls))
        if warnings:
            check("it names the sample", "wafer_A" in warnings[0][2],
                  warnings[0][2])
        for record in runs:
            check("recorded as suspected",
                  record.metadata.get("compliance_suspected") == "yes",
                  repr(record.metadata.get("compliance_suspected")))
    finally:
        _close(root, app)


# ---------------------------------------------------------------
# the progress bar
# ---------------------------------------------------------------
def test_the_bar_shows_time_left_while_a_run_is_live_and_clears_after(check):
    root = tk.Tk()
    app = LabApp(root, VanDerPauwExperiment, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    exp = app.experiment
    try:
        _vdp("1")[1](exp)
        params = exp._run_params()
        with exp.begin_run(parameters=params) as run:
            run.expect(params.readings_n)
            exp._start_progress()
            check("an estimate from the settings",
                  exp._progress_estimate == exp.estimate_run_seconds(params))
            check("time left is shown", exp.eta_var.get().startswith("about"),
                  exp.eta_var.get())
            check("a timer is running", exp._progress_job is not None)

            for n in range(params.readings_n):
                run.add_reading({"point": n + 1})
            exp._tick_progress()
            check("every reading in: finishing",
                  exp.eta_var.get() == "finishing...", exp.eta_var.get())
            check("and the bar is full",
                  float(exp.progress_bar.cget("value")) == 1.0,
                  str(exp.progress_bar.cget("value")))

        exp._end_run()
        check("the timer stops", exp._progress_job is None)
        check("the text clears", exp.eta_var.get() == "", exp.eta_var.get())
        check("the bar empties",
              float(exp.progress_bar.cget("value")) == 0.0)
    finally:
        _close(root, app)
