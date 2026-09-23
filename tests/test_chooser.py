"""The chooser's cards: every window has one, and a card is a button.

A card that looks clickable and is not - or a greyed card that still
opens a measurement window while another copy holds the instruments -
would be worse than the plain list of buttons it replaced. So this
drives the cards the way an operator does: a click, the keyboard, and
the locked state.
"""
import tkinter as tk

import pytest

from smuniversal_lab_suite.core import launcher
from smuniversal_lab_suite.core.gui.chooser import build_cards

pytestmark = [pytest.mark.gui]


@pytest.fixture
def root():
    window = tk.Tk()
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass


def _entries(enabled=True):
    return [{"title": launcher.window_title(key, spec),
             "description": launcher.DESCRIPTIONS[key],
             "keys": launcher.window_keys(spec), "value": key,
             "enabled": enabled}
            for key, (_label, spec) in launcher.WINDOWS.items()]


def test_every_window_says_what_it_is_for(check):
    for key, (_label, spec) in launcher.WINDOWS.items():
        check(f"{key} has a description",
              bool(launcher.DESCRIPTIONS.get(key, "").strip()))
        check(f"{key} has a title",
              bool(launcher.window_title(key, spec).strip()))
    check("no description is left over from a window that is gone",
          set(launcher.DESCRIPTIONS) == set(launcher.WINDOWS),
          sorted(set(launcher.DESCRIPTIONS) ^ set(launcher.WINDOWS)))


def test_a_window_wears_its_experiments_colours(check):
    check("a pair wears both", launcher.window_keys(
        launcher.WINDOWS["vdp_hall"][1]) == ["vanderpauw", "hall"])
    check("the plotter is neutral", launcher.window_keys(
        launcher.PLOTTER) == ["neutral"])


def test_a_card_is_a_button(root, check):
    chosen = []
    grid, cards = build_cards(root, _entries(), chosen.append)
    grid.pack()
    root.update()

    check("one card per window", len(cards) == len(launcher.WINDOWS))
    cards[1].event_generate("<Button-1>")
    check("a click on the card chooses its window",
          chosen == [list(launcher.WINDOWS)[1]], chosen)

    # The text is most of a card; clicking it must count too.
    children = [w for w in cards[2].winfo_children()[0].winfo_children()
                if w.winfo_class() == "TLabel"]
    children[0].event_generate("<Button-1>")
    check("so does a click on its title",
          chosen[-1] == list(launcher.WINDOWS)[2], chosen)

    # Tk delivers a key only to the widget holding the focus, and only a
    # mapped window can hold it - so this part needs the window shown.
    root.deiconify()
    root.update()
    cards[0].focus_force()
    root.update()
    check("Enter and Space are bound on the card itself",
          {"<Key-Return>", "<Key-space>"} <= set(cards[0].bind()),
          cards[0].bind())
    # A CI desktop may refuse a process the focus. Where it does, the
    # bindings above are what can be checked; where it does not, the
    # keypress is driven for real.
    if root.focus_get() is cards[0]:
        cards[0].event_generate("<Return>")
        root.update()
        check("Enter on a focused card chooses it",
              chosen[-1] == list(launcher.WINDOWS)[0], chosen)


def test_a_greyed_card_does_nothing(root, check):
    chosen = []
    grid, cards = build_cards(root, _entries(enabled=False), chosen.append)
    grid.pack()
    root.update()
    for card in cards:
        card.event_generate("<Button-1>")
        card.event_generate("<Return>")
    check("no greyed card opens anything", chosen == [], chosen)
    check("and none takes the keyboard focus",
          all(str(card.cget("takefocus")) == "0" for card in cards))
