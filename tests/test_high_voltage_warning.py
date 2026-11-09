"""The warning before a run puts a dangerous voltage on the terminals.

Decided 2026-10-15: the Keithley 487 is used without its interlock, runs
up to 505 V are allowed, and starting one above 50 V takes a deliberate
act - a ticked box and a button naming the voltage - never one Enter.
"""
import sys
import tkinter as tk

import pytest
from test_experiments_on_a_487 import close, connected

from smuniversal_lab_suite.core.gui import high_voltage
from smuniversal_lab_suite.core.gui.high_voltage import HighVoltageDialog
from smuniversal_lab_suite.drivers.base_instrument import BaseInstrument
from smuniversal_lab_suite.drivers.keithley_487 import Keithley487
from smuniversal_lab_suite.drivers.registry import (
    KNOWN_LOADS,
    KNOWN_SMUS,
    KNOWN_SUPPLIES,
)
from smuniversal_lab_suite.experiments.fixed_source.experiment import (
    FixedSourceExperiment,
)
from smuniversal_lab_suite.experiments.iv_sweep.experiment import (
    IVSweepExperiment,
)

pytestmark = [pytest.mark.gui]


#: Every real SMU that can exceed 50 V. The simulated one is left out -
#: there is nothing behind it - and so are the load, which only sinks,
#: and the supplies, which stop at 35 V.
HAZARDOUS = {"Keithley487", "Keithley2450", "Keithley2611A",
             "Keithley2635B", "GWInstekGSM20H10", "KeysightB2901A"}


def test_every_smu_above_50_v_declares_a_hazard(check):
    check("none by default", BaseInstrument.hazardous_above_v() is None)
    for cls in (*KNOWN_SMUS, *KNOWN_LOADS, *KNOWN_SUPPLIES):
        expected = 50.0 if cls.__name__ in HAZARDOUS else None
        check(f"{cls.__name__}", cls.hazardous_above_v() == expected,
              f"{cls.hazardous_above_v()}")
    for cls in KNOWN_SMUS:
        if cls.__name__ == "DummySMU":
            continue
        check(f"{cls.__name__} is listed if it can exceed 50 V",
              (cls.LIMITS.max_voltage > 50) == (cls.__name__ in HAZARDOUS),
              f"{cls.LIMITS.max_voltage} V")


def test_the_dialog_will_not_apply_until_the_box_is_ticked(check):
    root = tk.Tk()
    root.withdraw()
    try:
        dialog = HighVoltageDialog(root, "Keithley 487", 200.0, 50.0)
        check("Apply starts disabled",
              str(dialog.apply_btn.cget("state")) == "disabled")
        check("and names the voltage",
              dialog.apply_btn.cget("text") == "Apply 200 V")
        check("Cancel has the focus",
              dialog.window.focus_get() in (dialog.cancel_btn, None))
        dialog.apply()
        check("pressing it unticked does nothing", dialog.result is False
              and dialog.window.winfo_exists())
        dialog.checked.set(True)
        dialog._sync()
        check("ticking enables it",
              str(dialog.apply_btn.cget("state")) == "normal")
        dialog.apply()
        check("and applying says yes", dialog.result is True)
        check("and closes it", not dialog.window.winfo_exists())

        for how in ("cancel", "escape", "close"):
            dialog = HighVoltageDialog(root, "Keithley 487", 200.0, 50.0)
            dialog.checked.set(True)
            dialog._sync()
            if how == "cancel":
                dialog.cancel()
            elif how == "escape":
                dialog.window.event_generate("<Escape>")
                root.update()
            else:
                # What the window manager runs when the X is pressed.
                dialog.window.tk.call(
                    dialog.window.protocol("WM_DELETE_WINDOW"))
            check(f"{how} is a no, even ticked", dialog.result is False)
    finally:
        root.destroy()


@pytest.fixture
def asked(monkeypatch):
    """Stands in for the dialog: records each question, answers it."""
    record = {"calls": [], "answer": False}

    def ask(parent, instrument, volts, threshold):
        record["calls"].append((instrument, volts, threshold))
        return record["answer"]

    monkeypatch.setattr(high_voltage, "confirm_high_voltage", ask)
    return record


def started(app, monkeypatch):
    runs = []
    monkeypatch.setattr(app, "run_in_background",
                        lambda task: runs.append(task))
    return runs


def fixed_source_at(level):
    def setup(exp):
        exp.level_var.set(str(level))
        exp.compliance_var.set("2.5e-05")
        exp.duration_var.set("1")
        exp.interval_var.set("0.5")
    return setup


@pytest.mark.parametrize("level, asks", [(10, False), (50, False),
                                         (-200, True), (500, True)])
def test_fixed_source_asks_above_50_v(check, monkeypatch, asked, level,
                                      asks):
    root, app, exp = connected(FixedSourceExperiment)
    try:
        runs = started(app, monkeypatch)
        fixed_source_at(level)(exp)
        asked["answer"] = False
        exp.run_pressed()
        check("asked" if asks else "not asked",
              bool(asked["calls"]) == asks, f"{asked['calls']}")
        if asks:
            check("with the voltage and the threshold",
                  asked["calls"][0] == ("Keithley 487", abs(level), 50.0),
                  f"{asked['calls']}")
            check("declined: nothing started", not runs)
            asked["answer"] = True
            exp.run_pressed()
            check("accepted: started", len(runs) == 1)
        else:
            check("started without a question", len(runs) == 1)
    finally:
        close(root, app)


def test_iv_sweep_asks_for_the_highest_end(check, monkeypatch, asked):
    root, app, exp = connected(IVSweepExperiment)
    try:
        runs = started(app, monkeypatch)
        exp.start_var.set("-1")
        exp.stop_var.set("120")
        exp.points_var.set("5")
        exp.compliance_var.set("2.5e-05")
        exp.run_pressed()
        check("asked about 120 V",
              [c[1] for c in asked["calls"]] == [120.0],
              f"{asked['calls']}")
        check("declined: nothing started", not runs)
    finally:
        close(root, app)


def test_a_periodic_bias_counts_too(check, monkeypatch, asked):
    """A sweep that stays low around a high standby bias still puts the
    bias on the terminals."""
    root, app, exp = connected(IVSweepExperiment)
    try:
        started(app, monkeypatch)
        exp.start_var.set("-1")
        exp.stop_var.set("1")
        exp.points_var.set("5")
        exp.compliance_var.set("2.5e-05")
        exp.standby_var.set("Bias voltage")
        exp.bias_var.set("300")
        exp.cycles_var.set("1")
        exp.period_var.set("0")
        exp.run_periodic_pressed()
        check("asked about the 300 V bias",
              [c[1] for c in asked["calls"]] == [300.0],
              f"{asked['calls']}")
    finally:
        close(root, app)


def test_an_instrument_that_declares_nothing_is_never_asked(
        check, monkeypatch, asked):
    monkeypatch.setattr(Keithley487, "HAZARDOUS_ABOVE_V", None)
    root, app, exp = connected(FixedSourceExperiment)
    try:
        runs = started(app, monkeypatch)
        fixed_source_at(500)(exp)
        exp.run_pressed()
        check("no question", not asked["calls"])
        check("started", len(runs) == 1)
    finally:
        close(root, app)


def test_the_dialog_says_to_stay_clear_of_the_sample_and_probes(check):
    root = tk.Tk()
    root.withdraw()
    try:
        dialog = HighVoltageDialog(root, "Keithley 487", 200.0, 50.0)
        texts = []

        def walk(widget):
            try:
                texts.append(str(widget.cget("text")))
            except tk.TclError:
                pass
            for child in widget.winfo_children():
                walk(child)

        walk(dialog.window)
        shown = " ".join(texts)
        check("its own line", high_voltage.STAY_CLEAR in texts, shown)
        check("the probes named in what is ticked",
              any("probes" in t and "I have made" in t for t in texts),
              shown)
        dialog.cancel()
    finally:
        root.destroy()


def test_an_accepted_run_says_it_again_on_the_console(check, monkeypatch,
                                                      asked):
    root, app, exp = connected(FixedSourceExperiment)
    try:
        started(app, monkeypatch)
        lines = []
        monkeypatch.setattr(app, "log", lambda *parts: lines.append(
            " ".join(str(p) for p in parts)))
        fixed_source_at(200)(exp)
        asked["answer"] = True
        exp.run_pressed()
        check("on the console for the run",
              any("HIGH VOLTAGE" in line and "stay clear" in line
                  for line in lines), f"{lines}")
    finally:
        close(root, app)


def _window(experiment_cls, monkeypatch):
    """A window on the simulated SMU, made to declare the hazard, with
    the switch-box question answered yes."""
    import smuniversal_lab_suite.experiments.base_experiment as base
    from smuniversal_lab_suite.core.base_app import LabApp
    from smuniversal_lab_suite.core.identity import SampleRegistry
    from smuniversal_lab_suite.core.ownership import InstrumentOwnership
    from smuniversal_lab_suite.core.transports.null_transport import (
        NullTransport,
    )
    from smuniversal_lab_suite.drivers.dummy_smu import DummySMU

    monkeypatch.setattr(DummySMU, "HAZARDOUS_ABOVE_V", 50.0)
    module = sys.modules[experiment_cls.__module__]
    for target in (module, base):
        if hasattr(target, "messagebox"):
            monkeypatch.setattr(target.messagebox, "askokcancel",
                                lambda *a, **k: True)
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, experiment_cls, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    app.connect_role("source", NullTransport(), "<simulated sample>")
    root.update()
    return root, app, app.experiment


@pytest.mark.parametrize("compliance, asks", [("10", False),
                                              ("150", True)])
def test_van_der_pauw_asks_about_its_compliance(check, monkeypatch, asked,
                                                compliance, asks):
    from smuniversal_lab_suite.experiments.vanderpauw.experiment import (
        VanDerPauwExperiment,
    )
    root, app, exp = _window(VanDerPauwExperiment, monkeypatch)
    try:
        runs = started(app, monkeypatch)
        exp.sample_name_var.set("wafer_A")
        exp.thickness_entry_var.set("180 um")
        exp.vlim_var.set(compliance)
        exp.run_pressed()
        check("asked" if asks else "not asked",
              bool(asked["calls"]) == asks, f"{asked['calls']}")
        if asks:
            check("about the compliance",
                  asked["calls"][0][1] == 150.0, f"{asked['calls']}")
            check("declined: nothing started", not runs)
        else:
            check("started", len(runs) == 1)
    finally:
        close(root, app)


def test_4pp_asks_about_its_compliance(check, monkeypatch, asked):
    from smuniversal_lab_suite.experiments.ossila_4pp.experiment import (
        Ossila4PPExperiment,
    )
    root, app, exp = _window(Ossila4PPExperiment, monkeypatch)
    try:
        runs = started(app, monkeypatch)
        exp.sample_name_var.set("film_A")
        exp.width_var.set("10")
        exp.length_var.set("27")
        exp.thickness_var.set("180")
        exp.compliance_var.set("120")
        exp.run_pressed()
        check("asked about 120 V",
              [c[1] for c in asked["calls"]] == [120.0], f"{asked['calls']}")
        check("declined: nothing started", not runs)
    finally:
        close(root, app)
