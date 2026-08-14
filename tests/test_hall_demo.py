import pytest

pytestmark = [pytest.mark.gui]

import sys, os

"""
Full Hall run against the simulated sample, with no hardware.

Two halves, because Hall has two chains that can break independently:

  A. The measurement chain - transport, driver, sequencing, averaging.
     Checked against Ohm's law on the dummy's resistive sample.

  B. The calculation chain - results table, the Copy mapping, the
     eight-term average, the unit conversions. Checked by feeding in four
     rows built from a *known* carrier density and asserting it comes
     back out.

Half B matters more than it looks. COPY_MAP decides which measured
voltage becomes V13,P versus V31,P and so on; a single transposition
there still produces a plausible-looking number, just a wrong one. This
is the test that would catch it.

The dummy is a plain resistor with no magnetic response, so it cannot
produce a real Hall voltage - which is exactly why half B supplies
synthetic voltages rather than measuring them.
"""
import math
import tkinter as tk

from core.base_app import LabApp
from core.transports.null_transport import NullTransport
from core.parameters import HallParameters
from experiments.hall.experiment import HallExperiment
from experiments.hall import hall_math

Q_E = hall_math.Q_E


# Modal dialogs block forever without a user, so capture them instead.
# This is not only to unblock the test: it lets the guard-rail check
# assert that a warning was actually raised, rather than just that
# nothing changed.
class DialogRecorder:
    def __init__(self):
        self.calls = []

    def showerror(self, title, message, **kw):
        self.calls.append(("error", title, message))

    def showwarning(self, title, message, **kw):
        self.calls.append(("warning", title, message))

    def showinfo(self, title, message, **kw):
        self.calls.append(("info", title, message))

    def askokcancel(self, title, message, **kw):
        self.calls.append(("askokcancel", title, message))
        return True

    def askyesnocancel(self, title, message, **kw):
        # Wave 5c-ii: the save-collision pre-flight asks through this.
        # True means "same sample", which lets the run proceed.
        self.calls.append(("askyesnocancel", title, message))
        return True



def test_hall_end_to_end(check):
    dialogs = DialogRecorder()
    import experiments.hall.experiment as hall_experiment
    hall_experiment.messagebox = dialogs

    root = tk.Tk()
    app = LabApp(root, HallExperiment)
    exp = app.experiment

    failures = []

    # ---------------------------------------------------------------
    # A. measurement chain
    # ---------------------------------------------------------------
    driver = app.connect_role("source", NullTransport(), "<simulated sample>")
    root.update()
    print(f"Connected: {driver.DISPLAY_NAME}")
    print(f"Simulated sample: {driver.resistance:g} ohm per pair\n")

    level = 1e-4
    driver.output_on()
    # Wave 5a-ii: `_measure_polarity` takes a run context and a frozen
    # parameter snapshot, and puts its readings on the run rather than
    # returning them. A real run context is opened here rather than a
    # stub - the block checkpoints and sleeps through it, and a stub
    # would be a second implementation of the thing under test. The run
    # is never committed; this section is about the measurement chain,
    # not the commit gate.
    params = HallParameters(
        sample=app.samples.ref("demo"), position=1, field_sign="+",
        level_a=level, points_n=12, delay_s=0.0, compliance_v=1.0,
        thickness_m=1.5e-6)
    with exp.begin_run(parameters=params) as run:
        run.start()
        v_plus, i_plus = exp._measure_polarity(run, driver, params, +1)
        raw_pos = list(run.readings)
        v_minus, i_minus = exp._measure_polarity(run, driver, params, -1)
        raw_neg = list(run.readings)[len(raw_pos):]
    driver.output_off()

    expected_v = level * driver.resistance
    print(f"  V(+I) = {v_plus:+.6f} V   expected {+expected_v:+.6f}")
    print(f"  V(-I) = {v_minus:+.6f} V   expected {-expected_v:+.6f}")
    print(f"  raw rows captured: {len(raw_pos)} pos, {len(raw_neg)} neg")

    for name, got, want in (("V(+I)", v_plus, +expected_v),
                            ("V(-I)", v_minus, -expected_v)):
        error = abs(got - want) / abs(want)
        if error > 0.02:                       # dummy noise is ~0.1% per reading
            failures.append((name, got, want))

    if len(raw_pos) != 12 or len(raw_neg) != 12:
        failures.append(("raw row count", (len(raw_pos), len(raw_neg)), (12, 12)))

    # ---------------------------------------------------------------
    # B. calculation chain, from a known carrier density
    # ---------------------------------------------------------------
    ns_true_cm2 = 5e12                       # cm^-2
    current = 100e-6                         # A
    field = 0.82                             # T
    sheet_r = 250.0                          # ohm/sq
    thickness_um = 1.5

    vh_true = current * field / (Q_E * ns_true_cm2 * 1e4)
    offset = vh_true * 500.0                 # resistive drop the average must remove

    hi, lo = offset + vh_true, offset - vh_true

    # (position, B polarity) -> (V+, V-) as the results table would hold them
    rows = {
        (1, "+"): (hi, lo),
        (1, "-"): (lo, hi),
        (2, "+"): (hi, lo),
        (2, "-"): (lo, hi),
    }

    print(f"\n  Built 4 rows from n_s = {ns_true_cm2:g} cm^-2")
    print(f"  True V_H = {vh_true*1e3:.4f} mV, buried under a "
          f"{offset*1e3:.2f} mV resistive offset")

    for (pos, b_pol), (vp, vm) in rows.items():
        exp.tree.insert("", "end", text="☑",
                        values=("sample", f"Pos{pos}", b_pol,
                                f"{current:.6g}", f"{vp:.9g}", f"{vm:.9g}"))

    # drive the real buttons
    exp.copy_over()
    exp.calc_B_var.set(f"{field:g}")
    exp.calc_Rs_var.set(f"{sheet_r:g}")
    exp.calc_I_var.set(f"{current:g}")
    exp.thickness_entry_var.set(f"{thickness_um:g}")
    exp.sample_type_var.set("Thin film")
    exp.calculate_hall()
    root.update()

    vh_got = float(exp.vh_var.get())
    ns_got = float(exp.ns_var.get().split()[0])
    mu_got = float(exp.mu_var.get().split()[0])
    rho_got = float(exp.rho_var.get().split()[0])

    mu_expected = 1.0 / (Q_E * ns_true_cm2 * sheet_r)
    rho_expected = sheet_r * thickness_um * 1e-4

    print(f"\n  V_H        = {vh_got*1e3:.6f} mV    expected {vh_true*1e3:.6f}")
    print(f"  n_s        = {ns_got:.6g} cm^-2   expected {ns_true_cm2:.6g}")
    print(f"  mobility   = {mu_got:.6g} cm^2/Vs  expected {mu_expected:.6g}")
    print(f"  resistivity= {rho_got:.6g} ohm.cm  expected {rho_expected:.6g}")

    for name, got, want in (("V_H", vh_got, vh_true),
                            ("n_s", ns_got, ns_true_cm2),
                            ("mobility", mu_got, mu_expected),
                            ("resistivity", rho_got, rho_expected)):
        if not math.isclose(got, want, rel_tol=1e-5):
            failures.append((name, got, want))

    # the delta column should show 2*V_H on every pairing
    for attr in ("dv13_var", "dv31_var", "dv24_var", "dv42_var"):
        delta = float(getattr(exp, attr).get())
        if not math.isclose(abs(delta), 2 * vh_true, rel_tol=1e-5):
            failures.append((attr, delta, 2 * vh_true))

    # bulk should divide the sheet density by the thickness, nothing else
    exp.sample_type_var.set("Bulk")
    exp.calculate_hall()
    n_bulk = float(exp.ns_var.get().split()[0])
    n_bulk_expected = ns_true_cm2 / (thickness_um * 1e-4)
    print(f"  n_bulk     = {n_bulk:.6g} cm^-3   expected {n_bulk_expected:.6g}")
    if not math.isclose(n_bulk, n_bulk_expected, rel_tol=1e-5):
        failures.append(("bulk n", n_bulk, n_bulk_expected))

    # ---------------------------------------------------------------
    # C. the Copy guard rails
    # ---------------------------------------------------------------
    exp.clear_output()
    exp.tree.insert("", "end", text="☑",
                    values=("sample", "Pos1", "+", "1e-4", "0.1", "0.2"))
    before = exp.v13p_var.get()
    dialogs.calls.clear()
    exp.copy_over()          # only one row ticked - must refuse, not half-fill
    if exp.v13p_var.get() != before:
        failures.append(("copy guard", "modified boxes", "should have refused"))
    if not any(kind == "error" for kind, _t, _m in dialogs.calls):
        failures.append(("copy guard", "no dialog", "should have warned the user"))

    print("\n  Copy with 1 ticked row refused, boxes untouched: "
          f"{exp.v13p_var.get() == before}")
    print(f"  and told the user: {dialogs.calls[0][2].splitlines()[0]!r}")

    # a full set with a wrong combination must also refuse
    exp.clear_output()
    for pos, b_pol in ((1, "+"), (1, "+"), (2, "+"), (2, "-")):   # Pos1+ twice
        exp.tree.insert("", "end", text="☑",
                        values=("sample", f"Pos{pos}", b_pol, "1e-4", "0.1", "0.2"))
    dialogs.calls.clear()
    before = exp.v13p_var.get()
    exp.copy_over()
    if exp.v13p_var.get() != before or not dialogs.calls:
        failures.append(("combo guard", "accepted", "should have refused Pos1+ twice"))
    print(f"  Copy with a duplicated combo refused: {bool(dialogs.calls)}")

    app.on_close()

    check("every Hall check held", not failures,
          "; ".join(f"{n}: got {g!r} want {w!r}" for n, g, w in failures))
