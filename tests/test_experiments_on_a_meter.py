"""A multimeter at the connection panel: identified by every window,
accepted by none.

The rule lives in the app shell, not the driver, so it is tested end to
end. IV sweep and Fixed Source state no `ROLE_REQUIRES` - an electronic
load has to pass them - so without the meter's caveat both would take
it, reset it, and fail at Run asking it for a level. Nothing would have
said so at Connect.
"""
import sys
import tkinter as tk

import pytest
from test_34401a import MeterTransport

from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.ownership import InstrumentOwnership
from smuniversal_lab_suite.drivers.keysight_34401a import Keysight34401A
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

#: Every experiment. Listed rather than derived, so a new window means
#: deciding, here, whether it has a role a meter can fill.
EVERY_EXPERIMENT = (IVSweepExperiment, FixedSourceExperiment,
                    VanDerPauwExperiment, HallExperiment,
                    Ossila4PPExperiment)


class DialogLog:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def dialog(title="", message="", **_kwargs):
            self.calls.append((name, title, message))
            return True if name.startswith("ask") else None
        dialog.__name__ = name
        return dialog


DIALOGS = DialogLog()


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    DIALOGS.calls.clear()
    for name, module in list(sys.modules.items()):
        if (name.startswith(("smuniversal_lab_suite.core.",
                             "smuniversal_lab_suite.experiments."))
                and module is not None and hasattr(module, "messagebox")):
            monkeypatch.setattr(module, "messagebox", DIALOGS)


def _try_connect(experiment_cls, auto):
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, experiment_cls, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    transport = MeterTransport()
    try:
        try:
            if auto:
                app.connect_role("source", transport, "fake")
            else:
                app.connect_role_manual("source", transport, "fake",
                                        Keysight34401A)
            return None, transport
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}", transport
    finally:
        try:
            app.shutdown()
        except Exception:
            pass
        root.destroy()


@pytest.mark.parametrize("experiment", EVERY_EXPERIMENT,
                         ids=lambda e: e.__name__)
@pytest.mark.parametrize("auto", (True, False), ids=("by-idn", "by-hand"))
def test_every_window_refuses_a_meter_at_connect(experiment, auto, check):
    refused, transport = _try_connect(experiment, auto)
    name = experiment.__name__
    check(f"{name}: refused", refused is not None,
          "it connected, and would have been asked for a level at Run")
    check(f"{name}: as unsuitable, not as unrecognised",
          (refused or "").startswith("InstrumentUnsuitable"), refused)
    check(f"{name}: names the instrument",
          "Keysight 34401A" in (refused or ""), refused)
    check(f"{name}: and says it is a meter",
          "multimeter" in (refused or ""), refused)
    check(f"{name}: the port was closed again", not transport.connected)
    check(f"{name}: nothing was configured on it",
          not [s for s in transport.sent if s != "*IDN?"], transport.sent)


def test_no_window_has_invited_a_meter(check):
    """Guards against a quiet widening: the first role for a meter is a
    decision, and it should arrive as a change to this file."""
    for experiment in EVERY_EXPERIMENT:
        accepted = {name for names in (experiment.ROLE_ACCEPTS or {}).values()
                    for name in names}
        check(f"{experiment.__name__} has not accepted measures_only",
              "measures_only" not in accepted, f"{experiment.ROLE_ACCEPTS}")
