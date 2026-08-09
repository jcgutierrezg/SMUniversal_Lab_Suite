"""
Carrier type, and the Van der Pauw -> Hall sheet-resistance handoff.

Two things worth guarding:

  A. Carrier type follows the sign of V_H, and nothing else. Getting this
     backwards would mislabel every sample the lab measures, and the
     numbers would all still look right - which is exactly why it is
     asserted rather than eyeballed.

  B. The result file written by Van der Pauw must be readable by Hall.
     These are two separate windows that never share memory, so the file
     is the entire interface between them. It is tested as one.
"""
import pytest

pytestmark = [pytest.mark.gui]

import os, sys
import math
import tempfile
import tkinter as tk

from core import vdp_result
from vdp_harness import run_vdp
from core.base_app import LabApp
from core.run_store import Run
from core.transports.null_transport import NullTransport
from experiments.hall import hall_math
from experiments.hall.experiment import HallExperiment
from experiments.vanderpauw.experiment import VanDerPauwExperiment


class DialogRecorder:
    """Modal dialogs would block a headless run; capture them instead."""

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


# ---- A. carrier type ----
def _collect_carrier_type():
    """Sign of V_H maps to carrier type, and zero is indeterminate."""
    bad = []
    cases = [
        (+1e-3, hall_math.P_TYPE),
        (+1e-12, hall_math.P_TYPE),
        (-1e-3, hall_math.N_TYPE),
        (-1e-12, hall_math.N_TYPE),
        (0.0, hall_math.INDETERMINATE),
    ]
    for vh, expected in cases:
        got = hall_math.carrier_type(vh)
        if got != expected:
            bad.append((f"V_H = {vh:+g}", got, expected))

    # reversing the field must reverse the reported type, and nothing else
    base = [0.031, -0.012, 0.027, -0.009, 0.030, -0.011, 0.026, -0.010]
    vh_forward = hall_math.hall_voltage(*base)
    # swapping the P and N groups is what reversing B does
    swapped = base[4:] + base[:4]
    vh_reversed = hall_math.hall_voltage(*swapped)

    if not math.isclose(vh_reversed, -vh_forward, rel_tol=1e-12):
        bad.append(("field reversal", vh_reversed, -vh_forward))
    if hall_math.carrier_type(vh_forward) == hall_math.carrier_type(vh_reversed):
        bad.append(("field reversal", "type unchanged", "type should flip"))
    return bad


# ---- B. the result file, as text ----
def _collect_result_file_roundtrip():
    """format_result -> parse_result must survive intact."""
    bad = []
    text = vdp_result.format_result(
        sample="wafer_A", rh=1234.5678, rv=1240.1234,
        rs=5623.456789, rho=0.5623456789, thickness_um=1.5,
        stage_lines=["# stage_temp_C: 24.8", "# stage_state: IDLE"])

    fields = vdp_result.parse_result(text)
    expected = {
        "sample": "wafer_A",
        "thickness_um": "1.5",
        "stage_temp_C": "24.8",
        "stage_state": "IDLE",
    }
    for key, want in expected.items():
        if fields.get(key) != want:
            bad.append((key, fields.get(key), want))

    if not math.isclose(float(fields[vdp_result.RS_KEY]), 5623.456789, rel_tol=1e-9):
        bad.append(("Rs", fields[vdp_result.RS_KEY], 5623.456789))

    # a file that has gained an unknown field must still parse
    grown = text + "# future_field: 42\n"
    if vdp_result.parse_result(grown).get("future_field") != "42":
        bad.append(("unknown field", "dropped", "kept"))

    # a file with no Rs must raise, not return a wrong number
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "not_a_result.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# sample: wafer_A\n# thickness_um: 1.5\n")
        try:
            vdp_result.read_result(path)
            bad.append(("missing Rs", "no exception", "ValueError"))
        except ValueError:
            pass
    return bad


# ---- B2. the handoff, through the real GUIs ----
def _collect_vdp_to_hall_handoff():
    """A real VdP Calculate writes a file a real Hall load can read."""
    bad = []

    with tempfile.TemporaryDirectory() as tmp:
        # --- Van der Pauw: measure, calculate, which saves the result ---
        root = tk.Tk()
        app = LabApp(root, VanDerPauwExperiment)
        vdp = app.experiment
        app.storage_path = tmp
        vdp.sample_name_var.set("wafer_A")
        vdp.thickness_entry_var.set("1.5")

        driver = app.connect_role("source", NullTransport(), "<simulated>")
        root.update()

        # the real run path, so runs land in the store as they would in
        # use - _polarity_block alone would skip the recording step
        for pos in (1, 2, 3, 4):
            run_vdp(vdp, root, pos, points=8)

        if len(vdp.run_store) != 4:
            bad.append(("runs recorded", len(vdp.run_store), 4))

        for var, item in zip(vdp.pos_vars, vdp.tree.get_children()):
            var.set(str(vdp.tree.item(item, "values")[4]))

        vdp.calculate_vdp()
        root.update()

        # Take the reference from the value that actually gets written,
        # not from the on-screen one.
        #
        # rs_var is a *display* string formatted to 6 significant
        # figures; the CSV and the Hall loader both carry 9. Comparing
        # the round trip against the display value therefore measures
        # the label's formatting, not the handoff - and it fails only
        # when Rs needs more than 6 significant figures, i.e. once it
        # goes above about 1000 Ω/□ with any decimals. Below that the
        # truncation is invisible and the test passes, so this sat here
        # as an intermittent failure that looked like noise.
        #
        # The round trip was never the lossy step. The reference was.
        rs_measured = float(vdp._calculated["Rs_ohm_per_sq"])
        rs_displayed = float(vdp.rs_var.get())

        # nothing is on disk until Save is pressed
        if [f for f in os.listdir(tmp) if f.endswith(".csv")]:
            bad.append(("auto-save", "a CSV appeared", "nothing before Save"))

        vdp_dialogs = DialogRecorder()
        import experiments.base_experiment as base_module
        base_module.messagebox = vdp_dialogs
        vdp.save_runs()
        root.update()
        app.on_close()

        saved = [f for f in os.listdir(tmp) if f.endswith("_vanderpauw.csv")]
        if len(saved) != 1:
            bad.append(("saved CSV", saved, "exactly one"))
            return bad
        result_path = os.path.join(tmp, saved[0])
        print(f"    VdP saved {saved[0]}, Rs = {rs_measured:.6f} Ω/□ "
              f"(shown as {rs_displayed:g})")

        # --- Hall: load it back through the real handler ---
        root = tk.Tk()
        app = LabApp(root, HallExperiment)
        hall = app.experiment
        app.storage_path = tmp
        hall.sample_name_var.set("wafer_A")
        hall.thickness_um = 1.5

        dialogs = DialogRecorder()
        import experiments.hall.experiment as hall_module
        hall_module.messagebox = dialogs
        hall_module.filedialog = type("FD", (), {
            "askopenfilename": staticmethod(lambda **kw: result_path)})()

        hall.load_rs_from_vdp()
        root.update()

        loaded = float(hall.calc_Rs_var.get())
        print(f"    Hall loaded Rs = {loaded:.6f} Ω/□")

        if not math.isclose(loaded, rs_measured, rel_tol=1e-6):
            bad.append(("Rs handoff: loaded vs written",
                        loaded, rs_measured))
        if dialogs.calls:
            bad.append(("matching sample", dialogs.calls, "no warning expected"))
        if hall.rs_source_path != result_path:
            bad.append(("provenance", hall.rs_source_path, result_path))

        # results and provenance must both reach the saved Hall CSV
        hall._record_run(
            ("wafer_A", "Pos1", "+", "0.0001", "0.1", "-0.1"),
            Run(sample="wafer_A",
                metadata={"meas_number": 1, "position": 1, "b_polarity": "+"},
                readings=[{"point": 1, "voltage_V": 0.1, "current_A": 1e-4}]))

        for attr, value in (("v13p_var", 0.11), ("v31p_var", 0.09),
                            ("v24p_var", 0.11), ("v42p_var", 0.09),
                            ("v13n_var", 0.09), ("v31n_var", 0.11),
                            ("v24n_var", 0.09), ("v42n_var", 0.11)):
            getattr(hall, attr).set(str(value))
        hall.calc_B_var.set("0.82")
        hall.calc_I_var.set("1e-4")
        hall.calculate_hall()

        import experiments.base_experiment as base_module
        base_module.messagebox = dialogs
        hall.save_runs()
        root.update()

        hall_files = [f for f in os.listdir(tmp) if f.endswith("_hall.csv")]
        if not hall_files:
            bad.append(("hall save", "no file", "one CSV"))
        else:
            with open(os.path.join(tmp, hall_files[0]), encoding="utf-8") as f:
                content = f.read()
            for needed in ("# Rs_source:", "# carrier_type:",
                           "# Rs_ohm_per_sq:", "# V_H_V:"):
                if needed not in content:
                    bad.append((f"{needed} in saved CSV", "absent", "present"))
            print(f"    Hall saved {hall_files[0]} with results + provenance")

        # --- mismatch must warn but still load ---
        dialogs.calls.clear()
        hall.thickness_um = 200.0            # wrong sample entirely
        hall.calc_Rs_var.set("")
        hall.load_rs_from_vdp()
        root.update()

        if not hall.calc_Rs_var.get():
            bad.append(("mismatch", "refused to load", "should load anyway"))
        warned = [c for c in dialogs.calls if c[0] == "warning"]
        if not warned:
            bad.append(("mismatch", "no warning", "should warn on thickness"))
        else:
            print("    Thickness mismatch warned: "
                  + warned[0][2].splitlines()[2][:58] + "...")

        app.on_close()
    return bad


TESTS = [
    ("carrier type from sign of V_H", _collect_carrier_type),
    ("result file round trip", _collect_result_file_roundtrip),
    ("VdP -> Hall handoff through the GUIs", _collect_vdp_to_hall_handoff),
]

if __name__ == "__main__":
    failures = 0
    for name, fn in TESTS:
        bad = fn()
        print(f"  {'ok  ' if not bad else 'FAIL'}  {name}")
        for item in bad[:6]:
            print(f"          {item}")
        failures += len(bad)
    print(f"\n{'PASS' if not failures else f'{failures} FAILURE(S)'}")
    sys.exit(1 if failures else 0)


# --- Wave 0a: these used to return a list of failures that only the
# --- __main__ block inspected. Under pytest a returned value is
# --- ignored, so without these wrappers all of them would pass
# --- unconditionally. The collectors above are unchanged.

def test_carrier_type():
    bad = _collect_carrier_type()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_result_file_roundtrip():
    bad = _collect_result_file_roundtrip()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_vdp_to_hall_handoff():
    bad = _collect_vdp_to_hall_handoff()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"
