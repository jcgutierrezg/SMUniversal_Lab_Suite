"""Full Van der Pauw run against the simulated sample, with no hardware.

The dummy's default sample is symmetric, so all four positions read the
same R and the sheet resistance has a closed form:

    Rs = pi * R / ln(2)

This test drives the real experiment code end to end and checks the
answer against that. It's the regression guard for the whole chain -
transport, driver, sequencing, averaging, and solver.
"""
import pytest

pytestmark = [pytest.mark.slow, pytest.mark.gui]

import math
import tkinter as tk

from core.base_app import LabApp
from core.transports.null_transport import NullTransport
from experiments.vanderpauw.experiment import VanDerPauwExperiment

TOLERANCE_PERCENT = 0.5


def test_vdp_chain_recovers_sheet_resistance(check):
    root = tk.Tk()
    app = LabApp(root, VanDerPauwExperiment)
    exp = app.experiment

    # connect through the normal path - NullTransport identifies as the
    # dummy, so this exercises real *IDN? detection
    driver = app.connect_role("source", NullTransport(), "<simulated sample>")
    root.update()
    print(f"Connected: {driver.DISPLAY_NAME}")
    print(f"Simulated sample: {driver.resistance:g} ohm per pair\n")

    # dropdowns should now come from the driver's declared limits
    print(f"Level dropdown repopulated: {len(exp.level_combo['values'])} entries")
    print(f"  {list(exp.level_combo['values'])}\n")

    # run all four positions
    driver.output_on()
    measured = []
    for pos in (1, 2, 3, 4):
        r_pos = exp._polarity_block(driver, +1, 12, 1e-4, 0.0, pos)
        r_neg = exp._polarity_block(driver, -1, 12, 1e-4, 0.0, pos)
        rave = (r_pos + r_neg) / 2.0
        measured.append(rave)
        print(f"  Pos{pos}: R(+)={r_pos:9.4f}  R(-)={r_neg:9.4f}  R(ave)={rave:9.4f}")
    driver.output_off()

    # feed them into the calculation exactly as the Copy button would
    for var, val in zip(exp.pos_vars, measured):
        var.set(f"{val:.6g}")
    exp.calculate_vdp()

    rs = float(exp.rs_var.get())
    expected = driver.expected_sheet_resistance

    print(f"\nSolved   Rs = {rs:.4f} ohm/sq")
    print(f"Analytic Rs = {expected:.4f} ohm/sq   (pi*R/ln2)")
    error = abs(rs - expected) / expected * 100
    print(f"Error       = {error:.4f}%   (noise floor is {driver.noise_fraction*100:g}% per reading)")

    check("the solved Rs matches pi*R/ln2 within tolerance",
          error < TOLERANCE_PERCENT, f"{error:.4f}% > {TOLERANCE_PERCENT}%")
    root.destroy()
