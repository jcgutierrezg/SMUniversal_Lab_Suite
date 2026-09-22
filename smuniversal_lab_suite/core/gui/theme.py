"""
The window's look: two modes, one accent per experiment, one place.

Dark is the default and looks like the bench instruments. Light looks like
the lab notebook, with the same paper, ink and grid colours as the CSV
plotter (`plotter/style.py`). The operator switches between them with the
button in the header strip, and the switch happens in place: nothing is
rebuilt, no run is interrupted, and the choice is remembered for the next
launch.

How a switch reaches every widget
---------------------------------
Three kinds of widget, three routes:

* **ttk widgets** take their colours from named styles. Reconfiguring a
  style repaints every widget using it, so most of the window follows
  for free. Panels therefore never pass a literal `foreground=` - they
  pick a semantic style (`Hint.TLabel`, `Warn.TLabel`, `Stale.TLabel`,
  ...) and the palette decides what that looks like.
* **Plain Tk widgets** - canvases, the console's Text, the matplotlib
  toolbar - have no styles. Whoever builds one registers a callback
  with `Theme.on_change()`, which runs it once immediately and again on
  every switch.
* **Plots** are redrawn: an experiment's figure registers its
  `refresh_plot`, and `style_axes()` colours the axes from the palette
  on every redraw, so a redraw after a switch is a redraw in the new
  colours.

What never changes with the mode
--------------------------------
The safety cues. Stop is red, the output lamp is green when live, a
connection is green when made and red when not, in either mode and for
every experiment. An operator who learnt "green lamp means live" on one
window must not have to relearn it on another.

Each experiment's accent is its identity, not a status: it colours the
header strip, panel titles, focus rings, Run, the progress bar and
ticked boxes. Plot lines keep the plotter's palette, so an accent never
stands for a run.
"""
from __future__ import annotations

import json
import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

DARK = "dark"
LIGHT = "light"
MODES = (DARK, LIGHT)
DEFAULT_MODE = DARK

#: File, inside the per-machine state directory, that remembers the mode.
PREFS_FILENAME = "ui.json"


@dataclass(frozen=True)
class Palette:
    """Every colour one mode uses. Hex strings throughout."""
    mode: str
    bg: str             # window and panel ground
    header: str         # the header strip
    field: str          # entries, tables, the console
    field_border: str
    button: str
    button_border: str
    ink: str            # body text
    ink2: str           # labels beside fields, table headings
    muted: str          # hints, idle progress, stale results
    rule: str           # panel borders, separators
    track: str          # progress trough, scrollbar trough
    good: str           # connected
    warn: str           # caution notes, demo mode
    bad: str            # not connected, errors
    stop: str           # the Stop button while it can be pressed
    tooltip: str
    tooltip_ink: str
    n_type: str         # carrier type: these two carry meaning, so they
    p_type: str         # keep their own hues rather than the accent
    hot: str            # the stage heating, and the stage cooling. Also
    cold: str           # meaning, also not the accent's to carry.
    on_accent: str      # text on an accent-filled button
    # figures
    plot_bg: str
    plot_grid: str
    plot_axis: str
    plot_ink: str
    series: tuple
    # the corner diagram
    role_current: str
    role_voltage: str
    role_unused: str
    diagram_body: str
    diagram_edge: str


LIGHT_PALETTE = Palette(
    mode=LIGHT,
    bg="#f5f4ef", header="#fcfcfb", field="#ffffff", field_border="#c3c2b7",
    button="#fbfaf7", button_border="#c3c2b7",
    ink="#0b0b0b", ink2="#52514e", muted="#6e6c66", rule="#d6d5cc",
    track="#e1e0d9",
    good="#1d7a43", warn="#9a4c00", bad="#c0302a", stop="#c2362f",
    tooltip="#fffbe6", tooltip_ink="#0b0b0b",
    n_type="#12549e", p_type="#b3241f",
    hot="#b3241f", cold="#12549e", on_accent="#ffffff",
    plot_bg="#fcfcfb", plot_grid="#e1e0d9", plot_axis="#c3c2b7",
    plot_ink="#52514e",
    # The plotter's validated categorical palette, in its fixed order.
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100",
            "#e87ba4", "#008300", "#4a3aa7", "#e34948"),
    role_current="#f6b07e", role_voltage="#8fdcb9", role_unused="#dcdbd3",
    diagram_body="#fcfcfb", diagram_edge="#0b0b0b",
)

DARK_PALETTE = Palette(
    mode=DARK,
    bg="#1a1d21", header="#0e1013", field="#0e1012", field_border="#3a3f47",
    button="#262a30", button_border="#3a3f47",
    ink="#e7e5de", ink2="#b3b1a9", muted="#8f8d86", rule="#30343a",
    track="#0b0c0e",
    good="#4cc27a", warn="#f0a44a", bad="#ff7a70", stop="#d0443c",
    tooltip="#2a2e35", tooltip_ink="#e7e5de",
    n_type="#7fb6ff", p_type="#ff8078",
    hot="#ff8078", cold="#7fb6ff", on_accent="#0b0c0e",
    plot_bg="#0e1012", plot_grid="#262a30", plot_axis="#3a3f47",
    plot_ink="#b3b1a9",
    # The same hues lifted for a dark ground, in the same order, so a
    # run keeps its colour when the mode changes.
    series=("#5ea6f7", "#ff8c59", "#38d19b", "#f3bb44",
            "#f08bb4", "#5cc85c", "#a595ff", "#ff6b6a"),
    role_current="#c46a2e", role_voltage="#2e9e70", role_unused="#3a3f47",
    diagram_body="#15181c", diagram_edge="#b3b1a9",
)

PALETTES = {LIGHT: LIGHT_PALETTE, DARK: DARK_PALETTE}

#: Each experiment's signature colour, per mode: deeper ink on paper,
#: brighter on the dark panel. Keyed by `Experiment.THEME_KEY`.
ACCENTS = {
    "iv_sweep":     {LIGHT: "#1f5fae", DARK: "#5ea6f7"},
    "vanderpauw":   {LIGHT: "#0d7f5c", DARK: "#38d19b"},
    "hall":         {LIGHT: "#4a3aa7", DARK: "#a595ff"},
    "ossila_4pp":   {LIGHT: "#b4481a", DARK: "#ff8c59"},
    "fixed_source": {LIGHT: "#946300", DARK: "#f3bb44"},
    # Windows that are not an experiment: the launcher and the plotter.
    "neutral":      {LIGHT: "#1f5fae", DARK: "#5ea6f7"},
}
DEFAULT_ACCENT = "neutral"

#: Label styles a calculated result can wear, each of which gets a
#: `Stale.`-prefixed twin for when the inputs have moved on. Greying a
#: result must not also un-bold it, which is why this is a list of the
#: real styles rather than one flat "stale" colour.
STALE_BASES = ("TLabel", "Bold.TLabel", "Hint.TLabel", "Readout.TLabel",
               "NType.Bold.TLabel", "PType.Bold.TLabel")


def stale(style_name, is_stale=True):
    """The greyed twin of `style_name`, or `style_name` itself."""
    return f"Stale.{style_name}" if is_stale else style_name


# --- fonts ---------------------------------------------------------------
#
# Only faces that ship with Windows 11, each with fallbacks, because CI
# also runs on Linux where none of them exist. The first installed family
# in each list wins.

_FAMILIES = {
    "body": {LIGHT: ("Segoe UI", "DejaVu Sans", "Helvetica"),
             DARK: ("Bahnschrift", "Segoe UI", "DejaVu Sans", "Helvetica")},
    "heading": {LIGHT: ("Cambria", "Georgia", "DejaVu Serif", "Times"),
                DARK: ("Bahnschrift SemiBold", "Bahnschrift", "Segoe UI",
                       "DejaVu Sans", "Helvetica")},
    "number": {LIGHT: ("Cascadia Mono", "Consolas", "DejaVu Sans Mono",
                       "Courier"),
               DARK: ("Bahnschrift", "Segoe UI", "DejaVu Sans",
                      "Helvetica")},
    "mono": {LIGHT: ("Cascadia Mono", "Consolas", "DejaVu Sans Mono",
                     "Courier"),
             DARK: ("Cascadia Mono", "Consolas", "DejaVu Sans Mono",
                    "Courier")},
}

#: The named fonts this module owns: (role, size, weight) per mode. Panels
#: use the names, so a switch re-sizes and re-faces them in place.
FONTS = {
    "SMUHeading": {LIGHT: ("heading", 9, "normal"),
                   DARK: ("heading", 10, "normal")},
    "SMUTitle":   {LIGHT: ("heading", 17, "normal"),
                   DARK: ("heading", 15, "normal")},
    "SMUReadout": {LIGHT: ("number", 18, "normal"),
                   DARK: ("number", 22, "normal")},
    "SMUBold":    {LIGHT: ("body", 9, "bold"), DARK: ("body", 9, "bold")},
    "SMUSmall":   {LIGHT: ("body", 8, "normal"), DARK: ("body", 8, "normal")},
    "SMUCanvas":  {LIGHT: ("body", 9, "normal"), DARK: ("body", 9, "normal")},
    "SMUCanvasBold": {LIGHT: ("body", 10, "bold"),
                      DARK: ("body", 10, "bold")},
}

#: Tk's own named fonts, re-faced per mode. Sizes are left as Tk chose
#: them, which is what keeps the windows inside `test_layout.py`.
_TK_FONTS = {"TkDefaultFont": "body", "TkTextFont": "body",
             "TkHeadingFont": "body", "TkMenuFont": "body",
             "TkCaptionFont": "body", "TkTooltipFont": "body",
             "TkFixedFont": "mono"}


def resolve_family(candidates, installed):
    """The first of `candidates` that is installed, else the last one.

    The last candidate is a Tk-universal name, so falling through to it
    still gives Tk something it can map to a real face.
    """
    lowered = {name.lower() for name in installed}
    for name in candidates:
        if name.lower() in lowered:
            return name
    return candidates[-1]


# --- colour arithmetic ---------------------------------------------------

def _rgb(hex_colour):
    value = hex_colour.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def blend(colour, other, amount):
    """`colour` moved `amount` (0..1) of the way towards `other`."""
    a, b = _rgb(colour), _rgb(other)
    mixed = (round(x + (y - x) * amount) for x, y in zip(a, b))
    return "#" + "".join(f"{c:02x}" for c in mixed)


def contrast_ratio(foreground, background):
    """WCAG 2.1 contrast ratio between two hex colours."""
    def luminance(colour):
        channels = []
        for c in _rgb(colour):
            s = c / 255
            channels.append(s / 12.92 if s <= 0.03928
                            else ((s + 0.055) / 1.055) ** 2.4)
        r, g, b = channels
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    hi, lo = sorted((luminance(foreground), luminance(background)),
                    reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# --- the saved choice ----------------------------------------------------

def _prefs_path():
    # Imported here so this module stays importable without the rest of
    # core - a panel test builds widgets and nothing else.
    from smuniversal_lab_suite.core.single_instance import lock_directory
    return lock_directory() / PREFS_FILENAME


def load_mode():
    """The mode chosen last time, or `DEFAULT_MODE`.

    Anything unreadable - no file, a half-written one, a mode this build
    does not know - is the default rather than an error: the operator
    loses a preference, never a window.
    """
    try:
        with open(_prefs_path(), encoding="utf-8") as handle:
            mode = json.load(handle).get("mode")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_MODE
    return mode if mode in MODES else DEFAULT_MODE


def save_mode(mode):
    """Remember `mode` for the next launch. Best effort, never raises."""
    try:
        path = _prefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"mode": mode}, handle)
    except OSError:
        pass


# --- the per-window manager ----------------------------------------------

#: Where a root keeps its `Theme`. An attribute on the root rather than a
#: module-level map: the theme holds the root, so any map keyed by root
#: would keep every window ever built alive for the life of the process.
_ATTRIBUTE = "_smu_theme"


def theme_for(widget):
    """The `Theme` of the window `widget` belongs to, created on demand.

    One per Tk interpreter, because ttk styles are per interpreter. A
    panel built in a test with no `LabApp` around it gets one too, so no
    builder has to ask whether it is inside an application.
    """
    root = widget._root()
    theme = getattr(root, _ATTRIBUTE, None)
    if theme is None:
        theme = Theme(root)
    return theme


class Theme:
    """Applies a mode and an accent to one Tk interpreter, and keeps the
    plain-Tk widgets that registered with it in step."""

    def __init__(self, root, mode=None, accent=DEFAULT_ACCENT):
        self.root = root
        self.mode = mode if mode in MODES else load_mode()
        self.accent_key = accent if accent in ACCENTS else DEFAULT_ACCENT
        self._listeners = []
        self._fonts = {}
        self.style = ttk.Style(root)
        setattr(root, _ATTRIBUTE, self)
        self._apply()

    # ---- what the widgets read ----
    @property
    def palette(self):
        return PALETTES[self.mode]

    @property
    def accent(self):
        return ACCENTS[self.accent_key][self.mode]

    def accent_of(self, key):
        """Another experiment's accent in the current mode - the colour
        dot on a notebook tab that is not the one in front."""
        return ACCENTS.get(key, ACCENTS[DEFAULT_ACCENT])[self.mode]

    @property
    def is_dark(self):
        return self.mode == DARK

    # ---- changing it ----
    def set_mode(self, mode, save=True):
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        if save:
            save_mode(mode)
        if mode != self.mode:
            self.mode = mode
            self._apply()

    def toggle(self):
        """Flip between dark and light, and remember the choice."""
        self.set_mode(LIGHT if self.is_dark else DARK)

    def set_accent(self, key):
        key = key if key in ACCENTS else DEFAULT_ACCENT
        if key != self.accent_key:
            self.accent_key = key
            self._apply()

    def on_change(self, callback, widget=None):
        """Call `callback(theme)` now and after every switch.

        With `widget`, the callback is dropped once that widget has been
        destroyed, so a closed Equations window or a torn-down tab does
        not keep receiving repaints for widgets that no longer exist.
        """
        self._listeners.append((widget, callback))
        callback(self)
        return callback

    # ---- applying it ----
    def _apply(self):
        self._configure_fonts()
        self._configure_styles()
        self._configure_options()
        self._recolour_popdowns(self.root)
        self._recolour_toplevel(self.root)
        self._notify()

    def _notify(self):
        alive = []
        for widget, callback in self._listeners:
            if widget is not None:
                try:
                    if not widget.winfo_exists():
                        continue
                except tk.TclError:
                    continue
            alive.append((widget, callback))
            try:
                callback(self)
            except tk.TclError:
                # A widget torn down between the existence check and the
                # repaint. It is gone; so is its listener.
                alive.pop()
        self._listeners = alive

    def _configure_fonts(self):
        installed = tkfont.families(self.root)
        families = {role: resolve_family(candidates[self.mode], installed)
                    for role, candidates in _FAMILIES.items()}
        for name, role in _TK_FONTS.items():
            try:
                tkfont.nametofont(name, root=self.root).configure(
                    family=families[role])
            except tk.TclError:
                pass              # a Tk build without that named font
        for name, spec in FONTS.items():
            role, size, weight = spec[self.mode]
            options = dict(family=families[role], size=size, weight=weight)
            existing = self._fonts.get(name)
            if existing is None:
                self._fonts[name] = tkfont.Font(root=self.root, name=name,
                                                exists=False, **options)
            else:
                existing.configure(**options)
        self.families = families

    def _configure_styles(self):
        p, accent = self.palette, self.accent
        style = self.style
        style.theme_use("clam")
        soft = blend(accent, p.field, 0.72)
        hover = blend(p.button, accent, 0.14)
        pressed = blend(p.button, accent, 0.26)
        accent_hover = blend(accent, p.ink, 0.12)

        style.configure(".", background=p.bg, foreground=p.ink,
                        fieldbackground=p.field, bordercolor=p.rule,
                        lightcolor=p.bg, darkcolor=p.bg,
                        troughcolor=p.track, selectbackground=soft,
                        selectforeground=p.ink, insertcolor=p.ink,
                        focuscolor=accent, arrowcolor=p.ink2,
                        font="TkDefaultFont")
        style.map(".", foreground=[("disabled", p.muted)])

        style.configure("TFrame", background=p.bg)
        style.configure("TLabel", background=p.bg, foreground=p.ink)
        style.configure("TLabelframe", background=p.bg, bordercolor=p.rule,
                        lightcolor=p.bg, darkcolor=p.bg)
        style.configure("TLabelframe.Label", background=p.bg,
                        foreground=accent, font="SMUHeading")
        style.configure("TSeparator", background=p.rule)

        # Semantic label styles. A panel names what a label *is*; the
        # palette decides what that looks like in each mode.
        for name, colour in (("Hint", p.muted), ("Warn", p.warn),
                             ("Good", p.good), ("Bad", p.bad),
                             ("Accent", accent), ("NType", p.n_type),
                             ("PType", p.p_type), ("Hot", p.hot),
                             ("Cold", p.cold)):
            style.configure(f"{name}.TLabel", foreground=colour)
            # A bold twin of each, for the readouts that are bold
            # *and* coloured. ttk inherits down one name at a time, so
            # "Warn.Bold.TLabel" would otherwise find the font and not
            # the colour.
            style.configure(f"{name}.Bold.TLabel", foreground=colour,
                            font="SMUBold")
        style.configure("Small.Hint.TLabel", font="SMUSmall")
        style.configure("Bold.TLabel", font="SMUBold")
        style.configure("Readout.TLabel", font="SMUReadout")
        style.configure("Title.TLabel", font="SMUTitle")
        # A stale calculation is greyed and keeps its face, so every
        # style a result label can wear needs a greyed twin. ttk
        # inherits the rest of the options from the base name.
        faded = blend(p.muted, p.bg, 0.35)
        for base in STALE_BASES:
            style.configure(f"Stale.{base}", foreground=faded)
        style.configure("Tooltip.TLabel", background=p.tooltip,
                        foreground=p.tooltip_ink, bordercolor=p.rule)

        # The header strip sits on its own darker (or whiter) band.
        style.configure("Header.TFrame", background=p.header)
        style.configure("Header.TLabel", background=p.header,
                        foreground=p.ink)
        style.configure("Title.Header.TLabel", font="SMUTitle")
        style.configure("Sub.Header.TLabel", foreground=p.muted)
        style.configure("AccentBar.TFrame", background=accent)

        # --- buttons ---
        style.configure("TButton", background=p.button, foreground=p.ink,
                        bordercolor=p.button_border, lightcolor=p.button,
                        darkcolor=p.button, focuscolor=accent,
                        padding=(8, 2))
        style.map("TButton",
                  background=[("disabled", p.bg), ("pressed", pressed),
                              ("active", hover)],
                  foreground=[("disabled", p.muted)],
                  bordercolor=[("disabled", p.rule),
                               ("focus", accent)],
                  lightcolor=[("disabled", p.bg), ("pressed", pressed),
                              ("active", hover)],
                  darkcolor=[("disabled", p.bg), ("pressed", pressed),
                             ("active", hover)])
        style.configure("Run.TButton", background=accent,
                        foreground=p.on_accent, bordercolor=accent,
                        lightcolor=accent, darkcolor=accent,
                        font="SMUBold")
        style.map("Run.TButton",
                  background=[("disabled", p.bg), ("active", accent_hover)],
                  foreground=[("disabled", p.muted)],
                  bordercolor=[("disabled", p.rule)],
                  lightcolor=[("disabled", p.bg), ("active", accent_hover)],
                  darkcolor=[("disabled", p.bg), ("active", accent_hover)])
        stop_hover = blend(p.stop, "#000000", 0.12)
        style.configure("Stop.TButton", background=p.stop,
                        foreground="#ffffff", bordercolor=p.stop,
                        lightcolor=p.stop, darkcolor=p.stop,
                        font="SMUBold")
        style.map("Stop.TButton",
                  background=[("disabled", p.bg), ("active", stop_hover)],
                  foreground=[("disabled", p.muted)],
                  bordercolor=[("disabled", p.rule)],
                  lightcolor=[("disabled", p.bg), ("active", stop_hover)],
                  darkcolor=[("disabled", p.bg), ("active", stop_hover)])
        style.configure("Header.TButton", background=p.button,
                        bordercolor=p.button_border)

        # --- fields ---
        for widget in ("TEntry", "TCombobox", "TSpinbox"):
            style.configure(widget, fieldbackground=p.field,
                            foreground=p.ink, bordercolor=p.field_border,
                            lightcolor=p.field, darkcolor=p.field,
                            insertcolor=p.ink, arrowcolor=p.ink2,
                            background=p.button, selectbackground=soft,
                            selectforeground=p.ink)
            style.map(widget,
                      fieldbackground=[("disabled", p.bg),
                                       ("readonly", "disabled", p.bg),
                                       ("readonly", p.field)],
                      foreground=[("disabled", p.muted)],
                      bordercolor=[("focus", accent)],
                      lightcolor=[("focus", accent)],
                      selectbackground=[("readonly", "!focus", p.field),
                                        ("readonly", "focus", soft)],
                      selectforeground=[("readonly", p.ink)],
                      arrowcolor=[("disabled", p.muted)])

        # --- ticks and dots ---
        for widget in ("TCheckbutton", "TRadiobutton"):
            style.configure(widget, background=p.bg, foreground=p.ink,
                            indicatorbackground=p.field,
                            indicatorforeground=p.on_accent,
                            upperbordercolor=p.field_border,
                            lowerbordercolor=p.field_border,
                            focuscolor=accent)
            style.map(widget,
                      background=[("active", p.bg)],
                      indicatorbackground=[("disabled", p.bg),
                                           ("selected", accent),
                                           ("pressed", soft)],
                      indicatorforeground=[("selected", p.on_accent)],
                      upperbordercolor=[("selected", accent)],
                      lowerbordercolor=[("selected", accent)],
                      foreground=[("disabled", p.muted)])

        # --- tables ---
        # Tight on purpose: a table is eight rows in a window whose
        # height budget is measured in tens of pixels, so every pixel
        # here is multiplied by eight - see `tests/test_layout.py`.
        row_height = max(18, tkfont.nametofont(
            "TkDefaultFont", root=self.root).metrics("linespace") + 2)
        style.configure("Treeview", background=p.field,
                        fieldbackground=p.field, foreground=p.ink,
                        bordercolor=p.rule, lightcolor=p.field,
                        darkcolor=p.field, rowheight=row_height)
        style.map("Treeview",
                  background=[("selected", soft)],
                  foreground=[("selected", p.ink)])
        style.configure("Treeview.Heading", background=p.bg,
                        foreground=p.ink2, bordercolor=p.rule,
                        lightcolor=p.bg, darkcolor=p.bg, relief="flat")
        style.map("Treeview.Heading", background=[("active", hover)])

        # --- progress, scrollbars, tabs ---
        style.configure("Horizontal.TProgressbar", background=accent,
                        troughcolor=p.track, bordercolor=p.rule,
                        lightcolor=accent, darkcolor=accent)
        for orient in ("Vertical", "Horizontal"):
            style.configure(f"{orient}.TScrollbar", background=p.button,
                            troughcolor=p.bg, bordercolor=p.rule,
                            lightcolor=p.button, darkcolor=p.button,
                            arrowcolor=p.ink2, gripcount=0)
            style.map(f"{orient}.TScrollbar",
                      background=[("active", hover)])
        style.configure("TNotebook", background=p.bg, bordercolor=p.rule,
                        lightcolor=p.bg, darkcolor=p.bg, tabmargins=(0, 2, 0, 0))
        style.configure("TNotebook.Tab", background=p.bg, foreground=p.ink2,
                        bordercolor=p.rule, lightcolor=p.bg, darkcolor=p.bg,
                        padding=(12, 3))
        style.map("TNotebook.Tab",
                  background=[("selected", p.header), ("active", hover)],
                  foreground=[("selected", p.ink)],
                  lightcolor=[("selected", accent)])
        style.configure("TPanedwindow", background=p.rule)
        style.configure("Sash", sashthickness=6, gripcount=0,
                        background=p.bg, lightcolor=p.bg, darkcolor=p.bg,
                        bordercolor=p.rule)

    def _configure_options(self):
        """Defaults for plain Tk widgets created from now on - chiefly the
        listbox a Combobox drops down, which Tk builds the first time
        the list opens."""
        p = self.palette
        soft = blend(self.accent, p.field, 0.72)
        for pattern, value in (
                ("*TCombobox*Listbox.background", p.field),
                ("*TCombobox*Listbox.foreground", p.ink),
                ("*TCombobox*Listbox.selectBackground", soft),
                ("*TCombobox*Listbox.selectForeground", p.ink),
                ("*TCombobox*Listbox.font", "TkDefaultFont")):
            self.root.option_add(pattern, value)

    def _recolour_popdowns(self, widget):
        """Drop-down lists that already exist keep their old colours - the
        option database only reaches widgets built after it changed - so
        walk the window and repaint them."""
        p = self.palette
        soft = blend(self.accent, p.field, 0.72)
        try:
            children = widget.winfo_children()
            is_combo = widget.winfo_class() == "TCombobox"
        except tk.TclError:
            return
        if is_combo:
            try:
                popdown = widget.tk.call("ttk::combobox::PopdownWindow",
                                         widget)
                widget.tk.call(f"{popdown}.f.l", "configure",
                               "-background", p.field, "-foreground", p.ink,
                               "-selectbackground", soft,
                               "-selectforeground", p.ink)
            except tk.TclError:
                pass
        for child in children:
            self._recolour_popdowns(child)

    def _recolour_toplevel(self, window):
        """The Tk root's own ground, and on Windows the title bar."""
        p = self.palette
        try:
            window.configure(background=p.bg)
        except tk.TclError:
            return
        set_dark_title_bar(window, self.is_dark)

    def paint_toplevel(self, window):
        """Bring a `Toplevel` built after the last switch into line, and
        keep it there."""
        self.on_change(lambda theme: theme._recolour_toplevel(window),
                       widget=window)


def set_dark_title_bar(window, dark):
    """Ask Windows to draw `window`'s title bar dark or light.

    Windows 10 1809+ honours DWMWA_USE_IMMERSIVE_DARK_MODE (20; 19 on
    builds before 20H1). Anywhere else, or if the call fails, the title
    bar simply keeps the system colour - it is decoration.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value),
                    ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


# --- figures -------------------------------------------------------------

def style_figure(fig, palette):
    """The figure's own ground. Axes are styled per redraw by
    `style_axes`, because `Axes.clear()` resets them."""
    fig.set_facecolor(palette.plot_bg)


def style_axes(ax, palette):
    """Colour one axes from the palette. Call after every `ax.clear()`."""
    ax.set_facecolor(palette.plot_bg)
    ax.set_prop_cycle(color=list(palette.series))
    for spine in ax.spines.values():
        spine.set_color(palette.plot_axis)
    ax.tick_params(colors=palette.plot_ink, which="both")
    ax.xaxis.label.set_color(palette.plot_ink)
    ax.yaxis.label.set_color(palette.plot_ink)
    ax.title.set_color(palette.ink)


def style_legend(legend, palette):
    """A legend on the plot's own ground, in its ink."""
    if legend is None:
        return
    frame = legend.get_frame()
    frame.set_facecolor(palette.plot_bg)
    frame.set_edgecolor(palette.plot_axis)
    for text in legend.get_texts():
        text.set_color(palette.plot_ink)


def grid_kwargs(palette):
    """What `ax.grid()` should be called with."""
    return dict(color=palette.plot_grid, alpha=1.0, linewidth=0.8)


def style_toolbar(toolbar, palette):
    """The matplotlib navigation toolbar: plain Tk widgets throughout.

    `NavigationToolbar2Tk` recolours its icons for a dark background
    when asked to reload them, so each button's image is reloaded after
    its background changes.
    """
    def paint(widget):
        try:
            widget.configure(background=palette.bg)
        except tk.TclError:
            pass
        try:
            widget.configure(foreground=palette.ink,
                             activebackground=blend(palette.bg, palette.ink,
                                                    0.12),
                             highlightbackground=palette.bg)
        except tk.TclError:
            pass
        try:
            # Back and Forward sit disabled until there is a view to go
            # back to. Tk draws a disabled button's *icon* stippled,
            # which reads correctly in both modes; this is for the
            # disabled *text* of any button that has some, which would
            # otherwise be a light system colour on a dark toolbar.
            widget.configure(disabledforeground=palette.muted)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            paint(child)
    paint(toolbar)
    reload = getattr(toolbar, "_set_image_for_button", None)
    if reload is not None:
        for button in getattr(toolbar, "_buttons", {}).values():
            try:
                reload(button)
            except Exception:
                pass              # a matplotlib without the recolouring
