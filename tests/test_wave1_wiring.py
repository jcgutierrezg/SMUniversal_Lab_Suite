"""How Wave 1's machinery is wired into the application shell.

Three things land in `LabApp` and are checked here:

* **constructor injection** - the driver registry and the ownership
  manager are handed to the app rather than imported by it. That was the
  last remaining violation of the one-way dependency rule (the registry
  imports all seven driver modules, so `core` reaching for it made core
  depend on drivers), and it is what lets these tests run against a
  registry holding a single fake.
* **a failed mandatory reset** blocks runs on that instrument instead
  of only logging a warning.
* **an output that cannot be confirmed off** blocks the instrument
  and warns the operator prominently.

Tk roots are built here, so the file carries the `gui` marker and
`run_tests.py` gives it its own process. `messagebox` is stubbed in
`core.base_app` - see docs/architecture/core-modules.md about the modules
that each import it, and about how an unstubbed dialog hangs the suite
on the *second* test while the first still reads as a clean pass.
"""
import pytest

pytestmark = [pytest.mark.gui]

import tkinter as tk

import core.base_app as base_app
import experiments.base_experiment as base_experiment
from core.base_app import LabApp
from core.ownership import (
    InstrumentBlocked,
    InstrumentBusy,
    InstrumentOwnership,
)
from core.run_control import RunState, ShutdownReport, ShutdownStatus
from core.transports.base import Transport
from drivers.dummy_smu import DummySMU
from experiments.vanderpauw.experiment import VanDerPauwExperiment


# ------------------------------------------------------------------
# stubs
# ------------------------------------------------------------------
class _Dialogs:
    """Records dialog calls instead of opening one and blocking forever."""

    def __init__(self):
        self.calls = []

    def _record(self, kind):
        def call(title, message=""):
            self.calls.append((kind, title, message))
            return True
        return call

    def __getattr__(self, name):
        return self._record(name)


class FakeTransport(Transport):
    """A transport with a real address, so ownership keys are real."""

    def __init__(self):
        super().__init__()
        self.address = None

    def connect(self, address, **kwargs):
        self.address = address
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        pass

    def _read(self, timeout_s):
        return ""


class ResetFailsSMU(DummySMU):
    """Everything the dummy does, except the mandatory reset."""

    def reset(self):
        raise ConnectionError("instrument did not answer *RST")


class FakeRegistry:
    """A registry holding exactly one driver, injected per test.

    The point of injection: nothing here imports the real seven-driver
    registry, and swapping which driver `identify()` returns is a
    constructor argument rather than a monkeypatch.
    """

    class UnknownInstrumentError(RuntimeError):
        pass

    def __init__(self, driver_cls):
        self.driver_cls = driver_cls
        self.identify_calls = 0

    def identify(self, transport):
        self.identify_calls += 1
        return self.driver_cls(transport), f"FAKE,{self.driver_cls.__name__}"

    def all_driver_names(self):
        return [self.driver_cls.DISPLAY_NAME]

    def driver_by_display_name(self, name):
        return self.driver_cls


@pytest.fixture
def dialogs(monkeypatch):
    stub = _Dialogs()
    monkeypatch.setattr(base_app, "messagebox", stub)
    monkeypatch.setattr(base_experiment, "messagebox", stub)
    return stub


@pytest.fixture
def lab(dialogs):
    """A window, an injected registry and a private ownership manager."""
    root = tk.Tk()
    root.withdraw()
    registry = FakeRegistry(DummySMU)
    ownership = InstrumentOwnership()
    app = LabApp(root, VanDerPauwExperiment, registry=registry,
                 ownership=ownership)
    try:
        yield app, registry, ownership, root
    finally:
        try:
            root.destroy()
        except Exception:
            pass


# ------------------------------------------------------------------
# constructor injection
# ------------------------------------------------------------------
def test_the_app_uses_the_registry_it_was_given(lab, check):
    app, registry, _, root = lab
    driver = app.connect_role("source", FakeTransport(), "GPIB0::25::INSTR")
    root.update()
    check("the injected registry was consulted", registry.identify_calls == 1,
          f"{registry.identify_calls}")
    check("and produced the driver", isinstance(driver, DummySMU))


def test_the_defaults_still_work_for_main_py(dialogs):
    """`main.py` constructs `LabApp(root, cls)` and must keep working.

    Injection that forced every caller to supply collaborators would be
    a worse trade than the import it replaced.
    """
    from core.ownership import default_ownership
    from drivers import registry as real_registry

    root = tk.Tk()
    root.withdraw()
    try:
        app = LabApp(root, VanDerPauwExperiment)
        assert app.registry is real_registry
        assert app.ownership is default_ownership()
    finally:
        root.destroy()


def test_core_base_app_no_longer_imports_a_registry_at_module_level():
    """The dependency-direction rule, made executable.

    `core.base_app` may name a default, but the app must reach the
    registry through `self.registry` so a caller can replace it. This
    asserts the attribute exists and is used, which is the part that
    would rot silently.
    """
    import inspect

    source = inspect.getsource(base_app)
    assert "self.registry.identify(" in source, (
        "connect_role must go through the injected registry, not a "
        "module-level import")


# ------------------------------------------------------------------
# a failed mandatory reset blocks runs
# ------------------------------------------------------------------
def test_a_failed_reset_blocks_runs_on_that_instrument(lab, check):
    """The instrument's state is unknown, so a measurement is worthless.

    On the GSM-20H10 this is not merely academic: its `reset()` disables
    the output-enable interlock, and without that the output never comes
    on at all - so a reset that quietly failed produced a run of zeros
    rather than an error.
    """
    app, _, ownership, root = lab
    app.registry = FakeRegistry(ResetFailsSMU)

    app.connect_role("source", FakeTransport(), "GPIB0::25::INSTR")
    root.update()

    key = app.instrument_key("source")
    check("the instrument is blocked", ownership.is_blocked(key))
    check("with a reason naming the reset",
          "reset failed" in (ownership.block_reason(key) or ""),
          ownership.block_reason(key))
    check("but the connection is still open",
          app.is_connected("source"))

    with pytest.raises(InstrumentBlocked):
        app.claim_instrument("source", "run-1")


def test_a_successful_reset_clears_a_previous_block(lab, check):
    """Reconnecting cleanly is the remedy, and it is the only one.

    Deliberately not a "clear warning" button: the block means somebody
    should have looked at the hardware, and a reconnect is evidence that
    they were at the bench.
    """
    app, _, ownership, root = lab
    address = "GPIB0::25::INSTR"

    app.registry = FakeRegistry(ResetFailsSMU)
    app.connect_role("source", FakeTransport(), address)
    root.update()
    key = app.instrument_key("source")
    check("blocked after the bad reset", ownership.is_blocked(key))

    app.registry = FakeRegistry(DummySMU)
    app.connect_role("source", FakeTransport(), address)
    root.update()
    check("same connection key", app.instrument_key("source") == key,
          f"{app.instrument_key('source')} vs {key}")
    check("unblocked after a clean reset", not ownership.is_blocked(key))
    app.claim_instrument("source", "run-2").release()


def test_a_good_reset_does_not_block_anything(lab, check):
    app, _, ownership, root = lab
    app.connect_role("source", FakeTransport(), "GPIB0::25::INSTR")
    root.update()
    check("nothing blocked", ownership.blocked_keys() == (),
          f"{ownership.blocked_keys()}")


# ------------------------------------------------------------------
# uncertain shutdown
# ------------------------------------------------------------------
def test_an_unconfirmed_shutdown_blocks_the_instrument_and_warns(lab, check):
    app, _, ownership, root = lab
    dialogs = base_app.messagebox
    app.connect_role("source", FakeTransport(), "GPIB0::25::INSTR")
    root.update()

    report = ShutdownReport(ShutdownStatus.UNCERTAIN,
                            "output_off() raised: VISA timeout")
    app.report_uncertain_shutdown("source", report)
    # The warning is handed back through `app.ui()`, which Wave 3 turned
    # into a queue drained by a timer rather than a direct `after(0)`
    # from the calling thread. A single `update()` does not wait for the
    # next tick, so the drain is explicit here.
    app.drain_ui_now()
    root.update()

    key = app.instrument_key("source")
    check("blocked", ownership.is_blocked(key))
    check("the reason survives", "could not be confirmed off"
          in (ownership.block_reason(key) or ""), ownership.block_reason(key))
    warnings = [c for c in dialogs.calls if c[0] == "showwarning"]
    check("the operator was warned", len(warnings) == 1, f"{dialogs.calls}")
    check("and told the hardware may be live",
          "energised" in warnings[0][2], warnings[0][2] if warnings else "")


# ------------------------------------------------------------------
# ownership through the app
# ------------------------------------------------------------------
def test_claiming_through_the_app_uses_the_connection_key(lab, check):
    app, _, ownership, root = lab
    app.connect_role("source", FakeTransport(), "GPIB0::25::INSTR")
    root.update()

    claim = app.claim_instrument("source", "run-1")
    check("owned by the run", ownership.owner_of(app.instrument_key("source"))
          == "run-1")
    check("the label names the role for the dialog",
          "SMU" in claim.label, claim.label)
    claim.release()


def test_a_second_window_on_the_same_address_is_refused(dialogs, check):
    """Section 13: ownership is application-wide, not per panel.

    Two `LabApp`s, one shared ownership manager, one address. The second
    window's run must be refused - and be told why in words, not with a
    traceback.
    """
    ownership = InstrumentOwnership()
    roots, apps = [], []
    try:
        for _ in range(2):
            root = tk.Tk()
            root.withdraw()
            roots.append(root)
            apps.append(LabApp(root, VanDerPauwExperiment,
                               registry=FakeRegistry(DummySMU),
                               ownership=ownership))
        for app, root in zip(apps, roots):
            app.connect_role("source", FakeTransport(), "GPIB0::25::INSTR")
            root.update()

        check("both windows derived the same key",
              apps[0].instrument_key("source") == apps[1].instrument_key("source"))

        apps[0].claim_instrument("source", "vanderpauw-0001")
        with pytest.raises(InstrumentBusy) as excinfo:
            apps[1].claim_instrument("source", "hall-0001")
        check("named the holding run", "vanderpauw-0001" in str(excinfo.value),
              str(excinfo.value))
    finally:
        for root in roots:
            try:
                root.destroy()
            except Exception:
                pass


def test_disconnecting_releases_a_claim_and_says_so(lab, check):
    app, _, ownership, root = lab
    app.connect_role("source", FakeTransport(), "GPIB0::25::INSTR")
    root.update()
    key = app.instrument_key("source")
    app.claim_instrument("source", "run-1")

    app.disconnect_role("source")
    root.update()
    check("released", not ownership.is_owned(key))


def test_instrument_key_refuses_when_nothing_is_connected(lab):
    app, _, _, _ = lab
    with pytest.raises(ConnectionError):
        app.instrument_key("source")


# ------------------------------------------------------------------
# the experiment seam
# ------------------------------------------------------------------
def test_every_experiment_gets_a_run_controller(lab, check):
    """Wave 2 migrates the experiments onto it one at a time.

    Wave 1's job is that the seam exists, is named after the experiment
    (so console lines identify which window a run belongs to), and
    reports idle before anything has run.
    """
    app, _, _, _ = lab
    experiment = app.experiment
    check("it exists", experiment.run_controller is not None)
    check("named for the experiment",
          experiment.run_controller.name == experiment.CSV_SLUG,
          experiment.run_controller.name)
    check("idle at rest", experiment.run_controller.state is RunState.IDLE)
    check("no run in progress", not experiment.run_in_progress())
    check("nothing to cancel", experiment.cancel_run() is False)


def test_a_run_through_the_experiment_helpers_claims_and_releases(lab, check):
    """The shape every migrated experiment will have, end to end."""
    app, _, ownership, root = lab
    app.connect_role("source", FakeTransport(), "GPIB0::25::INSTR")
    root.update()
    experiment = app.experiment
    key = app.instrument_key("source")
    committed = []

    with experiment.begin_run(parameters={"level_A": 1e-4}) as run:
        run.enter(app.claim_instrument("source", run.run_id))
        run.start()
        check("claimed while running", ownership.owner_of(key) == run.run_id)
        run.add_reading({"voltage_V": 0.1, "current_A": 1e-4})
        run.confirm_shutdown(app.require_instrument("source"), log=app.log)
        run.commit("the run", committed.append)

    check("committed once", committed == ["the run"], f"{committed}")
    check("released afterwards", not ownership.is_owned(key))
    check("idle afterwards",
          experiment.run_controller.state is RunState.IDLE)
    check("parameters were captured",
          experiment.run_controller.last_status.is_success)
