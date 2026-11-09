"""
The contact check a four-contact run makes before its sweep, the
instrument column, and a Hall save that writes the Van der Pauw tab too.

All three came out of one bench session (2026-11-09): a Hall run that
read a clean 2 kOhm line on a film whose other runs read 0.5 Ohm, the
next run open at the compliance limit, a summary citing a Van der Pauw
result whose runs were never saved, and files that could not say which
SMU measured them.

The faults are made on the demo instrument: it reads the same
resistance at every position and pins at the compliance limit, so
raising its resistance gives either fault on demand.
"""
import pytest

pytestmark = [pytest.mark.gui]

import csv
import glob
import io
import os
import tempfile
import tkinter as tk

from hall_harness import run_hall
from vdp_harness import run_vdp

import smuniversal_lab_suite.core.base_app as base_app
import smuniversal_lab_suite.experiments.base_experiment as base_experiment
import smuniversal_lab_suite.experiments.four_contact as four_contact
import smuniversal_lab_suite.experiments.hall.experiment as hall_experiment
import smuniversal_lab_suite.experiments.vanderpauw.experiment as vdp_experiment
from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.ownership import InstrumentOwnership
from smuniversal_lab_suite.core.run_control import ContactCheckFailed, Outcome
from smuniversal_lab_suite.core.transports.null_transport import NullTransport
from smuniversal_lab_suite.experiments.hall.experiment import HallExperiment
from smuniversal_lab_suite.experiments.iv_sweep.iv_math import fit_sweep
from smuniversal_lab_suite.experiments.vanderpauw.experiment import (
    VanDerPauwExperiment,
)

COMBOS = (("C", "+"), ("C", "-"), ("D", "+"), ("D", "-"))


class DialogRecorder:
    def __init__(self):
        self.calls = []

    def _record(self, kind):
        def call(title, message=None, **kw):
            self.calls.append((kind, title, message))
            return True
        return call

    def __getattr__(self, name):
        return self._record(name)


dialogs = DialogRecorder()
vdp_experiment.messagebox = dialogs
hall_experiment.messagebox = dialogs
four_contact.messagebox = dialogs
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs


def make_app(folder=None):
    """A combined Van der Pauw + Hall window on the demo SMU."""
    root = tk.Tk()
    app = LabApp(root, [VanDerPauwExperiment, HallExperiment],
                 ownership=InstrumentOwnership(), samples=SampleRegistry())
    app.connect_role("source", NullTransport(), "demo")
    if folder is not None:
        app.storage_path = folder
        app.note_sample_context_changed()
        app._ask_summary_collision = lambda *a, **k: "same"
    vdp = app.experiment_of(VanDerPauwExperiment)
    vdp.sample_name_var.set("wafer_A")
    vdp.thickness_entry_var.set("1.5 um")
    root.update()
    dialogs.calls.clear()
    return root, app, vdp, app.experiment_of(HallExperiment)


def close(root, app):
    for _ in range(5):
        root.update()
    try:
        app.on_close()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass
    dialogs.calls.clear()


def last_status(exp):
    history = exp.run_controller.history
    return history[-1] if history else None


def slope_of(record):
    readings = [r for r in record.readings
                if isinstance(r.get("current_A"), float)]
    slope, _, _, _ = fit_sweep([r["current_A"] for r in readings],
                               [r["voltage_V"] for r in readings], "current")
    return slope


# ------------------------------------------------------------------
# refusing
# ------------------------------------------------------------------
def test_an_open_contact_refuses_the_run_before_the_sweep(check):
    root, app, vdp, hall = make_app()
    try:
        smu = app.instruments["source"]
        smu.resistance = 1e9            # pins at the 0.3 V compliance
        with pytest.raises(ContactCheckFailed) as caught:
            run_hall(hall, root, "C", "-", level="1 µA")
        message = str(caught.value)
        check("it says the path is open", "open" in message, message)
        check("it names the corners the current goes through",
              "corners 2 and 4" in message, message)
        check("nothing reached the table", hall.tree.get_children() == ())
        check("nothing reached the store", len(hall.run_store) == 0)
        status = last_status(hall)
        check("the run ended as failed, not completed",
              status is not None and status.outcome is Outcome.FAILED,
              str(status))
        check("it stopped at the first reading: the sweep never started",
              smu._reading_count == 1, smu._reading_count)
        check("the output is off", smu._output_on is False)
    finally:
        close(root, app)


def test_a_run_far_above_the_sample_is_refused(check):
    """The 2 kOhm D- run: a clean line, far above every other run of
    the sample. Van der Pauw's runs are the reference for Hall's first."""
    root, app, vdp, hall = make_app()
    try:
        for position in ("A", "B"):
            run_vdp(vdp, root, position, level="1 µA")
        smu = app.instruments["source"]
        smu.resistance *= 20            # 20 kOhm at 1 uA: 20 mV, no clamp
        with pytest.raises(ContactCheckFailed) as caught:
            run_hall(hall, root, "D", "-", level="1 µA")
        message = str(caught.value)
        check("it gives the ratio", "20 times" in message, message)
        check("it says how to run anyway",
              "Check contacts first" in message, message)
        check("nothing reached the table", hall.tree.get_children() == ())
    finally:
        close(root, app)


def test_the_dialog_is_titled_for_the_contacts(check):
    root, app, vdp, hall = make_app()
    try:
        def refuse():
            raise ContactCheckFailed("PosC: open")
        app.guard_run(refuse)()
        app.drain_ui_now()
        check("a 'Contact check failed' warning, not 'Cannot start'",
              ("showwarning", "Contact check failed", "PosC: open")
              in dialogs.calls, dialogs.calls)
    finally:
        close(root, app)


# ------------------------------------------------------------------
# passing, and what it records
# ------------------------------------------------------------------
def test_a_normal_run_passes_and_records_the_check(check):
    root, app, vdp, hall = make_app()
    try:
        run_vdp(vdp, root, "A", level="1 µA")
        reference = slope_of(vdp.run_store.all_runs()[0])
        run_hall(hall, root, "C", "+", level="1 µA")
        records = hall.run_store.all_runs()
        check("the run committed", len(records) == 1)
        if not records:
            return
        meta = records[0].metadata
        check("the check was on", meta.get("contact_check") is True,
              meta.get("contact_check"))
        check("its reference is Van der Pauw's run",
              meta.get("contact_reference_ohm") == reference,
              f"{meta.get('contact_reference_ohm')} vs {reference}")
        ohms = meta.get("contact_check_ohm")
        check("the check's reading is recorded, near the demo's 1 kOhm",
              isinstance(ohms, float) and abs(ohms - 1000) < 20, ohms)
        check("the instrument is named",
              str(meta.get("instrument_source", "")).startswith("Dummy"),
              meta.get("instrument_source"))
    finally:
        close(root, app)


def test_unticked_the_check_does_not_run(check):
    root, app, vdp, hall = make_app()
    try:
        run_vdp(vdp, root, "A", level="1 µA")
        app.instruments["source"].resistance *= 20
        hall.contact_check_var.set(False)
        run_hall(hall, root, "C", "+", level="1 µA")
        records = hall.run_store.all_runs()
        check("the run committed", len(records) == 1)
        if records:
            meta = records[0].metadata
            check("it is recorded as off", meta.get("contact_check") is False)
            check("with no reading", meta.get("contact_check_ohm") == "")
    finally:
        close(root, app)


def test_a_clamped_run_is_not_a_reference(check):
    """An open contact's slope is the limit's, and would raise the bar
    for every run after it."""
    root, app, vdp, hall = make_app()
    try:
        run_vdp(vdp, root, "A", level="1 µA")
        record = vdp.run_store.all_runs()[0]
        sample_id = record.metadata["sample_id"]
        check("a clean run is a reference",
              vdp.contact_reference(sample_id)[0] is not None)
        record.metadata["compliance_suspected"] = "yes"
        check("a clamped one is not",
              vdp.contact_reference(sample_id) == (None, ""),
              vdp.contact_reference(sample_id))
    finally:
        close(root, app)


# ------------------------------------------------------------------
# one Save, both tabs
# ------------------------------------------------------------------
def header_of(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            key, _, value = line[1:].strip().partition(":")
            out[key.strip()] = value.strip()
    return out


def test_hall_save_writes_the_vdp_tab_too(check):
    with tempfile.TemporaryDirectory() as folder:
        root, app, vdp, hall = make_app(folder)
        try:
            for position in ("A", "B"):
                run_vdp(vdp, root, position)
            for position, sign in COMBOS:
                run_hall(hall, root, position, sign)
            hall.save_runs()
            vdp_files = glob.glob(os.path.join(folder, "*_vanderpauw*.csv"))
            hall_files = glob.glob(os.path.join(folder, "*_hall*.csv"))
            check("one Van der Pauw file", len(vdp_files) == 1, vdp_files)
            check("one Hall file", len(hall_files) == 1, hall_files)
            if vdp_files and hall_files:
                check("both from one press: the same save id",
                      header_of(vdp_files[0])["save_id"]
                      == header_of(hall_files[0])["save_id"])
            check("both tabs are marked saved",
                  not vdp.run_store.has_unsaved
                  and not hall.run_store.has_unsaved)
            check("one dialog lists both files",
                  any(kind == "showinfo" and "vanderpauw" in (msg or "")
                      and "hall" in (msg or "")
                      for kind, _, msg in dialogs.calls), dialogs.calls)

            # Van der Pauw's own Save still saves only Van der Pauw.
            vdp.save_runs()
            check("a Van der Pauw save adds one Van der Pauw file only",
                  len(glob.glob(os.path.join(folder, "*_vanderpauw*.csv")))
                  == 2
                  and len(glob.glob(os.path.join(folder, "*_hall*.csv")))
                  == 1)
        finally:
            close(root, app)


def test_the_instrument_column_reaches_the_file(check):
    with tempfile.TemporaryDirectory() as folder:
        root, app, vdp, hall = make_app(folder)
        try:
            run_vdp(vdp, root, "A")
            vdp.save_runs()
            path = glob.glob(os.path.join(folder, "*_vanderpauw*.csv"))[0]
            with open(path, encoding="utf-8") as f:
                rows = list(csv.DictReader(
                    io.StringIO("".join(l for l in f if not l.startswith("#")))))
            check("every row names the instrument",
                  rows and all(r["instrument_source"].startswith("Dummy")
                               for r in rows),
                  rows[0].get("instrument_source") if rows else "no rows")
        finally:
            close(root, app)


def test_a_save_writes_the_summary_another_tab_calculated(check):
    """Van der Pauw saved while only Hall holds a result for the sample.
    The summary used to be skipped: it asked only the saving tab which
    sample it had calculated, and Van der Pauw had calculated none."""
    with tempfile.TemporaryDirectory() as folder:
        root, app, vdp, hall = make_app(folder)
        try:
            app.summary_collision_decision("wafer_A")
            run_vdp(vdp, root, "A")
            for position, sign in COMBOS:
                run_hall(hall, root, position, sign)
            for item in hall.tree.get_children():
                hall.tree.item(item, text="☑")
            hall.copy_over()
            hall.calc_B_var.set("0.82")
            hall.calc_Rs_var.set("250")
            hall.calculate_hall()
            root.update()
            check("Hall has a result", hall._calc_result is not None)

            vdp.save_runs()
            summaries = glob.glob(os.path.join(folder, "*_summary*.csv"))
            check("a summary was written", len(summaries) == 1, summaries)
            if summaries:
                with open(summaries[0], encoding="utf-8") as f:
                    text = f.read()
                check("it carries the Hall result", "Hall mobility" in text,
                      text)
        finally:
            close(root, app)
