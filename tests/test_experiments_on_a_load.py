"""The IV sweep, driven end to end on an electronic load.

`test_experiments_on_every_driver.py` runs every daily-use experiment on
every registered driver - and it iterates `KNOWN_SMUS`, so until this
file existed **no experiment had ever run on a load at all**. The
driver's own tests prove it sends the right strings to a fake; the
checkup proves the instrument agrees. Neither goes near `_prepare()`,
the sweep loop, the commit, or the form that feeds them.

That gap produced a real refusal at the bench, on a legal run: a voltage
sweep to 0.7 V with the current range set to 30 A was rejected with
"Requested current 30 A is positive, which in this suite's convention
means current flowing *out* of the instrument". The polarity rule was
being applied to the compliance dropdown - a bound on magnitude that was
never a request for +30 A. One run through this file would have caught
it before the instrument was ever plugged in.

The forms here are the runs a load can actually do, which is a
different list from the SMU one:

  * **no sweep through zero.** The SMU file sweeps -1 V to +1 V and
    -100 uA to +100 uA precisely because crossing zero is where source
    levels get interesting. A load cannot enter the half of either span
    below zero, and refusing to is correct behaviour rather than a
    failure - so that case is asserted as a refusal, not run as a sweep.
  * **the sweep starts above the headroom floor.** 0.45 V on this
    model at 10 A, where 0.431 V is measured.
"""
import sys
import tkinter as tk
import traceback

import pytest
from test_72_13200 import LoadTransport

import smuniversal_lab_suite.experiments.iv_sweep.experiment as iv
from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.ownership import InstrumentOwnership
from smuniversal_lab_suite.core.run_control import Outcome
from smuniversal_lab_suite.drivers.multicomp_72_13200 import (
    MulticompPro7213200,
)

pytestmark = [pytest.mark.slow, pytest.mark.gui]


class DialogLog:
    """Writes down every dialog rather than showing it.

    A run that raises one has told the operator something went wrong,
    which is a finding here and not a prompt to answer.
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


def load_transport():
    """A 72-13200 with a source across its terminals.

    5 V and 0.2 A sinking, which is what the bench supply was set to
    when this driver was commissioned. The numbers matter only in that
    they are not zero: a fake reading zero would let a sweep "succeed"
    against a driver returning nothing.
    """
    return LoadTransport(volts=5.0, amps=0.2,
                         current_ceiling=30.0, voltage_ceiling=120.0)


def _iv(mode, start, stop, points, compliance):
    def setup(exp):
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


#: The runs a load can do. A solar CV sweep starts above the headroom
#: floor and climbs toward Voc; the current form is the mirror image,
#: with levels negative because in this suite a sink is negative.
RUNS = {
    "IV voltage sweep 0.45 V to 0.8 V, 30 A range":
        _iv("voltage", "0.45", "0.8", "15", "30"),
    "IV voltage sweep 0.45 V to 0.8 V, 3 A range":
        _iv("voltage", "0.45", "0.8", "15", "3"),
    "IV current sweep 0 to -2 A":
        _iv("current", "0", "-2", "11", "18"),
}

#: Forms a load must refuse, and the reason each one is impossible.
REFUSED = {
    "a sweep through zero into reverse bias":
        (_iv("voltage", "-0.2", "0.8", "21", "30"),
         "cannot reverse its terminals"),
    "a current sweep asking it to source":
        (_iv("current", "0", "2", "11", "18"),
         "means current flowing *out* of the instrument"),
}


def run_on(run):
    """One run, on the load, through the path the Run button takes."""
    experiment_cls, setup, begin = run
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, experiment_cls, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    try:
        app.connect_role_manual("source", load_transport(), "fake",
                                MulticompPro7213200)
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
        }
    finally:
        try:
            app.shutdown()
        except Exception:
            pass
        root.destroy()


@pytest.mark.parametrize("name", sorted(RUNS))
def test_the_iv_sweep_runs_on_a_load(name, check):
    """A run a load can do completes and records its data.

    Deliberately narrow, exactly as the SMU version is: an ordinary run
    finishes, keeps its rows, and raises no dialog. The fake is not an
    instrument and the physics is not being checked.
    """
    got = run_on(RUNS[name])
    check(f"{name}: not refused by the form or the gate",
          got["refused"] is None, got["refused"])
    check(f"{name}: nothing raised", got["raised"] is None, got["raised"])
    check(f"{name}: completed", got["outcome"] is Outcome.COMPLETED,
          f"{got['outcome']}")
    check(f"{name}: kept its data", got["rows"] >= 1, f"{got['rows']} rows")
    check(f"{name}: no dialog", not got["dialogs"], got["dialogs"])


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_a_load_refuses_the_runs_it_cannot_do(name, check):
    """Refusing is the correct behaviour, and it has to happen at the
    gate rather than mid-sweep.

    Both of these are legal forms on every SMU in the fleet. On a load
    they ask for a region the instrument physically cannot enter, and
    the failure mode without the gate is not an error - it is a curve
    with readings in it from somewhere the instrument never went.
    """
    run, expected = REFUSED[name]
    got = run_on(run)
    check(f"{name}: refused", got["refused"] is not None,
          "it was accepted, and the sweep would have recorded readings "
          "from a region the instrument cannot reach")
    check(f"{name}: and said why", expected in (got["refused"] or ""),
          got["refused"])
    check(f"{name}: nothing was recorded", got["rows"] == 0,
          f"{got['rows']} rows")


def test_the_compliance_dropdown_is_not_polarity_checked(check):
    """The bug this file was written after.

    A voltage sweep to 0.7 V with the current range at 30 A was refused
    with "Requested current 30 A is positive". The dropdown value is a
    bound on the magnitude the measured quantity will reach - it was
    never a request to source +30 A - and applying the one-quadrant
    polarity rule to it rejected a run the instrument can do perfectly
    well.

    Pinned at the widest range on purpose: 30 A is the value that
    triggered it, and it is also the one a 10 A cell needs.
    """
    got = run_on(_iv("voltage", "0.45", "0.7", "11", "30"))
    check("the run was not refused", got["refused"] is None,
          got["refused"])
    check("and it completed", got["outcome"] is Outcome.COMPLETED,
          f"{got['outcome']}")


def test_the_run_records_that_there_was_no_compliance(check):
    """`None` in metadata reads as "not recorded". A run with no ceiling
    has to say so, because that is a fact about the measurement."""
    got = run_on(RUNS["IV voltage sweep 0.45 V to 0.8 V, 3 A range"])
    applied = [run.metadata.get("compliance_applied")
               for run in got["runs"]]
    check("a run was recorded", applied, "no runs in the store")
    check("with a written reason rather than None",
          any(isinstance(a, str) and "no compliance" in a for a in applied),
          f"{applied}")
    check("naming the instrument",
          any(isinstance(a, str) and "Multicomp" in a for a in applied),
          f"{applied}")
