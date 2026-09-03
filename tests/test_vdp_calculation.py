"""
Van der Pauw's calculation on the Wave 4 integrity layer.

`test_vdp_lifecycle.py` covers the measurement; this covers what happens
to the numbers afterwards. Split because they fail for different reasons
and at different speeds: the lifecycle file blocks a fake instrument at
named stages and takes seconds, this one presses buttons and takes
milliseconds.

What is guarded here
--------------------
A. the four-position set is complete and distinct
B. mixed-sample inputs are refused
C. the result names the runs it came from
D. staleness, and the save-side gate that makes it mean something

The one that matters most is D's second half. Greying a number is a hint
the operator can ignore; `calculated_fields()` returning nothing is not
ignorable, and it is the difference between warning about bad data and
being unable to write it.
"""
import pytest

pytestmark = [pytest.mark.gui]

import tkinter as tk

from vdp_harness import run_vdp

import core.base_app as base_app
import experiments.base_experiment as base_experiment
import experiments.vanderpauw.experiment as vdp_experiment
from core.base_app import LabApp
from core.identity import SampleRegistry
from core.ownership import InstrumentOwnership
from core.transports.null_transport import NullTransport
from experiments.vanderpauw.experiment import VanDerPauwExperiment


class DialogRecorder:
    """Swallow dialogs, and remember them so refusals can be asserted."""

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
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs


def make_bench(sample="wafer_A", positions=(1, 2, 3, 4)):
    """An app with one run per position already measured and ticked."""
    root = tk.Tk()
    app = LabApp(root, VanDerPauwExperiment,
                 ownership=InstrumentOwnership(), samples=SampleRegistry())
    exp = app.experiment
    app.connect_role("source", NullTransport(), "demo")
    root.update()

    exp.sample_name_var.set(sample)
    exp.thickness_entry_var.set("180")
    for pos in positions:
        run_vdp(exp, root, pos)
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


# ------------------------------------------------------------------
# A. the complete set
# ------------------------------------------------------------------
def test_four_distinct_positions_calculate(check):
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
        root.update()

        check("a result was issued", exp._calc_result is not None)
        check("Rs is on screen", exp.rs_var.get() not in ("", "-", "ERR"),
              exp.rs_var.get())
        check("and rho with it", exp.rho_var.get() not in ("", "-"),
              exp.rho_var.get())
    finally:
        close(root, app)


def test_three_positions_are_refused(check):
    """An incomplete set must not be averaged into a plausible Rs.

    Pos1 and Pos2 make Rh, Pos3 and Pos4 make Rv. Miss one and the
    solver still returns a number - it just isn't this sample's sheet
    resistance.
    """
    root, app, exp = make_bench(positions=(1, 2, 3))
    try:
        dialogs.calls.clear()
        tick_all(exp)
        exp.copy_over()
        root.update()

        errors = [c for c in dialogs.calls if c[0] == "showerror"]
        check("it is refused", bool(errors), str(dialogs.calls[-2:]))
        check("nothing was calculated", exp._calc_result is None)
    finally:
        close(root, app)


def test_the_same_position_twice_is_refused(check):
    """Two runs at Pos1 and none at Pos4 is the wrong row ticked, not an
    unfinished measurement - and it is the easy mistake to make when a
    position has been remeasured."""
    root, app, exp = make_bench(positions=(1, 1, 2, 3))
    try:
        dialogs.calls.clear()
        tick_all(exp)
        exp.copy_over()
        root.update()

        errors = [c for c in dialogs.calls if c[0] == "showerror"]
        check("it is refused", bool(errors), str(dialogs.calls[-2:]))
        if errors:
            message = errors[-1][2] or ""
            check("and says which position is doubled",
                  "Pos1" in message, message[:140])
    finally:
        close(root, app)


# ------------------------------------------------------------------
# B. mixed samples
# ------------------------------------------------------------------
def test_a_calculation_across_two_samples_is_refused(check):
    """The measurements are wafer_A's; the panel now says wafer_B.

    The arithmetic would work perfectly, which is exactly the problem.
    """
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
        root.update()
        check("calculated for wafer_A first", exp._calc_result is not None)

        dialogs.calls.clear()
        exp.sample_name_var.set("wafer_B")
        exp.calculate_vdp()
        root.update()

        errors = [c for c in dialogs.calls if c[0] == "showerror"]
        check("it is refused", bool(errors), str(dialogs.calls[-2:]))
        if errors:
            message = errors[-1][2] or ""
            check("naming the sample measured", "wafer_A" in message,
                  message[:140])
            check("and the sample now selected", "wafer_B" in message,
                  message[:140])
        check("no number is left standing under the refusal",
              exp.rs_var.get() == "-", exp.rs_var.get())
        check("and nothing would be saved", exp.calculated_fields() == {})
    finally:
        close(root, app)


# ------------------------------------------------------------------
# C. provenance
# ------------------------------------------------------------------
def test_the_result_names_its_four_runs(check):
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
        root.update()

        result = exp._calc_result
        check("a result was issued", result is not None)
        if result is None:
            return

        stored = {r.metadata["run_id"]
                  for r in exp.run_store.runs_for("wafer_A")}
        check("it names four source runs",
              len(result.source_run_ids) == 4, str(result.source_run_ids))
        check("and they are the runs that were measured",
              set(result.source_run_ids) == stored,
              f"{sorted(result.source_run_ids)} vs {sorted(stored)}")
        check("it records the method and version",
              result.method_tag == "vdp_sheet_resistance:1", result.method_tag)
        check("it binds to the sample by identity",
              result.sample_id.startswith("smp-"), result.sample_id)

        header = exp.calculated_fields()
        check("the header carries the result id", "result_id" in header,
              str(sorted(header))[:100])
        check("and still carries Rs_ohm_per_sq for the Hall handoff",
              "Rs_ohm_per_sq" in header, str(sorted(header))[:100])
    finally:
        close(root, app)


def test_typing_over_a_box_drops_that_lineage(check):
    """A hand-edited value must not inherit the run it replaced.

    A provenance chain pointing at the wrong measurement is worse than
    none at all, because it looks checkable.
    """
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
        root.update()
        check("copied result has four sources",
              len(exp._calc_result.source_run_ids) == 4)

        exp.pos_vars[0].set("1234.5")
        exp.calculate_vdp()
        root.update()

        check("the calculation still happens - a typed value is allowed",
              exp._calc_result is not None and
              exp.rs_var.get() not in ("", "-", "ERR"), exp.rs_var.get())
        if exp._calc_result is None:
            return
        check("but the edited box's run is no longer claimed",
              len(exp._calc_result.source_run_ids) == 3,
              str(exp._calc_result.source_run_ids))
        check("and the panel says how much is traceable",
              "3 of 4" in exp.calc_status_var.get(),
              exp.calc_status_var.get())
    finally:
        close(root, app)


# ------------------------------------------------------------------
# D. staleness
# ------------------------------------------------------------------
def test_a_result_goes_stale_and_cannot_be_saved(check):
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
        root.update()

        fresh = exp.rs_var.get()
        check("a fresh result saves", "result_id" in exp.calculated_fields(),
              str(sorted(exp.calculated_fields()))[:80])

        exp.thickness_entry_var.set("900")
        root.update()
        check("editing the thickness marks it stale",
              "Stale" in exp.calc_status_var.get(), exp.calc_status_var.get())
        check("the number is greyed, not blanked",
              exp.rs_var.get() == fresh, exp.rs_var.get())
        check("and it can no longer reach a file",
              exp.calculated_fields() == {},
              str(exp.calculated_fields())[:60])

        exp.calculate_vdp()
        root.update()
        check("recalculating clears the warning",
              "Stale" not in exp.calc_status_var.get(),
              exp.calc_status_var.get())
        check("and rho moved with the thickness",
              "result_id" in exp.calculated_fields())
    finally:
        close(root, app)


def test_a_fresh_result_is_never_stale(check):
    """The regression guard for a bug this wave actually shipped.

    The calculation stored its thickness under `thickness_m` while the
    staleness trace sampled `thickness_um`. The two signatures could
    then never match, so every result read as permanently stale and its
    numbers silently stopped reaching the CSV - no error, no dialog,
    just a header with no Rs in it.

    Nothing about that is visible by inspection, and it would have
    survived any test that only checked the arithmetic. Asserting that a
    result is fresh the instant it is calculated is what catches it, and
    `DerivedResult.stale_because()` is what says why when it does.
    """
    root, app, exp = make_bench()
    try:
        tick_all(exp)
        exp.copy_over()
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
