"""The theme's colours and saved choice, without building a window.

Two things are pinned here. Legibility: every text colour the palettes
define reads at WCAG AA against every ground it can sit on, in both
modes, and so does each experiment's accent. The accent is used as text
(panel titles) and as a fill under text (Run), so it is checked both
ways. And robustness: the saved mode is a preference, so anything wrong
with the file falls back to the default instead of failing the launch.
"""
import json
import pathlib
import re

import pytest

from smuniversal_lab_suite.core.gui import theme
from smuniversal_lab_suite.core.gui.theme import (
    ACCENTS,
    DARK,
    DEFAULT_MODE,
    LIGHT,
    MODES,
    PALETTES,
    blend,
    contrast_ratio,
    load_mode,
    resolve_family,
    save_mode,
)

AA = 4.5
TEXT = ("ink", "ink2", "muted", "good", "warn", "bad")
GROUNDS = ("bg", "field", "header")


def test_dark_is_the_default():
    assert DEFAULT_MODE == DARK


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("ground", GROUNDS)
@pytest.mark.parametrize("text", TEXT)
def test_text_reads_on_every_ground(mode, ground, text):
    palette = PALETTES[mode]
    ratio = contrast_ratio(getattr(palette, text), getattr(palette, ground))
    assert ratio >= AA, f"{mode}: {text} on {ground} is {ratio:.2f}:1"


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("key", sorted(ACCENTS))
def test_accents_read_as_text_and_under_text(mode, key):
    palette, accent = PALETTES[mode], ACCENTS[key][mode]
    assert contrast_ratio(accent, palette.bg) >= AA
    assert contrast_ratio(palette.on_accent, accent) >= AA


@pytest.mark.parametrize("mode", MODES)
def test_the_safety_cues_read(mode):
    palette = PALETTES[mode]
    assert contrast_ratio("#ffffff", palette.stop) >= AA
    assert contrast_ratio(palette.tooltip_ink, palette.tooltip) >= AA


def test_the_modes_keep_one_series_order():
    """A run keeps its colour slot when the mode changes."""
    assert len(PALETTES[DARK].series) == len(PALETTES[LIGHT].series) == 8


def test_every_experiment_has_an_accent():
    """Read from the launcher, so a sixth experiment cannot be added
    without choosing its colour."""
    from smuniversal_lab_suite.core.launcher import PLOTTER, WINDOWS
    classes = set()
    for _label, spec in WINDOWS.values():
        if spec == PLOTTER:
            continue
        classes.update([spec] if isinstance(spec, type) else spec)
    assert len(classes) == 5
    for cls in classes:
        assert cls.THEME_KEY in ACCENTS, cls.__name__
        assert cls.THEME_KEY != theme.DEFAULT_ACCENT, cls.__name__


#: A widget option being handed a literal colour. What the theme
#: replaced, and what must not come back: a colour written into a panel
#: is a colour that cannot follow a mode switch.
LITERAL_COLOUR = re.compile(
    r"(foreground|background|fg|bg|fill|outline|activebackground"
    r"|highlightbackground|insertbackground|selectbackground)"
    r"\s*=\s*[\"'](#[0-9a-fA-F]{3,6}|red|green|blue|gray|grey|white|black"
    r"|orange|yellow)[\"']")

#: The three files allowed to name a colour, and why.
COLOUR_OWNERS = {
    # the palettes themselves
    "core/gui/theme.py",
    # the plotter's validated categorical palette
    "plotter/style.py",
    # the output lamp: green when live, grey when not, in both modes,
    # because a safety cue that changes with the look is not one
    "core/gui/run_controls.py",
}


def test_no_panel_names_a_colour():
    root = pathlib.Path(__file__).resolve().parent.parent
    package = root / "smuniversal_lab_suite"
    offenders = []
    for path in package.rglob("*.py"):
        relative = path.relative_to(package).as_posix()
        if relative in COLOUR_OWNERS:
            continue
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if LITERAL_COLOUR.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert not offenders, (
        "a literal colour cannot follow a theme switch - use a semantic "
        "style or the palette:\n  " + "\n  ".join(offenders))


def test_font_resolution_falls_back():
    installed = ["DejaVu Sans", "Courier"]
    assert resolve_family(("Bahnschrift", "DejaVu Sans"), installed) == \
        "DejaVu Sans"
    assert resolve_family(("Cambria", "Times"), installed) == "Times"
    assert resolve_family(("cambria",), ["Cambria"]) == "cambria"


def test_blend_ends_and_middle():
    assert blend("#000000", "#ffffff", 0) == "#000000"
    assert blend("#000000", "#ffffff", 1) == "#ffffff"
    assert blend("#000000", "#ffffff", 0.5) == "#808080"


def test_the_mode_round_trips():
    save_mode(LIGHT)
    assert load_mode() == LIGHT
    save_mode(DARK)
    assert load_mode() == DARK


def test_no_file_is_the_default():
    assert load_mode() == DEFAULT_MODE


@pytest.mark.parametrize("content", ["", "{", "[]", '{"mode": "sepia"}',
                                     '{"mode": 3}'])
def test_a_bad_file_is_the_default(content):
    path = theme._prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    assert load_mode() == DEFAULT_MODE


def test_saving_writes_only_the_mode():
    save_mode(LIGHT)
    data = json.loads(theme._prefs_path().read_text(encoding="utf-8"))
    assert data == {"mode": LIGHT}
