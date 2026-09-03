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

import core.base_app as base_app
import experiments.base_experiment as base_experiment
import experiments.hall.experiment as hall_experiment
from core.base_app import LabApp
from core.identity import SampleRegistry
from core.ownership import InstrumentOwnership
from core.transports.null_transport import NullTransport
from experiments.hall import hall_math
from experiments.hall.experiment import HallExperiment

COMBOS = ((1, "+"), (1, "-"), (2, "+"), (2, "-"))


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
    exp.thickness_entry_var.set("1.5")
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
# the complete set (§27)
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
    root, app, exp = make_bench(combos=((1, "+"), (1, "-"), (2, "+")))
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
    """Pos1+ measured twice and Pos2- not at all - the wrong row ticked
    after a remeasurement, which is the easy mistake here."""
    root, app, exp = make_bench(combos=((1, "+"), (1, "+"), (1, "-"), (2, "+")))
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
# mixed samples (§16)
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
# provenance (§17)
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
# staleness (§18)
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
