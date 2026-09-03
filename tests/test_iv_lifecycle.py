
"""IV sweep on the run lifecycle: cancellation, and the standby contract.

Wave 6. Three properties, each of which was false before:

  * Stop discards. IV was the only experiment where the sweep in flight
    was allowed to finish and be recorded, so a stopped run left rows in
    the table that no other tab would have kept (decision W6-1).

  * Nothing is configured while the sample is energised. `_apply_standby`
    used to turn the output on with no compliance set at all, and
    `_one_sweep` sent compliance, ranges, sensing, NPLC and OVP *after* a
    held bias was already live (house rule 12, decision W6-7).

  * The source function never changes under a live output. When the
    standby and sweep functions differ, the output comes down for the
    change deliberately and the interruption is measured and recorded,
    rather than the code hoping the instrument tolerates it (W6-3, W6-6).

The driver here is the real DummySMU with a recorder around it, so the
order of operations under test is the order the bench would see.
"""
import tkinter as tk

import pytest

from core.ranges import NOT_SOURCED

pytestmark = [pytest.mark.slow, pytest.mark.gui]

import experiments.iv_sweep.experiment as iv
from core.base_app import LabApp
from core.transports.null_transport import NullTransport
from experiments.iv_sweep.experiment import IVSweepExperiment

#: Everything that configures the instrument. If any of these lands
#: between an output_on and its output_off, house rule 12 is broken.
CONFIG_CALLS = {
    "set_source_function", "set_current_limit", "set_voltage_limit",
    "apply_ranges", "set_remote_sense",
    "set_nplc", "set_output_off_mode", "set_voltage_protection",
    "set_source_delay",
}


class Recorder:
    """Wraps a driver and writes down what it was asked to do.

    A proxy rather than a fake instrument: every call goes through to
    the real driver, so the sequence under test is the one that would
    reach the bench, not a reimplementation of it that could drift.
    """

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "calls", [])

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def recorded(*a, **kw):
            self.calls.append(name)
            return attr(*a, **kw)
        return recorded

    def while_energised(self):
        """Every call made between an output_on and the next off."""
        out, live = [], False
        for name in self.calls:
            if name == "output_on":
                live = True
            elif name in ("output_off", "safe_output_off"):
                live = False
            elif live:
                out.append(name)
        return out


def build(root, **form):
    app = LabApp(root, IVSweepExperiment)
    app.connect_role("source", NullTransport(), "demo")
    root.update_idletasks()
    exp = app.experiment
    exp.start_var.set(form.get("start", "0"))
    exp.stop_var.set(form.get("stop", "1"))
    exp.points_var.set(form.get("points", "5"))
    exp.delay_var.set("0")
    exp.runs_var.set(form.get("repeats", "1"))
    exp.mode_var.set(form.get("mode", "voltage"))
    exp.on_mode_changed()
    exp.compliance_var.set(form.get("compliance", "0.01"))
    exp.cycles_var.set(form.get("cycles", "2"))
    exp.period_var.set("0")
    exp.standby_var.set(form.get("standby", "Remain idle"))
    exp.bias_var.set(form.get("bias", "0.5"))
    exp.on_standby_changed()

    rec = Recorder(app.instruments["source"])
    app.instruments["source"] = rec
    return app, exp, rec


def drain(root):
    for _ in range(60):
        root.update()


@pytest.fixture(autouse=True)
def _fast_settle(monkeypatch):
    """The 2 s pre-sweep settle is real on the bench and pointless here.

    Patched by name rather than by editing the sequence, which is why it
    is a module constant in the first place.
    """
    monkeypatch.setattr(iv, "PRE_SWEEP_SETTLE_S", 0.0)


# ---------------------------------------------------------------
# A. Stop discards
# ---------------------------------------------------------------

def test_stop_during_a_periodic_run_discards_completed_cycles(check):
    """Decision W6-1: a cancelled run keeps nothing, cycles included.

    The old code broke out of the cycle loop and left every finished
    sweep in the results table. This cancels partway through the second
    cycle, after the first has completed and would have been recorded.
    """
    root = tk.Tk()
    try:
        app, exp, rec = build(root, standby="Bias voltage", mode="voltage",
                              cycles="3", points="4")

        # Cancel from inside the sequence, at a known point rather than
        # after a sleep: waiting on a fact, not on a duration.
        original = exp._one_sweep
        seen = []

        def counting(run, smu, params, label, **kw):
            result = original(run, smu, params, label, **kw)
            seen.append(label)
            if len(seen) == 2:
                exp.cancel_run("test")
            return result
        exp._one_sweep = counting

        params = exp._sweep_params()
        exp._do_periodic(params, exp._periodic_params())
        drain(root)

        check("more than one sweep completed before the cancel",
              len(seen) >= 2, f"{seen}")
        check("but the results table is empty",
              exp.tree.get_children() == (),
              f"{len(exp.tree.get_children())} rows survived")
        check("and the run store holds nothing",
              len(exp.run_store.runs()) == 0
              if hasattr(exp.run_store, "runs") else True)
    finally:
        root.destroy()


def test_a_completed_periodic_run_records_every_sweep(check):
    """The other half: without a cancel, nothing is lost either.

    A discard-on-stop rule is only safe if the non-stopped path still
    commits in full - otherwise this test suite would pass with a
    commit that never fires.
    """
    root = tk.Tk()
    try:
        app, exp, rec = build(root, standby="Bias voltage", mode="voltage",
                              cycles="3", points="4")
        params = exp._sweep_params()
        exp._do_periodic(params, exp._periodic_params())
        drain(root)
        check("three cycles produced three rows",
              len(exp.tree.get_children()) == 3,
              f"got {len(exp.tree.get_children())}")
    finally:
        root.destroy()


# ---------------------------------------------------------------
# B. house rule 12 - nothing configured while energised
# ---------------------------------------------------------------

@pytest.mark.parametrize("standby,mode", [
    ("Remain idle", "voltage"),
    ("Bias voltage", "voltage"),
    ("Bias current", "current"),
    ("Bias voltage", "current"),
    ("Bias current", "voltage"),
])
def test_nothing_is_configured_while_the_sample_is_live(check, standby, mode):
    """Every standby/sweep combination, including the mismatched ones.

    Parameterised rather than written once for the happy case: the two
    mismatched combinations are precisely where the old code sent a
    source-function change into a live output.
    """
    root = tk.Tk()
    try:
        app, exp, rec = build(root, standby=standby, mode=mode,
                              cycles="2", points="4",
                              compliance="0.01" if mode == "voltage" else "1")
        params = exp._sweep_params()
        exp._do_periodic(params, exp._periodic_params())
        drain(root)

        offenders = [c for c in rec.while_energised() if c in CONFIG_CALLS]
        check(f"{standby} -> source {mode}: no configuration under a live "
              f"output", not offenders, ", ".join(sorted(set(offenders))))
    finally:
        root.destroy()


# ---------------------------------------------------------------
# C. the bias-continuity contract
# ---------------------------------------------------------------

def test_matching_functions_hold_the_bias_across_the_boundary(check):
    """W6-6: no function change, so no reason to drop the output.

    This is what `alreadyOn` was for. If the sequence took the output
    down here it would discharge the very thing being measured.
    """
    root = tk.Tk()
    try:
        app, exp, rec = build(root, standby="Bias voltage", mode="voltage",
                              cycles="2", points="4")
        params = exp._sweep_params()
        exp._do_periodic(params, exp._periodic_params())
        drain(root)

        offs = [c for c in rec.calls if c in ("output_off", "safe_output_off")]
        check("the output goes down once, at the end of the run",
              len(offs) == 1, f"{len(offs)} output-off calls")

        rows = exp.run_store
        first = exp.tree.get_children()[0]
        meta = rows.get(first).metadata
        check("and the file says the bias was continuous",
              meta.get("bias_continuous") == "yes", meta.get("bias_continuous"))
        check("with no interruption recorded",
              meta.get("bias_gap_s") in ("", None), meta.get("bias_gap_s"))
    finally:
        root.destroy()


def test_mismatched_functions_interrupt_the_bias_and_say_so(check):
    """W6-3: allowed, but the file has to admit it happened.

    A mismatched run and a continuous one are otherwise structurally
    identical, and describe different physics.
    """
    root = tk.Tk()
    try:
        app, exp, rec = build(root, standby="Bias current", mode="voltage",
                              cycles="2", points="4")
        params = exp._sweep_params()
        exp._do_periodic(params, exp._periodic_params())
        drain(root)

        first = exp.tree.get_children()[0]
        meta = exp.run_store.get(first).metadata
        check("the file says the bias was not continuous",
              meta.get("bias_continuous") == "no", meta.get("bias_continuous"))
        check("and carries a measured gap",
              str(meta.get("bias_gap_s", "")).strip() != "",
              f"{meta.get('bias_gap_s')!r}")

        # The whole point of taking the output down: the function change
        # must never happen under a live output.
        offenders = [c for c in rec.while_energised()
                     if c == "set_source_function"]
        check("the source function never changes while energised",
              not offenders, f"{len(offenders)} times")
    finally:
        root.destroy()


def test_stop_during_a_sweep_abandons_it_rather_than_reading_it_out(check):
    """Cancellation must be noticed *inside* the poll loop.

    Added after a mutation round: deleting the checkpoint from
    `_await_sweep` left every other test in this file green, because the
    commit gate refuses a cancelled run anyway and the table ends up
    empty either way. Empty-table is therefore not a discriminating
    assertion for this property.

    What separates the two is whether the sweep was abandoned or run to
    completion first. With the checkpoint, RunCancelled unwinds before
    the buffer is ever read; without it, the loop polls to the end and
    reads the sweep out before anyone objects. So this waits on the fact
    that `read_sweep` was never reached.

    Open item, stated rather than faked: what the in-poll checkpoint
    buys on top of this is *promptness* on a long sweep - noticing at
    the next poll instead of at the end. The demo instrument completes
    a sweep in one poll, so this suite cannot distinguish that, and no
    test here claims to.
    """
    root = tk.Tk()
    try:
        app, exp, rec = build(root, standby="Remain idle", mode="voltage",
                              cycles="1", points="6")

        inner = rec._inner
        original = inner.sweep_points_ready

        def cancel_on_first_poll():
            exp.cancel_run("test")
            return original()
        inner.sweep_points_ready = cancel_on_first_poll

        params = exp._sweep_params()
        exp._do_periodic(params, exp._periodic_params())
        drain(root)

        check("the sweep was polled at least once",
              "sweep_points_ready" in rec.calls)
        check("but never read out",
              "read_sweep" not in rec.calls,
              "the buffer was read after the cancel")
        check("and nothing was recorded",
              exp.tree.get_children() == ())
    finally:
        root.destroy()


# ---------------------------------------------------------------
# D. the sweep fixes its own source range
# ---------------------------------------------------------------

def _captured_plan(root, **form):
    """Run one sweep and return the RangePlan the experiment built."""
    app, exp, rec = build(root, **form)
    plans = []
    inner = rec._inner
    # Bind the original *before* rebinding the attribute, or `capture`
    # calls itself.
    original = inner.apply_ranges

    def capture(plan, log=None):
        plans.append(plan)
        return original(plan, log=log)
    inner.apply_ranges = capture

    params = exp._sweep_params()
    exp._do_periodic(params, exp._periodic_params())
    drain(root)
    return plans


def test_a_voltage_sweep_fixes_its_source_range_to_the_span(check):
    """Wave 6d-ii, and the reason the ranging split was worth doing.

    Until now IV set no source range at all, so a sweep relied on source
    autoranging - and a sweep is precisely the operation that walks
    across range boundaries. Each crossing leaves a step where the two
    segments were sourced with different gain and offset errors, and a
    straight line fitted across that step absorbs it as slope. Slope is
    resistance: an excellent R-squared and a wrong answer.

    Added after a mutation round: reverting the source axis to AUTO left
    every other test in this file green, because nothing looked at what
    the plan actually asked for.
    """
    root = tk.Tk()
    try:
        plans = _captured_plan(root, standby="Remain idle", mode="voltage",
                               cycles="1", points="4",
                               start="-2", stop="8", compliance="0.01")
        check("a plan was applied", bool(plans), "apply_ranges was never called")
        if not plans:
            return
        plan = plans[0]
        check("the source voltage range spans the widest end of the sweep",
              plan.source_voltage == 8.0, f"got {plan.source_voltage!r}")
        check("the measure current range is sized to the compliance",
              plan.measure_current == 0.01, f"got {plan.measure_current!r}")
        # Was `is AUTO` until 2026-08-20. The sweep asks for nothing out
        # of the current source, and saying so with `AUTO` was
        # indistinguishable from asking the instrument to pick a range -
        # which two instruments were damaged by. See fault 23.
        check("and the unused source axis is marked as not sourced",
              plan.source_current is NOT_SOURCED,
              f"got {plan.source_current!r}")
    finally:
        root.destroy()


def test_a_current_sweep_ranges_the_mirror_image(check):
    """The control for the test above.

    Without it, a driver that hard-coded the voltage axis would pass.
    """
    root = tk.Tk()
    try:
        plans = _captured_plan(root, standby="Remain idle", mode="current",
                               cycles="1", points="4",
                               start="-0.003", stop="0.001",
                               compliance="2")
        check("a plan was applied", bool(plans))
        if not plans:
            return
        plan = plans[0]
        check("the source current range spans the widest end",
              plan.source_current == 0.003, f"got {plan.source_current!r}")
        check("the measure voltage range is sized to the compliance",
              plan.measure_voltage == 2.0, f"got {plan.measure_voltage!r}")
        check("and the unused source axis is marked as not sourced",
              plan.source_voltage is NOT_SOURCED,
              f"got {plan.source_voltage!r}")
    finally:
        root.destroy()
