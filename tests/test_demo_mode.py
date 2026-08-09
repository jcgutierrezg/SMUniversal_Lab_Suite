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
from vdp_harness import run_vdp

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

    # Run all four positions through the real run path.
    #
    # Wave 5a-i: this used to drive `_polarity_block` directly with
    # loose arguments, which skipped the run lifecycle entirely and so
    # never recorded anything. Going through `run_vdp` means the demo
    # exercises what the operator exercises - snapshot, ownership claim,
    # commit gate and all - which is the whole point of a demo mode.
    for pos in (1, 2, 3, 4):
        run_vdp(exp, root, pos, points=12)

    for item in exp.tree.get_children():
        values = exp.tree.item(item, "values")
        print(f"  {values[1]}: R(+)={float(values[2]):9.4f}  "
              f"R(-)={float(values[3]):9.4f}  R(ave)={float(values[4]):9.4f}")

    # Copy the four ticked rows in exactly as the operator would, which
    # also carries the provenance across.
    for item in exp.tree.get_children():
        exp.tree.item(item, text="\u2611")
    exp.copy_over()
    root.update()

    rs = float(exp.rs_var.get())
    expected = driver.expected_sheet_resistance

    print(f"\nSolved   Rs = {rs:.4f} ohm/sq")
    print(f"Analytic Rs = {expected:.4f} ohm/sq   (pi*R/ln2)")
    error = abs(rs - expected) / expected * 100
    print(f"Error       = {error:.4f}%   (noise floor is {driver.noise_fraction*100:g}% per reading)")

    check("the solved Rs matches pi*R/ln2 within tolerance",
          error < TOLERANCE_PERCENT, f"{error:.4f}% > {TOLERANCE_PERCENT}%")
    root.destroy()
