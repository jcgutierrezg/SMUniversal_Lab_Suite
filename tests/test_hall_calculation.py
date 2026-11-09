"""
Hall's calculation on the Wave 4 integrity layer.

`test_hall_lifecycle.py` covers the measurement; this covers what
happens to the numbers afterwards.

What Hall adds over Van der Pauw
--------------------------------
Four ticked rows populate *eight* voltage boxes - each run carries a V+
and a V-, its readings at +I and -I - so provenance is one source run
per pair of boxes, not per box. And three inputs the operator types
directly (B, Rs and the current) are not measured by this experiment at
all, so a Hall result is only ever partly traceable. The status line
says which part.

The one that deserves the most attention is `sample_type`. Switching
"Thin film" to "Bulk" changes which carrier density is reported by a
factor of the thickness, and **none of the eight voltages move when it
happens**. A staleness rule that watched only the numbers would miss it
entirely.
"""
import pytest

pytestmark = [pytest.mark.gui]

import math
import tkinter as tk

from hall_harness import run_hall

import smuniversal_lab_suite.core.base_app as base_app
import smuniversal_lab_suite.experiments.base_experiment as base_experiment
import smuniversal_lab_suite.experiments.four_contact as four_contact
import smuniversal_lab_suite.experiments.hall.experiment as hall_experiment
from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.ownership import InstrumentOwnership
from smuniversal_lab_suite.core.transports.null_transport import NullTransport
from smuniversal_lab_suite.core.validation import ValidationError
from smuniversal_lab_suite.experiments.hall import hall_math
from smuniversal_lab_suite.experiments.hall.experiment import HallExperiment

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
hall_experiment.messagebox = dialogs
four_contact.messagebox = dialogs
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs


def make_bench(sample="wafer_A", combos=COMBOS):
    """An app with one run per (position, field sign), all ticked."""
    root = tk.Tk()
    app = LabApp(root, HallExperiment,
                 ownership=InstrumentOwnership(), samples=SampleRegistry())
    exp = app.experiment
    app.connect_role("source", NullTransport(), "demo")
    root.update()

    exp.sample_name_var.set(sample)
    exp.thickness_entry_var.set("1.5 um")
    for position, sign in combos:
        run_hall(exp, root, position, sign)
    return root, app, exp


def close(root, app):
    for _ in range(10):
        root.update()
    try:
        app.on_close()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


def tick_all(exp):
    for item in exp.tree.get_children():
        exp.tree.item(item, text="\u2611")


def fill_calc_inputs(exp, field="0.82", rs="250", current="1e-4"):
    exp.calc_B_var.set(field)
    exp.calc_Rs_var.set(rs)
    exp.calc_I_var.set(current)


# ------------------------------------------------------------------
# the complete set
# ------------------------------------------------------------------
def test_four_distinct_combinations_calculate(check):
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
        fill_calc_inputs(exp)
        exp.calculate_hall()
        root.update()

        check("a result was issued", exp._calc_result is not None)
        check("V_H is on screen", exp.vh_var.get() not in ("", "-"),
              exp.vh_var.get())
        check("carrier density too", exp.ns_var.get() not in ("", "-", "ERR"),
              exp.ns_var.get())
    finally:
        close(root, app)


def test_a_missing_combination_is_refused(check):
    """Three of the four. The eight-term average would still return a
    number; it just would not be this sample's Hall voltage."""
    root, app, exp = make_bench(combos=(("C", "+"), ("C", "-"), ("D", "+")))
    try:
        dialogs.calls.clear()
        tick_all(exp)
        exp.copy_over()
        root.update()

        errors = [c for c in dialogs.calls if c[0] == "showerror"]
        check("it is refused", bool(errors), str(dialogs.calls[-2:]))
        check("nothing was copied into the boxes",
              exp.v13p_var.get() in ("", "-"), exp.v13p_var.get())
    finally:
        close(root, app)


def test_the_same_combination_twice_is_refused(check):
    """PosC+ measured twice and PosD- not at all - the wrong row ticked
    after a remeasurement, which is the easy mistake here."""
    root, app, exp = make_bench(combos=(("C", "+"), ("C", "+"), ("C", "-"),
                                        ("D", "+")))
    try:
        dialogs.calls.clear()
        tick_all(exp)
        exp.copy_over()
        root.update()

        errors = [c for c in dialogs.calls if c[0] == "showerror"]
        check("it is refused", bool(errors), str(dialogs.calls[-2:]))
    finally:
        close(root, app)


# ------------------------------------------------------------------
# mixed samples
# ------------------------------------------------------------------
def test_a_calculation_across_two_samples_is_refused(check):
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
        fill_calc_inputs(exp)
        exp.calculate_hall()
        root.update()
        check("calculated for wafer_A first", exp._calc_result is not None)

        dialogs.calls.clear()
        exp.sample_name_var.set("wafer_B")
        exp.calculate_hall()
        root.update()

        errors = [c for c in dialogs.calls if c[0] == "showerror"]
        check("it is refused", bool(errors), str(dialogs.calls[-2:]))
        if errors:
            message = errors[-1][2] or ""
            check("naming the sample measured", "wafer_A" in message,
                  message[:140])
            check("and the sample now selected", "wafer_B" in message,
                  message[:140])
        check("no carrier density left standing", exp.ns_var.get() == "-",
              exp.ns_var.get())
        check("and nothing would be saved", exp.calculated_fields() == {})
    finally:
        close(root, app)


# ------------------------------------------------------------------
# provenance
# ------------------------------------------------------------------
def test_the_result_names_its_four_runs(check):
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
        fill_calc_inputs(exp)
        exp.calculate_hall()
        root.update()

        result = exp._calc_result
        check("a result was issued", result is not None)
        if result is None:
            return

        stored = {r.metadata["run_id"]
                  for r in exp.run_store.runs_for("wafer_A")}
        check("it names four source runs - not eight",
              len(result.source_run_ids) == 4, str(result.source_run_ids))
        check("and they are the runs that were measured",
              set(result.source_run_ids) == stored,
              f"{sorted(result.source_run_ids)} vs {sorted(stored)}")
        check("it binds to the sample by identity",
              result.sample_id.startswith("smp-"), result.sample_id)

        header = exp.calculated_fields()
        check("the header records every formula involved",
              "hall_voltage:1" in header.get("contributing_methods", ""),
              header.get("contributing_methods", ""))
        check("including the mobility",
              "hall_mobility:1" in header.get("contributing_methods", ""),
              header.get("contributing_methods", ""))
        check("the header carries the result id", "result_id" in header,
              str(sorted(header))[:100])
    finally:
        close(root, app)


def test_typing_over_a_voltage_drops_that_runs_lineage(check):
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
        fill_calc_inputs(exp)
        exp.calculate_hall()
        root.update()
        check("copied result has four sources",
              len(exp._calc_result.source_run_ids) == 4)

        exp.v13p_var.set("0.123456789")
        exp.calculate_hall()
        root.update()

        check("the calculation still happens - a typed value is allowed",
              exp._calc_result is not None)
        if exp._calc_result is None:
            return
        check("but that run is no longer claimed",
              len(exp._calc_result.source_run_ids) == 3,
              str(exp._calc_result.source_run_ids))
        check("and the panel says how much is traceable",
              "3 of 4" in exp.calc_status_var.get(),
              exp.calc_status_var.get())
    finally:
        close(root, app)


# ------------------------------------------------------------------
# staleness
# ------------------------------------------------------------------
def test_changing_the_field_marks_the_result_stale(check):
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
        fill_calc_inputs(exp)
        exp.calculate_hall()
        root.update()

        check("a fresh result saves", "result_id" in exp.calculated_fields(),
              str(sorted(exp.calculated_fields()))[:80])

        exp.calc_B_var.set("0.5")
        root.update()
        check("editing B marks it stale",
              "Stale" in exp.calc_status_var.get(), exp.calc_status_var.get())
        check("and it can no longer reach a file",
              exp.calculated_fields() == {},
              str(exp.calculated_fields())[:60])

        exp.calculate_hall()
        root.update()
        check("recalculating clears the warning",
              "Stale" not in exp.calc_status_var.get(),
              exp.calc_status_var.get())
    finally:
        close(root, app)


def test_switching_to_bulk_marks_the_result_stale(check):
    """The dangerous edit, because nothing numeric moves.

    Thin film reports a sheet density in cm^-2; bulk divides through by
    the thickness and reports cm^-3. Same eight voltages, same B, same
    Rs - a readout that stayed put would be reporting the wrong quantity
    with no indication at all.
    """
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
        fill_calc_inputs(exp)
        exp.sample_type_var.set("Thin film")
        exp.calculate_hall()
        root.update()

        thin = exp.ns_var.get()
        check("thin film reports a sheet density", "cm^-2" in thin, thin)

        exp.sample_type_var.set("Bulk")
        root.update()
        check("switching sample type marks it stale",
              "Stale" in exp.calc_status_var.get(), exp.calc_status_var.get())
        check("and it cannot be saved as it stands",
              exp.calculated_fields() == {})

        exp.calculate_hall()
        root.update()
        check("recalculating reports a bulk density",
              "cm^-3" in exp.ns_var.get(), exp.ns_var.get())
    finally:
        close(root, app)


def test_a_fresh_result_is_never_stale(check):
    """The regression guard for the bug Wave 5a-i shipped.

    There, the calculation stored a thickness under one key while the
    trace sampled another, so every result read as permanently stale and
    its numbers silently stopped reaching the CSV. Hall has fourteen
    watched fields rather than five, so the same drift is that much
    easier to introduce.
    """
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
        fill_calc_inputs(exp)
        exp.calculate_hall()
        root.update()

        result = exp._calc_result
        check("a result was issued", result is not None)
        if result is None:
            return

        current = exp._calc_signature()
        check("it is not stale the instant it is made",
              not result.is_stale(current),
              "; ".join(result.stale_because(current)))
        check("the signature fields agree on both sides",
              set(result.signature_fields) == {n for n, _ in current},
              f"{sorted(result.signature_fields)} vs "
              f"{sorted(n for n, _ in current)}")
    finally:
        close(root, app)


# ------------------------------------------------------------------
# carrier type from the sign of V_H
# ------------------------------------------------------------------
# Rehomed here in Wave 5c. It lived in `test_hall_handoff.py`, whose
# other half was the Van der Pauw result *file* - and that file stopped
# being the interface between the two experiments when the sheet
# resistance began crossing in memory. The file went; this did not,
# because it guards something entirely separate and still true.
#
# Why it is asserted rather than eyeballed: getting the sign convention
# backwards would mislabel every sample the lab measures as the opposite
# carrier type, and every number on the panel would go on looking
# perfectly reasonable.
def test_carrier_type_follows_the_sign_of_vh(check):
    for vh, expected in ((+1e-3, hall_math.P_TYPE),
                         (+1e-12, hall_math.P_TYPE),
                         (-1e-3, hall_math.N_TYPE),
                         (-1e-12, hall_math.N_TYPE),
                         (0.0, hall_math.INDETERMINATE)):
        check(f"V_H = {vh:+g}", hall_math.carrier_type(vh) == expected,
              hall_math.carrier_type(vh))


def test_reversing_the_field_reverses_the_reported_type(check):
    """Swapping the P and N groups is what reversing B does. V_H must
    change sign and nothing else, and the reported type must follow."""
    base = [0.031, -0.012, 0.027, -0.009, 0.030, -0.011, 0.026, -0.010]
    forward = hall_math.hall_voltage(*base)
    reversed_field = hall_math.hall_voltage(*(base[4:] + base[:4]))

    check("V_H changes sign and not magnitude",
          math.isclose(reversed_field, -forward, rel_tol=1e-12),
          f"{reversed_field} vs {-forward}")
    check("so the carrier type flips",
          hall_math.carrier_type(forward)
          != hall_math.carrier_type(reversed_field),
          hall_math.carrier_type(forward))


def test_the_sweep_is_typed_and_refused_when_unreadable(check):
    """Hall used to swap an unreadable level for 100 uA and run anyway."""
    root, app, exp = make_bench(combos=())
    try:
        exp.start_var.set("-47u")
        exp.stop_var.set("47u")
        check("levels between range steps are accepted",
              abs(exp._run_params().level_a - 47e-6) < 1e-12)
        for bad in ("abc", "0", "1u", ""):
            exp.start_var.set(bad)
            try:
                exp._run_params()
                check(f"{bad!r} is refused", False, "accepted")
            except ValidationError:
                pass
            check(f"{bad!r} is left in the box, not replaced",
                  exp.start_var.get() == bad, exp.start_var.get())
    finally:
        close(root, app)


def test_the_magnet_default_is_this_labs(check):
    root, app, exp = make_bench(combos=())
    try:
        check("B starts at the lab magnet's field",
              exp.calc_B_var.get() == "0.487597", exp.calc_B_var.get())
    finally:
        close(root, app)


def measured_mean_current(exp):
    """The mean |I| of every half of every run in the table - all four
    are copied in these tests."""
    halves = [abs(float(record.metadata[key]))
              for item in exp.tree.get_children()
              for record in [exp.run_store.get(item)]
              for key in ("I_mean_pos_A", "I_mean_neg_A")]
    return math.fsum(halves) / len(halves)


def calculate_with_blank_current(exp, root):
    tick_all(exp)
    exp.copy_over()
    fill_calc_inputs(exp, current="")
    exp.calculate_hall()
    root.update()


def test_an_empty_current_box_uses_the_runs_measured_current(check):
    """With no I typed, the carrier density uses the mean current the
    copied runs' halves measured - the current their voltages belong
    to - and not the setup form, which describes the next run."""
    root, app, exp = make_bench()
    try:
        calculate_with_blank_current(exp, root)
        result = exp._calc_result
        check("a result was issued", result is not None)
        if result is None:
            return
        expected = measured_mean_current(exp)
        used = result.inputs["current_a"].value
        check("it used the runs' measured mean current",
              math.isclose(used, expected, rel_tol=1e-12),
              f"{used} vs {expected}")
        check("the header says where the current came from",
              exp._calculated.get("I_A_from") == "measured mean of 4 run(s)",
              exp._calculated.get("I_A_from"))

        # Editing the setup form after the runs must not move it.
        exp.start_var.set("-1m")
        exp.stop_var.set("1m")
        root.update()
        check("the setup form does not change the current used",
              exp.current_for_calculation() == used,
              exp.current_for_calculation())
        check("nor does it make the result stale",
              not result.is_stale(exp._calc_signature()),
              "; ".join(result.stale_because(exp._calc_signature())))
    finally:
        close(root, app)


def test_a_blank_current_result_is_fresh_and_reaches_the_file(check):
    """The 2026-11-09 bench fault. The result stored the current it used
    while the trace sampled the empty box, so it was stale on arrival:
    the panel looked calculated, but the CSV, the summary and Equations
    all saw nothing."""
    root, app, exp = make_bench()
    try:
        calculate_with_blank_current(exp, root)
        result = exp._calc_result
        check("a result was issued", result is not None)
        if result is None:
            return
        current = exp._calc_signature()
        check("it is not stale the instant it is made",
              not result.is_stale(current),
              "; ".join(result.stale_because(current)))
        check("the calculated fields reach the CSV header",
              exp.calculated_fields().get("carrier_type") not in (None, ""),
              sorted(exp.calculated_fields()))
        check("the summary gets the Hall rows",
              bool(exp.summary_contribution(result.sample_id)))
        values, note = exp.equation_values()
        check("Equations shows the numbers", bool(values), note)
        check("the status line is not the stale warning",
              not exp.calc_status_var.get().startswith("Stale"),
              exp.calc_status_var.get())
    finally:
        close(root, app)


def test_typing_a_current_after_a_blank_one_marks_it_stale(check):
    root, app, exp = make_bench()
    try:
        calculate_with_blank_current(exp, root)
        result = exp._calc_result
        check("a result was issued", result is not None)
        if result is None:
            return
        exp.calc_I_var.set("1e-3")
        root.update()
        check("a typed current makes the result stale",
              result.is_stale(exp._calc_signature()))
        check("and the panel says so",
              exp.calc_status_var.get().startswith("Stale"),
              exp.calc_status_var.get())
    finally:
        close(root, app)


def test_an_empty_current_with_typed_voltages_is_refused(check):
    """No measured runs behind the voltages means no measured current.
    Refused rather than guessed from the setup form."""
    root, app, exp = make_bench(combos=())
    try:
        for i, attr in enumerate(exp.VOLTAGE_ATTRS):
            getattr(exp, attr).set(f"{(i + 1) * 1e-4:g}")
        fill_calc_inputs(exp, current="")
        dialogs.calls.clear()
        exp.calculate_hall()
        root.update()
        check("no result was issued", exp._calc_result is None)
        check("the operator was told to type I",
              any(kind == "showerror" and "Type the current into I"
                  in (message or "")
                  for kind, _, message in dialogs.calls),
              dialogs.calls)
    finally:
        close(root, app)


def test_the_plot_marks_the_current_in_use(check):
    """Dashed lines at -I and +I, following the I box."""
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.refresh_plot()
        exp.copy_over()
        root.update()

        def marker_xs():
            return sorted(round(line.get_xdata()[0], 15)
                          for line in exp.plot_ax.lines
                          if line.get_linestyle() == "--")

        expected = measured_mean_current(exp)
        check("blank I: lines at the runs' measured mean current",
              marker_xs() == sorted(round(x, 15)
                                    for x in (-expected, expected)),
              marker_xs())
        legend = exp.plot_ax.get_legend()
        check("the legend names it",
              legend is not None and any(t.get_text().startswith("I used")
                                         for t in legend.get_texts()))

        exp.calc_I_var.set("2e-4")
        root.update()
        check("typed I: the lines follow the box",
              marker_xs() == [-2e-4, 2e-4], marker_xs())

        exp.calc_I_var.set("abc")
        root.update()
        check("an unreadable box draws no lines", marker_xs() == [],
              marker_xs())
    finally:
        close(root, app)
