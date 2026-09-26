"""Every daily-use experiment, run offline on every real driver.

The experiment checkup. `tools/smu_checkup.py` asks whether a driver is
right about its instrument, and `test_checkup_all_drivers.py` runs it on
every driver; neither runs an experiment. The experiment tests run the
real experiments, but on the DummySMU, which declares no floor, no range
ladder and no dialect. So nothing ran an IV sweep on a 2401 until one
was tried by hand, and the first one tried - a current sweep through
zero in 201 points - stopped at its midpoint.

This closes that gap without an instrument: each experiment is driven
through the same path the Run button takes (`app.guard_run` around the
experiment's own run method, after the same parameter snapshot and
limit check), on each registered driver connected the way the app
connects one, over that driver's own fake transport - the fakes the
per-driver tests already use, which speak each instrument's dialect.

What it asserts is deliberately narrow: an ordinary run **completes and
records its data, with no dialog raised**. It does not check the
physics - the fakes are not instruments - and it does not repeat the
lifecycle tests' cancellation and threading matrices, which are about
the experiment rather than the driver.

The forms are the runs people actually do: sweeps through zero in both
modes, a 4PP list and a 4PP triangle, one VdP and one Hall position,
and a short fixed-source trace.
"""
import sys
import tkinter as tk
import traceback

import pytest
from test_checkup_all_drivers import CASES

import smuniversal_lab_suite.experiments.iv_sweep.experiment as iv
from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.ownership import InstrumentOwnership
from smuniversal_lab_suite.core.run_control import Outcome
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

pytestmark = [pytest.mark.slow, pytest.mark.gui]


class DialogLog:
    """Stands on every dialog seam and writes down what would have shown.

    A run that raises a dialog has told the operator something went
    wrong, which is a finding here, not a prompt to answer. Questions
    are answered yes so a run is not stopped by a confirmation it would
    get past at the bench.
    """

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def dialog(title="", message="", **_kwargs):
            self.calls.append((name, title, message))
            return True if name.startswith("ask") else None
        dialog.__name__ = name
        return dialog

    def raised(self):
        return [c for c in self.calls if not c[0].startswith("ask")]


#: Module-level so the conftest guard can see which test file owns it.
DIALOGS = DialogLog()


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    DIALOGS.calls.clear()
    for name, module in list(sys.modules.items()):
        if (name.startswith(("smuniversal_lab_suite.core.", "smuniversal_lab_suite.experiments.")) and module is not None
                and hasattr(module, "messagebox")):
            monkeypatch.setattr(module, "messagebox", DIALOGS)
    # The 2 s settle before a sweep is real at the bench and only time
    # here. Patched by name, which is why it is a module constant.
    monkeypatch.setattr(iv, "PRE_SWEEP_SETTLE_S", 0.0)


# ---------------------------------------------------------------
# the runs people do
# ---------------------------------------------------------------
def _iv(mode, start, stop, points, compliance):
    def setup(exp):
        # Mode first: changing it resets the fields that carry units.
        exp.mode_var.set(mode)
        exp.on_mode_changed()
        exp.start_var.set(start)
        exp.stop_var.set(stop)
        exp.points_var.set(points)
        exp.delay_var.set("0")
        exp.runs_var.set("1")
        exp.compliance_var.set(compliance)
        exp.standby_var.set("Remain idle")
        exp.on_standby_changed()

    def begin(exp):
        params = exp._sweep_params()
        exp._check_limits(params)
        return lambda: exp._do_single(params)
    return iv.IVSweepExperiment, setup, begin


def _vdp():
    def setup(exp):
        exp.sample_name_var.set("wafer_A")
        exp.thickness_entry_var.set("180 um")
        exp.pos_var.set("A")
        exp.points_var.set("6")
        exp.start_var.set("-100 µA")
        exp.stop_var.set("100 µA")
        exp.delay_ms_var.set("0")

    def begin(exp):
        params = exp._run_params()
        return lambda: exp._do_run(params)
    return VanDerPauwExperiment, setup, begin


def _hall():
    def setup(exp):
        exp.sample_name_var.set("wafer_A")
        exp.thickness_entry_var.set("1.5 um")
        exp.pos_var.set("C")
        exp.field_sign_var.set("+")
        exp.points_var.set("6")
        exp.start_var.set("-100 µA")
        exp.stop_var.set("100 µA")
        exp.delay_ms_var.set("0")

    def begin(exp):
        params = exp._run_params()
        return lambda: exp._do_run(params)
    return HallExperiment, setup, begin


def _fourpp(mode):
    def setup(exp):
        exp.sample_name_var.set("film_A")
        exp.dataset_var.set(mode)
        exp.reversals_var.set("2")
        exp.delay_var.set("0")
        exp.width_var.set("10")
        exp.length_var.set("27")
        exp.thickness_var.set("180")
        exp.sweep_mode_var.set(mode)
        exp.on_sweep_mode_changed()
        if mode == "list":
            for index, var in enumerate(exp.current_vars):
                var.set(f"{(index + 1) * 1e-4:g}" if index < 4 else "")
        else:
            exp.tri_start_var.set("-1e-4")
            exp.tri_stop_var.set("1e-4")
            # The form allows up to 30. 27 is the largest odd count whose
            # zero point computes to a residue over this span.
            exp.tri_points_var.set("27")

    def begin(exp):
        params = exp._sweep_params()
        exp._check_limits(params)
        return lambda: exp._do_run(params)
    return Ossila4PPExperiment, setup, begin


def _fixed_source():
    def setup(exp):
        exp.sample_name_var.set("film_A")
        exp.mode_var.set("voltage")
        exp.on_mode_changed()
        exp.level_var.set("0.1")
        exp.compliance_var.set("0.01")
        exp.duration_var.set("0.3")
        exp.interval_var.set("0.1")
        exp.dataset_var.set("trace")
        exp.watch_compliance_var.set(False)

    def begin(exp):
        exp._watch_compliance = False
        params = exp._params()
        exp._check_limits(params)
        return lambda: exp._do_run(params)
    return FixedSourceExperiment, setup, begin


RUNS = {
    "IV voltage sweep -1 V to +1 V": _iv("voltage", "-1", "1", "21", "0.01"),
    "IV current sweep -100 uA to +100 uA, 201 points":
        _iv("current", "-1e-4", "1e-4", "201", "2"),
    "Van der Pauw, one position": _vdp(),
    "Hall, one position": _hall(),
    "4PP current list": _fourpp("list"),
    "4PP triangle through zero": _fourpp("triangular"),
    "fixed source, short trace": _fixed_source(),
}


def run_on(driver_case, run):
    """One run, one driver. Returns what happened."""
    name, driver_cls, transport_factory = driver_case
    experiment_cls, setup, begin = run
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, experiment_cls, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    try:
        app.connect_role_manual("source", transport_factory(), "fake",
                                driver_cls)
        root.update()
        exp = app.experiment
        setup(exp)
        root.update()
        refused = raised = None
        try:
            go = begin(exp)
        except Exception as exc:          # the form or limits refused it
            refused = f"{type(exc).__name__}: {exc}"
        else:
            try:
                app.guard_run(go)()
            except Exception as exc:
                # At the bench this reaches only the console, from the
                # worker thread's wrapper. Here it is a finding, with
                # the frame it came from.
                where = traceback.extract_tb(exc.__traceback__)[-1]
                raised = (f"{type(exc).__name__}: {exc} "
                          f"[{where.filename.rsplit(chr(92), 1)[-1]}:"
                          f"{where.lineno} {where.name}]")
        app.drain_ui_now()
        for _ in range(30):
            root.update()
        app.drain_ui_now()
        status = exp.run_controller.last_status
        return {
            "refused": refused,
            "raised": raised,
            "outcome": getattr(status, "outcome", None),
            "detail": getattr(status, "detail", ""),
            "rows": len(exp.tree.get_children()),
            # Less the compliance warning. Several fakes model a real
            # sample, and the 2635B's sits at its compliance for these
            # levels, so the warning there is the software being right.
            # Its wiring is tested in `test_clamp_and_progress_gui.py`.
            "dialogs": [d for d in DIALOGS.raised()
                        if d[1] != "Compliance limit reached"],
        }
    finally:
        app.on_close()
        try:
            root.destroy()
        except tk.TclError:
            pass              # on_close() destroys the root itself


def _verdict(result):
    if result["refused"]:
        return f"refused before running - {result['refused']}"
    problems = []
    if result["raised"]:
        problems.append(f"raised {result['raised']}")
    if result["outcome"] is not Outcome.COMPLETED:
        problems.append(f"outcome {result['outcome']}: {result['detail']}")
    if not result["rows"]:
        problems.append("no row recorded")
    if result["dialogs"]:
        problems.append("dialogs: " + "; ".join(
            f"{kind} {title!r}: {message[:160]}"
            for kind, title, message in result["dialogs"]))
    return " | ".join(problems)


#: Runs that do not complete on a driver by design, with the reason.
#: Checked in both directions: if one of these ever completes, the
#: behaviour it records has changed and the entry has to be revisited.
EXPECTED = {
    ("KeysightU2722A", "4PP triangle through zero"): (
        "one knob per quantity with no autorange: the plan's AUTO takes "
        "R120mA, and a triangle's levels near zero are below its 73 uA "
        "floor. Decided - the driver warns when it takes the widest range, "
        "and the remedy is another instrument or explicit ranges. See "
        "docs/instruments/keysight-u2722a.md."),
    # The same floor, since Van der Pauw and Hall became sweeps through
    # zero: their levels near zero are below it too. A two-point sweep -
    # the old +I and -I - still runs there.
    ("KeysightU2722A", "Van der Pauw, one position"): (
        "a sweep through zero has levels below R120mA's 73 uA floor. "
        "Decided, as for the 4PP triangle; two points, -I and +I, is the "
        "form that runs on this instrument."),
    ("KeysightU2722A", "Hall, one position"): (
        "a sweep through zero has levels below R120mA's 73 uA floor. "
        "Decided, as for the 4PP triangle; two points, -I and +I, is the "
        "form that runs on this instrument."),
}


@pytest.mark.parametrize("run_name", list(RUNS))
def test_every_daily_run_completes_on_every_driver(check, run_name):
    for case in CASES:
        DIALOGS.calls.clear()
        verdict = _verdict(run_on(case, RUNS[run_name]))
        expected = EXPECTED.get((case[0], run_name))
        if expected:
            check(f"{case[0]}: {run_name} - still does not complete, as "
                  f"recorded; if it does, revisit EXPECTED",
                  bool(verdict), expected)
            continue
        check(f"{case[0]}: {run_name}", not verdict, verdict)


def test_every_expected_exception_names_a_real_case():
    """An entry for a driver or run that no longer exists is dead weight
    that reads as coverage."""
    drivers = {name for name, _, _ in CASES}
    for driver, run in EXPECTED:
        assert driver in drivers, driver
        assert run in RUNS, run
