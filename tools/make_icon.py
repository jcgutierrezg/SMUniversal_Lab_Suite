"""
Draw the application icon: `smuniversal_lab_suite/assets/app_icon.ico`
and `app_icon.png`.

    uv run python tools/make_icon.py

Drawn in code rather than kept only as an image, so the icon can be
changed by editing a few numbers and every size regenerated in step.
The output files are committed; nothing draws them at run time.

What it shows
-------------
A dark instrument-panel tile - the dark mode's ground - carrying an I-V
curve in the suite's blue: the measurement every experiment here is a
variation on. At its four corners sit contacts in the four experiments'
own colours (Van der Pauw, Hall, the four-point probe, fixed source),
which is both the Van der Pauw sample and the suite in one picture.

Each size is drawn on its own, not scaled down from the largest. At 16
and 24 px the corner contacts would be four specks of noise, so the
small sizes carry the tile and the curve only, with the strokes
thickened to stay legible.
"""
from __future__ import annotations

import math
import pathlib

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "smuniversal_lab_suite" / "assets"

#: The sizes Windows asks an .ico for: title bars and small lists (16),
#: the taskbar (24-32), Explorer and the desktop (48 and up).
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
#: Below this many pixels the contacts are dropped.
CONTACTS_FROM = 32
#: Drawn this many times larger, then reduced, for smooth edges.
OVERSAMPLE = 8

# The dark palette's colours, so the icon and the window it opens match.
# Values from `core/gui/theme.py` (DARK_PALETTE and ACCENTS[..][DARK]).
TILE = (26, 29, 33)             # bg
TILE_EDGE = (58, 63, 71)        # field_border
AXES = (143, 141, 134)          # muted
CURVE = (94, 166, 247)          # the IV sweep's accent
CONTACTS = ((56, 209, 155),     # Van der Pauw, top left
            (165, 149, 255),    # Hall, top right
            (255, 140, 89),     # four-point probe, bottom right
            (243, 187, 68))     # fixed source, bottom left


def draw(size: int) -> Image.Image:
    """The icon at `size` x `size` pixels."""
    big = size * OVERSAMPLE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)

    def at(u: float, v: float) -> tuple[float, float]:
        """A point given in a 0..1 square, in oversampled pixels."""
        return u * big, v * big

    small = size < CONTACTS_FROM
    # Strokes are fractions of the tile, with a floor so a 16 px icon
    # still gets a line at least ~1.6 real pixels wide.
    def stroke(fraction: float, floor_px: float) -> int:
        return max(1, round(max(fraction * big, floor_px * OVERSAMPLE)))

    # --- the tile ---
    inset = 0.04 * big
    radius = 0.2 * big
    pen.rounded_rectangle((inset, inset, big - inset, big - inset),
                          radius=radius, fill=TILE,
                          outline=TILE_EDGE, width=stroke(0.022, 1.0))

    # --- the axes: the origin sits low and left, as on an I-V plot ---
    origin_u, origin_v = 0.38, 0.62
    axis_width = stroke(0.022, 1.0)
    pen.line([at(0.2, origin_v), at(0.8, origin_v)], fill=AXES,
             width=axis_width)
    pen.line([at(origin_u, 0.22), at(origin_u, 0.8)], fill=AXES,
             width=axis_width)

    # --- the curve: a diode, flat through reverse bias, then rising ---
    # It ends short of the top-right corner, where the Hall contact sits.
    curve_width = stroke(0.075, 1.9 if small else 1.6)
    r = curve_width / 2
    previous = None
    steps = 4 * big                             # about 4 discs per pixel
    for step in range(steps + 1):
        u = 0.19 + 0.49 * step / steps          # 0.19 .. 0.68
        x = (u - origin_u) / 0.30               # bias, about -0.6 .. 1
        current = (math.exp(3.4 * x) - 1) / (math.exp(3.4) - 1)
        cx, cy = at(u, origin_v - 0.37 * current)
        # A wide PIL line is jagged along a curve, so the stroke is laid
        # down as overlapping discs instead: smooth edges, round ends.
        if previous is not None and math.dist(previous, (cx, cy)) < r / 4:
            continue
        pen.ellipse((cx - r, cy - r, cx + r, cy + r), fill=CURVE)
        previous = (cx, cy)

    # --- the four contacts, one per experiment ---
    if not small:
        r = 0.056 * big
        corners = ((0.21, 0.21), (0.79, 0.21), (0.79, 0.79), (0.21, 0.79))
        for (u, v), colour in zip(corners, CONTACTS):
            cx, cy = at(u, v)
            pen.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour)

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    images = [draw(size) for size in SIZES]
    largest = images[-1]
    # Every size drawn on its own goes into the .ico, rather than
    # letting Pillow scale the largest down for the rest.
    largest.save(ASSETS / "app_icon.ico", format="ICO",
                 sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    largest.save(ASSETS / "app_icon.png")
    # The small one Tk shows in a title bar, where the .ico is not used.
    images[SIZES.index(32)].save(ASSETS / "app_icon_32.png")
    print(f"wrote {ASSETS / 'app_icon.ico'} ({len(SIZES)} sizes) and PNGs")


if __name__ == "__main__":
    main()
