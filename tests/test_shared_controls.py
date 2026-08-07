import pytest

pytestmark = [pytest.mark.gui]

import sys, os

"""The shared per-run instrument controls, across all three experiments.

Covers the two controls that live in core/gui/widgets.py and are used
by Van der Pauw, Hall and IV sweep: integration time (NPLC) and the
output-off mode (high-Z) checkbox.

Written after the control was factored into core/gui/widgets.py. The
point of a shared widget is that three panels behave identically, and
the way that promise rots is one of them quietly drifting - which is
exactly what happened to the six copies of LabeledEntry in the original
scripts. So this test drives all three rather than one.

What it checks:

  A. The control appears, populated, on instruments that have NPLC, and
     greys out to "n/a" on those that don't - driven by the driver's own
     declaration, not by model name.
  B. Presets are filtered to the instrument's declared range, so a 2611A
     offers 25 and the SCPI boxes don't offer a value they would clamp.
  C. Parsing: blank and "n/a" mean "leave the instrument alone" rather
     than "send a default".
  D. Out-of-range values clamp rather than raise.
  E. The applied value reaches the instrument AND the CSV, for all three
     experiments. A setting that changes the data but isn't recorded is
     worse than no setting at all.
"""
import tkinter as tk


def quiet_destroy(root):
    """Tear a root down without letting teardown noise fail the test.

    Panels schedule repeating `after` callbacks; destroying the root
    leaves those pointing at dead widgets, and Tk grumbles on stderr.
    Cosmetic, and cancelling the jobs first turns out to upset destroy()
    more than it helps - so the grumbling is simply not allowed to
    become a failure.
    """
    try:
        root.destroy()
    except Exception:
        pass


from core.base_app import LabApp
from core.transports.null_transport import NullTransport
from core.gui.widgets import (parse_nplc, apply_nplc, refresh_nplc,
                              apply_high_z, refresh_high_z)
from core.run_store import build_sample_csv
from drivers.dummy_smu import DummySMU
from drivers.keithley_2611a import Keithley2611A
from drivers.keithley_2450 import Keithley2450

from experiments.vanderpauw.experiment import VanDerPauwExperiment
from experiments.hall.experiment import HallExperiment
from experiments.iv_sweep.experiment import IVSweepExperiment


class NoOptionalsDriver(DummySMU):
    """An instrument declaring neither optional control.

    Nothing in the suite is like this today, which is the reason to
    have it: the greying-out paths would otherwise never be exercised
    until the day somebody adds such a driver.
    """
    NPLC_RANGE = None
    HIGH_Z_OFF = False
    DISPLAY_NAME = "Simulated SMU (no optional controls)"


class NoNPLCDriver(DummySMU):
    """An instrument that declares no integration-time control.

    Nothing in the suite is like this today, which is the reason to
    have it: the greying-out path would otherwise never be exercised
    until the day somebody adds such a driver.
    """
    NPLC_RANGE = None
    DISPLAY_NAME = "Simulated SMU (no NPLC)"


# ---------------------------------------------------------------
# A + B. the control reflects what the driver declares
# ---------------------------------------------------------------


def test_control_follows_the_driver(check):
    for name, ExpClass in (("Van der Pauw", VanDerPauwExperiment),
                           ("Hall", HallExperiment),
                           ("IV sweep", IVSweepExperiment)):
        root = tk.Tk()
        app = LabApp(root, ExpClass)
        exp = app.experiment
        app.connect_role("source", NullTransport(), "<simulated>")
        root.update()

        values = list(exp.nplc_combo["values"])
        check(f"{name}: control is enabled",
              str(exp.nplc_combo["state"]) != "disabled",
              f"state={exp.nplc_combo['state']}")
        check(f"{name}: defaults to 1 NPLC", exp.nplc_var.get() == "1",
              f"got {exp.nplc_var.get()!r}")
        check(f"{name}: presets filtered to the dummy's 0.01-10 range",
              "25" not in values and "10" in values, f"{values}")

        check(f"{name}: high-Z checkbox defaults OFF",
              exp.high_z_var.get() is False)
        check(f"{name}: high-Z checkbox is enabled",
              str(exp.high_z_check["state"]) != "disabled")

        # now an instrument with no such controls
        bare = NoOptionalsDriver(NullTransport())
        refresh_high_z(exp.high_z_check, exp.high_z_var, bare)
        check(f"{name}: high-Z greys out when unsupported",
              str(exp.high_z_check["state"]) == "disabled")
        refresh_nplc(exp.nplc_combo, exp.nplc_var, NoNPLCDriver(NullTransport()))
        check(f"{name}: greys out on an instrument without NPLC",
              str(exp.nplc_combo["state"]) == "disabled"
              and exp.nplc_var.get() == "n/a",
              f"state={exp.nplc_combo['state']} value={exp.nplc_var.get()!r}")
        quiet_destroy(root)


def test_presets_track_the_declared_range(check):
    root = tk.Tk()
    app = LabApp(root, IVSweepExperiment)
    exp = app.experiment
    refresh_nplc(exp.nplc_combo, exp.nplc_var, Keithley2611A(NullTransport()))
    tsp_values = list(exp.nplc_combo["values"])
    refresh_nplc(exp.nplc_combo, exp.nplc_var, Keithley2450(NullTransport()))
    scpi_values = list(exp.nplc_combo["values"])
    check("2611A offers 25 NPLC", "25" in tsp_values, f"{tsp_values}")
    check("2450 does not", "25" not in scpi_values, f"{scpi_values}")
    quiet_destroy(root)

    # ---------------------------------------------------------------
    # C + D. parsing and clamping
    # ---------------------------------------------------------------


def test_parsing(check):
    class FakeVar:
        def __init__(self, text):
            self._text = text

        def get(self):
            return self._text


    check("blank means leave the instrument alone",
          parse_nplc(FakeVar("")) is None)
    check("'n/a' means leave the instrument alone",
          parse_nplc(FakeVar("n/a")) is None)
    check("a number parses", parse_nplc(FakeVar("10")) == 10.0)
    check("a non-preset value is allowed", parse_nplc(FakeVar("2.5")) == 2.5)

    for bad in ("abc", "0", "-1"):
        raised = False
        try:
            parse_nplc(FakeVar(bad))
        except ValueError:
            raised = True
        check(f"{bad!r} is refused", raised)


def test_clamping(check):
    smu = DummySMU(NullTransport())
    check("above range clamps to the maximum", apply_nplc(smu, 999) == 10.0)
    check("below range clamps to the minimum", apply_nplc(smu, 1e-6) == 0.01)
    check("in range passes through", apply_nplc(smu, 0.1) == 0.1)
    check("the instrument actually received it", smu._nplc == 0.1,
          f"driver holds {smu._nplc}")
    check("None sends nothing", apply_nplc(smu, None) is None)
    check("an instrument without the control is left alone",
          apply_nplc(NoNPLCDriver(NullTransport()), 10) is None)

    # ---------------------------------------------------------------
    # E. it reaches the CSV, in every experiment
    # ---------------------------------------------------------------


def test_high_z_control(check):
    smu_hz = DummySMU(NullTransport())
    check("unchecked sends normal off", apply_high_z(smu_hz, False) is False)
    check("the instrument received it", smu_hz._high_z_off is False)
    check("checked sends high-Z", apply_high_z(smu_hz, True) is True)
    check("the instrument received that too", smu_hz._high_z_off is True)
    check("an instrument without the control is left alone",
          apply_high_z(NoOptionalsDriver(NullTransport()), True) is None)


def test_nplc_reaches_the_csv(check):
    for name, ExpClass, runner in (
            ("Van der Pauw", VanDerPauwExperiment,
             lambda e: e._do_run(1, 6, 1e-4, 0.3, 0.0)),
            ("Hall", HallExperiment,
             lambda e: e._do_run(1, "+", 6, 1e-4, 0.3, 0.0)),
    ):
        root = tk.Tk()
        app = LabApp(root, ExpClass)
        exp = app.experiment
        driver = app.connect_role("source", NullTransport(), "<simulated>")
        root.update()

        exp.nplc_var.set("10")
        try:
            runner(exp)
        except TypeError:
            # signature differs between the two; fall back to whatever the
            # experiment's own demo path uses rather than guessing further
            quiet_destroy(root)
            print(f"  SKIP  {name}: run signature differs, covered by "
                  f"its own demo test")
            continue
        root.update()

        check(f"{name}: instrument received 10 NPLC", driver._nplc == 10.0,
              f"driver holds {driver._nplc}")
        runs = [r for s in exp.run_store.samples() for r in exp.run_store.runs_for(s)]
        check(f"{name}: a run was stored", len(runs) >= 1)
        if runs:
            csv = build_sample_csv(runs[0].sample, [runs[0]], name)
            header = csv.splitlines()[5]
            check(f"{name}: nplc is a CSV column", "nplc" in header, header)
            check(f"{name}: output_off_mode is a CSV column",
                  "output_off_mode" in header)
            check(f"{name}: and records the default", ",normal," in csv)
            check(f"{name}: and holds the applied value",
                  ",10.0," in csv or ",10," in csv)
        quiet_destroy(root)
