"""The Start delay: every sweep holds its first level before it begins.

Feedback from the bench: a sweep's first reading or two lag the source,
because the step from wherever the output was - zero, a bias, the last
sweep's stop - to the start value is the largest step in the sweep, and
the sample takes longer to follow it than one point's increment. Every
sweep now sources its first level and holds it for the Start delay
before the first reading, on top of that point's usual Delay.

Four properties, on all four sweeps:

  * the first level is what is held, and the first reading comes at
    least the Start delay after it;
  * Stop during the hold is felt at once and discards the run;
  * the box is refused rather than guessed at, and its value is saved
    with the run and counted in the time estimate;
  * the form offers it directly under Delay, in seconds, at 2 s.

Van der Pauw and Hall took their Delay in milliseconds until the Start
delay arrived; both boxes are seconds now, like the IV sweep's and the
4PP's, and the last test here holds them to it.

The driver is the real DummySMU with a timestamping recorder around it,
so the sequence under test is the one the bench would see.
"""
import threading
import time
import tkinter as tk

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.gui]

from hall_harness import run_hall
from vdp_harness import run_vdp

import smuniversal_lab_suite.core.base_app as base_app
import smuniversal_lab_suite.experiments.base_experiment as base_experiment
import smuniversal_lab_suite.experiments.four_contact as four_contact
import smuniversal_lab_suite.experiments.iv_sweep.experiment as iv_experiment
from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.transports.null_transport import NullTransport
from smuniversal_lab_suite.core.validation import ValidationError
from smuniversal_lab_suite.experiments.hall.experiment import HallExperiment
from smuniversal_lab_suite.experiments.iv_sweep.experiment import (
    IVSweepExperiment,
)
from smuniversal_lab_suite.experiments.ossila_4pp.experiment import (
    Ossila4PPExperiment,
)
from smuniversal_lab_suite.experiments.vanderpauw.experiment import (
    VanDerPauwExperiment,
)

#: Long enough to measure against scheduling noise, short enough that
#: four runs of it cost little.
HOLD_S = 0.3

#: What a wait timed by `Event.wait` may come in under its request by.
TIMER_SLACK_S = 0.02

SET_LEVEL = ("set_voltage_level", "set_current_level")

#: The first thing a sweep does that reads the sample: a reading on the
#: point-by-point sweeps, the instrument's own staircase on the IV one.
FIRST_READING = ("measure", "start_linear_sweep")


class Dialogs:
    """Answers yes to everything, so a headless run never blocks."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: True


@pytest.fixture(autouse=True)
def _no_dialogs(monkeypatch):
    for module in (base_app, base_experiment, four_contact, iv_experiment):
        monkeypatch.setattr(module, "messagebox", Dialogs())


class Recorder:
    """Wraps a driver and writes down each call, its arguments and when.

    A proxy rather than a fake: every call reaches the real driver, as
    in `test_iv_lifecycle.py`, with a clock added because the property
    under test is a duration.
    """

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "calls", [])

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def recorded(*a, **kw):
            self.calls.append((name, a, time.monotonic()))
            return attr(*a, **kw)
        return recorded

    def names(self):
        return [name for name, _, _ in self.calls]

    def after_output_on(self):
        """Every call from the first output_on on."""
        names = self.names()
        return self.calls[names.index("output_on"):]


def build(root, experiment_cls):
    app = LabApp(root, experiment_cls)
    app.connect_role("source", NullTransport(), "demo")
    exp = app.experiment
    exp.sample_name_var.set("film")
    rec = Recorder(app.instruments["source"])
    app.instruments["source"] = rec
    root.update()
    return app, exp, rec


def drain(root, app):
    app.drain_ui_now()
    for _ in range(40):
        root.update()
    app.drain_ui_now()


def close(root, app):
    drain(root, app)
    app.on_close()
    try:
        root.destroy()
    except tk.TclError:
        pass


# ---- driving each experiment once, with the Start delay as typed ----
def _iv(root, app, exp):
    exp.mode_var.set("voltage")
    exp.on_mode_changed()
    exp.start_var.set("0.2")
    exp.stop_var.set("0.5")
    exp.points_var.set("4")
    exp.delay_var.set("0")
    exp.compliance_var.set("0.01")
    params = exp._sweep_params()
    exp._check_limits(params)
    exp._do_single(params)
    return params["start"]


def _vdp(root, app, exp):
    params = run_vdp(exp, root, "A", points=2)
    return params.levels_a[0]


def _hall(root, app, exp):
    params = run_hall(exp, root, "C", field_sign="+", points=2)
    return params.levels_a[0]


def _four_pp(root, app, exp):
    exp.delay_var.set("0")
    params = exp._sweep_params()
    exp._check_limits(params)
    exp._do_run(params)
    return params.currents_a[0]


SWEEPS = [
    pytest.param(IVSweepExperiment, _iv, id="iv"),
    pytest.param(VanDerPauwExperiment, _vdp, id="vdp"),
    pytest.param(HallExperiment, _hall, id="hall"),
    pytest.param(Ossila4PPExperiment, _four_pp, id="4pp"),
]


@pytest.mark.parametrize("experiment_cls, measure", SWEEPS)
def test_the_first_level_is_held_for_the_start_delay(check, experiment_cls,
                                                     measure):
    """Output on, the first level set, then nothing read for HOLD_S."""
    root = tk.Tk()
    app, exp, rec = build(root, experiment_cls)
    try:
        exp.start_delay_var.set(f"{HOLD_S:g}")
        first_level = measure(root, app, exp)
        drain(root, app)

        live = rec.after_output_on()
        names = [name for name, _, _ in live]
        held = next(i for i, name in enumerate(names) if name in SET_LEVEL)
        read = next(i for i, name in enumerate(names)
                    if name in FIRST_READING)
        _, args, set_at = live[held]
        _, _, read_at = live[read]

        check("a level is set before anything is read", held < read,
              f"{names[:8]}")
        check("and it is the sweep's first level",
              args and args[0] == pytest.approx(first_level),
              f"held {args}, first level {first_level}")
        check(f"held for at least {HOLD_S} s before the first reading",
              read_at - set_at >= HOLD_S - TIMER_SLACK_S,
              f"{read_at - set_at:.3f} s")

        rows = exp.tree.get_children()
        check("the run committed", len(rows) >= 1, f"{len(rows)} rows")
        if rows:
            meta = exp.run_store.get(rows[0]).metadata
            check("and saved its Start delay",
                  meta.get("start_delay_s") == pytest.approx(HOLD_S),
                  f"{meta.get('start_delay_s')!r}")
    finally:
        close(root, app)


def test_the_iv_output_comes_up_at_the_start_value(check):
    """Not at the last sweep's stop, or at a reset level: the start
    level is set before the output goes on, on every repeat."""
    root = tk.Tk()
    app, exp, rec = build(root, IVSweepExperiment)
    try:
        exp.runs_var.set("2")
        _iv(root, app, exp)
        drain(root, app)

        before_each_on = []
        last_level = None
        for name, args, _ in rec.calls:
            if name == "set_voltage_level":
                last_level = args[0]
            elif name == "output_on":
                before_each_on.append(last_level)
        check("the output went on once per repeat",
              len(before_each_on) == 2, f"{before_each_on}")
        check("each time already at Start",
              all(level == pytest.approx(0.2) for level in before_each_on),
              f"{before_each_on}")
    finally:
        close(root, app)


def _start_iv(exp):
    exp.mode_var.set("voltage")
    exp.on_mode_changed()
    exp.start_var.set("0.2")
    exp.stop_var.set("0.5")
    exp.points_var.set("4")
    exp.delay_var.set("0")
    exp.compliance_var.set("0.01")
    params = exp._sweep_params()
    return lambda: exp._do_single(params)


def _start_vdp(exp):
    exp.pos_var.set("A")
    exp.points_var.set("4")
    exp.delay_var.set("0")
    params = exp._run_params()
    return lambda: exp._do_run(params)


@pytest.mark.parametrize("experiment_cls, start", [
    pytest.param(IVSweepExperiment, _start_iv, id="iv"),
    pytest.param(VanDerPauwExperiment, _start_vdp, id="vdp"),
])
def test_stop_during_the_start_delay_is_felt_at_once(check, experiment_cls,
                                                     start):
    """A 60 s hold, cut short by Stop, and nothing kept.

    Waited on facts rather than durations: the cancel goes in once the
    hold has begun, which is when the recorder has seen the output on
    and the first level set.
    """
    root = tk.Tk()
    app, exp, rec = build(root, experiment_cls)
    try:
        exp.start_delay_var.set("60")
        worker = threading.Thread(target=start(exp), daemon=True)
        worker.start()

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            root.update()
            names = rec.names()
            if ("output_on" in names and any(
                    n in SET_LEVEL for n in names[names.index("output_on"):])):
                break
            time.sleep(0.01)
        time.sleep(0.1)

        stopped = time.monotonic()
        exp.cancel_run("test")
        while worker.is_alive() and time.monotonic() - stopped < 5:
            root.update()
            time.sleep(0.01)
        elapsed = time.monotonic() - stopped
        drain(root, app)

        check("the run ended within moments of Stop",
              not worker.is_alive() and elapsed < 3, f"{elapsed:.2f} s")
        check("without reading the sample",
              not any(n in FIRST_READING for n in rec.names()),
              f"{rec.names()}")
        check("and kept nothing", exp.tree.get_children() == (),
              f"{len(exp.tree.get_children())} rows")
    finally:
        close(root, app)


# ---- the form ----
def _form(exp):
    """The parameter snapshot, as the Run press takes it."""
    if isinstance(exp, IVSweepExperiment):
        return exp._sweep_params()
    if isinstance(exp, Ossila4PPExperiment):
        return exp._sweep_params()
    return exp._run_params()


ALL = [pytest.param(cls, id=cls.__name__) for cls in (
    IVSweepExperiment, VanDerPauwExperiment, HallExperiment,
    Ossila4PPExperiment)]


@pytest.mark.parametrize("experiment_cls", ALL)
@pytest.mark.parametrize("typed", ["-1", "soon", ""])
def test_a_start_delay_that_cannot_be_used_is_refused(experiment_cls, typed):
    root = tk.Tk()
    app, exp, rec = build(root, experiment_cls)
    try:
        exp.start_delay_var.set(typed)
        with pytest.raises(ValidationError, match="Start delay"):
            _form(exp)
    finally:
        close(root, app)


@pytest.mark.parametrize("experiment_cls", ALL)
def test_the_estimate_counts_the_start_delay(experiment_cls):
    """The progress bar's first guess includes the hold."""
    root = tk.Tk()
    app, exp, rec = build(root, experiment_cls)
    try:
        exp.start_delay_var.set("0")
        quick = _form(exp)
        exp.start_delay_var.set("5")
        held = _form(exp)
        if isinstance(exp, IVSweepExperiment):
            gap = exp._estimate_single(held) - exp._estimate_single(quick)
        else:
            gap = (exp.estimate_run_seconds(held)
                   - exp.estimate_run_seconds(quick))
        assert gap == pytest.approx(5.0)
    finally:
        close(root, app)


def _entry_row(frame_root, var):
    """(grid master, row) of the Entry bound to `var`."""
    pending = [frame_root]
    while pending:
        widget = pending.pop()
        pending.extend(widget.winfo_children())
        if widget.winfo_class() not in ("TEntry", "Entry"):
            continue
        if str(widget.cget("textvariable")) == str(var):
            return widget.master, int(widget.grid_info()["row"])
    return None, None


@pytest.mark.real_start_delay
@pytest.mark.parametrize("experiment_cls", ALL)
def test_every_sweep_offers_a_start_delay_under_its_delay(check,
                                                          experiment_cls):
    """In seconds, at 2 s, on the row directly below Delay."""
    root = tk.Tk()
    app, exp, rec = build(root, experiment_cls)
    try:
        check("it starts at 2 s", exp.start_delay_var.get() == "2",
              repr(exp.start_delay_var.get()))
        delay_master, delay_row = _entry_row(root, exp.delay_var)
        start_master, start_row = _entry_row(root, exp.start_delay_var)
        check("both boxes are on the form",
              delay_row is not None and start_row is not None)
        check("in the same grid", start_master is delay_master)
        check("Start delay directly below Delay",
              start_row == (delay_row or 0) + 1,
              f"Delay row {delay_row}, Start delay row {start_row}")

        labels = [
            str(widget.cget("text"))
            for widget in (start_master.winfo_children()
                           if start_master is not None else ())
            if widget.winfo_class() == "TLabel"
            and int(widget.grid_info().get("row", -1)) in (delay_row,
                                                           start_row)]
        check("both labelled in seconds",
              sorted(labels) == ["Delay (s):", "Start delay (s):"],
              f"{labels}")
    finally:
        close(root, app)


@pytest.mark.parametrize("experiment_cls", [
    pytest.param(VanDerPauwExperiment, id="vdp"),
    pytest.param(HallExperiment, id="hall"),
])
def test_van_der_pauw_and_hall_take_their_delay_in_seconds(check,
                                                           experiment_cls):
    """0.25 in the box is a quarter of a second, not 0.25 ms; and a box
    that cannot be read is refused rather than replaced with 50 ms."""
    root = tk.Tk()
    app, exp, rec = build(root, experiment_cls)
    try:
        exp.delay_var.set("0.25")
        check("0.25 is 0.25 s", _form(exp).delay_s == pytest.approx(0.25))
        exp.delay_var.set("0")
        check("0 is allowed, as on the other sweeps",
              _form(exp).delay_s == 0.0)
        for typed in ("-0.1", "soon"):
            exp.delay_var.set(typed)
            with pytest.raises(ValidationError, match="Delay"):
                _form(exp)
    finally:
        close(root, app)
