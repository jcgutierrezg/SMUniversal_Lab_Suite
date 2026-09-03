"""
Saving: nothing reaches disk until asked, bad runs can be discarded, and
what does get written is one grouped CSV per sample.

The behaviour being guarded is a trade. Runs are no longer written the
moment they finish, so a spoiled measurement never leaves a file behind -
but an unsaved run exists only in memory. The close prompt driven by
has_unsaved_runs() is the whole safety net, so it is asserted here rather
than left to be noticed the first time somebody loses an hour of work.
"""
import pytest

pytestmark = [pytest.mark.gui]

import csv
import io
import os
import sys
import tempfile
import tkinter as tk

from vdp_harness import run_vdp

from core.base_app import LabApp
from core.run_store import Run, RunStore, build_sample_csv
from core.transports.null_transport import NullTransport
from experiments.vanderpauw.experiment import VanDerPauwExperiment


class DialogRecorder:
    """Captures dialogs and answers yes, so headless runs don't block."""

    def __init__(self, answer=True):
        self.calls = []
        self.answer = answer

    def _record(self, kind):
        def call(title, message, **kw):
            self.calls.append((kind, title, message))
            return self.answer
        return call

    def __getattr__(self, name):
        return self._record(name)


def _make_run(sample, meas, position, points=3):
    return Run(
        sample=sample,
        metadata={"meas_number": meas, "position": position, "level_A": 1e-4},
        readings=[{"point": i + 1, "voltage_V": 0.1 * i, "current_A": 1e-4}
                  for i in range(points)],
    )


# ---- the store on its own ----
def _collect_store():
    bad = []
    store = RunStore()

    if store.has_unsaved:
        bad.append(("empty store", "unsaved", "nothing to lose"))

    store.add("a", _make_run("wafer_A", 1, 1))
    store.add("b", _make_run("wafer_A", 2, 2))
    store.add("c", _make_run("wafer_B", 3, 1))

    if not store.has_unsaved:
        bad.append(("after add", "clean", "unsaved"))
    if store.samples() != ["wafer_A", "wafer_B"]:
        bad.append(("samples", store.samples(), ["wafer_A", "wafer_B"]))
    if len(store.runs_for("wafer_A")) != 2:
        bad.append(("runs_for", len(store.runs_for("wafer_A")), 2))

    store.mark_saved()
    if store.has_unsaved:
        bad.append(("after save", "unsaved", "clean"))

    # deleting is itself a change worth re-saving after
    if store.remove(["b"]) != 1:
        bad.append(("remove", "wrong count", 1))
    if not store.has_unsaved:
        bad.append(("after remove", "clean", "unsaved"))
    if len(store) != 2:
        bad.append(("len after remove", len(store), 2))

    store.clear()
    if len(store) or store.has_unsaved:
        bad.append(("after clear", (len(store), store.has_unsaved), (0, False)))
    return bad


# ---- the CSV format ----
def _collect_csv_format():
    """Header holds the calculated values; the table holds one row per
    raw reading and must survive a standard csv reader."""
    bad = []
    runs = [_make_run("wafer_A", 1, 1, points=3),
            _make_run("wafer_A", 2, 2, points=2)]

    text = build_sample_csv(
        "wafer_A", runs, "Van der Pauw - sheet resistance",
        calculated={"Rs_ohm_per_sq": "4532.36", "rho_ohm_cm": "0.453",
                    "empty_is_skipped": ""})

    header = [l for l in text.splitlines() if l.startswith("#")]
    body = [l for l in text.splitlines() if not l.startswith("#")]

    if not any("Rs_ohm_per_sq: 4532.36" in l for l in header):
        bad.append(("header", "Rs missing", "present"))
    if any("empty_is_skipped" in l for l in header):
        bad.append(("header", "blank value written", "skipped"))

    rows = list(csv.reader(io.StringIO("\n".join(body))))
    rows = [r for r in rows if r]
    if len(rows) != 6:                      # 1 header + 5 readings
        bad.append(("csv rows", len(rows), 6))

    columns = rows[0]
    for needed in ("meas_number", "position", "point", "voltage_V", "current_A"):
        if needed not in columns:
            bad.append((f"column {needed}", "missing", "present"))

    # per-run metadata must repeat on every reading of that run
    meas_index = columns.index("meas_number")
    point_index = columns.index("point")
    first_run = [r for r in rows[1:] if r[meas_index] == "1"]
    if len(first_run) != 3:
        bad.append(("rows for run 1", len(first_run), 3))
    if [r[point_index] for r in first_run] != ["1", "2", "3"]:
        bad.append(("point numbering", [r[point_index] for r in first_run],
                    ["1", "2", "3"]))

    # a bare `#`-comment skip must leave a clean table, as pandas would do
    stripped = "\n".join(l for l in text.splitlines() if not l.startswith("#"))
    if len(list(csv.DictReader(io.StringIO(stripped)))) != 5:
        bad.append(("comment stripping", "table not clean", "5 data rows"))
    return bad


# ---- the real GUI workflow ----
def _collect_save_workflow():
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        dialogs = DialogRecorder()
        import experiments.base_experiment as base_module
        base_module.messagebox = dialogs

        root = tk.Tk()
        app = LabApp(root, VanDerPauwExperiment)
        exp = app.experiment
        app.storage_path = tmp
        exp.sample_name_var.set("wafer_A")

        app.connect_role("source", NullTransport(), "<simulated>")
        root.update()

        for pos in (1, 2, 3, 4):
            run_vdp(exp, root, pos)

        # nothing on disk yet - that is the entire point of the change
        if os.listdir(tmp):
            bad.append(("auto-save", os.listdir(tmp), "empty until Save"))
        if len(exp.run_store) != 4:
            bad.append(("runs held", len(exp.run_store), 4))
        if not exp.has_unsaved_runs():
            bad.append(("unsaved flag", False, True))
        print(f"    4 runs measured, files on disk: {len(os.listdir(tmp))}")

        # discard one as if the contacts had been poor
        rows = exp.tree.get_children()
        exp.tree.item(rows[1], text="☑")
        exp.delete_ticked()
        root.update()
        if len(exp.run_store) != 3 or len(exp.tree.get_children()) != 3:
            bad.append(("after delete",
                        (len(exp.run_store), len(exp.tree.get_children())),
                        (3, 3)))
        print(f"    1 run discarded, {len(exp.run_store)} left")

        # a second sample, to prove grouping
        exp.sample_name_var.set("wafer_B")
        run_vdp(exp, root, 1)

        exp.sample_name_var.set("wafer_A")
        for var, item in zip(exp.pos_vars, exp.tree.get_children()):
            var.set(str(exp.tree.item(item, "values")[4]))
        exp.calculate_vdp()
        exp.save_runs()
        root.update()

        files = sorted(os.listdir(tmp))
        print(f"    saved: {files}")
        data_files = sorted(f for f in files if f.endswith("_vanderpauw.csv"))
        if data_files != ["wafer_A_vanderpauw.csv", "wafer_B_vanderpauw.csv"]:
            bad.append(("grouped files", data_files, "one per sample"))
        # Wave 5c-ii: the calculated sample gets a summary alongside its
        # data CSV; the uncalculated one does not. A summary for wafer_B
        # here would mean the calculation leaked onto a sample it does
        # not describe.
        summaries = sorted(f for f in files if f.endswith("_summary.csv"))
        if summaries != ["wafer_A_summary.csv"]:
            bad.append(("summary files", summaries,
                        "one, for the calculated sample only"))

        with open(os.path.join(tmp, "wafer_A_vanderpauw.csv"), encoding="utf-8") as f:
            a_text = f.read()
        with open(os.path.join(tmp, "wafer_B_vanderpauw.csv"), encoding="utf-8") as f:
            b_text = f.read()

        if "# Rs_ohm_per_sq:" not in a_text:
            bad.append(("wafer_A header", "no Rs", "Rs present"))
        # the calculation describes wafer_A, so it must not be copied onto
        # wafer_B, which was never calculated
        if "# Rs_ohm_per_sq:" in b_text:
            bad.append(("wafer_B header", "Rs copied over",
                        "raw data only"))
        print("    calculated results attached to wafer_A only: "
              f"{'# Rs_ohm_per_sq:' in a_text and '# Rs_ohm_per_sq:' not in b_text}")

        if exp.has_unsaved_runs():
            bad.append(("after save", "still unsaved", "clean"))

        # closing with everything saved must not prompt
        dialogs.calls.clear()
        app.on_close()
        if any(c[0] == "askyesno" for c in dialogs.calls):
            bad.append(("close when saved", "prompted", "no prompt"))

    # ...but closing with unsaved work must
    with tempfile.TemporaryDirectory() as tmp:
        dialogs = DialogRecorder()
        import experiments.base_experiment as base_module
        base_module.messagebox = dialogs
        import core.base_app as app_module
        app_module.messagebox = dialogs

        root = tk.Tk()
        app = LabApp(root, VanDerPauwExperiment)
        exp = app.experiment
        app.storage_path = tmp
        app.connect_role("source", NullTransport(), "<simulated>")
        root.update()
        run_vdp(exp, root, 1, points=4)

        dialogs.calls.clear()
        app.on_close()
        prompted = [c for c in dialogs.calls if c[0] == "askyesno"]
        if not prompted:
            bad.append(("close when unsaved", "no prompt", "should warn"))
        else:
            print(f"    close with unsaved work warns: {prompted[0][1]!r}")
    return bad


TESTS = [
    ("run store bookkeeping", _collect_store),
    ("CSV header + table format", _collect_csv_format),
    ("save / delete / group workflow", _collect_save_workflow),
]

if __name__ == "__main__":
    failures = 0
    for name, fn in TESTS:
        bad = fn()
        print(f"  {'ok  ' if not bad else 'FAIL'}  {name}")
        for item in bad[:6]:
            print(f"          {item}")
        failures += len(bad)
    print(f"\n{'PASS' if not failures else f'{failures} FAILURE(S)'}")
    sys.exit(1 if failures else 0)


# --- Wave 0a: these used to return a list of failures that only the
# --- __main__ block inspected. Under pytest a returned value is
# --- ignored, so without these wrappers all of them would pass
# --- unconditionally. The collectors above are unchanged.

def test_store():
    bad = _collect_store()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_csv_format():
    bad = _collect_csv_format()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_save_workflow():
    bad = _collect_save_workflow()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"
