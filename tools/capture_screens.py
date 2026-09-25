#!/usr/bin/env python
"""Take the user guide's screenshots, in both looks, from the real windows.

Each window is opened on screen, connected to the demo instrument, given
a sample name and run once, so the pictures show a window mid-session -
a filled results table and a plot - rather than an empty form. Then the
whole window and each of its panels are captured, once in the light
look and once in the dark, into `docs/assets/screens/`.

The panels are found by `tools/build_guide.py`'s `window_panels()`,
which is also what writes the table under each picture, so a picture
and its table are always of the same panel.

Usage
-----
    uv run python tools/capture_screens.py                 # every window
    uv run python tools/capture_screens.py iv_sweep        # just one

Windows only, because the capture is a grab of the screen: run it on a
bench or development PC with nothing covering the middle of the screen,
and leave the mouse alone until it finishes. It is not run by CI - a
screenshot depends on the machine's fonts and scaling, so it cannot be
compared byte for byte the way a generated page is. Re-run it when a
window's layout changes; `tests/test_guide.py` fails if a picture the
guide shows is missing.

Your saved light/dark choice is not touched: the look is switched for
these windows only.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build_guide  # noqa: E402

#: Pixels of window around each panel's crop, so its border is kept.
MARGIN = 4

#: How long a run may take before the capture gives up on it.
RUN_TIMEOUT_S = 60

#: What a window is filled in with before its run.
SAMPLE = "demo-sample"

#: Settings made after connecting, per window, so the demo run shows
#: a clean measurement. Connecting re-offers each setting from the
#: instrument's own ranges, and the IV sweep lands on a 0.1 mA
#: compliance that clips the demo sample's 1 kOhm curve - a correct
#: picture of the wrong thing for a guide's first figure.
DEMO_SETTINGS = {
    "iv_sweep": {"compliance_var": "1e-3"},
}

#: The save folder the pictures show, in place of the real one.
SAVE_FOLDER = r"D:\Measurements\{date}"


class _Yes:
    """Stands in for `tkinter.messagebox` while capturing: every question
    is answered yes and nothing blocks. A dialog would sit over the
    window and end up in the picture."""

    def __getattr__(self, name):
        return lambda *a, **k: True


def _dpi_aware():
    """Make Tk's coordinates the screen's pixels, so a crop computed from
    a widget's position lands on that widget under display scaling."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def _silence_dialogs():
    import importlib

    for name in ("smuniversal_lab_suite.core.base_app",
                 "smuniversal_lab_suite.experiments.base_experiment",
                 "smuniversal_lab_suite.experiments.iv_sweep.experiment",
                 "smuniversal_lab_suite.experiments.fixed_source.experiment",
                 "smuniversal_lab_suite.experiments.ossila_4pp.experiment",
                 "smuniversal_lab_suite.experiments.vanderpauw.experiment",
                 "smuniversal_lab_suite.experiments.hall.experiment",
                 "smuniversal_lab_suite.core.gui.connection_panel"):
        module = importlib.import_module(name)
        if hasattr(module, "messagebox"):
            module.messagebox = _Yes()


def _drive(root, steps):
    """Run `steps` - a generator - inside the window's own event loop.

    The loop has to be the real one. A connection runs on a worker
    thread, as it does in the app, and a worker's hand-off to Tk only
    works while the main thread sits in `mainloop()`; pumping with
    `update()` instead fails with "main thread is not in main loop".

    The generator yields a number of seconds to wait, or a function to
    wait on until it returns true.
    """
    failure: list[BaseException] = []

    def report(_exc, value, _tb):
        failure.append(value)
        root.quit()

    root.report_callback_exception = report

    def advance():
        try:
            wait = next(steps)
        except StopIteration:
            root.quit()
            return
        if callable(wait):
            deadline = time.monotonic() + RUN_TIMEOUT_S

            def poll():
                if wait():
                    root.after(300, advance)
                elif time.monotonic() > deadline:
                    report(None, TimeoutError("timed out waiting"), None)
                else:
                    root.after(50, poll)
            root.after(50, poll)
        else:
            root.after(int(wait * 1000), advance)

    root.after(0, advance)
    root.mainloop()
    if failure:
        raise failure[0]


def _grab(widgets, path: Path, margin: int = MARGIN):
    """Save the screen under `widgets` - one, or several whose bounding
    box is taken together - to `path`."""
    from PIL import ImageGrab

    if not isinstance(widgets, (list, tuple)):
        widgets = [widgets]
    left = min(w.winfo_rootx() for w in widgets)
    top = min(w.winfo_rooty() for w in widgets)
    right = max(w.winfo_rootx() + w.winfo_width() for w in widgets)
    bottom = max(w.winfo_rooty() + w.winfo_height() for w in widgets)
    box = (left - margin, top - margin, right + margin, bottom + margin)
    path.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(bbox=box, all_screens=True).save(path, optimize=True)


def _session(app, root, key, mode, shared, written):
    """Connect the demo instrument through the Instruments panel, run
    once, then take the pictures."""
    from smuniversal_lab_suite.core.gui.connection_panel import _connect_with
    from smuniversal_lab_suite.core.transports.null_transport import (
        NullTransport,
    )

    app.theme.set_mode(mode, save=False)
    root.geometry("+40+40")
    root.attributes("-topmost", True)
    root.deiconify()
    yield 1.0

    # Through the panel's own Demo path, so the row reads as it does for
    # an operator - but not through Connect, which would add "demo" to
    # this PC's remembered addresses.
    for role, widgets in app.conn_widgets.items():
        widgets["transport_var"].set("Demo")
        _connect_with(app, role, NullTransport, "demo", demo=True)
    yield lambda: all(app.is_connected(r) for r in app.conn_widgets)

    # A public picture must not show whose PC it was taken on.
    app.sample_name_var.set(SAMPLE)
    app.path_display_var.set(SAVE_FOLDER.format(date=time.strftime("%Y-%m-%d")))
    exp = app.experiments[0]
    for name, value in DEMO_SETTINGS.get(key, {}).items():
        getattr(exp, name).set(value)
    yield 0.3
    exp.run_pressed()
    yield 0.5
    yield lambda: not exp.run_in_progress()
    yield 1.0
    app.tooltips.hide()

    path = build_guide.SCREENS / key / f"window-{mode}.png"
    _grab(root, path, margin=0)
    written.append(path)
    for panel in build_guide.window_panels(app):
        if not panel.widgets:
            continue
        path = build_guide.SCREENS / key / f"{panel.slug}-{mode}.png"
        _grab(panel.widgets, path)
        written.append(path)
        if panel.title in shared and not panel.tab:
            path = (build_guide.SCREENS / build_guide.SHARED
                    / f"{panel.slug}-{mode}.png")
            _grab(panel.widgets, path)
            written.append(path)


def capture(key: str, modes=("light", "dark"), shared=frozenset()):
    """Capture window `key` in each look. `shared` names the panels to
    also save under `shared/` - the ones the Every window page shows."""
    import tkinter as tk

    from smuniversal_lab_suite.core.base_app import LabApp
    from smuniversal_lab_suite.core.identity import SampleRegistry
    from smuniversal_lab_suite.core.launcher import WINDOWS
    from smuniversal_lab_suite.core.ownership import InstrumentOwnership

    written: list[Path] = []
    for mode in modes:
        root = tk.Tk()
        app = LabApp(root, WINDOWS[key][1], ownership=InstrumentOwnership(),
                     samples=SampleRegistry())
        try:
            _drive(root, _session(app, root, key, mode, shared, written))
        finally:
            app.on_close()
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("windows", nargs="*",
                        help="window keys; default every measurement window")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("capture_screens.py grabs the screen and runs on Windows only.")
        return 1

    _dpi_aware()
    _silence_dialogs()
    keys = args.windows or build_guide.measurement_windows()
    shared = frozenset(p.title for p in build_guide.collect()[build_guide.SHARED])
    written = []
    for key in keys:
        # The IV sweep is the window the shared panels are pictured from.
        written += capture(key, shared=shared if key == "iv_sweep" else ())
    for path in written:
        print(path.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
