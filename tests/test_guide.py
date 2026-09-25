"""The user guide's control tables match the windows they describe.

The tables are the windows' own tooltips, read out by
`tools/build_guide.py`. A tooltip reworded, a control added, or a panel
renamed without rebuilding the guide fails here - the same mechanism as
the generated pages in `tests/test_docs.py`, for the part of the guide
that needs a window built to know.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build_guide  # noqa: E402

pytestmark = [pytest.mark.gui]


def test_the_control_tables_match_the_windows(check):
    stale = build_guide.build(check=True)
    check("the user guide's control tables are current", not stale,
          "run `uv run python tools/build_guide.py`: " + ", ".join(stale))


def test_every_unlabelled_control_is_named(check):
    """A control with no words on it needs `name=` where its tooltip is
    attached, or its row in the guide falls back to a generic word."""
    marker = build_guide.UNNAMED.split("{")[0]
    unnamed = []
    for key, panels in build_guide.collect().items():
        for panel in panels:
            unnamed += [f"{key} / {panel.title}: {name}"
                        for name, _words in panel.rows
                        if name.startswith(marker)]
    check("every control in the guide has a name of its own", not unnamed,
          "\n  " + "\n  ".join(unnamed))


def test_every_window_has_a_guide_page(check):
    """A window added to the launcher without a page in the guide is a
    window its users have to learn by trial - or from the tooltips
    alone, which say what each control does and not how to use them
    together."""
    documented = {key for keys in build_guide.pages().values()
                  for key in keys}
    wanted = set(build_guide.measurement_windows()) | {
        build_guide.PLOTTER, build_guide.SHARED}
    missing = sorted(wanted - documented)
    check("every window has a page in docs/guide/windows/", not missing,
          "no controls block for: " + ", ".join(missing))


def test_a_window_page_names_real_windows(check):
    """A controls block for a window that does not exist would be caught
    by the build raising; this says which page when it happens."""
    windows = set(build_guide.measurement_windows()) | {
        build_guide.SHARED, build_guide.PLOTTER}
    wrong = [f"{page.name}: {key}"
             for page, keys in build_guide.pages().items()
             for key in keys if key not in windows]
    check("every controls block names a window", not wrong,
          "\n  " + "\n  ".join(wrong))
