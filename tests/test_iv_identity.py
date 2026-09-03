"""Which sample an IV sweep says it measured, and which row a stored run is.

Wave 7b-i. Two defects, one of them found by probe rather than by
reading, and one design constraint that only shows up in this
experiment.

**The sample name was read on the worker thread, at the end of every
sweep.** `_finish_sweep` called `current_sample_name()`, which reads a
Tk variable, from `Thread-1`. Two consequences, and the second is the
one that produces bad data rather than a crash:

  * Tk access off the main thread usually works and then does not -
    `core/thread_guard.py` exists because that failure cannot be found
    by reading.
  * Retyping the sample-name box while a run was in flight re-filed the
    remaining sweeps under the new name. A periodic run could put its
    cycles under two different samples, with nothing logged. This is
    House rule 10 - a derived value carries its provenance. The IV
    sweep was the last experiment to get it.

**One IV run commits several stored records.** Every other experiment is
one run, one record; a periodic IV run is one run and N records, all
sharing a `run_id`. That is why `record_id` exists: Wave 7b makes saving
an explicit snapshot, so a reader de-duplicates overlapping files, and
de-duplicating on `run_id` would silently collapse a periodic run's
cycles into a single row.

The run-press tests drive `_do_single` directly on the main thread so
the binding is proved without racing a worker. The threading question
gets its own test, with the guard on, the way `test_4pp_lifecycle.py`
does it.
"""
import csv
import io
import time
import tkinter as tk

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.gui]

import core.base_app as base_app
import experiments.base_experiment as base_experiment
import experiments.iv_sweep.experiment as iv
from core.base_app import LabApp
from core.identity import SampleRegistry
from core.ownership import InstrumentOwnership
from core.run_store import Run, build_sample_csv
from core.thread_guard import ThreadAffinityGuard
from core.transports.null_transport import NullTransport
from experiments.iv_sweep.experiment import IVSweepExperiment


class DialogRecorder:
    """Stand in for `messagebox` so nothing blocks on a real dialog."""

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
iv.messagebox = dialogs
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs


def build(root, **form):
    """One app, one IV experiment, one dummy instrument, ready to run.

    Its own ownership manager and sample registry, so nothing here can
    be affected by - or leak into - another file sharing the process.
    """
    app = LabApp(root, IVSweepExperiment,
                 ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    app.connect_role("source", NullTransport(), "demo")
    root.update_idletasks()
    exp = app.experiment
    exp.start_var.set("0")
    exp.stop_var.set("1")
    exp.points_var.set(form.get("points", "4"))
    exp.delay_var.set("0")
    exp.runs_var.set(form.get("repeats", "1"))
    exp.mode_var.set("voltage")
    exp.on_mode_changed()
    exp.compliance_var.set("0.01")
    exp.cycles_var.set(form.get("cycles", "2"))
    exp.period_var.set("0")
    exp.standby_var.set(form.get("standby", "Remain idle"))
    exp.bias_var.set("0.5")
    exp.on_standby_changed()
    exp.sample_name_var.set(form.get("sample", "BEFORE"))
    return app, exp


def drain(root, app):
    """Service the Tk loop until the committed rows have landed."""
    for _ in range(80):
        root.update()
    app.drain_ui_now()
    root.update()


@pytest.fixture(autouse=True)
def _fast_settle(monkeypatch):
    monkeypatch.setattr(iv, "PRE_SWEEP_SETTLE_S", 0.0)


# ------------------------------------------------------------------
# A. the sample is bound at the Run press
# ------------------------------------------------------------------

def test_renaming_the_box_mid_run_does_not_move_the_data(check):
    """Provenance for the IV sweep, which was the last to get it.

    The rename happens after the parameter snapshot and before the
    sweep, which is exactly where an operator correcting a typo lands.
    Everything the run stores must still describe the sample that was
    named when Run was pressed.

    Deterministic on purpose: `_do_single` is driven on this thread, so
    the assertion is about *where the name is read*, not about winning a
    race with a worker.
    """
    root = tk.Tk()
    try:
        app, exp = build(root, sample="BEFORE", cycles="1")
        params = exp._sweep_params()          # the Run press

        exp.sample_name_var.set("AFTER")      # operator retypes, mid-run

        exp._do_single(params)
        drain(root, app)

        stored = exp.run_store.all_runs()
        check("the run was stored", len(stored) >= 1, f"{len(stored)}")
        check("filed under the name at the Run press",
              all(r.sample == "BEFORE" for r in stored),
              str([r.sample for r in stored]))
        check("and the label recorded on the run agrees",
              all(r.metadata.get("sample_label") == "BEFORE" for r in stored),
              str([r.metadata.get("sample_label") for r in stored]))
    finally:
        root.destroy()


def test_a_periodic_run_files_every_cycle_under_one_sample(check):
    """The half a single-sweep test cannot see.

    Before this wave the name was re-read at the end of *each* sweep, so
    a rename partway through a periodic run split it: earlier cycles
    under the old name, later ones under the new. Two files, one
    measurement, and nothing anywhere saying they belong together.
    """
    root = tk.Tk()
    try:
        app, exp = build(root, sample="BEFORE", cycles="3")
        params = exp._sweep_params()
        periodic = exp._periodic_params()

        original = exp._one_sweep
        seen = []

        def renaming(run, smu, sweep_params, label, **kw):
            result = original(run, smu, sweep_params, label, **kw)
            seen.append(label)
            if len(seen) == 1:
                # Between cycle one and cycle two.
                exp.sample_name_var.set("AFTER")
            return result
        exp._one_sweep = renaming

        exp._do_periodic(params, periodic)
        drain(root, app)

        stored = exp.run_store.all_runs()
        check("every cycle was recorded", len(stored) == 3, f"{len(stored)}")
        check("the rename happened while the run was in flight",
              len(seen) >= 2, f"{seen}")
        check("all cycles under one sample",
              {r.sample for r in stored} == {"BEFORE"},
              str(sorted({r.sample for r in stored})))
        check("all cycles under one sample_id",
              len({r.metadata.get("sample_id") for r in stored}) == 1,
              str({r.metadata.get("sample_id") for r in stored}))
    finally:
        root.destroy()


def test_the_iv_sweep_records_the_identity_columns_the_others_do(check):
    """The point of the wave: one shape of file across four experiments.

    Somebody opening these CSVs to do their own processing should not
    have to special-case the IV sweep. Named explicitly rather than
    compared against another experiment's output, so that dropping a
    column from *both* cannot make this pass.
    """
    root = tk.Tk()
    try:
        app, exp = build(root, cycles="1")
        exp._do_single(exp._sweep_params())
        drain(root, app)

        stored = exp.run_store.all_runs()
        check("a run was stored", len(stored) >= 1)
        if not stored:
            return
        record = stored[0]
        for key in ("run_id", "sample_id", "sample_label", "meas_number"):
            check(f"metadata carries {key}",
                  bool(record.metadata.get(key)),
                  f"got {record.metadata.get(key)!r}")

        text = build_sample_csv(record.sample, [record], exp.CSV_TITLE)
        body = [l for l in text.splitlines() if not l.startswith("#")]
        columns = next(csv.reader(io.StringIO("\n".join(body))))
        for key in ("record_id", "run_timestamp", "run_id", "sample_id",
                    "sample_label"):
            check(f"{key} is a CSV column", key in columns, str(columns))
    finally:
        root.destroy()


# ------------------------------------------------------------------
# B. record_id: one row, one identifier
# ------------------------------------------------------------------

def test_one_periodic_run_yields_one_run_id_and_distinct_record_ids(check):
    """The constraint that makes `record_id` necessary rather than tidy.

    If these were the same column, de-duplicating two overlapping
    snapshot files would delete two of this run's three cycles - real
    measurements, removed by an operation whose whole purpose is to
    remove duplicates. Nothing would report it.
    """
    root = tk.Tk()
    try:
        app, exp = build(root, cycles="3")
        exp._do_periodic(exp._sweep_params(), exp._periodic_params())
        drain(root, app)

        stored = exp.run_store.all_runs()
        check("three cycles stored", len(stored) == 3, f"{len(stored)}")
        run_ids = {r.metadata.get("run_id") for r in stored}
        record_ids = {r.record_id for r in stored}
        check("one lifecycle run", len(run_ids) == 1, str(run_ids))
        check("three distinct records", len(record_ids) == 3, str(record_ids))
        check("a record id is not a run id",
              not (record_ids & run_ids), str(record_ids & run_ids))
    finally:
        root.destroy()


def test_a_record_id_is_minted_without_the_experiment_asking(check):
    """`Run` mints it, so a future experiment cannot forget to.

    The alternative - each experiment putting one in its metadata - fails
    silently and late: the omission has no symptom until somebody
    concatenates two saved files months afterwards and finds rows they
    cannot tell apart.
    """
    plain = Run("s", {"meas_number": 1}, [{"point": 1}])
    other = Run("s", {"meas_number": 2}, [{"point": 1}])
    check("minted with no argument", bool(plain.record_id), plain.record_id)
    check("and it is unique", plain.record_id != other.record_id,
          f"{plain.record_id} vs {other.record_id}")
    check("recognisable prefix", plain.record_id.startswith("rec-"),
          plain.record_id)


def test_every_saved_row_carries_its_record_id(check):
    """Not just the header - the value has to be on each reading row.

    A column that is present and empty de-duplicates to one row, which
    is worse than having no column at all: the reader gets an answer
    rather than an error.
    """
    runs = [Run("s", {"meas_number": 1},
                [{"point": 1}, {"point": 2}, {"point": 3}]),
            Run("s", {"meas_number": 2}, [{"point": 1}])]
    text = build_sample_csv("s", runs, "T")
    body = [l for l in text.splitlines() if not l.startswith("#")]
    rows = list(csv.DictReader(io.StringIO("\n".join(body))))

    check("one row per reading", len(rows) == 4, f"{len(rows)}")
    check("every row has a record id",
          all(r["record_id"] for r in rows),
          str([r["record_id"] for r in rows]))
    check("repeated across a run's own readings, distinct between runs",
          len({r["record_id"] for r in rows}) == 2,
          str({r["record_id"] for r in rows}))


# ------------------------------------------------------------------
# C. and the thread it all happens on
# ------------------------------------------------------------------

def test_the_iv_worker_never_reads_a_tk_variable(check):
    """Issue B2 for the IV sweep, which alone was never checked.

    4PP has had this test since Wave 3. The IV sweep did not, and that
    is how a `current_sample_name()` call sat on the worker path from
    Wave 6a until it was found by probing rather than by reading.

    A real threaded run, with the guard watching `Variable.get` and
    `.set`. `guard.calls > 0` is not decoration: without it the test
    would pass just as happily against a run that never happened.
    """
    root = tk.Tk()
    guard = ThreadAffinityGuard(tk.Variable, ("get", "set"))
    try:
        app, exp = build(root, cycles="1")
        with guard:
            exp.run_pressed()
            deadline = time.time() + 20.0
            while time.time() < deadline:
                root.update()
                if exp.run_controller.is_idle and exp.run_store.all_runs():
                    break
                time.sleep(0.005)
            app.drain_ui_now()
            root.update()

        check("the run completed, so the guard watched a real run",
              len(exp.run_store) >= 1, f"{len(exp.run_store)} stored")
        check("the guard was actually watching",
              guard.calls > 0, f"{guard.calls} guarded call(s)")
        check("no Tk variable was read or written from a worker thread",
              not guard.violations, guard.report())
    finally:
        guard.remove()
        root.destroy()
