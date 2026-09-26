#!/usr/bin/env python
"""Take the user guide's screenshots, in both looks, from the real windows.

Each window is opened on screen, connected to the demo instrument and
taken through a short session - a few runs, and the calculation where
the window has one - so the pictures show a window in use rather than
an empty form. Then the whole window and each of its panels are
captured, once in the light look and once in the dark, into
`docs/assets/screens/`.

The panels are found by `tools/build_guide.py`'s `window_panels()`,
which is also what writes the table under each picture, so a picture
and its table are always of the same panel.

Usage
-----
    uv run python tools/capture_screens.py                 # every window
    uv run python tools/capture_screens.py iv_sweep        # just one

The plotter is pictured with the IV sweep's demo files open, so it is
captured after the IV sweep: naming `plotter` alone captures both.

Windows only. Each picture is read from the window's own pixels
(`PrintWindow`), not from the screen, so a video call or a notification
over the window does not end up in it. The window must fit on its
screen, though - Windows does not draw the part of a window that is off
it - so the capture stops, rather than save a cut-off picture, when one
does not. Leave the mouse alone until it finishes - a pointer resting on
a control opens its tooltip. It is not run by CI - a
screenshot depends on the machine's fonts and scaling, so it cannot be
compared byte for byte the way a generated page is. Re-run it when a
window's layout changes; `tests/test_docs.py` fails if a picture the
guide shows is missing.

Nothing here touches this PC's settings or files: the look is switched
for these windows only, every window saves into a temporary folder that
is deleted afterwards, and the pictures show a made-up save folder in
place of it.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build_guide  # noqa: E402

#: Pixels of window around each panel's crop, so its border is kept.
MARGIN = 4

#: How long a run may take before the capture gives up on it.
RUN_TIMEOUT_S = 90

#: What a window is filled in with before its run.
SAMPLE = "demo-sample"

#: The save folder the pictures show, in place of the real one.
SAVE_FOLDER = r"D:\Measurements\{date}"


class _Yes:
    """Stands in for `tkinter.messagebox` and `filedialog` while
    capturing: every question is answered yes and nothing blocks. A
    dialog would sit over the window and end up in the picture."""

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
                 "smuniversal_lab_suite.core.gui.connection_panel",
                 "smuniversal_lab_suite.plotter.window"):
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
        except BaseException as exc:          # noqa: BLE001 - reported
            report(None, exc, None)
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


def shown_pictures() -> set[Path]:
    """Every picture a page under docs/ shows. A panel is only pictured
    if some page shows it, so the folder holds nothing nobody sees - a
    window's copy of a panel described on Every window, for one."""
    import re

    image = re.compile(r"!\[[^\]]*\]\(([^)#\s]+)")
    shown = set()
    for page in (ROOT / "docs").rglob("*.md"):
        for target in image.findall(page.read_text(encoding="utf-8")):
            shown.add((page.parent / target).resolve())
    return shown


def _window_image(top):
    """The whole of window `top` - frame included - as a picture, and
    the screen position of its top-left corner. Read from the window's
    own pixels, so whatever covers it, the picture is of the window
    alone. A window running off its screen is refused: Windows leaves the
    part that is off it undrawn."""
    import ctypes
    from ctypes import wintypes

    from PIL import Image

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    handle = ctypes.c_void_p
    user32.GetWindowDC.argtypes = [handle]
    user32.GetWindowDC.restype = handle
    user32.ReleaseDC.argtypes = [handle, handle]
    user32.PrintWindow.argtypes = [handle, handle, wintypes.UINT]
    gdi32.CreateCompatibleDC.argtypes = [handle]
    gdi32.CreateCompatibleDC.restype = handle
    gdi32.CreateCompatibleBitmap.argtypes = [handle, ctypes.c_int,
                                             ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = handle
    gdi32.SelectObject.argtypes = [handle, handle]
    gdi32.SelectObject.restype = handle
    gdi32.GetDIBits.argtypes = [handle, handle, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.c_void_p,
                                wintypes.UINT]
    gdi32.DeleteObject.argtypes = [handle]
    gdi32.DeleteDC.argtypes = [handle]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32.MonitorFromWindow.argtypes = [handle, wintypes.DWORD]
    user32.MonitorFromWindow.restype = handle
    user32.GetMonitorInfoW.argtypes = [handle, ctypes.c_void_p]

    hwnd = int(top.wm_frame(), 16)
    rect = wintypes.RECT()
    user32.GetWindowRect(handle(hwnd), ctypes.byref(rect))
    client_left, client_top = top.winfo_rootx(), top.winfo_rooty()
    client_right = client_left + top.winfo_width()
    client_bottom = client_top + top.winfo_height()
    monitor = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2),  # nearest
                           ctypes.byref(monitor))
    screen = monitor.rcMonitor
    if (client_left < screen.left or client_top < screen.top
            or client_right > screen.right or client_bottom > screen.bottom):
        raise RuntimeError(
            f"{top.title()!r} is {client_right - client_left} x "
            f"{client_bottom - client_top} and runs off its "
            f"{screen.right - screen.left} x {screen.bottom - screen.top} "
            "screen, so part of it would be pictured blank. Capture on a "
            "larger screen, or at a lower display scaling.")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        # PW_RENDERFULLCONTENT: the window as the compositor holds it.
        if not user32.PrintWindow(hwnd, memory_dc, 2):
            raise RuntimeError("PrintWindow could not read the window")
        header = BITMAPINFOHEADER(
            biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=width,
            biHeight=-height, biPlanes=1, biBitCount=32, biCompression=0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels,
                        ctypes.byref(header), 0)
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)
    image = Image.frombuffer("RGB", (width, height), pixels.raw,
                             "raw", "BGRX", 0, 1)
    return image, (rect.left, rect.top)


def _grab(widgets, path: Path, margin: int = MARGIN):
    """Save the part of the window under `widgets` - one, or several
    whose bounding box is taken together - to `path`."""
    if not isinstance(widgets, (list, tuple)):
        widgets = [widgets]
    image, (x0, y0) = _window_image(widgets[0].winfo_toplevel())
    left = min(w.winfo_rootx() for w in widgets)
    top = min(w.winfo_rooty() for w in widgets)
    right = max(w.winfo_rootx() + w.winfo_width() for w in widgets)
    bottom = max(w.winfo_rooty() + w.winfo_height() for w in widgets)
    box = (left - margin - x0, top - margin - y0,
           right + margin - x0, bottom + margin - y0)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.crop(box).save(path, optimize=True)


# --------------------------------------------------------------------------
# One short session per window
# --------------------------------------------------------------------------

def _run(exp):
    """Press Run and wait for the run to finish."""
    exp.run_pressed()
    yield 0.5
    yield lambda: not exp.run_in_progress()
    yield 0.5


def _tick_all(exp):
    for item in exp.tree.get_children():
        exp.tree.item(item, text="☑")


def _iv_sweep(app, _saved):
    exp = app.experiments[0]
    # Connecting re-offers the compliance from the instrument's ranges,
    # and lands on 0.1 mA - which clips the demo sample's 1 kOhm curve.
    # 2 mA, not 1: at 1 mA a +-1 V sweep of 1 kOhm ends exactly on the
    # limit, and every run in the pictures was flagged as suspected of
    # touching it - a correct picture of the wrong thing for a guide.
    exp.compliance_var.set("2e-3")
    exp.dataset_var.set("forward")
    yield from _run(exp)
    exp.start_var.set("1.0")
    exp.stop_var.set("-1.0")
    exp.dataset_var.set("reverse")
    yield from _run(exp)
    _tick_all(exp)
    exp.copy_over()
    yield 0.5


def _vdp_hall(app, _saved):
    vdp, hall = app.experiments
    vdp.thickness_entry_var.set("180 um")
    # A shorter sweep than the default 80 points at 100 ms, so the
    # session takes seconds; the pictures look the same either way.
    for exp in (vdp, hall):
        exp.points_var.set("20")
        exp.delay_ms_var.set("20")

    for position in ("A", "B"):
        vdp.pos_var.set(position)
        vdp.on_pos_changed()
        yield from _run(vdp)
    _tick_all(vdp)
    vdp.copy_over()
    yield 0.3
    vdp.calculate_vdp()
    yield 0.5

    app.notebook.select(1)
    yield 0.5
    for position in ("C", "D"):
        for sign in ("+", "-"):
            hall.pos_var.set(position)
            hall.field_sign_var.set(sign)
            hall.on_pos_changed()
            yield from _run(hall)
    _tick_all(hall)
    hall.copy_over()
    yield 0.3
    hall.take_rs_from_vdp()
    yield 0.3
    hall.calculate_hall()
    yield 0.5
    app.notebook.select(0)
    yield 0.5


def _fixed_source(app, _saved):
    exp = app.experiments[0]
    exp.duration_var.set("6")
    exp.interval_var.set("0.2")
    exp.show_source_var.set(True)
    yield from _run(exp)


def _ossila_4pp(app, _saved):
    exp = app.experiments[0]
    yield from _run(exp)
    _tick_all(exp)
    exp.copy_over()
    yield 0.3
    exp.calculate()
    yield 0.5


#: window key -> the session it is taken through before the pictures.
SESSIONS = {
    "iv_sweep": _iv_sweep,
    "vdp_hall": _vdp_hall,
    "fixed_source": _fixed_source,
    "ossila_4pp": _ossila_4pp,
}


def _measurement_session(app, root, key, saved: list[Path]):
    """Connect the demo instrument, take the window's session, and save
    its runs into the temporary folder for the plotter to open."""
    from smuniversal_lab_suite.core.gui.connection_panel import _connect_with
    from smuniversal_lab_suite.core.transports.null_transport import (
        NullTransport,
    )

    # Through the panel's own Demo path, so the row reads as it does for
    # an operator - but not through Connect, which would add "demo" to
    # this PC's remembered addresses.
    for role, widgets in app.conn_widgets.items():
        widgets["transport_var"].set("Demo")
        _connect_with(app, role, NullTransport, "demo", demo=True)
    yield lambda: all(app.is_connected(r) for r in app.conn_widgets)

    app.sample_name_var.set(SAMPLE)
    yield 0.3
    yield from SESSIONS[key](app, saved)

    folder = Path(app.storage_path)
    before = set(folder.rglob("*.csv"))
    for exp in app.experiments:
        if exp.tree.get_children():
            exp.save_runs()
    yield 0.5
    saved += sorted(set(folder.rglob("*.csv")) - before)
    # A public picture must not show whose PC it was taken on, nor the
    # temporary folder standing in for it.
    app.path_display_var.set(SAVE_FOLDER.format(date=time.strftime("%Y-%m-%d")))
    yield 0.5


def _pictures(app, root, key, mode, shared, written):
    """The whole window - once per tab where it has tabs - and each
    panel, with its tab brought to the front first."""
    tooltips = app.tooltips
    tooltips.hide()
    shown = shown_pictures()
    notebook = getattr(app, "notebook", None)
    tabs = notebook.tabs() if notebook is not None else ()

    if not tabs:
        path = build_guide.SCREENS / key / f"window-{mode}.png"
        _grab(root, path, margin=0)
        written.append(path)
    for index, tab in enumerate(tabs):
        notebook.select(index)
        yield 0.6
        slug = build_guide.slug(notebook.tab(tab, "text"))
        path = build_guide.SCREENS / key / f"window-{slug}-{mode}.png"
        _grab(root, path, margin=0)
        written.append(path)

    for panel in build_guide.window_panels(app):
        if not panel.widgets:
            continue
        if panel.tab and notebook is not None:
            for tab in tabs:
                if notebook.tab(tab, "text").strip() == panel.tab:
                    notebook.select(tab)
            yield 0.4
        path = build_guide.SCREENS / key / f"{panel.slug}-{mode}.png"
        if path.resolve() in shown:
            _grab(panel.widgets, path)
            written.append(path)
        if panel.title in shared and not panel.tab:
            path = (build_guide.SCREENS / build_guide.SHARED
                    / f"{panel.slug}-{mode}.png")
            _grab(panel.widgets, path)
            written.append(path)
    if tabs:
        notebook.select(0)


def _session(app, root, key, mode, shared, written, saved, folder):
    from smuniversal_lab_suite.core.gui.theme import theme_for

    theme_for(root).set_mode(mode, save=False)
    # No -topmost: the picture is read from the window itself, so
    # nothing on top of it matters, and it does not cover the screen.
    root.geometry("+40+40")
    root.deiconify()
    yield 1.0

    if key == build_guide.PLOTTER:
        app.open_paths([str(p) for p in saved])
        yield 1.0
        app.tabs.select(1)             # Compare: the runs side by side
        yield 0.5
    else:
        app.storage_path = str(folder)
        app.path_display_var.set(str(folder))
        yield from _measurement_session(app, root, key, saved)
    yield from _pictures(app, root, key, mode, shared, written)


def capture(key: str, folder: Path, saved: list[Path],
            modes=("light", "dark"), shared=frozenset()):
    """Capture window `key` in each look. `shared` names the panels to
    also save under `shared/` - the ones the Every window page shows."""
    written: list[Path] = []
    for mode in modes:
        # Each look is its own session, so each saves its own files; the
        # plotter opens the first session's, in both looks.
        reading = key == build_guide.PLOTTER
        session_saved = saved if reading or mode == modes[0] else []
        root, app = build_guide.build_window(key, visible=True)
        try:
            _drive(root, _session(app, root, key, mode, shared, written,
                                  session_saved, folder / mode))
        finally:
            build_guide.close_window(app)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("windows", nargs="*",
                        help="window keys; default every window")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("capture_screens.py reads windows through the Windows API and runs on Windows only.")
        return 1

    _dpi_aware()
    _silence_dialogs()
    keys = args.windows or (build_guide.measurement_windows()
                            + [build_guide.PLOTTER])
    if build_guide.PLOTTER in keys and "iv_sweep" not in keys:
        keys = ["iv_sweep"] + keys
    # The plotter opens the IV sweep's files, so it goes last.
    keys = sorted(keys, key=lambda k: k == build_guide.PLOTTER)
    shared = frozenset(p.title
                       for p in build_guide.collect()[build_guide.SHARED])

    written = []
    saved: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="smu-guide-") as tmp:
        for key in keys:
            folder = Path(tmp) / key
            for mode in ("light", "dark"):
                (folder / mode).mkdir(parents=True, exist_ok=True)
            # The IV sweep is the window the shared panels are pictured
            # from, and the one whose files the plotter opens.
            written += capture(
                key, folder,
                saved if key in ("iv_sweep", build_guide.PLOTTER) else [],
                shared=shared if key == "iv_sweep" else ())
        for path in written:
            print(path.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
