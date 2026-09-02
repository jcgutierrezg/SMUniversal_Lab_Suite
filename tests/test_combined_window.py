"""
The combined Van der Pauw + Hall window (Wave 5b).

Everything here guards a failure that is **silent**. That is the whole
selection rule: a window hosting two experiments does not crash when it
gets this wrong, it goes on looking correct while one of the two reads a
number that belongs to the other, or drives a heater nobody is watching.

The five it covers, in order of how badly they would hurt:

A. **One temperature stage per window.** Two tabs each holding their own
   `TemperatureController` would be two objects opening one COM port -
   which fails at the bench and *cannot* fail in this suite, because no
   test has a serial stage attached. So the test is structural: the
   controller is one object, the panel is built once, and tearing down
   one experiment does not close the port the other is using.

B. **One sample and one thickness.** A Hall carrier density computed
   from a thickness that the Van der Pauw sheet resistance did not use
   is wrong in a way that looks entirely reasonable on screen. The
   variables are shared objects, not copies kept in step, so this
   asserts identity rather than equality - two variables holding the
   same value today prove nothing about tomorrow.

C. **The session counter and save path are the app's.** Before Wave 5b
   each setup panel did `exp.app.measnum_var = tk.IntVar(...)` from
   inside a panel. In a one-experiment window that was merely the wrong
   layer; in a two-tab window the second tab silently rebound the app
   attribute and the first tab's counter froze at whatever it last
   showed. No error, no wrong number, just a readout that quietly
   stopped being true.

D. **The run gate.** The tabs share one SMU, so one measurement runs at
   a time. Ownership is the guarantee; this is about *when* the refusal
   arrives - before the operator has been sent to the switch box.

E. **Closing the window sees both tabs.** `on_close()` used to ask
   `self.experiment`, singular, which in a two-tab window would have
   discarded the other tab's measurements without mentioning them.

Single-experiment windows are exercised too, because they are still the
common case and the shell now has two shapes.
"""
import pytest

pytestmark = [pytest.mark.gui]

import tkinter as tk

import core.base_app as base_app
import experiments.base_experiment as base_experiment
import experiments.hall.experiment as hall_experiment
import experiments.vanderpauw.experiment as vdp_experiment
from core.base_app import LabApp
from core.identity import SampleRegistry
from core.ownership import InstrumentOwnership
from core.run_control import ShutdownStatus
from core.run_store import Run
from devices.temperature_control import StageShutdownReport
from experiments.hall.experiment import HallExperiment
from experiments.iv_sweep.experiment import IVSweepExperiment
from experiments.ossila_4pp.experiment import Ossila4PPExperiment
from experiments.vanderpauw.experiment import VanDerPauwExperiment

COMBINED = [VanDerPauwExperiment, HallExperiment]


class DialogRecorder:
    """Swallow dialogs, and remember them so a refusal can be asserted.

    Same shape as the one in `test_vdp_calculation.py`. Copied rather
    than shared because these files run in separate processes and a
    common helper module would be one more import for each of them to
    get right.
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


dialogs = DialogRecorder()
vdp_experiment.messagebox = dialogs
hall_experiment.messagebox = dialogs
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs


class FakeStage:
    """A temperature controller that opens no port and counts calls.

    The real one is only interesting here for how many of it exist and
    who closes it, so the fake records exactly that.

    It implements `confirm_pid_off()` rather than `pid_off()` because
    that is what the close path calls: a stage that cannot say whether
    its heater stopped is reported as UNCERTAIN, so a fake left on the
    old bare command would put a modal warning into every test in this
    file. Failure-injection versions of this contract live in
    `tests/test_shutdown_safety.py`.
    """

    def __init__(self):
        self.closed = 0
        self.pid_offs = 0
        self.connected = False

    def is_connected(self):
        return self.connected

    def close(self):
        self.closed += 1
        self.connected = False

    def confirm_pid_off(self):
        self.pid_offs += 1
        if not self.connected:
            return StageShutdownReport(ShutdownStatus.NOT_ATTEMPTED,
                                       "the stage was not connected")
        return StageShutdownReport(ShutdownStatus.CONFIRMED,
                                   "the stage reports IDLE after OFF")


def make_app(spec=None, stage=None):
    """A window hosting `spec`, with its own ownership and sample
    registry so nothing leaks between tests."""
    root = tk.Tk()
    app = LabApp(root, spec or COMBINED,
                 ownership=InstrumentOwnership(), samples=SampleRegistry())
    if stage is not None:
        app.temp_ctrl = stage
    root.update()
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


def tabs(app):
    """The two hosted experiments, Van der Pauw first."""
    return app.experiment_of(VanDerPauwExperiment), app.experiment_of(HallExperiment)


# --- A. one temperature stage per window -----------------------------

def test_one_temperature_controller_for_the_window(check):
    """Both tabs must reach the same controller object.

    Equality is not the assertion. Two controllers configured for the
    same port would compare however their class says and would still be
    two objects opening one COM port.
    """
    root, app = make_app()
    vdp, hall = tabs(app)
    try:
        check("vdp sees the app's controller", vdp.temp_ctrl is app.temp_ctrl)
        check("hall sees the same one", hall.temp_ctrl is app.temp_ctrl)
        check("and it is one object", vdp.temp_ctrl is hall.temp_ctrl)
    finally:
        close(root, app)


def test_one_stage_panel_built_once(check):
    """The readout exists on the app and inside neither tab's columns.

    A stage panel that drifted back into an experiment's `col_left`
    would be one panel per tab, which is the two-controller fault again
    wearing a layout costume.
    """
    root, app = make_app()
    vdp, hall = tabs(app)
    try:
        readout = getattr(app, "temp_readout_label", None)
        check("the app owns a stage readout", readout is not None)
        for exp, name in ((vdp, "vdp"), (hall, "hall")):
            node, found = readout, False
            while node is not None:
                if str(node) in (str(exp.col_left), str(exp.col_mid),
                                 str(exp.col_right)):
                    found = True
                    break
                node = getattr(node, "master", None)
            check(f"stage is not inside {name}'s columns", not found)
        check("experiments hold no stage widgets of their own",
              not hasattr(vdp, "temp_readout_label")
              and not hasattr(hall, "temp_readout_label"))
    finally:
        close(root, app)


def test_experiment_shutdown_does_not_close_the_shared_stage(check):
    """Tearing one tab down must leave the other tab's port open.

    Before Wave 5b `Experiment.shutdown_devices()` closed the
    controller. With one controller per window, the first tab torn down
    would have closed the port out from under the second - and the
    second would then have closed it again.
    """
    stage = FakeStage()
    root, app = make_app(stage=stage)
    vdp, hall = tabs(app)
    try:
        stage.connected = True
        vdp.shutdown_devices()
        hall.shutdown_devices()
        check("no experiment closed the stage", stage.closed == 0,
              f"closed {stage.closed} time(s)")
        check("no experiment switched the PID off", stage.pid_offs == 0)

        app.shutdown_devices()
        check("the app closes it once", stage.closed == 1,
              f"closed {stage.closed} time(s)")
        check("and switches the PID off first", stage.pid_offs == 1)
    finally:
        close(root, app)


def test_window_close_shuts_the_stage_down_once(check):
    """`on_close()` walks every tab and then the app's own devices."""
    stage = FakeStage()
    root, app = make_app(stage=stage)
    stage.connected = True
    app.on_close()
    try:
        check("stage closed exactly once", stage.closed == 1,
              f"closed {stage.closed} time(s)")
        check("PID switched off exactly once", stage.pid_offs == 1)
    finally:
        try:
            root.destroy()
        except Exception:
            pass
        dialogs.clear()


# --- B. one sample, one thickness ------------------------------------

def test_sample_and_thickness_are_one_variable(check):
    """Shared objects, not two variables kept in step.

    A trace-synchronised pair would work until the ordering went wrong
    once, and the failure - a Hall calculation carrying a Van der Pauw
    thickness - reads exactly like a correct one.
    """
    root, app = make_app()
    vdp, hall = tabs(app)
    try:
        check("sample name is one variable",
              vdp.sample_name_var is hall.sample_name_var
              is app.sample_name_var)
        check("thickness is one variable",
              vdp.thickness_entry_var is hall.thickness_entry_var
              is app.thickness_entry_var)

        app.sample_name_var.set("film_7")
        app.thickness_entry_var.set("180")
        check("vdp reads the new sample", vdp.current_sample_name() == "film_7")
        check("hall reads the new sample", hall.current_sample_name() == "film_7")
        check("vdp reads the new thickness",
              vdp.thickness_entry_var.get() == "180")
        check("hall reads the new thickness",
              hall.thickness_entry_var.get() == "180")
    finally:
        close(root, app)


def test_what_is_typed_on_the_strip_is_what_both_tabs_read(check):
    """Types into the actual widget, not into the variable behind it.

    The identity assertion above is necessary and **not sufficient**,
    and the gap is worth naming because it hid a real regression while
    this file was being written. A panel doing
    `exp.app.sample_name_var = tk.StringVar(...)` rebinds the attribute:
    both experiments and the app go on agreeing perfectly, and the only
    thing left pointing at the original variable is the box the operator
    types in. Typing then changes nothing, every reader sees "sample"
    forever, and nothing anywhere raises.

    So this drives the Entry the way a finger does.
    """
    root, app = make_app()
    vdp, hall = tabs(app)
    try:
        app.sample_entry.delete(0, "end")
        app.sample_entry.insert(0, "film_9")
        app.thickness_entry.delete(0, "end")
        app.thickness_entry.insert(0, "180")
        root.update()

        check("vdp reads what was typed",
              vdp.current_sample_name() == "film_9",
              f"vdp sees {vdp.current_sample_name()!r}")
        check("hall reads what was typed",
              hall.current_sample_name() == "film_9",
              f"hall sees {hall.current_sample_name()!r}")
        check("vdp reads the typed thickness",
              vdp.thickness_entry_var.get() == "180")
        check("hall reads the typed thickness",
              hall.thickness_entry_var.get() == "180")
    finally:
        close(root, app)


def test_every_session_widget_is_wired_to_the_live_variable(check):
    """No widget in any window shape is left bound to an orphan.

    Checked per window rather than only on the combined one: the IV
    sweep and the 4PP bind the app's sample-name and save-path
    variables into their own panels, so a rebinding anywhere strands a
    box in a window this wave was not otherwise changing.
    """
    from core.gui.session_strip import bound_variable

    for spec, label in ((COMBINED, "combined"),
                        (VanDerPauwExperiment, "vanderpauw"),
                        (IVSweepExperiment, "iv_sweep"),
                        (Ossila4PPExperiment, "ossila_4pp")):
        root, app = make_app(spec=spec)
        try:
            pairs = [("measnum", getattr(app, "measnum_entry", None),
                      app.measnum_var),
                     ("save path", getattr(app, "path_entry", None),
                      app.path_display_var),
                     ("sample", getattr(app, "sample_entry", None),
                      app.sample_name_var),
                     ("thickness", getattr(app, "thickness_entry", None),
                      app.thickness_entry_var)]
            for name, widget, var in pairs:
                if widget is None:
                    continue          # this window does not show that field
                check(f"{label}: {name} box is wired to the live variable",
                      bound_variable(widget) == str(var),
                      f"box shows {bound_variable(widget)}, app holds {var}")
        finally:
            close(root, app)


def test_the_session_strip_stays_one_row_tall(check):
    """A second row on the strip costs every window ~20 vertical pixels.

    Wave 5c added a sample-name reminder as its own row and it passed
    here, passed the layout tripwire locally, and failed Ubuntu CI -
    where the runner's font metrics had left the combined window only
    10 pixels under the height budget. `test_layout.py` is the right
    guard for "this got a lot bigger", but it can only fire on a machine
    whose fonts are large enough, so it reports a real regression as a
    difference between machines.

    This one fails identically everywhere, because it asserts the
    structure rather than the pixels: whatever goes on the strip goes
    *beside* what is already there, not underneath it. The strip is the
    one widget every window shape pays for.
    """
    for spec, label in ((COMBINED, "combined"),
                        (VanDerPauwExperiment, "vanderpauw"),
                        (IVSweepExperiment, "iv_sweep"),
                        (Ossila4PPExperiment, "ossila_4pp")):
        root, app = make_app(spec=spec)
        try:
            strip = getattr(app, "session_strip", None)
            if strip is None:
                continue          # no experiment here asks for a field
            # The holder is two rows - the strip and the rule under it.
            # The strip itself must be one.
            row_frame = strip.winfo_children()[0]
            rows = {int(w.grid_info().get("row", 0))
                    for w in row_frame.winfo_children()}
            check(f"{label}: strip widgets are all on one row",
                  rows == {0} or not rows, sorted(rows))
        finally:
            close(root, app)


def test_both_tabs_mean_the_same_sample(check):
    """One mounted film is one `SampleRef` across the window.

    `core/identity.py` has said so since Wave 2 - application-scoped
    registry, not per experiment - but until Wave 5b the two tabs read
    two different name boxes, so agreeing was a matter of the operator
    typing the same thing twice. Wave 5c's in-memory handoff of a sheet
    resistance rests on this.
    """
    root, app = make_app()
    vdp, hall = tabs(app)
    try:
        app.sample_name_var.set("wafer_B")
        check("same sample id",
              vdp.current_sample_ref().sample_id
              == hall.current_sample_ref().sample_id)
    finally:
        close(root, app)


def test_a_panel_cannot_shadow_the_shared_variables(check):
    """Assigning over them raises rather than quietly making a copy.

    The read-only property is the guard: the alternative failure is a
    second box holding a second sample name, agreeing with the first
    until one day it doesn't.
    """
    root, app = make_app()
    vdp, _hall = tabs(app)
    try:
        for name in ("sample_name_var", "thickness_entry_var", "temp_ctrl"):
            try:
                setattr(vdp, name, tk.StringVar(value="x"))
            except AttributeError:
                continue
            check(f"assigning {name} should have raised", False)
    finally:
        close(root, app)


# --- C. the session counter and save path ----------------------------

def test_measurement_counter_is_shared_and_stays_live(check):
    """One counter per window, and the displayed variable is the app's.

    This is the bug the session strip exists for. The old panels each
    created `exp.app.measnum_var`, so the second tab built rebound the
    attribute `take_meas_number()` updates and the first tab's box
    stopped moving.
    """
    root, app = make_app()
    vdp, hall = tabs(app)
    try:
        first = vdp.app.take_meas_number()
        second = hall.app.take_meas_number()
        check("the counter is shared", (first, second) == (1, 2),
              f"got {first} then {second}")

        app.drain_ui_now()
        root.update()
        check("the strip shows the next number",
              app.measnum_var.get() == 3, f"shows {app.measnum_var.get()}")
    finally:
        close(root, app)


def test_save_path_is_one_variable(check):
    """Both tabs write into the same folder, and both show it."""
    root, app = make_app()
    try:
        app.storage_path = "/tmp/example"
        app.path_display_var.set(app.storage_path)
        check("the strip shows it",
              app.path_display_var.get() == "/tmp/example")
    finally:
        close(root, app)


def test_session_strip_fields_follow_the_declarations(check):
    """The strip carries a field because a hosted experiment asked.

    4PP declares neither: its thickness is part of a geometry that also
    carries a width and a length, and a second box on the strip claiming
    to hold the same quantity would be a second thing to be wrong.
    """
    root, app = make_app()
    try:
        check("combined window offers a sample box",
              getattr(app, "sample_entry", None) is not None)
        check("combined window offers a thickness box",
              getattr(app, "thickness_entry", None) is not None)
    finally:
        close(root, app)

    root, app = make_app(spec=Ossila4PPExperiment)
    try:
        check("4PP declares no strip fields",
              Ossila4PPExperiment.SESSION_FIELDS == ())
        check("so it gets no strip thickness box",
              getattr(app, "thickness_entry", None) is None)
    finally:
        close(root, app)


# --- D. the run gate -------------------------------------------------

def test_a_busy_tab_refuses_the_other(check):
    """One measurement at a time in a window.

    Driven through the run controller rather than a real threaded run:
    the question here is the gate, and `test_vdp_lifecycle.py` and
    `test_hall_lifecycle.py` already drive the worker path.
    """
    root, app = make_app()
    vdp, hall = tabs(app)
    try:
        check("nobody is busy to start with",
              app.busy_experiment() is None)
        check("hall would be allowed", not hall.refuse_if_sibling_busy())

        with vdp.begin_run():
            check("the app names the busy tab",
                  app.busy_experiment() is vdp)
            dialogs.clear()
            check("hall is refused", hall.refuse_if_sibling_busy())
            check("and told why", any("Measurement in progress" in str(c[1])
                                      for c in dialogs.calls),
                  f"dialogs: {dialogs.calls}")
            check("vdp is not refused by itself",
                  not vdp.refuse_if_sibling_busy())

        check("the gate reopens when the run ends",
              app.busy_experiment() is None)
        check("and hall is allowed again",
              not hall.refuse_if_sibling_busy())
    finally:
        close(root, app)


def test_the_idle_tab_run_button_greys_out(check):
    """The refusal is visible before it is clicked.

    The busy tab's own Run button is left alone: it manages its own
    Run/Stop pair, and two authorities over one widget is how a button
    ends up permanently disabled after an unlucky ordering.
    """
    root, app = make_app()
    vdp, hall = tabs(app)
    try:
        with vdp.begin_run():
            app.drain_ui_now()
            root.update()
            check("hall's Run is disabled",
                  str(hall.run_btn["state"]) == "disabled",
                  f"state {hall.run_btn['state']}")

        app.drain_ui_now()
        root.update()
        check("hall's Run comes back",
              str(hall.run_btn["state"]) == "normal",
              f"state {hall.run_btn['state']}")
    finally:
        close(root, app)


def test_a_single_experiment_window_has_no_sibling_to_refuse(check):
    """The gate must be a no-op where there is only one tab."""
    root, app = make_app(spec=VanDerPauwExperiment)
    exp = app.experiment
    try:
        check("nothing busy", app.busy_experiment() is None)
        check("no refusal", not exp.refuse_if_sibling_busy())
        with exp.begin_run():
            check("still nothing to refuse against",
                  app.busy_experiment(exclude=exp) is None)
            check("and the run does not refuse itself",
                  not exp.refuse_if_sibling_busy())
    finally:
        close(root, app)


# --- E. closing the window sees both tabs ----------------------------

def test_unsaved_runs_are_counted_across_tabs(check):
    """Both results tables, not just the visible one.

    `on_close()` asked `self.experiment` before Wave 5b, so closing a
    two-tab window would have discarded the other tab's measurements
    without mentioning them.
    """
    root, app = make_app()
    vdp, hall = tabs(app)
    try:
        check("nothing unsaved to start", app.unsaved_run_count() == 0)

        vdp.run_store.add("row-1", Run(sample="s", metadata={}, readings=[]))
        check("one from the vdp tab", app.unsaved_run_count() == 1)

        hall.run_store.add("row-2", Run(sample="s", metadata={}, readings=[]))
        hall.run_store.add("row-3", Run(sample="s", metadata={}, readings=[]))
        check("three across the window", app.unsaved_run_count() == 3,
              f"counted {app.unsaved_run_count()}")

        vdp.run_store.mark_saved()
        hall.run_store.mark_saved()
        check("saved runs stop counting", app.unsaved_run_count() == 0)
    finally:
        close(root, app)


# --- the shell, both shapes ------------------------------------------

def test_single_experiment_windows_build_no_notebook(check):
    """A tab strip with one unclickable tab is vertical budget spent on
    nothing, and `test_layout.py` says there is none to spare."""
    for cls in (VanDerPauwExperiment, HallExperiment, IVSweepExperiment,
                Ossila4PPExperiment):
        root, app = make_app(spec=cls)
        try:
            check(f"{cls.__name__}: one experiment",
                  len(app.experiments) == 1)
            check(f"{cls.__name__}: no notebook", app.notebook is None)
            check(f"{cls.__name__}: `experiment` still works",
                  isinstance(app.experiment, cls))
            check(f"{cls.__name__}: window titled after it",
                  root.title() == cls.NAME, f"titled {root.title()!r}")
        finally:
            close(root, app)


def test_the_combined_window_tracks_the_visible_tab(check):
    """`app.experiment` is what the operator is looking at.

    Every caller written before Wave 5b - the connection panel reading
    `ROLES`, most of the test suite - says `app.experiment` and means
    "the one on screen".
    """
    root, app = make_app()
    vdp, hall = tabs(app)
    try:
        check("two tabs", len(app.experiments) == 2)
        check("a notebook", app.notebook is not None)
        check("starts on Van der Pauw", app.experiment is vdp)

        app.notebook.select(1)
        root.update()
        check("follows the selection", app.experiment is hall)

        app.notebook.select(0)
        root.update()
        check("and back", app.experiment is vdp)
    finally:
        close(root, app)


def test_tab_labels_are_short_enough_to_read(check):
    """`NAME` is right for a title bar and too long for a tab."""
    root, app = make_app()
    try:
        for exp in app.experiments:
            check(f"{type(exp).__name__} has a short tab label",
                  len(exp.tab_label) <= 20,
                  f"{exp.tab_label!r} is {len(exp.tab_label)} chars")
        check("the window says it hosts both",
              "+" in root.title(), f"titled {root.title()!r}")
    finally:
        close(root, app)


def test_experiment_of_finds_the_other_tab(check):
    """How Wave 5c's Rs handoff will reach across without going through
    the notebook."""
    root, app = make_app()
    try:
        check("finds Van der Pauw",
              isinstance(app.experiment_of(VanDerPauwExperiment),
                         VanDerPauwExperiment))
        check("finds Hall",
              isinstance(app.experiment_of(HallExperiment), HallExperiment))
        check("says so when a class is not hosted",
              app.experiment_of(IVSweepExperiment) is None)
    finally:
        close(root, app)


def test_an_empty_window_is_refused(check):
    """A window hosting nothing is a programming mistake, not a state to
    render."""
    root = tk.Tk()
    try:
        with pytest.raises(ValueError):
            LabApp(root, [], ownership=InstrumentOwnership(),
                   samples=SampleRegistry())
    finally:
        try:
            root.destroy()
        except Exception:
            pass
