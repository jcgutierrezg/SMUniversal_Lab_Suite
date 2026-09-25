"""The [?] button: a window's own page in the user guide, in the browser.

Every window has a page on the documentation site that says what it
measures, how to wire the sample, how to run it and what each control
does. The button opens that page rather than the site's front door, so
the answer is one click away rather than one click and a search.

Which page belongs to which window is declared where the window is: an
experiment's `GUIDE_PAGE`, and `PLOTTER_PAGE` here for the plotter.
`tests/test_help_link.py` fails if one names a page the site does not
have, so a renamed page cannot leave a button pointing at nothing.
"""
import webbrowser
from tkinter import ttk

from smuniversal_lab_suite.core.gui.tooltips import tip

#: The published user guide. The one place the address is written in the
#: application; the README and the docs carry it separately, as text.
SITE_URL = "https://jcgutierrezg.github.io/SMUniversal_Lab_Suite/"

#: The plotter's page, relative to `SITE_URL`.
PLOTTER_PAGE = "guide/windows/plotter/"

HELP_TEXT = ("Open this window's page in the user guide, in your web "
             "browser: what it measures, how to run it, and what every "
             "control does. The guide is on the internet, so it needs a "
             "connection.")


def guide_url(page=""):
    """The address of `page` - a path like 'guide/windows/iv-sweep/' -
    on the documentation site. An empty page is the site's front page."""
    return SITE_URL + page.lstrip("/")


def open_guide(page="", log=None):
    """Open `page` of the user guide in the default browser.

    Never raises: a PC with no browser configured gets a line in the
    console naming the address, which can still be typed by hand.
    """
    url = guide_url(page)
    try:
        opened = webbrowser.open(url, new=2)
    except Exception:
        opened = False
    if log is not None:
        log(f"User guide: {url}" if opened else
            f"Could not open a browser. The user guide is at {url}")
    return url


def help_button(parent, page_of, owner=None, log=None, manager=None):
    """A small [?] button that opens the guide page `page_of()` names.

    `page_of` is called at the press rather than once, so a window with
    tabs can open the page for the tab in front. The tooltip goes through
    `owner` (an experiment) or `manager` (a `Tooltips`), whichever the
    window has.
    """
    button = ttk.Button(parent, text="?", width=3,
                        command=lambda: open_guide(page_of(), log=log))
    if manager is not None:
        manager.attach(button, HELP_TEXT, name="Help")
    elif owner is not None:
        tip(owner, button, HELP_TEXT, name="Help")
    return button
