#!/usr/bin/env python
"""Write the user guide's control tables from the windows themselves.

Why this exists
---------------
Every control in every window already says what it does, in its
tooltip, and `tests/test_tooltip_coverage.py` keeps that true. A user
guide that described the controls in its own words would be a second
copy of those sentences - and this repository has paid for two copies of
one thing more than once. So the guide's "what each control does"
tables are not written. They are read out of the windows: each window is
built, hidden, the way the tooltip test builds it, and walked panel by
panel.

What it writes
--------------
Only the spans between markers in the hand-written guide pages:

    <!-- generated:controls iv_sweep -->
    ...
    <!-- /generated:controls -->

A page describes one window in its own words - what it measures, how to
wire the sample, a run step by step - and the tables sit inside it. A
panel that looks the same in every measurement window (the header, the
Instruments panel, Run and Stop) is described once, under the key
`shared`, rather than on every page.

Usage
-----
    uv run python tools/build_guide.py            # rewrite the tables
    uv run python tools/build_guide.py --check    # fail if any is stale

`tests/test_guide.py` runs the check. It needs a display, like every
other test that builds a window.

Screenshots
-----------
Each panel's table sits under that panel's picture, in both looks. The
pictures are taken by `tools/capture_screens.py`, which finds the panels
through `window_panels()` here, so a picture and its table cannot be of
two different panels.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DOCS = ROOT / "docs"
SCREENS = DOCS / "assets" / "screens"

#: The key the panels common to every measurement window are filed under.
SHARED = "shared"

BEGIN = re.compile(r"<!-- generated:controls (\S+) -->\n")
END = "<!-- /generated:controls -->"

#: Widgets that are only ever the words beside a control. They are read
#: for a row's name and never become a row of their own.
LABELS = {"TLabel"}

#: The row name for a control with no words on it, no label beside it,
#: and no `name=` where its tooltip is attached. Deliberately not a
#: word a reader could take for a name: `tests/test_guide.py` fails on
#: it, and the fix is a `name=` at the `tip()` call.
UNNAMED = "(unnamed {cls})"


@dataclass
class Panel:
    """One panel of a window: its title, its own help, and its controls."""
    title: str
    help: str
    #: (row name, what it does), in the order they sit in the window.
    rows: list[tuple[str, str]] = field(default_factory=list)
    #: The tab it sits on, in a window with more than one; else "".
    tab: str = ""
    #: The frames it is drawn in - a screenshot crops to their union.
    #: One for a titled panel; the header strip is two.
    widgets: list = field(default_factory=list)

    @property
    def slug(self) -> str:
        words = f"{self.tab} {self.title}" if self.tab else self.title
        return re.sub(r"[^a-z0-9]+", "-", words.lower()).strip("-")

    def same_as(self, other: Panel) -> bool:
        return (self.title, self.help, self.rows) == (other.title,
                                                      other.help, other.rows)


#: The classes whose `text` option is words on screen. On an entry or a
#: combobox, `cget("text")` is Tk abbreviating `textvariable`, and
#: answers with the variable's internal name.
WORDED = {"TLabel", "TButton", "TCheckbutton", "TRadiobutton",
          "TLabelframe", "Label", "Button", "Checkbutton"}


def _text(widget) -> str:
    if widget.winfo_class() not in WORDED:
        return ""
    try:
        return str(widget.cget("text")).strip()
    except Exception:
        return ""


def _label_beside(widget) -> str:
    """The words to the left of a field that carries no label tooltip.

    Grid rows are read by row and column; a packed row by the sibling
    packed just before it.
    """
    master = widget.master
    try:
        info = widget.grid_info()
    except Exception:
        info = {}
    if info:
        row, column = int(info["row"]), int(info["column"])
        beside = [w for w in master.grid_slaves(row=row)
                  if int(w.grid_info()["column"]) < column
                  and w.winfo_class() in LABELS]
        if beside:
            best = max(beside, key=lambda w: int(w.grid_info()["column"]))
            return _text(best).rstrip(":").strip()
        return ""
    siblings = master.pack_slaves()
    if widget in siblings:
        index = siblings.index(widget)
        if index and siblings[index - 1].winfo_class() in LABELS:
            return _text(siblings[index - 1]).rstrip(":").strip()
    return ""


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _tab_of(app, widget) -> str:
    notebook = getattr(app, "notebook", None)
    if notebook is None:
        return ""
    path = str(widget)
    for tab_id in notebook.tabs():
        if path.startswith(tab_id + "."):
            return str(notebook.tab(tab_id, "text")).strip()
    return ""


def window_panels(app) -> list[Panel]:
    """The panels of a built window, in the order they appear.

    A panel is a titled frame. Controls outside every titled frame are
    grouped by where they sit: the strip across the top, and the Run
    and Stop row. Rows are the controls that carry a tooltip; a field's
    label and the field share one sentence, so they make one row, named
    by the label.
    """
    tips = app.tooltips
    #: frame path -> the group its unframed controls are filed under.
    groups = {}
    for exp in app.experiments:
        button = getattr(exp, "run_btn", None)
        if button is not None:
            groups[str(button.master.master)] = "Run controls"
    if getattr(app, "session_strip", None) is not None:
        groups[str(app.session_strip)] = "Sample and saving"
    # The emblem and look switch sit top left, the stage, console and
    # tooltip switches top right: one strip to the reader, two frames.
    for name in ("header_emblem", "console_btn", "temp_btn"):
        widget = getattr(app, name, None)
        if widget is not None:
            groups[str(widget.master)] = "Header strip"

    panels: dict[str, Panel] = {}
    order: list[str] = []

    def panel_for(widget) -> Panel:
        frame = widget
        while frame is not None and frame.winfo_class() != "TLabelframe":
            frame = frame.master
        if frame is not None:
            key = str(frame)
            title = _text(frame) or "Plot"
            help_text = tips.text_for(frame) or ""
            bounds = frame
        else:
            frame_path = next((g for g in groups
                               if str(widget).startswith(g + ".")), ".")
            title = groups.get(frame_path, "Window")
            # Keyed by title: the header strip is two frames on screen
            # and one strip to the reader.
            key = f"{_tab_of(app, widget)}/{title}"
            help_text = ""
            bounds = widget.nametowidget(frame_path)
        if key not in panels:
            panels[key] = Panel(title, help_text, tab=_tab_of(app, widget))
            order.append(key)
        if bounds not in panels[key].widgets:
            panels[key].widgets.append(bounds)
        return panels[key]

    for widget in _descendants(app.root):
        words = tips.text_for(widget)
        cls = widget.winfo_class()
        if not words or cls == "TLabelframe":
            continue
        panel = panel_for(widget)
        name = tips.name_for(widget) or _text(widget).rstrip(":").strip()
        if cls not in LABELS and panel.rows and panel.rows[-1][1] == words:
            continue          # the field beside the label just listed
        if not name:
            name = _label_beside(widget) or UNNAMED.format(cls=cls)
        panel.rows.append((name, words))

    return [panels[key] for key in order if panels[key].rows]


def build_window(key: str):
    """Build window `key` hidden, as the tooltip test does. Returns
    (root, app); the caller closes it with `app.on_close()`."""
    import tkinter as tk

    from smuniversal_lab_suite.core.base_app import LabApp
    from smuniversal_lab_suite.core.identity import SampleRegistry
    from smuniversal_lab_suite.core.launcher import WINDOWS
    from smuniversal_lab_suite.core.ownership import InstrumentOwnership

    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, WINDOWS[key][1], ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    root.update_idletasks()
    return root, app


def measurement_windows() -> list[str]:
    from smuniversal_lab_suite.core.launcher import PLOTTER, WINDOWS
    return [key for key, (_label, spec) in WINDOWS.items()
            if spec != PLOTTER]


def collect() -> dict[str, list[Panel]]:
    """Every measurement window's panels, with the common controls filed
    once under `SHARED`.

    Shared by the control, not by the panel, and only in the panels
    every window has. Most windows' header
    strips differ by one button - the 4PP has no stage - so sharing
    whole panels would describe the header five times over. A control
    that reads the same, in a panel of the same name, in two or more
    windows is described once on the shared page; each window's page
    keeps the controls that are its own.
    """
    by_window = {}
    for key in measurement_windows():
        _root, app = build_window(key)
        try:
            by_window[key] = window_panels(app)
        finally:
            app.on_close()

    # Only the window's furniture is shared: the panels every window
    # has. A control inside an experiment's own panel stays on that
    # window's page even where another window has one like it - a
    # reader looking at the IV sweep's Sweep setup should find all of
    # it there.
    titles = [{p.title for p in panels} for panels in by_window.values()]
    furniture = set.intersection(*titles)
    seen: dict[tuple[str, str, str], set[str]] = {}
    for key, panels in by_window.items():
        for panel in panels:
            for name, words in panel.rows:
                seen.setdefault((panel.title, name, words), set()).add(key)
    common = {row for row, keys in seen.items()
              if len(keys) > 1 and row[0] in furniture}

    shared: dict[str, Panel] = {}
    out: dict[str, list[Panel]] = {}
    for key, panels in by_window.items():
        own = []
        for panel in panels:
            mine = []
            for name, words in panel.rows:
                if (panel.title, name, words) not in common:
                    mine.append((name, words))
                    continue
                into = shared.setdefault(
                    panel.title, Panel(panel.title, panel.help))
                if (name, words) not in into.rows:
                    into.rows.append((name, words))
            own.append(Panel(panel.title, panel.help, mine, panel.tab,
                             panel.widgets))
        out[key] = own
    out[SHARED] = list(shared.values())
    return out


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def screenshot(page: Path, name: str, alt: str) -> str:
    """Markdown for one picture in both looks; the site shows the one
    matching the reader's light or dark setting."""
    out = []
    for mode in ("light", "dark"):
        image = SCREENS / f"{name}-{mode}.png"
        rel = Path(_relpath(image, page.parent)).as_posix()
        out.append(f"![{alt}]({rel}#only-{mode})")
    return "\n".join(out)


def _relpath(path: Path, start: Path) -> str:
    import os
    return os.path.relpath(path, start)


def render(key: str, panels: list[Panel], page: Path,
           shared_titles: tuple[str, ...] = ()) -> str:
    """The Markdown for one window's panels, or for the shared ones.

    A window page puts its panels under a "## The panels" heading of its
    own, so they are one level down; the shared page's are its sections.
    """
    level = 2 if key == SHARED else 3
    every = Path(_relpath(DOCS / "guide" / "windows" / "every-window.md",
                          page.parent)).as_posix()
    lines: list[str] = []
    if key != SHARED and shared_titles:
        names = ", ".join(shared_titles[:-1]) + " and " + shared_titles[-1]
        lines += [f"The controls every window has - in the {names} panels - are "
                  f"described once, on [Every window]({every}). What follows "
                  "is this window's own.", ""]
    tab = None
    for panel in panels:
        if key != SHARED and not panel.rows:
            continue
        depth = level
        if panel.tab:
            if panel.tab != tab:
                tab = panel.tab
                lines += [f"{'#' * level} The {tab} tab", ""]
            depth = level + 1
        lines += [f"{'#' * depth} {panel.title}", ""]
        lines += [screenshot(page, f"{key}/{panel.slug}",
                             f"The {panel.title} panel"), ""]
        if panel.help:
            lines += [" ".join(panel.help.split()), ""]
        if key != SHARED and panel.title in shared_titles:
            anchor = re.sub(r"[^a-z0-9]+", "-", panel.title.lower()).strip("-")
            lines += [f"Besides the controls below, it has the ones every "
                      f"window has - see [{panel.title}]({every}#{anchor}).",
                      ""]
        lines += ["| Control | What it does |", "|---|---|"]
        lines += [f"| **{_cell(name)}** | {_cell(words)} |"
                  for name, words in panel.rows]
        lines.append("")
    return "\n".join(lines)


def pages() -> dict[Path, list[str]]:
    """Guide pages holding a controls block, and the keys they hold."""
    found: dict[Path, list[str]] = {}
    for page in sorted((DOCS / "guide").rglob("*.md")):
        keys = BEGIN.findall(page.read_text(encoding="utf-8"))
        if keys:
            found[page] = keys
    return found


def rebuild(text: str, key: str, body: str) -> str:
    start = text.find(f"<!-- generated:controls {key} -->\n")
    end = text.find(END, start)
    if start == -1 or end == -1:
        raise ValueError(f"controls block {key!r} is not closed with {END}")
    head = text[:start] + f"<!-- generated:controls {key} -->\n"
    return head + body + text[end:]


def build(check: bool = False) -> list[str]:
    """Write (or verify) every controls block. Returns what was stale."""
    wanted = pages()
    if not wanted:
        return []
    panels = collect()
    stale = []
    for page, keys in wanted.items():
        text = page.read_text(encoding="utf-8")
        new = text
        for key in keys:
            if key not in panels:
                raise ValueError(f"{page.name}: no window called {key!r}")
            titles = tuple(p.title for p in panels[SHARED])
            new = rebuild(new, key, render(key, panels[key], page, titles))
        if page.read_bytes() != new.encode("utf-8"):
            stale.append(page.relative_to(ROOT).as_posix())
            if not check:
                page.write_text(new, encoding="utf-8", newline="\n")
    return stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if any controls table is stale")
    args = parser.parse_args()
    stale = build(check=args.check)
    if args.check and stale:
        print("The user guide's control tables are out of date:")
        for name in stale:
            print(f"  {name}")
        print("\nRun: uv run python tools/build_guide.py")
        return 1
    print("Rewrote:\n  " + "\n  ".join(stale) if stale else "Nothing to do.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
