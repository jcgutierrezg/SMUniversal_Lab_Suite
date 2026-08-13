"""
The Van der Pauw -> Hall sheet-resistance handoff (Wave 5c).

Replaces `test_hall_handoff.py`, which was entirely about a file round
trip that no longer exists. The two experiments now share a window and
the sheet resistance crosses in memory as a `DerivedResult`, so the
thing to guard changed shape completely rather than moving.

What can go wrong here, in the order it would hurt
--------------------------------------------------
A. **A stale sheet resistance walks into Hall's arithmetic.** A stale
   result already cannot reach Van der Pauw's own CSV; without a
   refusal at the handoff it could still leave through a side door and
   come back as a carrier density. Nothing on screen would say so.

B. **Provenance that is half true.** Typing over the Rs box must drop
   its citation. A header naming a Van der Pauw result that did not
   supply the number in use reads exactly like one that did.

C. **The signature fields drift apart.** The panel samples widgets to
   decide staleness; the calculation builds its own signature from the
   input object. If those two disagree about a field *name*, the result
   reads as permanently stale and its numbers silently stop reaching
   the file - Wave 5a-i shipped exactly that with `thickness_m` against
   `thickness_um`. Wave 5c adds a field to both sides, so it is checked
   directly rather than hoped for.

D. **A carried-over value outliving its sample.** The strip is shared,
   so the two tabs cannot disagree at any one instant - but the
   operator can calculate Van der Pauw, rename the sample, and
   calculate Hall.

Note what is asserted throughout: the value that reaches the *box* and
the result that reaches the *header*, never a displayed label. The old
file failed intermittently for years because it compared a round trip
against `rs_var`, which is formatted to six significant figures - so it
passed below about 1000 Ohm/sq and failed above it, and looked like noise.
"""
import pytest

pytestmark = [pytest.mark.gui]

import tkinter as tk

import core.base_app as base_app
import experiments.base_experiment as base_experiment
import experiments.hall.experiment as hall_experiment
import experiments.vanderpauw.experiment as vdp_experiment
from core.base_app import LabApp
from core.calculation import CalculationRefused
from core.identity import SampleRegistry
from core.ownership import InstrumentOwnership
from core.transports.null_transport import NullTransport
from experiments.hall.experiment import HallExperiment
from experiments.iv_sweep.experiment import IVSweepExperiment
from experiments.vanderpauw.experiment import VanDerPauwExperiment

from hall_harness import run_hall
from vdp_harness import run_vdp

COMBINED = [VanDerPauwExperiment, HallExperiment]
COMBOS = ((1, "+"), (1, "-"), (2, "+"), (2, "-"))


class DialogRecorder:
    """Swallow dialogs and remember them, so a refusal can be asserted.

    Same shape as the recorders in the neighbouring files. Copied rather
    than shared because these files run in separate processes and a
    common helper is one more import for each of them to get right.
    """

    def __init__(self):
        self.calls = []

    def _record(self, kind):
        def call(title, message=None, **kw):
            self.calls.append((kind, title, message))
            return True
        return call

    def __getattr__(self, name):
        return self._record(name)

    def clear(self):
        self.calls.clear()

    def of(self, kind):
        return [c for c in self.calls if c[0] == kind]


dialogs = DialogRecorder()
vdp_experiment.messagebox = dialogs
hall_experiment.messagebox = dialogs
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs


def make_window(spec=None):
    root = tk.Tk()
    app = LabApp(root, spec or COMBINED,
                 ownership=InstrumentOwnership(), samples=SampleRegistry())
    app.connect_role("source", NullTransport(), "demo")
    root.update()
    dialogs.clear()
    return root, app


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
    dialogs.clear()


def measured_vdp(app, root, sample="wafer_A", thickness="1.5"):
    """Four Van der Pauw runs, copied over and calculated."""
    vdp = app.experiment_of(VanDerPauwExperiment)
    vdp.sample_name_var.set(sample)
    vdp.thickness_entry_var.set(thickness)
    for position in (1, 2, 3, 4):
        run_vdp(vdp, root, position, points=5)
    for item in vdp.tree.get_children():
        vdp.tree.item(item, text="\u2611")
    vdp.copy_over()
    vdp.calculate_vdp()
    root.update()
    return vdp


def measured_hall(app, root):
    """Four Hall runs, ticked and copied into the eight voltage boxes."""
    hall = app.experiment_of(HallExperiment)
    for position, sign in COMBOS:
        run_hall(hall, root, position, sign)
    for item in hall.tree.get_children():
        hall.tree.item(item, text="\u2611")
    hall.copy_over()
    hall.calc_B_var.set("0.82")
    hall.calc_I_var.set("1e-4")
    root.update()
    return hall


# ------------------------------------------------------------------
# the happy path, end to end
# ------------------------------------------------------------------
def test_the_sheet_resistance_crosses_with_its_lineage(check):
    """One session: measure, calculate, take Rs, measure, calculate.

    The assertion that matters is the last one. A Hall result must be
    able to name the Van der Pauw runs four steps behind the number in
    its Rs box - that is the whole point of the wave, and it is what a
    retyped number cannot do.
    """
    root, app = make_window()
    try:
        vdp = measured_vdp(app, root)
        hall = app.experiment_of(HallExperiment)

        rs_computed = vdp._calc_result.outputs["Rs_ohm_per_sq"]
        hall.take_rs_from_vdp()
        root.update()

        check("the box holds the computed value",
              float(hall.calc_Rs_var.get()) == float(f"{rs_computed:.9g}"),
              f"{hall.calc_Rs_var.get()} vs {rs_computed!r}")
        check("no dialog on a clean transfer", not dialogs.calls,
              str(dialogs.calls))
        check("the panel says where it came from",
              "vdp_sheet_resistance:1" in hall.rs_source_var.get(),
              hall.rs_source_var.get())

        measured_hall(app, root)
        hall.calculate_hall()
        root.update()

        result = hall._calc_result
        check("Hall calculated", result is not None)
        if result is None:
            return
        check("it names the Van der Pauw result",
              result.source_result_ids == (vdp._calc_result.result_id,),
              result.source_result_ids)

        meta = result.to_metadata()
        line = meta.get("input_sheet_resistance_from", "")
        for run_id in vdp._calc_result.source_run_ids:
            check(f"the header names VdP run {run_id[:14]}...",
                  run_id in line, line)
        check("and keeps them out of Hall's own source runs",
              not any(r in meta["source_run_ids"]
                      for r in vdp._calc_result.source_run_ids),
              meta["source_run_ids"])
    finally:
        close(root, app)


def test_a_fresh_handoff_is_not_stale(check):
    """The §18 regression guard every wired experiment needs.

    Wave 5c adds a signature field, which is precisely the change that
    produced a permanently-stale result last time. A result that is
    stale the instant it is calculated saves no numbers at all and says
    nothing about why.
    """
    root, app = make_window()
    try:
        measured_vdp(app, root)
        hall = app.experiment_of(HallExperiment)
        hall.take_rs_from_vdp()
        measured_hall(app, root)
        hall.calculate_hall()
        root.update()

        result = hall._calc_result
        check("a result was issued", result is not None)
        if result is None:
            return
        check("it is not stale on arrival",
              not result.is_stale(hall._calc_signature()),
              result.stale_because(hall._calc_signature()))
        check("so its numbers reach the file",
              "result_sheet_density_cm2" in hall.calculated_fields(),
              sorted(hall.calculated_fields())[:6])
    finally:
        close(root, app)


def test_the_two_signatures_agree_on_field_names(check):
    """C. The wiring fault, checked directly rather than inferred.

    `signature_difference()` reports a disjoint field set as a wiring
    fault, but only once a result exists to compare. This asserts the
    stronger property: the fields the panel samples and the fields the
    calculation records are the same set, both with a carried-over Rs
    and with a typed one. An extra field on either side is a result that
    can never be fresh.
    """
    root, app = make_window()
    try:
        measured_vdp(app, root)
        hall = app.experiment_of(HallExperiment)
        measured_hall(app, root)

        hall.calc_Rs_var.set("250")
        hall.calculate_hall()
        root.update()
        typed = hall._calc_result
        check("typed: fields match",
              set(typed.signature_fields) == set(dict(hall._calc_signature())),
              f"{sorted(typed.signature_fields)} vs "
              f"{sorted(dict(hall._calc_signature()))}")
        check("typed: no upstream field",
              not any(f.startswith("_upstream") for f in typed.signature_fields),
              typed.signature_fields)

        hall.take_rs_from_vdp()
        hall.calculate_hall()
        root.update()
        carried = hall._calc_result
        check("carried: fields match",
              set(carried.signature_fields) == set(dict(hall._calc_signature())),
              f"{sorted(carried.signature_fields)} vs "
              f"{sorted(dict(hall._calc_signature()))}")
        check("carried: the upstream field is there",
              "_upstream_sheet_resistance" in carried.signature_fields,
              carried.signature_fields)
    finally:
        close(root, app)


# ------------------------------------------------------------------
# A. refusals at the handoff
# ------------------------------------------------------------------
def test_taking_rs_before_calculating_is_refused(check):
    """The state an operator is in when they press the button too early:
    boxes filled on the Van der Pauw tab, no result behind them."""
    root, app = make_window()
    try:
        hall = app.experiment_of(HallExperiment)
        hall.take_rs_from_vdp()
        root.update()

        check("refused", bool(dialogs.of("showerror")), str(dialogs.calls))
        check("the box is untouched", hall.calc_Rs_var.get() == "",
              hall.calc_Rs_var.get())
        check("and nothing is claimed", hall.rs_upstream() is None)
    finally:
        close(root, app)


def test_a_stale_sheet_resistance_is_refused(check):
    """A. The one that matters most.

    Calculate Van der Pauw, then correct the thickness - a misread
    profilometer, which is the realistic version of this. The Rs on
    screen no longer follows from what is on screen, and Van der Pauw's
    own `calculated_fields()` already returns nothing. The handoff must
    close the same door, and say which input moved rather than merely
    refusing.
    """
    root, app = make_window()
    try:
        vdp = measured_vdp(app, root, thickness="1.5")
        hall = app.experiment_of(HallExperiment)

        vdp.thickness_entry_var.set("900")
        root.update()
        dialogs.clear()

        hall.take_rs_from_vdp()
        root.update()

        errors = dialogs.of("showerror")
        check("refused", bool(errors), str(dialogs.calls))
        check("nothing reached the box", hall.calc_Rs_var.get() == "",
              hall.calc_Rs_var.get())
        if errors:
            message = errors[0][2] or ""
            check("says it is out of date", "out of date" in message, message)
            check("and names the input that moved",
                  "thickness" in message, message)
    finally:
        close(root, app)


def test_provide_refuses_rather_than_returning_a_stale_number(check):
    """The same guarantee at the seam rather than through the button.

    Worth asserting separately: the dialog above proves Hall handled a
    refusal, not that Van der Pauw issued one. A future caller that
    forgets to catch `CalculationRefused` should fail loudly, which
    means the refusal has to be an exception and not a None return.
    """
    root, app = make_window()
    try:
        vdp = measured_vdp(app, root)
        fresh = vdp.provide("sheet_resistance")
        check("fresh: a value comes back", fresh.value > 0, fresh.value)
        check("fresh: with the result attached",
              fresh.result is vdp._calc_result)

        vdp.thickness_entry_var.set("900")
        root.update()
        with pytest.raises(CalculationRefused):
            vdp.provide("sheet_resistance")
    finally:
        close(root, app)


def test_a_hall_only_window_has_nothing_to_take_from(check):
    """Wave 5c removed the standalone windows from the launcher, but the
    one-tab shape is still what most of this suite builds - and a button
    that reaches for a tab that is not there must say so rather than
    raise."""
    root, app = make_window(spec=HallExperiment)
    try:
        hall = app.experiment
        check("no provider", app.provider_of("sheet_resistance") is None)
        check("the button is greyed",
              str(hall.rs_take_btn.cget("state")) == "disabled",
              hall.rs_take_btn.cget("state"))

        hall.take_rs_from_vdp()
        root.update()
        check("and pressing it anyway explains itself",
              bool(dialogs.of("showerror")), str(dialogs.calls))
    finally:
        close(root, app)


def test_the_provider_is_found_by_quantity_not_by_class(check):
    """Why `provider_of` exists at all. Hall must not import Van der
    Pauw: a Hall tab that drags the other module in is not a separable
    experiment, and the 4PP computes a sheet resistance too."""
    root, app = make_window()
    try:
        hall = app.experiment_of(HallExperiment)
        vdp = app.experiment_of(VanDerPauwExperiment)
        check("found", app.provider_of("sheet_resistance", exclude=hall) is vdp)
        check("an unclaimed quantity finds nobody",
              app.provider_of("magnetic_field") is None)
        check("and an experiment cannot answer itself",
              app.provider_of("sheet_resistance", exclude=vdp) is None)
        check("Hall's module does not name Van der Pauw",
              "vanderpauw" not in open(
                  hall_experiment.__file__, encoding="utf-8").read().lower()
              .replace("van der pauw", ""),
              "hall/experiment.py imports or names the vanderpauw module")
        check("nor the other way round",
              "hall.experiment" not in open(
                  vdp_experiment.__file__, encoding="utf-8").read())
    finally:
        close(root, app)


# ------------------------------------------------------------------
# B. provenance is all-or-nothing
# ------------------------------------------------------------------
def test_typing_over_the_box_drops_the_citation(check):
    """H5, the same rule the measured voltages follow.

    A chain that is half true reads exactly like one that is whole, so
    an edited box loses its source rather than keeping one that no
    longer describes the value in it.
    """
    root, app = make_window()
    try:
        measured_vdp(app, root)
        hall = app.experiment_of(HallExperiment)
        hall.take_rs_from_vdp()
        root.update()
        check("claimed after the transfer", hall.rs_upstream() is not None)

        hall.calc_Rs_var.set("1234")
        root.update()
        check("dropped after an edit", hall.rs_upstream() is None)
        check("and the panel says so",
              "typed by hand" in hall.rs_source_var.get(),
              hall.rs_source_var.get())

        measured_hall(app, root)
        hall.calc_Rs_var.set("1234")
        hall.calculate_hall()
        root.update()
        result = hall._calc_result
        check("the result claims no upstream", result.source_result_ids == (),
              result.source_result_ids)
        check("and the header does not either",
              "input_sheet_resistance_from" not in result.to_metadata(),
              sorted(result.to_metadata()))
    finally:
        close(root, app)


def test_retyping_the_same_number_keeps_the_citation(check):
    """The complement, and it is not pedantry.

    An operator who clicks into the box and retypes what was already
    there has changed nothing about where the number came from. Dropping
    the citation there would teach them that the provenance line is
    noise, which is how a real drop gets ignored.
    """
    root, app = make_window()
    try:
        measured_vdp(app, root)
        hall = app.experiment_of(HallExperiment)
        hall.take_rs_from_vdp()
        root.update()
        carried = hall.calc_Rs_var.get()

        hall.calc_Rs_var.set("")
        hall.calc_Rs_var.set(carried)
        root.update()
        check("still claimed", hall.rs_upstream() is not None,
              hall.rs_source_var.get())
    finally:
        close(root, app)


# ------------------------------------------------------------------
# D. the sample the number belongs to
# ------------------------------------------------------------------
def test_renaming_the_sample_after_the_handoff_refuses_the_calculation(check):
    """§16 through the carried-over value, and *only* through it.

    Wave 4 decided the transfer itself stays a warning - loading a value
    into a box is not a calculation. The refusal belongs where the
    number is used, and this is that point: a Hall carrier density
    computed against another film's sheet resistance is arithmetically
    perfect and physically meaningless.

    **The eight voltages are typed rather than copied, and that is the
    whole point of the test.** With Hall's own runs behind them, those
    runs would belong to the old sample too and the pre-existing
    source-row check would refuse the calculation on its own - the test
    would pass whether or not the upstream check existed at all.
    Verified by deleting the upstream check and watching the copied
    version stay green.
    """
    root, app = make_window()
    try:
        measured_vdp(app, root, sample="wafer_A")
        hall = app.experiment_of(HallExperiment)
        hall.take_rs_from_vdp()
        root.update()

        # Typed, so `sources` is empty and the upstream result is the
        # only thing that can carry the old sample into the refusal.
        for attr, value in (("v13p_var", 0.11), ("v31p_var", 0.09),
                            ("v24p_var", 0.11), ("v42p_var", 0.09),
                            ("v13n_var", 0.09), ("v31n_var", 0.11),
                            ("v24n_var", 0.09), ("v42n_var", 0.11)):
            getattr(hall, attr).set(str(value))
        hall.calc_B_var.set("0.82")
        hall.calc_I_var.set("1e-4")

        hall.sample_name_var.set("wafer_B")
        root.update()
        dialogs.clear()
        hall.calculate_hall()
        root.update()

        errors = dialogs.of("showerror")
        check("refused", bool(errors), str(dialogs.calls))
        if errors:
            message = errors[0][2] or ""
            check("names both samples",
                  "wafer_A" in message and "wafer_B" in message, message)
            check("and says which input carried it over",
                  "sheet_resistance" in message, message)
        check("and no result was issued", hall._calc_result is None)
    finally:
        close(root, app)


def test_renaming_the_sample_is_refused_at_the_transfer_not_warned(check):
    """What actually happens when the strip is renamed, which is not
    what Wave 5c set out to build.

    The intent was a warning here and a refusal at calculate time. In
    practice Van der Pauw's own staleness signature includes the sample
    name, so renaming the strip makes its result stale and `provide()`
    refuses before any mismatch check runs. Stricter than planned, and
    correct: a sheet resistance calculated for a sample nobody is
    measuring any more should not reach another tab's arithmetic at all.

    Asserted here rather than left implicit, because it is the reason
    the sample-name warning was deleted rather than kept.
    """
    root, app = make_window()
    try:
        measured_vdp(app, root, sample="wafer_A")
        hall = app.experiment_of(HallExperiment)
        hall.sample_name_var.set("wafer_B")
        root.update()
        dialogs.clear()

        hall.take_rs_from_vdp()
        root.update()

        errors = dialogs.of("showerror")
        check("refused", bool(errors), str(dialogs.calls))
        check("nothing reached the box", hall.calc_Rs_var.get() == "",
              hall.calc_Rs_var.get())
        if errors:
            check("and it names the sample as what moved",
                  "_sample" in (errors[0][2] or ""), errors[0][2])
    finally:
        close(root, app)


class DriftingStage:
    """A stage that reports a fixed temperature and opens no port."""

    def __init__(self, temp_c):
        self.temp_c = temp_c

    def is_connected(self):
        return True

    def status(self):
        return type("Status", (), {"temp_c": self.temp_c, "is_stale": False,
                                   "fault": None})()

    def close(self):
        pass

    def pid_off(self):
        pass


def test_stage_drift_warns_but_still_carries_the_value_over(check):
    """The one mismatch check that survives, and the only one that is
    physics rather than a typo.

    Carrier density and mobility are strongly temperature-dependent, so
    an Rs measured at one stage temperature and applied at another
    describes two different samples. It warns rather than refuses
    because the operator may have good reason - a deliberate
    temperature series is exactly this shape.
    """
    root, app = make_window()
    try:
        app.temp_ctrl = DriftingStage(24.0)
        vdp = measured_vdp(app, root)
        # Backdate the recorded stage temperature on the runs behind the
        # result, then move the stage. Driving a real temperature series
        # would be a timing-dependent test of the stage, not of this.
        for run in vdp.run_store.all_runs():
            run.metadata["stage_temp_C"] = 24.0
        app.temp_ctrl = DriftingStage(80.0)

        hall = app.experiment_of(HallExperiment)
        dialogs.clear()
        hall.take_rs_from_vdp()
        root.update()

        warnings = dialogs.of("showwarning")
        check("warned", bool(warnings), str(dialogs.calls))
        if warnings:
            message = warnings[0][2] or ""
            check("names both temperatures",
                  "24.0" in message and "80.0" in message, message)
        check("but carried the value over anyway",
              hall.calc_Rs_var.get() != "", hall.calc_Rs_var.get())
        check("with its provenance intact", hall.rs_upstream() is not None)
    finally:
        close(root, app)


def test_a_matching_sample_transfers_silently(check):
    """The discriminating half of the test above.

    A warning that fires on the ordinary case is a warning nobody reads,
    and this is the ordinary case: one mounted film, two measurements,
    one name on the strip that nobody touched.
    """
    root, app = make_window()
    try:
        measured_vdp(app, root, sample="wafer_A")
        hall = app.experiment_of(HallExperiment)
        dialogs.clear()
        hall.take_rs_from_vdp()
        root.update()
        check("no warning", not dialogs.of("showwarning"), str(dialogs.calls))
        check("no error", not dialogs.of("showerror"), str(dialogs.calls))
    finally:
        close(root, app)


# ------------------------------------------------------------------
# what the file interface used to be
# ------------------------------------------------------------------
def test_the_csv_load_path_is_gone(check):
    """Decided in the plan and asserted here so it cannot creep back.

    Two routes to one number is the failure this codebase is built to
    avoid: they drift, and the one that drifts is the one nobody is
    watching. There is never a Monday Van der Pauw and a Tuesday Hall.
    """
    import importlib
    with pytest.raises(ImportError):
        importlib.import_module("core.vdp_result")

    hall_source = open(hall_experiment.__file__, encoding="utf-8").read()
    check("no file dialog left in Hall",
          "filedialog" not in hall_source)
    check("no old loader", "load_rs_from_vdp" not in hall_source)
    check("no file path recorded as provenance",
          "rs_source_path" not in hall_source)


def test_the_launcher_offers_no_standalone_vdp_or_hall(check):
    """H6. A Hall window opened on its own can no longer obtain a sheet
    resistance by any route but the keyboard, so offering one would be a
    trap rather than a choice. The IV sweep and the 4PP are unaffected -
    different instruments, nothing carried across."""
    import main
    check("the combined session is there", "vdp_hall" in main.WINDOWS)
    check("standalone Van der Pauw is not", "vanderpauw" not in main.WINDOWS)
    check("standalone Hall is not", "hall" not in main.WINDOWS)
    check("the IV sweep still is", "iv_sweep" in main.WINDOWS)
    check("the 4PP still is", "ossila_4pp" in main.WINDOWS)
    check("and IV is still constructible on its own",
          main.WINDOWS["iv_sweep"][1] is IVSweepExperiment)
