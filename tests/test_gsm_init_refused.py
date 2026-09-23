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
    """Takes the whole staircase setup, refuses `INIT`, and stays empty.

    `_buffered` is what the real instrument would leave behind: a
    staircase that never ran wrote nothing, so `TRAC:POIN:ACT?` answers
    zero and `TRAC:DATA?` has nothing to give.
    """

    def _write(self, text):
        super()._write(text)
        if text.strip().upper() == "INIT":
            self.errors.append((803, "Not permitted with OUTPUT off"))
            self.buffer_points = 0

    def _read(self, timeout_s=3.0):
        last = (self.sent[-1] if self.sent else "").strip().upper()
        if getattr(self, "buffer_points", None) == 0:
            if "TRAC:POIN:ACT" in last:
                return "0"
            if "TRAC:DATA" in last:
                return ""
        return super()._read(timeout_s)


class BusyDuringSweep(GSMTransport):
    """An instrument that will not answer the error queue while it is
    sweeping - which is what made the first version of this fix turn an
    intermittent fault into a reproducible one."""

    def _write(self, text):
        super()._write(text)
        if text.strip().upper() == "INIT":
            self.sweeping = True

    def _read(self, timeout_s=3.0):
        last = (self.sent[-1] if self.sent else "").upper()
        if getattr(self, "sweeping", False) and "ERR" in last:
            raise TimeoutError("busy sweeping; no reply to the error queue")
        return super()._read(timeout_s)


def armed(transport_cls=GSMTransport):
    transport = transport_cls()
    if not getattr(transport, "connected", False):
        transport.connect("fake")
    smu = GWInstekGSM20H10(transport)
    smu.reset()
    smu.set_source_function("voltage")
    smu.output_on()
    return smu, transport


def _sweep_and_read(smu, points=10):
    """Arm, let the poll loop give up, then read - the caller's path."""
    smu.start_linear_sweep("voltage", 0.0, 1.0, points, 0.0)
    for _ in range(20):
        if smu.sweep_points_ready() >= points:
            break
        time.sleep(0.02)
    return smu.read_sweep(points)


def test_a_refused_init_is_diagnosed_when_the_buffer_comes_back_empty(check):
    """The run the operator had, and what it does now.

    Without the check this returns nothing and the caller discovers it
    thirty seconds later. The fallback is not a workaround: a sweep
    taken point by point is a real measurement, and the alternative was
    no measurement at all.
    """
    smu, _ = armed(RefusesInit)
    check("it starts out claiming the staircase",
          smu.sweep_kind() == "hardware", smu.sweep_kind())

    _sweep_and_read(smu)

    check("it switched to software", smu.sweep_kind() == "software",
          smu.sweep_kind())
    note = smu.sweep_note() or ""
    check("and quotes the instrument", "803" in note, note)
    check("naming what it could not do", "produced nothing" in note, note)

    # The next sweep is the one that has to work.
    sourced, measured = _sweep_and_read(smu)
    check("the next sweep produced its points", len(measured) == 10,
          f"{len(measured)} points")
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
    _sweep_and_read(smu)
    sent = [c.strip().upper() for c in transport.sent]

    init_at = max(i for i, c in enumerate(sent) if c == "INIT")
    restored = [i for i, c in enumerate(sent)
                if "MODE FIX" in c]
    check("the source came out of sweep mode",
          any(i > init_at for i in restored),
          f"nothing restored the source mode: {sent[init_at:]}")


def test_an_accepted_init_is_left_alone(check):
    """The check must not cost a working instrument its staircase."""
    smu, _ = armed()
    _sweep_and_read(smu)
    check("still a hardware sweep", smu.sweep_kind() == "hardware",
          smu.sweep_kind())
    check("and it says nothing about a fallback",
          "produced nothing" not in (smu.sweep_note() or ""),
          smu.sweep_note())


def test_nothing_is_asked_while_the_instrument_is_sweeping(check):
    """`INIT` is the last word until the sweep is over.

    The first version of this fix read the error queue immediately
    after `INIT` - the right question at the one moment this instrument
    cannot answer it. It does not service the error queue while
    sweeping, so the query waits for the whole sweep, blows its 3 s
    timeout, latches the transport and discards the run. Every time.

    A diagnostic that costs every run is worse than the fault it
    diagnoses, so the question moved to `read_sweep()`, where the poll
    loop has already given up and the instrument is idle.
    """
    smu, transport = armed()
    mark = len(transport.sent)
    smu.start_linear_sweep("voltage", 0.0, 1.0, 10, 0.0)
    sent = [c.strip().upper() for c in transport.sent[mark:]]

    init_at = max(i for i, c in enumerate(sent) if c == "INIT")
    after = sent[init_at + 1:]
    check("nothing follows INIT", not after,
          f"sent while the instrument is sweeping: {after}")


def test_a_busy_instrument_does_not_cost_the_run(check):
    """The regression, pinned against an instrument that behaves the
    way the bench one does."""
    smu, transport = armed(BusyDuringSweep)
    smu.start_linear_sweep("voltage", 0.0, 1.0, 10, 0.0)
    check("arming completed without waiting on a reply it cannot get",
          smu.sweep_kind() == "hardware", smu.sweep_kind())


# ---------------------------------------------------------------
# The record has to say which sweep actually ran
# ---------------------------------------------------------------


def test_the_run_records_the_sweep_that_actually_happened(check):
    """`sweep_kind` is stamped in `_prepare`, before the sweep.

    That is where it belongs - it is part of the configuration - but a
    driver that only discovers at read-out time that its staircase
    produced nothing switches mid-run. Left unchecked, the next run
    files a sweep stepped point by point from the PC under `hardware`.

    The two give equally accurate levels and not equally trustworthy
    timing, which is the whole reason the column exists. A run under the
    wrong one is worse than a run that did not record it.

    **The first sweep of a session still fails**, and that is the
    honest consequence of not being able to ask the instrument anything
    while it is sweeping. What it no longer does is fail without
    saying why: the note names the code the instrument returned, and
    the session self-heals for every run after it.
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
        # Above what the fake's sample draws at 1 V, so the only dialog
        # this test could see is one about the sweep itself - not the
        # compliance warning a clamped sweep correctly raises.
        exp.compliance_var.set("0.01")
        exp.standby_var.set("Remain idle")
        exp.on_standby_changed()
        root.update()

        def sweep_once():
            params = exp._sweep_params()
            exp._check_limits(params)
            app.guard_run(lambda: exp._do_single(params))()
            app.drain_ui_now()
            for _ in range(40):
                root.update()
            app.drain_ui_now()

        sweep_once()
        driver = app.instruments["source"]
        check("the first sweep diagnosed itself",
              "803" in (driver.sweep_note() or ""), driver.sweep_note())
        check("and switched the session to the software sweep",
              driver.sweep_kind() == "software", driver.sweep_kind())

        DIALOGS.calls.clear()
        sweep_once()

        runs = list(exp.run_store.all_runs())
        check("the second sweep was recorded", runs, "nothing in the store")
        kinds = {r.metadata.get("sweep_kind") for r in runs}
        check("filed as the software sweep it actually was",
              kinds == {"software"},
              f"{kinds} - a point-by-point sweep recorded as hardware "
              f"claims an instrument timebase it never had")
        check("and it raised no dialog", not DIALOGS.raised(),
              [f"{title}: {message[:70]}"
               for _kind, title, message in DIALOGS.raised()])
    finally:
        try:
            app.shutdown()
        except Exception:
            pass
        root.destroy()
