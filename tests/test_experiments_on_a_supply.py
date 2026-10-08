"""A power supply at the connection panel, and in the one window that
has invited it.

The driver's own tests prove it sends the right strings, and the
checkup's prove the checkup can fail. Neither goes near the app shell -
and the rule this file is about lives there: **a supply is identified
by every window and accepted by one.**

It has to be tested end to end because the failure is invisible from
the driver. A supply sources and has a compliance, so on capabilities
alone Van der Pauw would take it, configure it, and ask a converter
whose smallest step is 10 mA for 100 uA. Nothing would raise.
"""
import sys
import tkinter as tk
import traceback

import pytest
from test_tsx_p import SupplyTransport

from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.ownership import InstrumentOwnership
from smuniversal_lab_suite.core.run_control import Outcome
from smuniversal_lab_suite.drivers.aimtti_tsx_p import (
    AimTTiTSX1820P,
    AimTTiTSX3510P,
)
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

pytestmark = [pytest.mark.slow, pytest.mark.gui]

#: Every experiment that has not invited a supply. Listed rather than
#: derived, so adding a window means deciding which side it is on.
UNINVITED = (IVSweepExperiment, VanDerPauwExperiment, HallExperiment,
             Ossila4PPExperiment)


class DialogLog:
    """Writes down every dialog rather than showing it."""

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


DIALOGS = DialogLog()


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    DIALOGS.calls.clear()
    for name, module in list(sys.modules.items()):
        if (name.startswith(("smuniversal_lab_suite.core.",
                             "smuniversal_lab_suite.experiments."))
                and module is not None and hasattr(module, "messagebox")):
            monkeypatch.setattr(module, "messagebox", DIALOGS)


def _app(experiment_cls):
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, experiment_cls, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    return root, app


def _close(root, app):
    try:
        app.shutdown()
    except Exception:
        pass
    root.destroy()


def _try_connect(experiment_cls, driver_cls=AimTTiTSX3510P, auto=False):
    """Connect a supply to one experiment. Returns the refusal, or None.

    `auto` goes through `*IDN?` the way the Connect button does; the
    default picks the driver by hand, which is the fallback path and
    must be gated just the same.
    """
    root, app = _app(experiment_cls)
    transport = SupplyTransport(model=driver_cls.MODEL_IDS[0])
    try:
        try:
            if auto:
                driver = app.connect_role("source", transport, "fake")
            else:
                driver = app.connect_role_manual("source", transport,
                                                 "fake", driver_cls)
            return None, transport, type(driver)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}", transport, None
    finally:
        _close(root, app)


# ---------------------------------------------------------------
# Refused at Connect
# ---------------------------------------------------------------


@pytest.mark.parametrize("experiment", UNINVITED,
                         ids=lambda e: e.__name__)
@pytest.mark.parametrize("auto", (True, False), ids=("by-idn", "by-hand"))
def test_an_uninvited_window_refuses_a_supply_at_connect(experiment, auto,
                                                         check):
    refused, transport, _ = _try_connect(experiment, auto=auto)
    name = experiment.__name__
    check(f"{name}: refused", refused is not None,
          "it connected, and would have been driven far below its "
          "resolution")
    check(f"{name}: as unsuitable, not as unrecognised",
          (refused or "").startswith("InstrumentUnsuitable"), refused)
    check(f"{name}: names the instrument",
          "Aim-TTi TSX3510P" in (refused or ""), refused)
    check(f"{name}: and says why in the instrument's own words",
          "not a source-measure unit" in (refused or ""), refused)
    check(f"{name}: the port was closed again", not transport.connected,
          "a refused connection left the port open")
    check(f"{name}: nothing was configured on it",
          not [s for s in transport.sent if s != "*IDN?"], transport.sent)


def test_the_window_that_invited_it_connects_it(check):
    for driver_cls in (AimTTiTSX3510P, AimTTiTSX1820P):
        refused, transport, got = _try_connect(FixedSourceExperiment,
                                               driver_cls, auto=True)
        name = driver_cls.__name__
        check(f"{name}: connected", refused is None, refused)
        check(f"{name}: identified as itself", got is driver_cls, got)
        check(f"{name}: and reset to known settings",
              transport.sent[:3] == ["*IDN?", "*RST", "*CLS"],
              transport.sent[:6])


def test_the_invitation_is_one_window_wide(check):
    """Guards the list above against a quiet widening - and against
    the opposite, a rule that refuses a supply everywhere."""
    check("Fixed Source accepts the caveat",
          FixedSourceExperiment.ROLE_ACCEPTS
          == {"source": ("power_supply_grade",)},
          f"{FixedSourceExperiment.ROLE_ACCEPTS}")
    for experiment in UNINVITED:
        check(f"{experiment.__name__} accepts none",
              not experiment.ROLE_ACCEPTS, f"{experiment.ROLE_ACCEPTS}")


# ---------------------------------------------------------------
# A run, in the window that invited it
# ---------------------------------------------------------------


def _fixed_source(mode, level, compliance):
    def setup(exp):
        exp.sample_name_var.set("heater_A")
        exp.mode_var.set(mode)
        exp.on_mode_changed()
        exp.level_var.set(level)
        exp.compliance_var.set(compliance)
        exp.duration_var.set("0.3")
        exp.interval_var.set("0.1")
        exp.dataset_var.set("trace")
        exp.watch_compliance_var.set(True)

    def begin(exp):
        exp._watch_compliance = True
        params = exp._params()
        exp._check_limits(params)
        return lambda: exp._do_run(params)
    return setup, begin


def run_on(form, load_ohms=10.0):
    """One Fixed Source run on a supply, through the path Run takes."""
    setup, begin = form
    root, app = _app(FixedSourceExperiment)
    transport = SupplyTransport(load_ohms=load_ohms)
    try:
        app.connect_role_manual("source", transport, "fake", AimTTiTSX3510P)
        root.update()
        exp = app.experiment
        setup(exp)
        root.update()
        refused = raised = None
        try:
            go = begin(exp)
        except Exception as exc:
            refused = f"{type(exc).__name__}: {exc}"
        else:
            try:
                app.guard_run(go)()
            except Exception as exc:
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
            "rows": len(exp.tree.get_children()),
            "dialogs": DIALOGS.raised(),
            "runs": list(exp.run_store.all_runs()),
            "transport": transport,
        }
    finally:
        _close(root, app)


def _settings(wire):
    """The level and compliance writes of the run, in order, after the
    reset that connecting sends."""
    sent = wire.sent[wire.sent.index("DAMPING 0") + 1:]
    return [s for s in sent if s[:2] in ("I ", "V ")]


def test_a_fixed_voltage_trace_runs_on_a_supply(check):
    """5 V into 10 ohms with a 1 A setting: constant voltage, 0.5 A."""
    got = run_on(_fixed_source("voltage", "5", "1"))
    check("not refused", got["refused"] is None, got["refused"])
    check("nothing raised", got["raised"] is None, got["raised"])
    check("completed", got["outcome"] is Outcome.COMPLETED,
          f"{got['outcome']}")
    check("kept its data", got["rows"] >= 1, f"{got['rows']} rows")
    check("no dialog", not got["dialogs"], got["dialogs"])

    wire = got["transport"]
    check("the compliance went to the current setting, then the level "
          "to the voltage", _settings(wire) == ["I 1", "V 5"],
          wire.writes())
    check("the output was switched off at the end",
          wire.output is False and wire.writes()[-1] == "OP 0",
          wire.writes()[-3:])

    run = got["runs"][0]
    check("the compliance is recorded as applied, not as absent",
          run.metadata.get("compliance_applied") == 1.0,
          f"{run.metadata.get('compliance_applied')!r}")
    check("the ranges say there were none to choose",
          str(run.metadata.get("ranges", "")).startswith("fixed"),
          f"{run.metadata.get('ranges')!r}")
    check("and the sensing is the wiring rule, not a checkbox",
          "links" in str(run.metadata.get("sensing", "")),
          f"{run.metadata.get('sensing')!r}")


def test_a_trace_in_current_limit_says_it_was_clamped(check):
    """5 V into 1 ohm against a 1 A setting. The trace is of the
    ceiling, not the sample, and the file has to say so."""
    got = run_on(_fixed_source("voltage", "5", "1"), load_ohms=1.0)
    check("completed", got["outcome"] is Outcome.COMPLETED,
          f"{got['outcome']} {got['raised']}")
    run = got["runs"][0]
    check("it was watching", run.metadata.get("compliance_watched") == "yes")
    check("and counted the clamped samples",
          (run.metadata.get("compliance_trips") or 0) >= 1,
          f"{run.metadata.get('compliance_trips')!r}")


def test_a_fixed_current_trace_runs_on_a_supply(check):
    """Sourcing current: 0.5 A into 10 ohms under a 12 V ceiling."""
    got = run_on(_fixed_source("current", "0.5", "12"))
    check("not refused", got["refused"] is None, got["refused"])
    check("completed", got["outcome"] is Outcome.COMPLETED,
          f"{got['outcome']} {got['raised']}")
    wire = got["transport"]
    check("the voltage setting is the compliance and the current the "
          "level", _settings(wire) == ["V 12", "I 0.5"], wire.writes())


@pytest.mark.parametrize("name,form,says", [
    ("a negative level",
     ("voltage", "-5", "1"), "cannot reverse its terminals"),
    ("a level above the range",
     ("voltage", "40", "1"), "maximum"),
    ("a compliance below 10 mA",
     ("voltage", "5", "0.001"), "below the smallest current setting"),
    ("a current level below 10 mA",
     ("current", "0.001", "12"), "below the smallest current setting"),
])
def test_what_a_supply_cannot_do_is_refused_before_the_run(name, form,
                                                           says, check):
    """At the gate, as a dialog - not on the worker thread mid-run."""
    got = run_on(_fixed_source(*form))
    check(f"{name}: refused", got["refused"] is not None,
          "accepted, and would have been rejected by the instrument "
          "after the run had started")
    check(f"{name}: and said why", says in (got["refused"] or ""),
          got["refused"])
    check(f"{name}: nothing was recorded", got["rows"] == 0)
    check(f"{name}: the output never came on",
          "OP 1" not in got["transport"].sent)
