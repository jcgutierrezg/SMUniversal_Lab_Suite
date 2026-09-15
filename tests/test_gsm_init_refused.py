"""A staircase that is armed and then refused to start.

Reported from the bench, 2026-09-15. An IV sweep at default settings on
a GSM-20H10 beeped several times, then ended with two dialogs: *"the
output could not be confirmed off - instrument reported 803"*, and
*"run incomplete, no readings acquired; expected 10, got 0; sweep timed
out with 0/10 points; no data returned; no sweep returned any data"*.

Three symptoms, one cause, and none of them named it.

`start_linear_sweep()` already drains the error queue and falls back to
the software sweep when the buffer setup is refused - that path exists
because a previous bench session found it, including the part about
taking the source out of `SWE` mode first so the fallback writes levels
instead of endpoints.

But every drain happens **before** `INIT`. So the check graded the
setup and never the command that actually starts the sweep. A refused
`INIT` is written, logged in the instrument's queue, and otherwise
silent: the buffer never fills, the caller polls it for thirty seconds,
and the run reports the symptom three times over while the instrument's
own answer sits unread.
"""
import sys
import time

import pytest
from test_gsm20h10 import GSMTransport

pytestmark = [pytest.mark.gui]


class DialogLog:
    """Stands on every dialog seam and writes down what would have shown.

    Not politeness: without it this file pops **real modal windows** at
    whoever is running the suite, and a failing assertion then blocks
    behind a dialog nobody is there to close. That happened while this
    file was being written - a mutation run put two windows on the
    author's screen and waited.

    It also turns "the operator got two dialogs" into something a test
    can assert, which is the actual complaint this file exists for.
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


#: Module-level so the conftest guard can see which file owns it.
DIALOGS = DialogLog()


@pytest.fixture(autouse=True)
def _no_real_dialogs(monkeypatch):
    # Every module this file touches has to be imported ALREADY, at the
    # top of the file, or it is not in `sys.modules` when this runs and
    # its `messagebox` goes unpatched. Importing `base_app` inside the
    # test instead put two real modal windows on the author's screen -
    # twice - and a suite that stops for a dialog nobody is there to
    # close is a suite that hangs in CI.
    DIALOGS.calls.clear()
    for name, module in list(sys.modules.items()):
        if (name.startswith(("smuniversal_lab_suite.core.",
                             "smuniversal_lab_suite.experiments."))
                and module is not None and hasattr(module, "messagebox")):
            monkeypatch.setattr(module, "messagebox", DIALOGS)

import tkinter as tk

from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.ownership import InstrumentOwnership
from smuniversal_lab_suite.drivers.gwinstek_gsm20h10 import GWInstekGSM20H10
from smuniversal_lab_suite.experiments.iv_sweep.experiment import (
    IVSweepExperiment,
)


class RefusesInit(GSMTransport):
    """Takes the whole staircase setup and then refuses `INIT`."""

    def _write(self, text):
        super()._write(text)
        if text.strip().upper() == "INIT":
            self.errors.append((803, "Not permitted with OUTPUT off"))


def armed(transport_cls=GSMTransport):
    transport = transport_cls()
    if not getattr(transport, "connected", False):
        transport.connect("fake")
    smu = GWInstekGSM20H10(transport)
    smu.reset()
    smu.set_source_function("voltage")
    smu.output_on()
    return smu, transport


def test_a_refused_init_falls_back_instead_of_timing_out(check):
    """The run the operator had, and what it does now.

    Without the check this returns nothing and the caller discovers it
    thirty seconds later. The fallback is not a workaround: a sweep
    taken point by point is a real measurement, and the alternative was
    no measurement at all.
    """
    smu, _ = armed(RefusesInit)
    check("it starts out claiming the staircase",
          smu.sweep_kind() == "hardware", smu.sweep_kind())

    smu.start_linear_sweep("voltage", 0.0, 1.0, 10, 0.0)

    check("it switched to software", smu.sweep_kind() == "software",
          smu.sweep_kind())
    note = smu.sweep_note() or ""
    check("and says INIT was the thing refused", "INIT" in note, note)
    check("quoting the instrument", "803" in note, note)

    for _ in range(60):
        if smu.sweep_points_ready() >= 10:
            break
        time.sleep(0.05)
    sourced, measured = smu.read_sweep(10)
    check("the sweep produced its points", len(measured) == 10,
          f"{len(measured)} points - this was 0 before the check existed")
    check("and the levels came out too", len(sourced) == 10,
          f"{len(sourced)}")


def test_the_source_is_taken_out_of_sweep_mode_first(check):
    """The bug a previous bench session found, on the new path.

    `SOUR:VOLT:MODE SWE` is already sent by the time `INIT` is refused.
    Falling straight through leaves it there, and the software sweep's
    `SOUR:VOLT <level>` is then read as a sweep *endpoint* - so the
    source never moves, the run completes, and every point sits at 0 V.
    A flat line from a working instrument.
    """
    smu, transport = armed(RefusesInit)
    smu.start_linear_sweep("voltage", 0.0, 1.0, 10, 0.0)
    sent = [c.strip().upper() for c in transport.sent]

    init_at = max(i for i, c in enumerate(sent) if c == "INIT")
    restored = [i for i, c in enumerate(sent)
                if "MODE" in c and "SWE" not in c.split("MODE")[-1]]
    check("the source came out of sweep mode after INIT was refused",
          any(i > init_at for i in restored),
          f"nothing restored the source mode after INIT: {sent[init_at:]}")


def test_an_accepted_init_is_left_alone(check):
    """The check must not cost a working instrument its staircase."""
    smu, _ = armed()
    smu.start_linear_sweep("voltage", 0.0, 1.0, 10, 0.0)
    check("still a hardware sweep", smu.sweep_kind() == "hardware",
          smu.sweep_kind())
    check("and it says nothing about a fallback",
          "INIT" not in (smu.sweep_note() or ""), smu.sweep_note())


def test_the_queue_is_asked_after_init_not_only_before(check):
    """The gap itself, stated as a property of the traffic.

    A drain that happens only before the arm cannot grade the arm.
    """
    smu, transport = armed()
    mark = len(transport.sent)
    smu.start_linear_sweep("voltage", 0.0, 1.0, 10, 0.0)
    sent = [c.strip().upper() for c in transport.sent[mark:]]

    init_at = max(i for i, c in enumerate(sent) if c == "INIT")
    after = [c for c in sent[init_at:] if "ERR" in c]
    check("the error queue is read after INIT", after,
          f"nothing asked after INIT: {sent[init_at:]}")


# ---------------------------------------------------------------
# The record has to say which sweep actually ran
# ---------------------------------------------------------------


def test_the_run_records_the_sweep_that_actually_happened(check):
    """`sweep_kind` is stamped in `_prepare`, before the sweep.

    That is where it belongs - it is part of the configuration - but a
    driver that only discovers at arming time that its staircase will
    not take falls back mid-call. Left unchecked, the run files a sweep
    stepped point by point from the PC under `hardware`.

    The two give equally accurate levels and not equally trustworthy
    timing, which is the whole reason the column exists. A run under the
    wrong one is worse than a run that did not record it.
    """
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, IVSweepExperiment, ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    try:
        app.connect_role_manual("source", RefusesInit(), "fake",
                                GWInstekGSM20H10)
        root.update()
        exp = app.experiment
        exp.mode_var.set("voltage")
        exp.on_mode_changed()
        exp.start_var.set("0")
        exp.stop_var.set("1")
        exp.points_var.set("10")
        exp.delay_var.set("0")
        exp.runs_var.set("1")
        exp.standby_var.set("Remain idle")
        exp.on_standby_changed()
        root.update()

        params = exp._sweep_params()
        exp._check_limits(params)
        app.guard_run(lambda: exp._do_single(params))()
        app.drain_ui_now()
        for _ in range(40):
            root.update()
        app.drain_ui_now()

        runs = list(exp.run_store.all_runs())
        check("the run was recorded", runs, "nothing in the store")
        kinds = {r.metadata.get("sweep_kind") for r in runs}
        check("filed as the software sweep it actually was",
              kinds == {"software"},
              f"{kinds} - a point-by-point sweep recorded as hardware "
              f"claims an instrument timebase it never had")

        # The complaint, stated as an assertion. The reported run put
        # two windows in front of the operator - one blaming the
        # shutdown for configuration errors, one reporting the sweep
        # timeout three different ways - and neither named the cause.
        check("and the operator sees no dialogs at all",
              not DIALOGS.raised(),
              [f"{title}: {message[:80]}"
               for _kind, title, message in DIALOGS.raised()])
    finally:
        try:
            app.shutdown()
        except Exception:
            pass
        root.destroy()
