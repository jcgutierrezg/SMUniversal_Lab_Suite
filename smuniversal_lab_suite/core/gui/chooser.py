"""
The first window of a session: one card per window the suite can open.

Each card carries the same emblem and colour its window wears in its own
header strip, the window's name, and a sentence on what it is for. The
point is recognition. An operator who has used the suite for a week
picks the green square with four dots without reading; one who has not
reads the sentence and knows which window measures what they came to
measure.

A whole card is the button: click anywhere on it, or Tab to it and press
Enter or Space. Its border takes the window's colour on hover and on
focus, so the keyboard path is as visible as the mouse one.

Cards for the measurement windows are greyed, and do nothing, when
another copy of the suite holds the instrument lock. The plotter's card
stays live, because reading saved files is safe beside a running
measurement - see `core/launcher.py`.
"""
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui.header import draw_emblem
from smuniversal_lab_suite.core.gui.theme import theme_for

#: The emblem on a card is larger than the one in a header strip: here it
#: is how the window is recognised, there it is a reminder.
CARD_EMBLEM = 48
#: A pair of experiments sharing a window shows both emblems, smaller,
#: in the same column - so the text beside them lines up with every
#: other card's.
PAIR_EMBLEM = 36
#: Between the emblem column and the text, in pixels.
EMBLEM_GAP = 14
#: Pixels. Wide enough for two lines of description at the body size.
DESCRIPTION_WRAP = 300


def build_cards(parent, entries, on_choose):
    """Lay out `entries` as a grid of cards, two to a row.

    `entries` is a list of dicts: `title`, `description`, `keys` (the
    emblem and colour keys, one per experiment in the window), `value`
    (what `on_choose` is called with) and `enabled`.

    Returns (the grid frame, the list of card frames in order).
    """
    grid = ttk.Frame(parent)
    for column in (0, 1):
        grid.grid_columnconfigure(column, weight=1, uniform="card")
    cards = []
    for index, entry in enumerate(entries):
        row, column = divmod(index, 2)
        # A lone card on the last row spans both columns, so the grid
        # never ends in a half-empty row - and uses the width for its
        # description rather than wrapping it into a narrow column.
        span = 2 if (index == len(entries) - 1 and column == 0) else 1
        card = _card(grid, entry, on_choose, wide=span == 2)
        card.grid(row=row, column=column, columnspan=span, sticky="nsew",
                  padx=6, pady=6)
        grid.grid_rowconfigure(row, uniform="row")
        cards.append(card)
    return grid, cards


def _card(parent, entry, on_choose, wide=False):
    """One card: accent bar, emblem, name, and what it is for."""
    theme = theme_for(parent)
    enabled = entry.get("enabled", True)
    keys = entry["keys"]

    # The border is a plain Tk frame's highlight, because that is the
    # one border Tk will recolour per widget on hover and on focus
    # without a style per card.
    outer = tk.Frame(parent, highlightthickness=2, borderwidth=0,
                     takefocus=1 if enabled else 0)
    body = ttk.Frame(outer, style="Card.TFrame", padding=(14, 12, 14, 14))
    body.pack(fill="both", expand=True)

    # The accent bar across the top: one segment per experiment, so the
    # Van der Pauw + Hall card wears both colours.
    bar = tk.Frame(body, height=4, borderwidth=0)
    bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
    segments = []
    for key in keys:
        segment = tk.Frame(bar, height=4, borderwidth=0)
        segment.pack(side="left", fill="x", expand=True)
        segments.append((segment, key))

    emblems = ttk.Frame(body, style="Card.TFrame", width=CARD_EMBLEM)
    emblems.grid(row=1, column=0, rowspan=2, sticky="n",
                 padx=(0, EMBLEM_GAP))
    size = CARD_EMBLEM if len(keys) == 1 else PAIR_EMBLEM
    canvases = []
    for key in keys:
        canvas = tk.Canvas(emblems, width=size, height=size,
                           highlightthickness=0, borderwidth=0)
        canvas.pack(pady=(0, 4))
        canvases.append((canvas, key))

    title = ttk.Label(body, text=entry["title"],
                      style="Title.Card.TLabel" if enabled
                      else "Off.Title.Card.TLabel")
    title.grid(row=1, column=1, sticky="w")
    description = ttk.Label(body, text=entry["description"],
                            style="Hint.Card.TLabel", justify="left",
                            wraplength=DESCRIPTION_WRAP * (2 if wide
                                                           else 1))
    description.grid(row=2, column=1, sticky="nw", pady=(4, 0))
    body.grid_columnconfigure(1, weight=1)
    # A fixed emblem column, so the text starts at the same place on
    # every card - a pair's two smaller emblems would otherwise pull it
    # left of its neighbours.
    # (A column's minimum size includes its cell's padding.)
    body.grid_columnconfigure(0, minsize=CARD_EMBLEM + EMBLEM_GAP)

    state = {"hover": False}

    def paint(current):
        palette = current.palette
        accent = current.accent_of(keys[0])
        outer.configure(background=palette.header,
                        highlightcolor=accent,
                        highlightbackground=(accent if state["hover"]
                                             and enabled else palette.rule))
        for segment, key in segments:
            segment.configure(background=(current.accent_of(key) if enabled
                                          else palette.rule))
        for canvas, key in canvases:
            canvas.configure(background=palette.header)
            if enabled:
                draw_emblem(canvas, key, current)
            else:
                _draw_muted(canvas, key, current)

    theme.on_change(paint, widget=outer)
    if not enabled:
        return outer

    def choose(_event=None):
        on_choose(entry["value"])

    def hover(on):
        state["hover"] = on
        paint(theme_for(outer))

    everything = [outer, body, bar, emblems, title, description]
    everything += [segment for segment, _key in segments]
    everything += [canvas for canvas, _key in canvases]
    for widget in everything:
        widget.bind("<Button-1>", choose)
        widget.configure(cursor="hand2")
    def leave(event):
        # Tk sends <Leave> to a frame when the pointer moves onto one of
        # its own children, so without this the border would flicker
        # off every time the pointer crossed from the card's edge onto
        # its text. Only a pointer that has left the card entirely counts.
        under = outer.winfo_containing(event.x_root, event.y_root)
        if under is not None and str(under).startswith(str(outer)):
            return
        hover(False)

    outer.bind("<Enter>", lambda _e: hover(True))
    outer.bind("<Leave>", leave)
    outer.bind("<Return>", choose)
    outer.bind("<space>", choose)
    return outer


def _draw_muted(canvas, key, theme):
    """An emblem for a window that cannot be opened right now: the same
    drawing, in the muted ink rather than the experiment's colour."""
    draw_emblem(canvas, key, theme)
    for item in canvas.find_all():
        for option in ("fill", "outline"):
            try:
                if canvas.itemcget(item, option):
                    canvas.itemconfigure(item,
                                         **{option: theme.palette.muted})
            except tk.TclError:
                pass          # a line has no outline; a text has no fill
