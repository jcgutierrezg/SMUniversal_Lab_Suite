"""
Full IV sweep run against the simulated sample, with no hardware.

This is the end-to-end check the house rules ask for: transport, driver,
sweep sequencing, the buffer poll, the fit, the results table, the plot
datasets and the CSV all exercised in one go. The dummy sample is a plain
1000 Ω resistor, so the answer is known in advance.

The part worth the most attention is the buffer poll. The originals slept
`round(points * delay * 1.30)` seconds and then read the buffer,
regardless of whether the instrument had finished; with the rounding, a
short sweep waited less than the sweep took. The replacement asks the
instrument how many points it has and waits until that reaches the
requested count. The dummy releases its points against the wall clock
specifically so this loop is genuinely exercised rather than short-
circuited - see DummySMU.start_linear_sweep().

Test 3 is the regression guard for that: a sweep whose nominal duration
rounds *down* to a shorter wait must still return every point.
"""
import pytest

pytestmark = [pytest.mark.slow, pytest.mark.gui]

import os, sys
import math
import tkinter as tk

from core.base_app import LabApp
from core.transports.null_transport import NullTransport
from drivers.dummy_smu import DummySMU, SAMPLE_RESISTANCE
from experiments.iv_sweep.experiment import IVSweepExperiment
import experiments.iv_sweep.experiment as iv_experiment
import experiments.base_experiment as base_experiment
import core.base_app as base_app


# Modal dialogs block a headless test forever. Capture them so the test
# can also assert that the right refusal was raised.
class DialogRecorder:
    def __init__(self):
        self.calls = []

    def showerror(self, title, message, **kw):
        self.calls.append(("error", title, message))

    def showwarning(self, title, message, **kw):
        self.calls.append(("warning", title, message))

    def showinfo(self, title, message, **kw):
        self.calls.append(("info", title, message))

    def askokcancel(self, title, message, **kw):
        self.calls.append(("askokcancel", title, message))
        return True

    def askyesno(self, title, message, **kw):
        self.calls.append(("askyesno", title, message))
        return True


dialogs = DialogRecorder()
iv_experiment.messagebox = dialogs
base_experiment.messagebox = dialogs
# Three modules raise dialogs, not two. LabApp.on_close() asks whether to
# discard unsaved runs, and it does so from its *own* messagebox import -
# so stubbing the two above is not enough. Every test here records a run
# and then closes, which means an unstubbed base_app blocks the suite
# permanently on the *second* test, with the first one's output already
# printed and looking like a pass.
base_app.messagebox = dialogs

# The 2 s pre-sweep settle is faithful to the original but makes a test
# suite crawl. Shortened here only.
iv_experiment.PRE_SWEEP_SETTLE_S = 0.01


def close_app(root, app):
    """Close a test window without leaving queued callbacks behind.

    app.log() posts its console append through root.after(). A line
    logged just before the window is destroyed fires into a dead
    interpreter and makes Tk print `invalid command name ..._append` -
    which reads exactly like a crash and is not one. Draining first
    keeps the suite output honest.
    """
    for _ in range(20):
        root.update()
    app.on_close()


def check(name, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"   {detail}" if detail else ""))
    return [] if condition else [name]


def build_app():
    """A connected experiment in demo mode, via the real connect path."""
    root = tk.Tk()
    app = LabApp(root, IVSweepExperiment)
    app.connect_role("source", NullTransport(), "demo")
    root.update_idletasks()
    return root, app, app.experiment


def run_sync(root, exp, periodic=False):
    """Drive one run to completion on the main thread.

    In the app a measurement runs on a daemon thread and posts results
    back with root.after(). That needs a live mainloop. A headless test
    has none: root.update() will *drain* queued callbacks, but Tk refuses
    to let a foreign thread *register* one at all, so the worker dies on
    its first self.app.ui(...) with "main thread is not in main loop".

    So the test calls the sequencing method directly, exactly as
    test_hall_demo.py calls _measure_polarity(). Everything from
    _do_single() downwards is the real code path - the only thing skipped
    is run_in_background(), which belongs to the app shell and is covered
    by the experiments that already use it.

    The validation and limit-gate steps from run_pressed() are repeated
    here rather than skipped, so a test can still be tripped by a bad
    setup instead of sailing past it.
    """
    params = exp._sweep_params()
    exp._check_limits(params)
    exp._begin_run()
    try:
        if periodic:
            exp._do_periodic(params, exp._periodic_params())
        else:
            exp._do_single(params)
    finally:
        # _do_* queue their table inserts and lamp changes through
        # app.ui(); drain them before anyone asserts on the table.
        for _ in range(50):
            root.update()
    return bool(exp.tree.get_children())


def _collect_voltage_sweep_recovers_resistance():
    """Source V, measure I on a 1000 Ω sample."""
    root, app, exp = build_app()
    bad = []
    try:
        exp.mode_var.set("voltage")
        exp.on_mode_changed()
        exp.start_var.set("-1.0")
        exp.stop_var.set("1.0")
        exp.points_var.set("21")
        exp.delay_var.set("0.01")
        exp.compliance_var.set("0.01")
        exp.dataset_var.set("vsweep")
        exp.sample_name_var.set("demo_sample")

        finished = run_sync(root, exp)
        bad += check("run completed", finished)

        rows = exp.tree.get_children()
        bad += check("one row per sweep", len(rows) == 1, f"{len(rows)} row(s)")
        if not rows:
            return bad

        run = exp.run_store.runs_for("demo_sample")[0]
        resistance = run.metadata["resistance_ohm"]
        error = abs(resistance - SAMPLE_RESISTANCE) / SAMPLE_RESISTANCE
        bad += check("resistance within 1%", error < 0.01,
                     f"{resistance:.6g} Ω vs {SAMPLE_RESISTANCE:g} Ω "
                     f"({error*100:.3f}%)")

        bad += check("all points returned",
                     run.metadata["points_returned"] == 21,
                     f"{run.metadata['points_returned']}/21")
        bad += check("readings stored", len(run.readings) == 21,
                     f"{len(run.readings)}")
        bad += check("readings carry both quantities",
                     "voltage_V" in run.readings[0] and
                     "current_A" in run.readings[0],
                     str(sorted(run.readings[0])))
        bad += check("R² near 1", run.metadata["fit_r_squared"] > 0.99,
                     f"{run.metadata['fit_r_squared']:.6f}")
        bad += check("plot dataset created", len(exp._datasets) == 1)
    finally:
        close_app(root, app)
    return bad


def _collect_current_sweep_recovers_resistance():
    """Source I, measure V on the same sample - the other half of the
    merge, and the half only Long bias had."""
    root, app, exp = build_app()
    bad = []
    try:
        exp.mode_var.set("current")
        exp.on_mode_changed()
        exp.start_var.set("-1e-3")
        exp.stop_var.set("1e-3")
        exp.points_var.set("21")
        exp.delay_var.set("0.01")
        exp.compliance_var.set("20")
        exp.dataset_var.set("isweep")
        exp.sample_name_var.set("demo_sample")

        bad += check("run completed", run_sync(root, exp))

        runs = exp.run_store.runs_for("demo_sample")
        if not runs:
            return bad + check("run recorded", False)

        resistance = runs[0].metadata["resistance_ohm"]
        error = abs(resistance - SAMPLE_RESISTANCE) / SAMPLE_RESISTANCE
        bad += check("resistance within 1%", error < 0.01,
                     f"{resistance:.6g} Ω vs {SAMPLE_RESISTANCE:g} Ω")
        bad += check("mode recorded as current",
                     runs[0].metadata["mode"] == "source_current",
                     runs[0].metadata["mode"])
    finally:
        close_app(root, app)
    return bad


def _collect_short_sweep_returns_every_point():
    """The regression guard for the original's rounded wait.

    10 points at 0.1 s is 1.3 s of sweep. The original computed
    round(1.3) = 1 second, slept that, and read the buffer - so it could
    return fewer points than it asked for. The poll must return all 10.
    """
    root, app, exp = build_app()
    bad = []
    try:
        exp.mode_var.set("voltage")
        exp.on_mode_changed()
        exp.start_var.set("-1.0")
        exp.stop_var.set("1.0")
        exp.points_var.set("10")
        exp.delay_var.set("0.1")           # the exact original case
        exp.compliance_var.set("0.01")
        exp.dataset_var.set("short")
        exp.sample_name_var.set("short_sample")

        original_wait = round(10 * 0.1 * 1.30)   # what the original slept
        bad += check("run completed", run_sync(root, exp))

        runs = exp.run_store.runs_for("short_sample")
        if not runs:
            return bad + check("run recorded", False)

        returned = runs[0].metadata["points_returned"]
        bad += check("no points lost to a rounded wait", returned == 10,
                     f"{returned}/10 (original slept {original_wait} s "
                     f"for a 1.3 s sweep)")
    finally:
        close_app(root, app)
    return bad


def _collect_limit_gate_refuses_out_of_range_stop():
    """A sweep legal at its start and illegal at its stop must be
    refused. Checking only the start value would let it through."""
    root, app, exp = build_app()
    bad = []
    try:
        before = len(dialogs.calls)
        exp.mode_var.set("voltage")
        exp.on_mode_changed()
        exp.start_var.set("-1.0")
        exp.stop_var.set("5000")           # far past the dummy's 200 V
        exp.points_var.set("11")
        exp.delay_var.set("0.01")
        exp.compliance_var.set("0.01")
        exp.run_pressed()
        root.update()

        raised = [c for c in dialogs.calls[before:] if c[0] == "error"]
        bad += check("out-of-range stop refused", bool(raised),
                     raised[0][1] if raised else "no dialog raised")
        bad += check("nothing measured", not exp.tree.get_children())
    finally:
        close_app(root, app)
    return bad


def _collect_equal_start_stop_refused():
    """The originals had a single-point branch here; it is dropped, and
    must be refused clearly rather than sweeping zero span."""
    root, app, exp = build_app()
    bad = []
    try:
        before = len(dialogs.calls)
        exp.start_var.set("1.0")
        exp.stop_var.set("1.0")
        exp.run_pressed()
        root.update()
        raised = [c for c in dialogs.calls[before:] if c[0] == "error"]
        bad += check("zero-span sweep refused", bool(raised),
                     raised[0][2].splitlines()[0] if raised else "none")
    finally:
        close_app(root, app)
    return bad


def _collect_csv_round_trip():
    """A saved file must load back as a clean numeric table."""
    import csv as csv_module
    import io
    import tempfile

    root, app, exp = build_app()
    bad = []
    try:
        exp.mode_var.set("voltage")
        exp.on_mode_changed()
        exp.start_var.set("-0.5")
        exp.stop_var.set("0.5")
        exp.points_var.set("11")
        exp.delay_var.set("0.01")
        exp.compliance_var.set("0.01")
        exp.dataset_var.set("csvrun")
        exp.sample_name_var.set("csv_sample")
        if not run_sync(root, exp):
            return bad + check("run completed", False)

        with tempfile.TemporaryDirectory() as folder:
            app.storage_path = folder
            exp.save_runs()
            files = os.listdir(folder)
            bad += check("one CSV per sample", len(files) == 1, str(files))
            if not files:
                return bad

            bad += check("filename uses the slug",
                         files[0] == "csv_sample_iv_sweep.csv", files[0])

            text = open(os.path.join(folder, files[0]), encoding="utf-8").read()
            header = [line for line in text.splitlines()
                      if line.startswith("#")]
            body = [line for line in text.splitlines()
                    if line and not line.startswith("#")]

            bad += check("header carries the fit",
                         any("resistance_ohm" in line for line in header))
            bad += check("one row per reading plus a header",
                         len(body) == 12, f"{len(body)} lines")

            rows = list(csv_module.DictReader(io.StringIO("\n".join(body))))
            bad += check("rows parse as numbers",
                         all(_is_number(r.get("voltage_V")) and
                             _is_number(r.get("current_A")) for r in rows))
            bad += check("per-run values repeat on every row",
                         len({r.get("dataset") for r in rows}) == 1)

            bad += check("marked saved", not exp.has_unsaved_runs())
    finally:
        close_app(root, app)
    return bad


def _is_number(text):
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False


def _collect_no_autosave():
    """Nothing may reach disk before Save is pressed."""
    import tempfile
    root, app, exp = build_app()
    bad = []
    try:
        with tempfile.TemporaryDirectory() as folder:
            app.storage_path = folder
            exp.mode_var.set("voltage")
            exp.on_mode_changed()
            exp.start_var.set("-0.5")
            exp.stop_var.set("0.5")
            exp.points_var.set("11")
            exp.delay_var.set("0.01")
            exp.compliance_var.set("0.01")
            exp.sample_name_var.set("nosave")
            run_sync(root, exp)

            bad += check("no file written before Save",
                         os.listdir(folder) == [], str(os.listdir(folder)))
            bad += check("unsaved runs flagged", exp.has_unsaved_runs())
    finally:
        close_app(root, app)
    return bad


def _collect_repeats_are_labelled():
    """Repeats must be suffixed the way the original named them, so old
    and new datasets line up."""
    root, app, exp = build_app()
    bad = []
    try:
        exp.mode_var.set("voltage")
        exp.on_mode_changed()
        exp.start_var.set("-0.5")
        exp.stop_var.set("0.5")
        exp.points_var.set("6")
        exp.delay_var.set("0.01")
        exp.compliance_var.set("0.01")
        exp.dataset_var.set("rep")
        exp.runs_var.set("3")
        exp.sample_name_var.set("rep_sample")

        run_sync(root, exp)

        labels = [exp.tree.item(i, "values")[0]
                  for i in exp.tree.get_children()]
        bad += check("three repeats recorded", len(labels) == 3, str(labels))
        bad += check("labelled as the original did",
                     labels == ["rep (1)", "rep (2)", "rep (3)"], str(labels))
    finally:
        close_app(root, app)
    return bad


if __name__ == "__main__":
    bad = []
    for test in (_collect_voltage_sweep_recovers_resistance,
                 _collect_current_sweep_recovers_resistance,
                 _collect_short_sweep_returns_every_point,
                 _collect_limit_gate_refuses_out_of_range_stop,
                 _collect_equal_start_stop_refused,
                 _collect_csv_round_trip,
                 _collect_no_autosave,
                 _collect_repeats_are_labelled):
        print(f"\n{test.__name__}:")
        bad += test()

    print(f"\n{'PASS' if not bad else f'{len(bad)} FAILURE(S): ' + ', '.join(bad)}")
    sys.exit(1 if bad else 0)


# --- Wave 0a: these used to return a list of failures that only the
# --- __main__ block inspected. Under pytest a returned value is
# --- ignored, so without these wrappers all of them would pass
# --- unconditionally. The collectors above are unchanged.

def test_voltage_sweep_recovers_resistance():
    bad = _collect_voltage_sweep_recovers_resistance()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_current_sweep_recovers_resistance():
    bad = _collect_current_sweep_recovers_resistance()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_short_sweep_returns_every_point():
    bad = _collect_short_sweep_returns_every_point()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_limit_gate_refuses_out_of_range_stop():
    bad = _collect_limit_gate_refuses_out_of_range_stop()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_equal_start_stop_refused():
    bad = _collect_equal_start_stop_refused()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_csv_round_trip():
    bad = _collect_csv_round_trip()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_no_autosave():
    bad = _collect_no_autosave()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_repeats_are_labelled():
    bad = _collect_repeats_are_labelled()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"
