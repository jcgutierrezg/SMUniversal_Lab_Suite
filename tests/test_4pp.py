import pytest

pytestmark = [pytest.mark.gui]

import sys, os

"""Ossila four-point probe: the arithmetic, and a full run in demo mode.

The physics is the part worth guarding. A four-point probe number is
three things multiplied together - the ideal pi/ln2 factor and two
correction factors - and only the first is fixed. The corrections come
from interpolated tables whose edges are where the interesting failures
live, so most of this file is about edges: samples too thick for the
table, too small for it, or with W and L swapped.

The original's own edge handling is the reason for several of these.
Its thickness branch printed a message and left the factor unassigned,
so a thick sample raised NameError one line later.
"""
import math
import tkinter as tk

from core.transports.null_transport import NullTransport
from core.base_app import LabApp
from drivers.dummy_smu import SAMPLE_RESISTANCE
from experiments.ossila_4pp.experiment import Ossila4PPExperiment
import experiments.ossila_4pp.experiment as fourpp_experiment
import experiments.base_experiment as base_experiment
import core.base_app as base_app
from experiments.ossila_4pp import fourpp_math as maths


class DialogRecorder:
    """Swallow dialogs so a headless run doesn't block."""

    def __init__(self):
        self.calls = []

    def _record(self, kind):
        def call(title, message=None, **kw):
            self.calls.append((kind, title, message))
            return True
        return call

    def __getattr__(self, name):
        return self._record(name)


# Three modules raise dialogs, not two - LabApp.on_close() has its own
# messagebox import, and an unstubbed one blocks the suite on the
# *second* test with the first already printed as a pass.
dialogs = DialogRecorder()
fourpp_experiment.messagebox = dialogs
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs


def close_app(root, app):
    for _ in range(20):
        root.update()
    app.on_close()


def run_sync(exp, root):
    """Drive one run to completion on the main thread.

    Wave 3 note: `_begin_run()` is gone - the run lifecycle owns the
    button state now, and `_do_run` opens its own `begin_run()` block.
    The rest is unchanged.

    This harness still calls `_do_run` directly rather than going
    through `run_pressed()`, so **it does not exercise the worker
    thread**. That is fine for what this file is about - the physics,
    the geometry rules and the plotting - but it means a green here says
    nothing about cancellation, ownership or threading. Those live in
    `test_4pp_lifecycle.py`, which drives the real threaded path.
    """
    params = exp._sweep_params()
    exp._check_limits(params)
    try:
        exp._do_run(params)
    finally:
        # Wave 3: work handed back with `app.ui()` is queued and drained
        # by a timer the main thread owns, so that workers never call
        # into Tcl off-thread. Sixty back-to-back `update()` calls take
        # well under one pump interval, so a manual loop like this one
        # has to drain explicitly or the committed row is still sitting
        # in the queue when the assertions run.
        exp.app.drain_ui_now()
        for _ in range(60):
            root.update()
        exp.app.drain_ui_now()
    return bool(exp.tree.get_children())


# ---------------------------------------------------------------
# A. the ideal factor and the full chain
# ---------------------------------------------------------------


def test_sheet_resistance_chain(check):
    check("ideal factor is pi/ln2",
          abs(maths.IDEAL_FACTOR - math.pi / math.log(2)) < 1e-5,
          f"{maths.IDEAL_FACTOR} vs {math.pi / math.log(2):.5f}")

    # Reproduces the original's own worked example: R = 100, t = 180 um,
    # W = 10 mm, L = 27 mm, s = 1.27 mm.
    result = maths.sheet_resistance(100.0, 10.0, 27.0, 180.0)
    check("thickness factor is 1 for a thin sample",
          result["thickness_factor"] == 1.0,
          f"t/s = {0.18 / 1.27:.4f}, below the table")
    check("geometry factor matches the original's table lookup",
          abs(result["geometry_factor"] - 0.8997) < 1e-3,
          f"{result['geometry_factor']:.4f}")
    check("Rs = 4.53236 x R x f_t x f_g",
          abs(result["sheet_resistance_ohm_sq"]
              - 4.53236 * 100.0 * result["thickness_factor"]
              * result["geometry_factor"]) < 1e-9,
          f"{result['sheet_resistance_ohm_sq']:.4f} Ω/□")

    # Units. The original computed resistivity as Rs x t with t in mm,
    # giving ohm-millimetres, and labelled it "mOhm/m". Here it is SI, so
    # it should be exactly 1000x smaller than the old number.
    old_style = result["sheet_resistance_ohm_sq"] * 0.18      # ohm-mm
    check("resistivity is in ohm-metres, 1000x the old ohm-mm figure",
          abs(result["resistivity_ohm_m"] * 1000 - old_style) < 1e-9,
          f"{result['resistivity_ohm_m']:.6g} Ω·m vs {old_style:.4f} Ω·mm")
    check("conductivity is the reciprocal of resistivity",
          abs(result["conductivity_S_per_m"]
              - 1.0 / result["resistivity_ohm_m"]) < 1e-9,
          f"{result['conductivity_S_per_m']:.4f} S/m")

    # ---------------------------------------------------------------
    # B. correction-table edges
    # ---------------------------------------------------------------


def test_correction_edges(check):
    factor, note = maths.thickness_correction(0.01)      # t/s far below table
    check("very thin sample gets no thickness correction", factor == 1.0)
    check("and no warning, because 1.0 is correct there", note == "")

    # The original raised NameError here: its else branch only printed.
    factor, note = maths.thickness_correction(10.0)      # t/s = 7.9, way above
    check("thick sample returns a number rather than raising",
          isinstance(factor, float), f"{factor:.4f}")
    check("thick sample is flagged", bool(note), note[:48])

    factor, note = maths.geometry_correction(0.5, 0.6)   # tiny sample
    check("out-of-table geometry returns 1.0", factor == 1.0)
    check("and says so, because 1.0 over-reports here", bool(note), note[:48])

    raised = None
    try:
        maths.thickness_correction(0.0)
    except ValueError as exc:
        raised = exc
    check("zero thickness is refused", raised is not None)

    # ---------------------------------------------------------------
    # C. reversal averaging
    # ---------------------------------------------------------------


def test_reversal_averaging(check):
    pattern = maths.reversal_pattern(1e-6, 8)
    check("alternates polarity", pattern[:4] == [1e-6, -1e-6, 1e-6, -1e-6])
    check("length matches the count", len(pattern) == 8)

    # A 1 mV thermoelectric offset riding on a +/-5 mV signal. The averaging
    # should recover 5 mV exactly and report the 1 mV it removed.
    signal, offset = 0.005, 0.001
    readings = [signal + offset, -signal + offset] * 4
    recovered, measured_offset = maths.average_reversals(readings)
    check("recovers the true signal", abs(recovered - signal) < 1e-12,
          f"{recovered:.6f} V vs {signal} V")
    check("reports the offset it cancelled",
          abs(measured_offset - offset) < 1e-12, f"{measured_offset:.6f} V")

    # Without reversal the offset would corrupt the reading - this is the
    # whole point of the feature.
    check("an unreversed reading would have been wrong by the offset",
          abs((signal + offset) - signal) > 1e-9, f"{offset} V error")

    # ---------------------------------------------------------------
    # D. the triangular sweep shape
    # ---------------------------------------------------------------


def test_triangular_shape(check):
    levels, start, length = maths.triangular_current_list(-8e-8, 8e-8, 21)
    check("starts at zero", abs(levels[0]) < 1e-15)
    check("ends at zero", abs(levels[-1]) < 1e-15)
    check("middle leg has the requested points", length == 21, f"{length}")
    check("middle leg starts at the start current",
          abs(levels[start] + 8e-8) < 1e-15, f"{levels[start]:.3e}")
    check("middle leg ends at the stop current",
          abs(levels[start + length - 1] - 8e-8) < 1e-15)

    raised = None
    try:
        maths.triangular_current_list(1e-8, 8e-8, 21)     # start not negative
    except ValueError as exc:
        raised = exc
    check("refuses a non-straddling range", raised is not None)

    # ---------------------------------------------------------------
    # E. a full run, both modes, in demo mode
    # ---------------------------------------------------------------


def test_demo_run(check):
    global app, exp, root
    root = tk.Tk()
    app = LabApp(root, Ossila4PPExperiment)
    exp = app.experiment
    app.connect_role("source", NullTransport(), "demo")
    root.update()

    exp.sample_name_var.set("film_A")
    exp.delay_var.set("0")
    exp.width_var.set("10")
    exp.length_var.set("27")
    exp.thickness_var.set("180")

    exp.sweep_mode_var.set("list")
    exp.on_sweep_mode_changed()
    exp.dataset_var.set("list_run")
    check("list run completes", run_sync(exp, root))

    runs = exp.run_store.runs_for("film_A")
    if runs:
        meta = runs[0].metadata
        error = abs(meta["resistance_ohm"] - SAMPLE_RESISTANCE) / SAMPLE_RESISTANCE
        check("recovers the demo sample resistance", error < 0.01,
              f"{meta['resistance_ohm']:.3f} Ω vs {SAMPLE_RESISTANCE} Ω")
        check("R² near 1", meta["fit_r_squared"] > 0.999,
              f"{meta['fit_r_squared']:.6f}")
        check("readings carry the cancelled offset",
              "cancelled_offset_V" in runs[0].readings[0],
              str(sorted(runs[0].readings[0]))[:60])
        check("per-current resistance is recorded",
              "resistance_at_point_ohm" in runs[0].readings[0],
              "salvaged from the working original's per-block fits")
        point_rs = [r["resistance_at_point_ohm"] for r in runs[0].readings]
        check("per-current resistances agree on an ohmic sample",
              max(point_rs) - min(point_rs) < 0.05 * SAMPLE_RESISTANCE,
              f"{min(point_rs):.2f} to {max(point_rs):.2f} Ω")
        check("probe spacing is recorded",
              meta["probe_spacing_mm"] == 1.27)
        check("geometry is recorded with the run",
              meta["width_mm"] == 10 and meta["length_mm"] == 27)

    exp.sweep_mode_var.set("triangular")
    exp.on_sweep_mode_changed()
    exp.dataset_var.set("tri_run")
    exp.tri_points_var.set("21")
    check("triangular run completes", run_sync(exp, root))

    runs = exp.run_store.runs_for("film_A")
    if len(runs) > 1:
        meta = runs[1].metadata
        check("triangular stores every level measured",
              meta["points"] > 21, f"{meta['points']} levels")
        check("but fits only the middle leg",
              meta["points_fitted"] == 21, f"{meta['points_fitted']} fitted")
        error = abs(meta["resistance_ohm"] - SAMPLE_RESISTANCE) / SAMPLE_RESISTANCE
        check("triangular recovers the sample too", error < 0.01,
              f"{meta['resistance_ohm']:.3f} Ω")

    # ---------------------------------------------------------------
    # F. copy to calculation keeps full precision
    # ---------------------------------------------------------------


def test_copy_precision(check):
    items = exp.tree.get_children()
    if items:
        exp.tree.item(items[0], text="☑")
        exp.copy_over()
        root.update()

        stored = exp._run_resistance[items[0]]
        copied = float(exp.calc_r_var.get())
        displayed = float(exp.tree.item(items[0], "values")[3])

        # The table shows 6 significant figures. Copying that string instead
        # of the stored value is the trap that made test_hall_handoff fail
        # intermittently, so this asserts the copy beats the display.
        # Compared relatively: an absolute tolerance on a ~1 kΩ value is
        # really a test of the format string's digit count, not of the copy.
        check("copied value matches the stored resistance exactly",
              copied == stored, f"{copied!r} vs {stored!r}")
        check("and is at least as precise as the displayed one",
              abs(copied - stored) <= abs(displayed - stored),
              f"display {displayed:.6g}, stored {stored:.9g}")
        check("calculation produced a sheet resistance",
              exp.result_vars["sheet"].get() not in ("", "-"),
              exp.result_vars["sheet"].get())

    # ---------------------------------------------------------------
    # G. geometry validation
    # ---------------------------------------------------------------


def test_geometry_validation(check):
    exp.width_var.set("27")
    exp.length_var.set("10")          # swapped
    raised = None
    try:
        exp._geometry_params()
    except ValueError as exc:
        raised = exc
    check("swapped W and L are refused", raised is not None,
          str(raised)[:52] if raised else "")

    exp.width_var.set("10")
    exp.length_var.set("27")
    exp.thickness_var.set("0")
    raised = None
    try:
        exp._geometry_params()
    except ValueError as exc:
        raised = exc
    check("zero thickness is refused", raised is not None)


    # ---------------------------------------------------------------
    # H. the plot follows the ticks and the overlap toggle
    # ---------------------------------------------------------------


def test_plot_filtering(check):
    # Section G left the geometry deliberately invalid; put it back.
    exp.width_var.set("10")
    exp.length_var.set("27")
    exp.thickness_var.set("180")


    def plotted_labels():
        """Dataset labels currently on the axes, ignoring fit lines."""
        return [line.get_label() for line in exp.plot_ax.get_lines()
                if not line.get_label().startswith("_")
                and "fit" not in line.get_label().lower()]


    # Three runs to choose between.
    for name in ("plot_a", "plot_b", "plot_c"):
        exp.sweep_mode_var.set("list")
        exp.on_sweep_mode_changed()
        exp.dataset_var.set(name)
        run_sync(exp, root)

    rows = [i for i in exp.tree.get_children() if i in exp._datasets]
    for row in rows:
        exp.tree.item(row, text="☐")
    exp.plot_overlap_var.set(True)
    exp.refresh_plot()
    root.update()

    # Nothing ticked draws the newest run rather than an empty plot: a run
    # that finishes and leaves blank axes reads as a failure.
    check("nothing ticked draws exactly one run", len(plotted_labels()) == 1,
          str(plotted_labels()))

    exp.tree.item(rows[-3], text="☑")
    exp.tree.item(rows[-2], text="☑")
    exp.refresh_plot()
    root.update()
    check("two ticked with overlap on draws both",
          len(plotted_labels()) == 2, str(plotted_labels()))

    exp.plot_overlap_var.set(False)
    exp.refresh_plot()
    root.update()
    check("overlap off narrows to one", len(plotted_labels()) == 1,
          str(plotted_labels()))

    exp.plot_overlap_var.set(True)
    exp.refresh_plot()
    root.update()
    labels = plotted_labels()
    check("an unticked run stays off the axes",
          not any("plot_c" in l for l in labels), str(labels))

    # Ticking must redraw on the spot, not wait for a button.
    before = len(plotted_labels())
    exp.tree.item(rows[-1], text="☑")
    exp.refresh_plot()
    root.update()
    check("ticking a third run adds it",
          len(plotted_labels()) == before + 1, str(plotted_labels()))

    # ---------------------------------------------------------------
    # I. Calculate is not redundant with Copy ticked
    # ---------------------------------------------------------------


def test_calculate_standalone(check):
    exp.calc_r_var.set("1500")
    exp.thickness_var.set("180")
    exp.calculate()
    root.update()
    thin = exp.result_vars["sheet"].get()

    # Same resistance, different geometry - Calculate has to pick up the
    # new thickness without re-copying the run. This is the job Copy ticked
    # does not do.
    exp.thickness_var.set("4000")      # t/s = 3.15, above the table
    exp.calculate()
    root.update()
    thick = exp.result_vars["sheet"].get()

    check("Calculate works on a typed resistance", thin not in ("", "-"), thin)
    check("Calculate picks up changed geometry", thin != thick,
          f"t=180 -> {thin}, t=4000 -> {thick}")
    check("a thick sample is flagged", bool(exp.calc_status_var.get()),
          exp.calc_status_var.get()[:44])

    # ---------------------------------------------------------------
    # J. geometry is snapshotted at run start
    # ---------------------------------------------------------------


    # ---------------------------------------------------------------
    # K. Wave 4: a result knows where it came from, and when it stops
    #    being true
    # ---------------------------------------------------------------


def _reset_calc_panel():
    """Put the geometry and sample back to the file's working values."""
    exp.width_var.set("10")
    exp.length_var.set("27")
    exp.thickness_var.set("180")
    exp.sample_name_var.set("film_A")


def test_copy_records_provenance(check):
    _reset_calc_panel()
    rows = [i for i in exp.tree.get_children() if i in exp._run_resistance]
    for row in rows:
        exp.tree.item(row, text="☐")
    exp.tree.item(rows[0], text="☑")
    exp.copy_over()
    root.update()

    record = exp.run_store.get(rows[0])
    result = exp._calc_result

    check("a result was issued", result is not None)
    if result is None:
        return
    check("it names the run it came from",
          result.source_run_ids == (record.metadata["run_id"],),
          str(result.source_run_ids))
    check("it names every reading the fit used",
          len(result.source_row_ids) == len(record.readings),
          f"{len(result.source_row_ids)} vs {len(record.readings)} readings")
    check("it names the sample by identity, not by label",
          result.sample_id == record.metadata["sample_id"],
          f"{result.sample_id} vs {record.metadata['sample_id']}")
    check("it records the method and its version",
          result.method_tag == "fourpp_sheet_resistance:1", result.method_tag)
    check("and the panel says so",
          record.metadata["run_id"] in exp.calc_status_var.get(),
          exp.calc_status_var.get())


def test_editing_the_resistance_drops_the_lineage(check):
    """The trap this closes: copy a run, then type over the number.

    The panel would happily keep the previous run's identifiers attached
    to a value that run never produced - a provenance chain that points
    at the wrong measurement is worse than none, because it looks
    checkable.
    """
    _reset_calc_panel()
    rows = [i for i in exp.tree.get_children() if i in exp._run_resistance]
    exp.tree.item(rows[0], text="☑")
    exp.copy_over()
    root.update()
    check("copied result has a source", bool(exp._calc_result.source_run_ids))

    exp.calc_r_var.set("1234.5")
    exp.calculate()
    root.update()
    check("a typed-over value claims no source run",
          exp._calc_result.source_run_ids == (),
          str(exp._calc_result.source_run_ids))
    check("and the panel says it was typed",
          "typed by hand" in exp.calc_status_var.get(),
          exp.calc_status_var.get())


def test_a_calculation_across_two_samples_is_refused(check):
    """§16. The measurement is from film_A; the panel now describes
    film_B. The arithmetic would work perfectly, which is the problem."""
    _reset_calc_panel()
    rows = [i for i in exp.tree.get_children() if i in exp._run_resistance]
    exp.tree.item(rows[0], text="☑")
    exp.copy_over()
    root.update()

    dialogs.calls.clear()
    exp.sample_name_var.set("film_B")
    exp.calculate()
    root.update()

    errors = [c for c in dialogs.calls if c[0] == "showerror"]
    check("it is refused", bool(errors), str(dialogs.calls[-3:]))
    if errors:
        message = errors[-1][2] or ""
        check("naming the sample measured", "film_A" in message, message[:120])
        check("and the sample now selected", "film_B" in message, message[:120])
    check("no number is left standing under the refusal",
          exp.result_vars["sheet"].get() == "-", exp.result_vars["sheet"].get())
    check("and nothing would be saved", exp.calculated_fields() == {})

    _reset_calc_panel()


def test_a_result_goes_stale_when_its_inputs_change(check):
    """§18, and the half of it that matters: a stale value is not merely
    marked, it becomes structurally unable to reach a file."""
    _reset_calc_panel()
    rows = [i for i in exp.tree.get_children() if i in exp._run_resistance]
    exp.tree.item(rows[0], text="☑")
    exp.copy_over()
    root.update()

    fresh = exp.result_vars["sheet"].get()
    check("a fresh result saves", "result_id" in exp.calculated_fields(),
          str(sorted(exp.calculated_fields()))[:80])
    check("and is not greyed",
          exp.result_labels["sheet"].cget("foreground") == "",
          repr(exp.result_labels["sheet"].cget("foreground")))

    exp.thickness_var.set("900")
    root.update()
    check("editing the thickness marks it stale",
          "Stale" in exp.calc_status_var.get(),
          exp.calc_status_var.get())
    check("the number is greyed, not blanked",
          exp.result_vars["sheet"].get() == fresh
          and exp.result_labels["sheet"].cget("foreground") != "",
          f"{exp.result_vars['sheet'].get()} / "
          f"{exp.result_labels['sheet'].cget('foreground')}")
    check("and it can no longer reach a file",
          exp.calculated_fields() == {}, str(exp.calculated_fields())[:60])

    exp.calculate()
    root.update()
    check("recalculating clears the warning",
          "Stale" not in exp.calc_status_var.get(),
          exp.calc_status_var.get())
    check("and the new number differs from the old",
          exp.result_vars["sheet"].get() != fresh,
          f"{fresh} -> {exp.result_vars['sheet'].get()}")

    _reset_calc_panel()
    exp.calculate()
    root.update()


def test_retyping_an_equivalent_value_does_not_cry_wolf(check):
    """A warning that fires on `180` -> `180.0` is a warning that gets
    ignored, which would defeat the point of marking staleness at all."""
    _reset_calc_panel()
    exp.calc_r_var.set("1500")
    exp.calculate()
    root.update()

    exp.thickness_var.set("180.0")
    root.update()
    check("an equivalent value is not stale",
          "Stale" not in exp.calc_status_var.get(),
          exp.calc_status_var.get())

    exp.thickness_var.set("181")
    root.update()
    check("but a different one is", "Stale" in exp.calc_status_var.get(),
          exp.calc_status_var.get())
    _reset_calc_panel()


def test_geometry_snapshot(check):
    exp.width_var.set("10")
    exp.length_var.set("27")
    exp.thickness_var.set("180")
    exp.dataset_var.set("snapshot")

    params = exp._sweep_params()
    try:
        # Blank the thickness box the instant the run starts, as a user
        # mid-edit would. The run must keep the geometry it began with
        # rather than re-reading and discarding a finished measurement.
        exp.thickness_var.set("")
        exp._do_run(params)
    finally:
        exp.app.drain_ui_now()
        for _ in range(60):
            root.update()
        exp.app.drain_ui_now()

    exp.thickness_var.set("180")
    saved = [r for r in exp.run_store.runs_for("film_A")
             if r.metadata["dataset"] == "snapshot"]
    check("a run survives the geometry box being edited mid-run",
          len(saved) == 1, f"{len(saved)} run(s) recorded")
    if saved:
        # Compared with a tolerance, not `==`. Wave 3 moved geometry
        # into the parameter snapshot in metres (house rule 5), so this
        # number has been converted to SI and back, and a round trip
        # through a power of ten is exact for most doubles but not all -
        # 180 um is one of the ones it is not. The tolerance is a
        # statement about floating point, not about the snapshot: what
        # is being checked is that the run kept the geometry it started
        # with rather than the blank box.
        check("and keeps the thickness it started with",
              math.isclose(saved[0].metadata["thickness_um"], 180.0,
                           rel_tol=1e-12),
              f"{saved[0].metadata['thickness_um']}")

    close_app(root, app)


    # ---------------------------------------------------------------
    # L. Wave 4: the result follows the sample, not the text box
    # ---------------------------------------------------------------


def test_result_is_filed_against_the_sample_that_produced_it(check):
    """§17, in the form that actually loses data.

    `save_runs()` used to attach the calculated block to the group whose
    *name* matched the sample box. Those two strings are produced by
    different rules: the store is keyed by `SampleRef.slug`, which
    strips characters a filename cannot carry, while the box was
    compared after only replacing spaces. Give a sample a label with
    punctuation in it - `film #1` - and the two disagree, so the
    calculation is quietly dropped from the file and the raw data saves
    without it. Nothing warns, and the loss is only visible months later
    when the CSV turns out to have no sheet resistance in it.

    Matching on `sample_id` cannot drift, because it is the same
    identifier the run was recorded under.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        local_root = tk.Tk()
        local_app = LabApp(local_root, Ossila4PPExperiment)
        local_exp = local_app.experiment
        local_app.storage_path = tmp
        local_app.connect_role("source", NullTransport(), "demo")
        local_root.update()

        local_exp.sample_name_var.set("film #1")
        local_exp.delay_var.set("0")
        local_exp.width_var.set("10")
        local_exp.length_var.set("27")
        local_exp.thickness_var.set("180")
        local_exp.sweep_mode_var.set("list")
        local_exp.on_sweep_mode_changed()
        local_exp.dataset_var.set("punctuated")

        check("run completes", run_sync(local_exp, local_root))

        # The two spellings this test exists for.
        stored_key = local_exp.run_store.samples()[0]
        by_the_old_rule = local_exp.current_sample_name()
        check("the store key and the box disagree",
              stored_key != by_the_old_rule,
              f"store {stored_key!r} vs box {by_the_old_rule!r}")

        rows = [i for i in local_exp.tree.get_children()
                if i in local_exp._run_resistance]
        local_exp.tree.item(rows[0], text="☑")
        local_exp.copy_over()
        local_root.update()
        check("a result was calculated", local_exp._calc_result is not None)

        local_exp.save_runs()
        local_root.update()

        files = sorted(os.listdir(tmp))
        check("one file written", len(files) == 1, str(files))
        if files:
            with open(os.path.join(tmp, files[0]), encoding="utf-8") as f:
                text = f.read()
            check("and the calculation is in it",
                  "# result_id:" in text,
                  "\n".join(l for l in text.splitlines()
                            if l.startswith("#"))[:200])
            check("with the method and version",
                  "# calculation_method: fourpp_sheet_resistance:1" in text)
            check("and the run it came from",
                  local_exp._calc_result.source_run_ids[0] in text)

        close_app(local_root, local_app)
