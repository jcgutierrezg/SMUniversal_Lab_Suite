import pytest

pytestmark = [pytest.mark.gui]

"""The interlock note reaches every experiment, and says it once.

The 200 V source range on both TSP instruments will not energise unless
a hardware interlock line is held high, and no command overrides it -
it is a physical line on the Digital I/O port. So the only thing
software can do is make sure the operator is told at the moment it could
matter, rather than watching a high-voltage run refuse to source and
going looking for a driver fault.

Two things are worth pinning, and the second is the one that decays
quietly:

  A. It is printed from `begin_run()`, the shared run seam, rather than
     from the one experiment that happened to have a connect-time note
     already. Wiring it per experiment would mean the others silently
     lacking it.

     Note that `begin_run()` currently reaches 4PP, Van der Pauw and
     Hall. **IV sweep is not on the run lifecycle yet** - that is Wave 6
     in docs/plan.md - so it gets the same fact by the older route, the
     connect-time `sweep_note()` hook, which carries the interlock line
     on both TSP drivers. Coverage is complete but arrives two different
     ways, so when Wave 6 migrates IV sweep, check the note still
     appears rather than assuming the new seam replaced the old one.

  B. It is printed ONCE per session, not once per run. A warning
     repeated on every run is a warning operators learn to skip, and
     the failure is invisible: the line is still there, still correct,
     and no longer read.
"""
import tkinter as tk

from test_2611a_driver import TSPTransport

from core.base_app import LabApp
from core.parameters import VanDerPauwParameters
from core.transports.null_transport import NullTransport
from drivers.dummy_smu import DummySMU
from drivers.keithley_2611a import Keithley2611A
from drivers.keithley_2635b import Keithley2635B
from experiments.vanderpauw.experiment import VanDerPauwExperiment


def _params(app):
    return VanDerPauwParameters(
        sample=app.samples.ref("interlock"), position=1,
        level_a=1e-4, points_n=3, delay_s=0.0, compliance_v=0.3)


def _console(app):
    """Drain the UI queue first, then read.

    `log()` enqueues rather than writing, and the queue is emptied by a
    10 ms main-thread timer. `root.update()` alone processes whatever
    Tk has pending *now*, so a fast test can read the console before its
    own lines have arrived - which silently turns "was it printed once"
    into "how many made it in time". Draining explicitly makes the
    reading a fact rather than a race.
    """
    app.drain_ui_now()
    return app.console.get("1.0", "end").lower()


@pytest.mark.parametrize("driver_cls", [Keithley2611A, Keithley2635B],
                         ids=lambda c: c.__name__)
def test_the_note_reaches_a_non_iv_experiment(driver_cls, check):
    """Van der Pauw, not IV sweep. The pre-existing connect-time note
    was only ever wired into IV sweep, so a driver fact printed there
    reaches one experiment out of four."""
    root = tk.Tk()
    app = LabApp(root, VanDerPauwExperiment)
    exp = app.experiment
    app.instruments["source"] = driver_cls(TSPTransport())

    with exp.begin_run(parameters=_params(app)):
        pass
    console = _console(app)
    check(f"{driver_cls.__name__}: the run said something about it",
          "interlock" in console, "nothing in the console mentions it")
    check("and named the threshold", "20.2" in console, console[-400:])
    root.destroy()


def test_it_is_said_once_not_once_per_run(check):
    root = tk.Tk()
    app = LabApp(root, VanDerPauwExperiment)
    exp = app.experiment
    app.instruments["source"] = Keithley2611A(TSPTransport())

    for _ in range(3):
        with exp.begin_run(parameters=_params(app)):
            pass
        root.update()

    # Count LINES, not occurrences: the note itself says "interlock"
    # twice, so counting the word reports two for a single line and the
    # assertion becomes untrustworthy in both directions.
    lines = [l for l in _console(app).splitlines() if "interlock" in l]
    check("three runs produced one interlock line", len(lines) == 1,
          f"counted {len(lines)} - a warning repeated every run is one "
          f"operators learn to skip: {lines}")
    root.destroy()


def test_an_instrument_without_one_stays_quiet(check):
    """Declared per model. If this leaked onto every driver it would be
    noise on six instruments that have no such line."""
    root = tk.Tk()
    app = LabApp(root, VanDerPauwExperiment)
    exp = app.experiment
    app.instruments["source"] = DummySMU(NullTransport())

    with exp.begin_run(parameters=_params(app)):
        pass

    console = _console(app)
    check("nothing about interlocks", "interlock" not in console)
    # Mutation-found: checking only for the word "interlock" passes an
    # implementation that logs the *absent* note verbatim - the console
    # then reads "DummySMU: None", which mentions no interlock and is
    # still a line that should never have been written.
    check("and no line at all was written for it",
          "none" not in console and "energise" not in console,
          f"a driver with no interlock produced output: "
          f"{[l for l in console.splitlines() if 'none' in l or 'energise' in l]}")
    root.destroy()


def test_a_broken_note_cannot_stop_a_run(check):
    """This is a console convenience. A convenience must never be able
    to stop a measurement starting, so the seam swallows its own
    errors."""
    class Exploding(Keithley2611A):
        @classmethod
        def interlock_note(cls):
            raise RuntimeError("boom")

    root = tk.Tk()
    app = LabApp(root, VanDerPauwExperiment)
    exp = app.experiment
    app.instruments["source"] = Exploding(TSPTransport())

    started = False
    with exp.begin_run(parameters=_params(app)):
        started = True
    check("the run still began", started)
    root.destroy()
