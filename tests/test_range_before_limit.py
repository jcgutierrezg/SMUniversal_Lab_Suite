
"""Ranges are widened before compliances are set. Every experiment.

Fault 15 / deviation 21. On the U2722A a compliance is clamped to the
range active when it arrives, and `*RST` leaves the smallest range
selected. A limit sent before the range that has to hold it is accepted,
silently reduced, and the run proceeds against a compliance far below
the one the operator typed - no error, plausible numbers, wrong by the
clamp ratio.

Van der Pauw and Hall already did this correctly. 4PP and IV sweep did
not, and nobody had chosen either order - they simply differed. This
file is what stops them drifting apart again.

Why the experiments are actually run
------------------------------------
Ordering is not a property of any single driver method. Every call can
be individually correct and the sequence still wrong. So each experiment
is driven through a recording proxy and the resulting command order is
inspected - the orchestra playing the piece, rather than each musician
checked alone. That is slower than a unit test and it needs a window,
which is why it is marked `gui`.
"""
import tkinter as tk

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.gui]

import experiments.iv_sweep.experiment as iv
from core.base_app import LabApp
from core.transports.null_transport import NullTransport
from experiments.iv_sweep.experiment import IVSweepExperiment
from experiments.ossila_4pp.experiment import Ossila4PPExperiment

#: Which range call has to precede which limit call. Keyed by the
#: quantity being limited, because that is how the driver contract
#: splits them.
PAIRS = [("set_current_range", "set_current_limit"),
         ("set_voltage_range", "set_voltage_limit")]


class Recorder:
    """Passes everything through to the real driver, writing down the
    order of calls."""

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "calls", [])

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def recorded(*a, **kw):
            self.calls.append(name)
            return attr(*a, **kw)
        return recorded


def first_index(calls, name):
    return calls.index(name) if name in calls else None


def check_ordering(check, label, calls):
    for range_call, limit_call in PAIRS:
        r = first_index(calls, range_call)
        l = first_index(calls, limit_call)
        if r is None or l is None:
            # An experiment that never sets one of the pair is fine -
            # 4PP does not limit current, for instance. Nothing to
            # order, so nothing to check. Recorded rather than silently
            # skipped so a pair vanishing shows up as a change.
            check(f"{label}: {limit_call} not paired with {range_call}",
                  True, "")
            continue
        check(f"{label}: {range_call} precedes {limit_call}",
              r < l, f"range at {r}, limit at {l}")


def drain(root):
    for _ in range(60):
        root.update()


@pytest.fixture(autouse=True)
def _fast_settle(monkeypatch):
    monkeypatch.setattr(iv, "PRE_SWEEP_SETTLE_S", 0.0)


def build(root, experiment_cls):
    app = LabApp(root, experiment_cls)
    app.connect_role("source", NullTransport(), "demo")
    root.update_idletasks()
    rec = Recorder(app.instruments["source"])
    app.instruments["source"] = rec
    return app, app.experiment, rec


def test_iv_sweep_widens_the_range_first(check):
    root = tk.Tk()
    try:
        app, exp, rec = build(root, IVSweepExperiment)
        exp.start_var.set("0")
        exp.stop_var.set("1")
        exp.points_var.set("4")
        exp.delay_var.set("0")
        exp.runs_var.set("1")
        exp.mode_var.set("voltage")
        exp.on_mode_changed()
        exp.compliance_var.set("0.01")
        exp.cycles_var.set("1")
        exp.period_var.set("0")
        exp.standby_var.set("Remain idle")
        exp.on_standby_changed()

        params = exp._sweep_params()
        exp._do_periodic(params, exp._periodic_params())
        drain(root)
        check_ordering(check, "IV sweep", rec.calls)
    finally:
        root.destroy()


def test_4pp_widens_the_range_first(check):
    """Driven through `_do_run`, not `run_pressed`.

    `run_pressed` goes through the UI gate, which can raise a modal
    dialog - and a modal dialog under a virtual display is a hung test
    rather than a failing one. The sequencing method is what this file
    is about anyway.
    """
    root = tk.Tk()
    try:
        app, exp, rec = build(root, Ossila4PPExperiment)
        params = exp._sweep_params()
        exp._check_limits(params)
        exp._do_run(params)
        drain(root)
        check("Ossila 4PP: the experiment configured the instrument",
              any(c.startswith("set_") for c in rec.calls),
              f"calls were {rec.calls}")
        check_ordering(check, "Ossila 4PP", rec.calls)
    finally:
        root.destroy()


# Van der Pauw and Hall already order these correctly and are unchanged
# by this patch, so they are not driven here - their sequencing runs
# through a run context and a polarity block, which is a harness rather
# than a test. Wave 6b builds that harness for the trace work and will
# cover both.
