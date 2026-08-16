"""
The per-sample summary in a running window, and the save-collision
pre-flight (Wave 5c-ii).

What is being guarded, worst first:

A. **A summary going backwards without looking damaged.** VdP and Hall
   both done, summary complete; a week later a quick VdP re-run under
   the same name saves, and the summary is regenerated with Hall marked
   "not calculated". It looks identical to a sample that was never
   Hall-measured. The pre-flight is what makes the operator decide,
   once, whether this session's summary may replace the old one.

B. **The cross-tab write.** Saving Van der Pauw fills the sheet
   resistance; saving Hall completes the *same* file. If the summary
   were written per experiment instead of per sample, each save would
   produce a half-summary and clobber the other tab's half.

C. **A stale half reaching the summary.** `summary_contribution` reads
   through `calculated_fields()`, which is empty for a stale result, so
   a stale section reads as "not calculated" rather than as a number
   the experiment's own CSV would have refused.

D. **The Windows lock.** A summary open in Excel raises PermissionError
   on os.replace. That must be a logged warning, never an aborted data
   save - the CSVs are already on disk by then.

The collision *dialog* is a Toplevel, so these tests answer it by
patching `_ask_summary_collision` rather than driving a real window -
the same reason the message boxes are swapped for a recorder.
"""
import pytest

pytestmark = [pytest.mark.gui]

import os
import csv
import io
import tempfile
import tkinter as tk

import core.base_app as base_app
import experiments.base_experiment as base_experiment
import experiments.hall.experiment as hall_experiment
import experiments.vanderpauw.experiment as vdp_experiment
from core.base_app import LabApp
from core.identity import SampleRegistry
from core.ownership import InstrumentOwnership
from core.transports.null_transport import NullTransport
from experiments.hall.experiment import HallExperiment
from experiments.vanderpauw.experiment import VanDerPauwExperiment

from vdp_harness import run_vdp
from hall_harness import run_hall

COMBINED = [VanDerPauwExperiment, HallExperiment]
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

    def clear(self):
        self.calls.clear()


dialogs = DialogRecorder()
vdp_experiment.messagebox = dialogs
hall_experiment.messagebox = dialogs
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs


def make_app(folder, collision="same"):
    """A combined window whose saves land in `folder`, with the
    collision dialog pre-answered `collision` ('same' | 'separate' |
    'cancel')."""
    root = tk.Tk()
    app = LabApp(root, COMBINED,
                 ownership=InstrumentOwnership(), samples=SampleRegistry())
    app.connect_role("source", NullTransport(), "demo")
    app.storage_path = folder
    app.note_sample_context_changed()
    app._ask_summary_collision = lambda *a, **k: collision
    root.update()
    dialogs.clear()
    return root, app


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
    dialogs.clear()


def measured_vdp(app, root, sample="wafer_A", thickness="1.5"):
    vdp = app.experiment_of(VanDerPauwExperiment)
    vdp.sample_name_var.set(sample)
    vdp.thickness_entry_var.set(thickness)
    # The run harness drives `_do_run` directly and so skips
    # `_ready_to_run`, where a real Run press arms the collision
    # decision. Arm it here the same way, so the save that follows sees
    # the decision a bench session would have taken.
    app.summary_collision_decision(sample)
    for position in (1, 2, 3, 4):
        run_vdp(vdp, root, position, points=5)
    for item in vdp.tree.get_children():
        vdp.tree.item(item, text="\u2611")
    vdp.copy_over()
    vdp.calculate_vdp()
    root.update()
    return vdp


def measured_hall(app, root, take_rs=True):
    hall = app.experiment_of(HallExperiment)
    app.summary_collision_decision(hall.current_sample_name())
    for position, sign in COMBOS:
        run_hall(hall, root, position, sign)
    for item in hall.tree.get_children():
        hall.tree.item(item, text="\u2611")
    hall.copy_over()
    if take_rs:
        hall.take_rs_from_vdp()
    hall.calc_B_var.set("0.82")
    hall.calc_I_var.set("1e-4")
    hall.calculate_hall()
    root.update()
    return hall


def summary_path(folder, sample="wafer_A"):
    return os.path.join(folder, f"{sample}_summary.csv")


def read_table(path):
    with open(path, encoding="utf-8") as f:
        body = "\n".join(l for l in f if not l.startswith("#"))
    return list(csv.DictReader(io.StringIO(body)))


# ------------------------------------------------------------------
# B. the cross-tab write
# ------------------------------------------------------------------
def test_saving_vdp_then_hall_completes_one_summary(check):
    """The file is per sample, not per experiment. Saving Van der Pauw
    fills the sheet resistance and leaves Hall "not calculated"; saving
    Hall later fills the same file rather than clobbering it."""
    with tempfile.TemporaryDirectory() as folder:
        root, app = make_app(folder)
        try:
            vdp = measured_vdp(app, root)
            vdp.save_runs()
            root.update()

            path = summary_path(folder)
            check("a summary exists after the VdP save", os.path.exists(path))
            if os.path.exists(path):
                rows = read_table(path)
                by_meas = {r["measurement"]: r for r in rows}
                check("Van der Pauw has real numbers",
                      any(r["measurement"].startswith("Van der Pauw")
                          and r["quantity"] != "not calculated" for r in rows),
                      rows)
                check("Hall is not calculated yet",
                      any(r["quantity"] == "not calculated" for r in rows),
                      rows)

            hall = measured_hall(app, root)
            hall.save_runs()
            root.update()

            rows = read_table(path)
            check("now Hall has numbers too",
                  any(r["measurement"].startswith("Hall")
                      and r["quantity"] != "not calculated" for r in rows),
                  rows)
            check("carrier type is one of them",
                  any(r["quantity"] == "Carrier type" for r in rows), rows)
            check("still one summary file",
                  len([n for n in os.listdir(folder)
                       if n.endswith("_summary.csv")]) == 1,
                  os.listdir(folder))
        finally:
            close(root, app)


def test_the_summary_names_the_result_each_number_came_from(check):
    with tempfile.TemporaryDirectory() as folder:
        root, app = make_app(folder)
        try:
            vdp = measured_vdp(app, root)
            vdp.save_runs()
            root.update()
            rows = read_table(summary_path(folder))
            rs = [r for r in rows if r["quantity"] == "Sheet resistance"]
            check("the sheet resistance row carries a result id",
                  rs and rs[0]["source"] == vdp._calc_result.result_id,
                  rs)
        finally:
            close(root, app)


# ------------------------------------------------------------------
# A. the summary must not silently go backwards
# ------------------------------------------------------------------
def test_a_full_summary_is_not_written_when_nothing_is_calculated(check):
    """Point 2 of the overwrite decision: never replace a good summary
    with a page of 'not calculated'. A tab that saves raw runs with no
    calculation writes no summary at all."""
    with tempfile.TemporaryDirectory() as folder:
        root, app = make_app(folder)
        try:
            vdp = app.experiment_of(VanDerPauwExperiment)
            vdp.sample_name_var.set("wafer_A")
            for position in (1, 2, 3, 4):
                run_vdp(vdp, root, position, points=5)
            # No copy_over, no calculate: raw runs only.
            vdp.save_runs()
            root.update()

            check("data CSV was written",
                  any(n.endswith("_vanderpauw.csv") for n in os.listdir(folder)),
                  os.listdir(folder))
            check("but no summary",
                  not any(n.endswith("_summary.csv")
                          for n in os.listdir(folder)),
                  os.listdir(folder))
        finally:
            close(root, app)


def test_write_sample_summary_skips_a_sample_with_no_contributions(check):
    """The guard itself, exercised where it actually lives.

    The test above never reaches `write_sample_summary` - with nothing
    calculated, `save_runs` has no `calculated_sample_id` to pass it. So
    this drives the writer directly with an id no tab has a result for,
    which is the real path the empty-guard protects: a sample whose only
    calculation belongs to a *different* sample must not overwrite a good
    summary with a page of 'not calculated'.
    """
    with tempfile.TemporaryDirectory() as folder:
        root, app = make_app(folder)
        try:
            good = summary_path(folder)
            with open(good, "w", encoding="utf-8") as f:
                f.write("# a good earlier summary\n")

            result = app.write_sample_summary("wafer_A", "smp-nobody-has-this")
            check("nothing written", result is None, result)
            check("the earlier summary is untouched",
                  "good earlier summary" in open(good, encoding="utf-8").read())
        finally:
            close(root, app)


def test_a_stale_calculation_reads_as_not_calculated(check):
    """C. A stale half must not reach the summary as a number.

    Calculate Hall, then move an input so the result is stale. Its own
    CSV would refuse it; the summary must too, showing 'not calculated'
    rather than the last good value.
    """
    with tempfile.TemporaryDirectory() as folder:
        root, app = make_app(folder)
        try:
            measured_vdp(app, root)
            hall = measured_hall(app, root)
            # Move a Hall input after calculating: now stale.
            hall.calc_B_var.set("0.5")
            root.update()

            hall.save_runs()
            root.update()

            rows = read_table(summary_path(folder))
            hall_rows = [r for r in rows if r["measurement"].startswith("Hall")]
            check("Hall shows not calculated",
                  hall_rows and all(r["quantity"] == "not calculated"
                                    for r in hall_rows),
                  hall_rows)
        finally:
            close(root, app)


# ------------------------------------------------------------------
# the collision pre-flight
# ------------------------------------------------------------------
def test_first_run_with_no_existing_files_asks_nothing(check):
    """A fresh sample in an empty folder has nothing to collide with, so
    the run proceeds without a dialog and the summary overwrites by
    default this session."""
    with tempfile.TemporaryDirectory() as folder:
        root, app = make_app(folder)
        asked = {"n": 0}
        app._ask_summary_collision = lambda *a, **k: (asked.__setitem__(
            "n", asked["n"] + 1) or "same")
        try:
            app.sample_name_var.set("fresh")
            ok = app.summary_collision_decision("fresh")
            check("run allowed", ok)
            check("nothing asked", asked["n"] == 0, asked["n"])
            check("overwrite armed", app._summary_overwrite)
        finally:
            close(root, app)


def test_existing_files_trigger_the_question_once_per_sample(check):
    """Asked at the first run that finds files, then remembered. A second
    run under the same name and folder does not ask again."""
    with tempfile.TemporaryDirectory() as folder:
        open(os.path.join(folder, "wafer_A_vanderpauw.csv"), "w").close()
        root, app = make_app(folder)
        asked = {"n": 0}
        app._ask_summary_collision = lambda *a, **k: (asked.__setitem__(
            "n", asked["n"] + 1) or "same")
        try:
            app.sample_name_var.set("wafer_A")
            check("first run asks",
                  app.summary_collision_decision("wafer_A") and asked["n"] == 1,
                  asked["n"])
            check("second run does not",
                  app.summary_collision_decision("wafer_A") and asked["n"] == 1,
                  asked["n"])
        finally:
            close(root, app)


def test_cancel_stops_the_run(check):
    with tempfile.TemporaryDirectory() as folder:
        open(os.path.join(folder, "wafer_A_vanderpauw.csv"), "w").close()
        root, app = make_app(folder, collision="cancel")
        try:
            app.sample_name_var.set("wafer_A")
            check("run refused", not app.summary_collision_decision("wafer_A"))
            check("no decision recorded, so it will ask again",
                  app._summary_decided_for is None)
        finally:
            close(root, app)


def test_the_collision_prompt_uses_the_messagebox_seam(check):
    """The bug this file shipped and had to fix.

    The first version of the prompt was a hand-rolled `Toplevel` with
    `grab_set()` and `wait_window()`. Nothing can stub that. Every GUI
    test in this suite neutralises dialogs by monkeypatching the
    `messagebox` module inside the module under test, so a window built
    by hand bypasses the seam entirely - and any headless test that
    pressed Run with a matching file in the save folder blocked forever,
    showing nothing that pointed at the cause. The house rules had it
    written down before this wave was started.

    Asserted structurally rather than by trying to detect a hang: a test
    that hangs cannot report anything, which is precisely what made the
    original so unpleasant to diagnose.
    """
    import inspect
    source = inspect.getsource(LabApp._ask_summary_collision)
    # Read the code, not the prose. The docstring explains *why* there is
    # no Toplevel here, and naming the thing it avoids would otherwise
    # trip the very check it is explaining - a test failing on its own
    # rationale. `getdoc()` re-indents, so the docstring is cut out by
    # its delimiters in the raw source rather than by string match.
    first = source.find('"""')
    second = source.find('"""', first + 3)
    body = source[:first] + source[second + 3:] if first != -1 else source

    check("asks through messagebox", "messagebox." in body, body[:200])
    check("does not build its own window",
          "Toplevel" not in body,
          "a hand-rolled dialog cannot be stubbed and will hang the suite")
    check("does not wait on a window",
          "wait_window" not in body, body[:200])


def test_a_stubbed_prompt_lets_a_colliding_run_proceed(check):
    """The behavioural half: with the standard recorder in place - the
    same one every other GUI file installs - a run that collides is not
    blocked, and the recorder sees the question."""
    with tempfile.TemporaryDirectory() as folder:
        open(os.path.join(folder, "wafer_A_vanderpauw.csv"), "w").close()
        root, app = make_app(folder)
        # Drop the per-test override so the real method runs against the
        # module-level recorder, exactly as an unrelated GUI test would.
        del app._ask_summary_collision
        try:
            app.sample_name_var.set("wafer_A")
            dialogs.clear()
            allowed = app.summary_collision_decision("wafer_A")
            check("the run was allowed", allowed)
            check("and the question went through messagebox",
                  any(c[0] == "askyesnocancel" for c in dialogs.calls),
                  [c[0] for c in dialogs.calls])
        finally:
            close(root, app)


def test_write_sample_summary_skips_a_sample_with_no_calculation(check):
    """The inner guard, exercised directly.

    `save_runs` only calls `write_sample_summary` when its tab has a
    calculated result, so the outer path never reaches the all-empty
    branch. But the app method is called per sample and must defend
    itself: asked to summarise a sample nothing has calculated, it must
    write nothing rather than a file full of 'not calculated' that would
    replace a good summary. Called here with a made-up id that no tab
    can match, which is exactly what a stale or renamed sample produces.
    """
    with tempfile.TemporaryDirectory() as folder:
        root, app = make_app(folder)
        try:
            result = app.write_sample_summary("ghost", "smp-nobody-has-this")
            check("nothing was written", result is None, result)
            check("and no file appeared",
                  not any(n.endswith("_summary.csv")
                          for n in os.listdir(folder)),
                  os.listdir(folder))
        finally:
            close(root, app)


def test_pressing_run_is_blocked_when_the_collision_is_cancelled(check):
    """The gate, exercised through the real Run path rather than by
    calling the decision directly.

    Without this, the gate could be deleted from every `_ready_to_run`
    and no test would notice - the decision function would still pass
    its own unit tests while nothing consulted it. Cancelling the
    collision must stop `run_pressed` before it reaches the switch-box
    confirm, so the operator is never sent to the fixture for a run that
    was refused on the way in.
    """
    with tempfile.TemporaryDirectory() as folder:
        open(os.path.join(folder, "wafer_A_vanderpauw.csv"), "w").close()
        root, app = make_app(folder, collision="cancel")
        try:
            vdp = app.experiment_of(VanDerPauwExperiment)
            vdp.sample_name_var.set("wafer_A")
            vdp.pos_var.set(1)
            vdp.points_var.set("5")
            dialogs.clear()

            vdp.run_pressed()
            root.update()

            titles = [c[1] for c in dialogs.calls]
            check("the switch-box confirm never appeared",
                  "Confirm position" not in titles, titles)
            check("no run started", not vdp.run_in_progress())
        finally:
            close(root, app)


def test_keep_separate_suffixes_the_summary(check):
    """'Continue - keep separate' must not overwrite the old summary. The
    new one auto-suffixes like every data file."""
    with tempfile.TemporaryDirectory() as folder:
        # An old summary already sits in the folder.
        old = summary_path(folder)
        with open(old, "w", encoding="utf-8") as f:
            f.write("# old summary\nmeasurement,quantity,value,unit,source\n")
        root, app = make_app(folder, collision="separate")
        try:
            measured_vdp(app, root)
            app.experiment_of(VanDerPauwExperiment).save_runs()
            root.update()

            summaries = sorted(n for n in os.listdir(folder)
                               if n.endswith(".csv") and "summary" in n)
            check("the old summary is untouched",
                  open(old, encoding="utf-8").readline().strip()
                  == "# old summary",
                  open(old, encoding="utf-8").readline())
            check("and a suffixed one was added",
                  any(n != "wafer_A_summary.csv" for n in summaries),
                  summaries)
        finally:
            close(root, app)


def test_same_sample_overwrites_the_summary(check):
    with tempfile.TemporaryDirectory() as folder:
        old = summary_path(folder)
        with open(old, "w", encoding="utf-8") as f:
            f.write("# old summary\nmeasurement,quantity,value,unit,source\n")
        root, app = make_app(folder, collision="same")
        try:
            measured_vdp(app, root)
            app.experiment_of(VanDerPauwExperiment).save_runs()
            root.update()

            summaries = [n for n in os.listdir(folder)
                         if n.endswith(".csv") and "summary" in n]
            check("still just the one summary file",
                  summaries == ["wafer_A_summary.csv"], summaries)
            check("and it was replaced, not the old text kept",
                  "old summary" not in open(old, encoding="utf-8").read(),
                  "overwrite did not happen")
        finally:
            close(root, app)


def test_changing_the_sample_name_rearms_the_question(check):
    with tempfile.TemporaryDirectory() as folder:
        open(os.path.join(folder, "wafer_A_vanderpauw.csv"), "w").close()
        open(os.path.join(folder, "wafer_B_vanderpauw.csv"), "w").close()
        root, app = make_app(folder)
        asked = {"n": 0}
        app._ask_summary_collision = lambda *a, **k: (asked.__setitem__(
            "n", asked["n"] + 1) or "same")
        try:
            app.sample_name_var.set("wafer_A")
            app.summary_collision_decision("wafer_A")
            app.sample_name_var.set("wafer_B")       # trace re-arms
            app.summary_collision_decision("wafer_B")
            check("asked once per distinct sample", asked["n"] == 2, asked["n"])
        finally:
            close(root, app)


def test_renaming_the_sample_clears_a_stale_overwrite_flag(check):
    """The trace does something the (sample, folder) keying does not.

    `summary_collision_decision` re-keys on the name it is passed, so a
    run under a new name asks again on its own. But `_summary_overwrite`
    is read at *save* time, and if the operator settles on 'overwrite'
    for one sample and then renames the box, that True must not carry
    onto the next sample. The trace is what clears it. Without the
    trace, the flag from the first sample would still be set with no run
    in between to reset it.
    """
    with tempfile.TemporaryDirectory() as folder:
        root, app = make_app(folder)
        try:
            app.sample_name_var.set("first")
            app._summary_overwrite = True
            app._summary_decided_for = ("first", app.storage_path)

            app.sample_name_var.set("second")     # trace should re-arm
            check("overwrite flag cleared by the rename",
                  app._summary_overwrite is False, app._summary_overwrite)
            check("and the decision is re-armed",
                  app._summary_decided_for is None, app._summary_decided_for)
        finally:
            close(root, app)


def test_retyping_the_same_name_does_not_wipe_the_decision(check):
    """The bug this file caught while it was being written.

    The sample-name trace fires on *every* write, including setting the
    variable to the value it already holds. Re-arming on those silently
    turned a chosen overwrite back into a suffix by the time Save ran -
    the run armed 'same sample', an incidental re-set of the name
    cleared it, and the save quietly wrote `_summary_1` instead of
    replacing the file the operator meant to replace. Only a genuine
    change to a different name may re-arm.
    """
    with tempfile.TemporaryDirectory() as folder:
        open(os.path.join(folder, "wafer_A_vanderpauw.csv"), "w").close()
        root, app = make_app(folder, collision="same")
        try:
            app.sample_name_var.set("wafer_A")
            check("armed to overwrite by the run",
                  app.summary_collision_decision("wafer_A")
                  and app._summary_overwrite)

            app.sample_name_var.set("wafer_A")       # same value, trace fires
            root.update()
            check("still armed to overwrite", app._summary_overwrite,
                  "a no-op name write wiped a valid decision")
            check("and still recorded, so Save will not re-ask",
                  app._summary_decided_for is not None)
        finally:
            close(root, app)


# ------------------------------------------------------------------
# D. the Windows lock
# ------------------------------------------------------------------
def test_a_locked_summary_does_not_fail_the_save(check):
    """os.replace onto a file open in Excel raises PermissionError on
    Windows. The data CSVs are already written; the summary refresh must
    degrade to a logged warning, never an aborted save."""
    with tempfile.TemporaryDirectory() as folder:
        root, app = make_app(folder)
        try:
            vdp = measured_vdp(app, root)

            real_replace = os.replace

            def deny_summary(src, dst):
                if dst.endswith("_summary.csv"):
                    raise PermissionError("in use by another process")
                return real_replace(src, dst)

            base_app.os.replace = deny_summary
            try:
                vdp.save_runs()
                root.update()
            finally:
                base_app.os.replace = real_replace

            check("the data CSV was still written",
                  any(n.endswith("_vanderpauw.csv") for n in os.listdir(folder)),
                  os.listdir(folder))
            check("no summary was left behind",
                  not any(n.endswith("_summary.csv")
                          for n in os.listdir(folder)),
                  os.listdir(folder))
            check("and the save reported success, not failure",
                  any(c[1] == "Saved" for c in dialogs.calls),
                  [c[1] for c in dialogs.calls])
        finally:
            close(root, app)
