"""
Layout guard: every experiment window must stay landscape and fit on a
normal monitor.

This exists because the failure is silent. Adding one more panel to a
column costs a few dozen pixels, nobody notices, and eventually the Run
button is below the bottom of somebody's screen with no error anywhere.
Before the three-column layout the Hall window was 1333x1219 - already
taller than a 1080p desktop - and nothing in the code or the tests said
so.

The budget below is deliberately loose. It is a tripwire for "this got a
lot bigger", not a pixel-perfect assertion that would fail on every
font-rendering difference between machines.
"""
import pytest

pytestmark = [pytest.mark.gui]

import sys
import tkinter as tk

from core.base_app import LabApp
from core.gui.console_panel import _toggle_console
from experiments.vanderpauw.experiment import VanDerPauwExperiment
from experiments.hall.experiment import HallExperiment
from experiments.iv_sweep.experiment import IVSweepExperiment
from experiments.ossila_4pp.experiment import Ossila4PPExperiment

# Target: fits a 1600x900 desktop with the console folded, and a 1920x1080
# one with it open. Allows headroom for font differences across machines.
MAX_WIDTH = 1600
MAX_HEIGHT_CONSOLE_OPEN = 1000
MAX_HEIGHT_CONSOLE_FOLDED = 860
MIN_ASPECT = 1.2                 # landscape, not portrait

# One entry per *window*, not per experiment. Wave 5b added the fifth:
# Van der Pauw and Hall hosted together in one tabbed window, which is
# the tallest and widest thing the suite builds and therefore the one
# most worth a tripwire.
WINDOWS = [VanDerPauwExperiment, HallExperiment, IVSweepExperiment,
           Ossila4PPExperiment,
           [VanDerPauwExperiment, HallExperiment]]

# Kept under its old name: several other files import it.
EXPERIMENTS = WINDOWS[:4]

# Which column each panel is expected to land in. Checked by widget
# parentage rather than by reading the source, so moving a panel without
# updating this list is caught.
#
# Per experiment, because they don't share a widget set: Van der Pauw and
# Hall have a corner diagram and a level dropdown, the IV sweep has a
# compliance dropdown and a plot. What they have in common is the
# *shape* - sample state on the left, controls in the middle, output on
# the right - and that is what each entry below asserts.
EXPECTED_COLUMN = {
    VanDerPauwExperiment: {
        "canvas": "col_left",
        "level_combo": "col_mid",
        "run_btn": "col_mid",
        "tree": "col_right",
    },
    HallExperiment: {
        "canvas": "col_left",
        "level_combo": "col_mid",
        "run_btn": "col_mid",
        "tree": "col_right",
    },
    Ossila4PPExperiment: {
        "width_entry": "col_left",
        "run_btn": "col_mid",
        "tree": "col_right",
        "plot_toolbar": "col_right",
    },
    IVSweepExperiment: {
        "compliance_combo": "col_left",
        "run_btn": "col_mid",
        "periodic_btn": "col_mid",
        "tree": "col_right",
        "plot_toolbar": "col_right",
    },
}


def _column_of(exp, widget):
    """Walk up the widget tree until one of the three columns is hit."""
    columns = {str(exp.col_left): "col_left",
               str(exp.col_mid): "col_mid",
               str(exp.col_right): "col_right"}
    node = widget
    while node is not None:
        name = columns.get(str(node))
        if name:
            return name
        node = getattr(node, "master", None)
    return "<not in any column>"


def _window_name(spec):
    classes = [spec] if isinstance(spec, type) else list(spec)
    if len(classes) == 1:
        return classes[0].NAME[:34]
    return " + ".join(c.TAB_NAME or c.NAME for c in classes)[:34]


def _collect_layout():
    bad = []
    for spec in WINDOWS:
        classes = [spec] if isinstance(spec, type) else list(spec)
        root = tk.Tk()
        app = LabApp(root, spec)
        root.update_idletasks()

        width = root.winfo_reqwidth()
        height = root.winfo_reqheight()
        aspect = width / height

        app.console_visible.set(False)
        _toggle_console(app)
        root.update_idletasks()
        folded_height = root.winfo_reqheight()

        name = _window_name(spec)
        print(f"  {name:36} {width:5d} x {height:<5d} "
              f"aspect {aspect:.2f}   folded {width}x{folded_height}")

        if width > MAX_WIDTH:
            bad.append((name, f"width {width} > {MAX_WIDTH}"))
        if height > MAX_HEIGHT_CONSOLE_OPEN:
            bad.append((name, f"height {height} > {MAX_HEIGHT_CONSOLE_OPEN}"))
        if folded_height > MAX_HEIGHT_CONSOLE_FOLDED:
            bad.append((name,
                        f"folded height {folded_height} > "
                        f"{MAX_HEIGHT_CONSOLE_FOLDED}"))
        if aspect < MIN_ASPECT:
            bad.append((name, f"aspect {aspect:.2f} < {MIN_ASPECT} (too tall)"))

        for exp in app.experiments:
            cls = type(exp)
            # every panel must have landed somewhere sensible
            for attr, expected in EXPECTED_COLUMN[cls].items():
                widget = getattr(exp, attr, None)
                if widget is None:
                    bad.append((name, f"{cls.__name__}: missing widget {attr}"))
                    continue
                actual = _column_of(exp, widget)
                if actual != expected:
                    bad.append((name, f"{cls.__name__}: {attr} is in {actual}, "
                                      f"expected {expected}"))

            # no column should be wildly taller than the window it lives in
            for column in ("col_left", "col_mid", "col_right"):
                column_height = getattr(exp, column).winfo_reqheight()
                if column_height > MAX_HEIGHT_CONSOLE_FOLDED:
                    bad.append((name, f"{cls.__name__}: {column} alone is "
                                      f"{column_height} px tall"))

        # Wave 5b: the stage belongs to the window, so it must exist once
        # and must not be inside any experiment's columns. A stage panel
        # that drifted back into a column would be one stage panel per
        # tab, which is two TemperatureControllers on one COM port - a
        # fault that appears at the bench and nowhere in this suite.
        if any(e.USES_TEMP_STAGE for e in app.experiments):
            readout = getattr(app, "temp_readout_label", None)
            if readout is None:
                bad.append((name, "no app-level temperature stage panel"))
            else:
                for exp in app.experiments:
                    where = _column_of(exp, readout)
                    if where != "<not in any column>":
                        bad.append((name, f"stage panel is inside {where}"))
        elif getattr(app, "temp_readout_label", None) is not None:
            bad.append((name, "a stage panel was built for a window that "
                              "declares no USES_TEMP_STAGE"))

        app.on_close()
    return bad


if __name__ == "__main__":
    print("  budget: "
          f"{MAX_WIDTH} x {MAX_HEIGHT_CONSOLE_OPEN} "
          f"({MAX_HEIGHT_CONSOLE_FOLDED} folded), aspect >= {MIN_ASPECT}\n")
    bad = _collect_layout()
    for item in bad:
        print(f"      {item}")
    print(f"\n{'PASS' if not bad else f'{len(bad)} FAILURE(S)'}")
    sys.exit(1 if bad else 0)


# --- Wave 0a: these used to return a list of failures that only the
# --- __main__ block inspected. Under pytest a returned value is
# --- ignored, so without these wrappers all of them would pass
# --- unconditionally. The collectors above are unchanged.

def test_layout():
    bad = _collect_layout()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"
