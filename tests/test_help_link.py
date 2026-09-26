"""The [?] button opens each window's own page in the user guide.

Two ways it could go wrong without anything else noticing: a page is
renamed or moved and the button keeps pointing at the old address - a
404 in the browser, which reads as "the help is broken" - or a window
opens another window's page. Both are checked here, the first against
the Markdown the site is built from, the second by pressing the button.
"""
import tkinter as tk
from pathlib import Path

import pytest

from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.gui import help_link
from smuniversal_lab_suite.core.identity import SampleRegistry
from smuniversal_lab_suite.core.launcher import PLOTTER, WINDOWS
from smuniversal_lab_suite.core.ownership import InstrumentOwnership

pytestmark = [pytest.mark.gui]

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _source_of(page):
    """The Markdown file the site builds `page` from."""
    return DOCS / (page.strip("/") + ".md")


def _experiments():
    for _label, spec in WINDOWS.values():
        if spec == PLOTTER:
            continue
        yield from (spec if isinstance(spec, list) else [spec])


def test_every_window_names_a_page_the_site_has(check):
    for cls in _experiments():
        check(f"{cls.__name__} names a guide page", bool(cls.GUIDE_PAGE))
        check(f"{cls.__name__}: {cls.GUIDE_PAGE} exists",
              _source_of(cls.GUIDE_PAGE).is_file(),
              str(_source_of(cls.GUIDE_PAGE)))
    check("the plotter's page exists",
          _source_of(help_link.PLOTTER_PAGE).is_file(),
          str(_source_of(help_link.PLOTTER_PAGE)))


@pytest.fixture
def opened(monkeypatch):
    """Every address the button hands the browser, instead of a browser."""
    urls = []
    monkeypatch.setattr(help_link.webbrowser, "open",
                        lambda url, new=0: urls.append(url) or True)
    return urls


@pytest.mark.parametrize("key", [k for k, (_l, spec) in WINDOWS.items()
                                 if spec != PLOTTER])
def test_the_button_opens_the_page_of_the_tab_in_front(key, opened, check):
    root = tk.Tk()
    root.withdraw()
    app = LabApp(root, WINDOWS[key][1], ownership=InstrumentOwnership(),
                 samples=SampleRegistry())
    try:
        tabs = app.notebook.tabs() if app.notebook is not None else [None]
        for index, _tab in enumerate(tabs):
            if app.notebook is not None:
                app.notebook.select(index)
                root.update()
            app.header_help_btn.invoke()
            want = help_link.guide_url(app.experiment.GUIDE_PAGE)
            check(f"{key}, tab {index}: opens its page",
                  opened[-1:] == [want], f"{opened[-1:]} vs {want}")
    finally:
        app.on_close()


def test_the_plotter_opens_its_page(opened, check):
    from smuniversal_lab_suite.plotter.window import PlotterWindow

    root = tk.Tk()
    root.withdraw()
    try:
        window = PlotterWindow(root)
        buttons = [w for w in window.mode_btn.master.winfo_children()
                   if str(w.cget("text")) == "?"]
        check("the toolbar has a [?] button", len(buttons) == 1)
        if buttons:
            buttons[0].invoke()
            check("it opens the plotter's page",
                  opened == [help_link.guide_url(help_link.PLOTTER_PAGE)],
                  str(opened))
    finally:
        root.destroy()


def test_no_browser_is_not_an_error():
    """A PC with no browser configured gets the address in the console,
    not a traceback."""
    lines = []
    original = help_link.webbrowser.open
    help_link.webbrowser.open = lambda url, new=0: False
    try:
        url = help_link.open_guide("guide/", log=lines.append)
    finally:
        help_link.webbrowser.open = original
    assert url == help_link.SITE_URL + "guide/"
    assert lines and url in lines[0]
