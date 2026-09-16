"""
How the plotter's figures look, in one place.

The palette is the validated reference palette of the dataviz method
this project's plots follow, used unchanged: eight categorical hues in a
fixed order, a single-hue sequential ramp, reserved status colours, and
recessive chrome. Its colour-vision checks were run against these exact
values, so a hex edited here is a palette nobody has validated.

Two rules drive most of what is below:

* **Colour follows the run, not its position.** A run keeps the slot it
  was given when it was ticked; unticking another run does not repaint
  it. `session.Session` owns that assignment.
* **Past eight runs there is no ninth hue.** Many runs of one sample -
  the cycles of a periodic IV run, a day of repeated sweeps - are drawn
  on the sequential ramp in time order instead, light to dark, which is
  what the reader wants from that many curves anyway: the drift.
"""
from __future__ import annotations

import numpy as np

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

CATEGORICAL = (
    "#2a78d6",   # blue
    "#eb6834",   # orange
    "#1baf7a",   # aqua
    "#eda100",   # yellow
    "#e87ba4",   # magenta
    "#008300",   # green
    "#4a3aa7",   # violet
    "#e34948",   # red
)

#: Sequential blue, lightest usable step first. Starts at step 250, not
#: 100: these are discrete curves on a light surface and the lightest
#: must still be visible against it.
SEQUENTIAL = ("#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6",
              "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b")

#: Reserved for state, never for a series. Always paired with a marker
#: shape and a legend label, never colour alone.
CRITICAL = "#d03b3b"
WARNING = "#fab219"

LINE_WIDTH = 1.5          # points; 2 px at the canvas' 100 dpi
MARKER_SIZE = 5.5         # points; about 8 px across
MARKER_EDGE = 1.0         # the surface-coloured ring around a marker
MAX_MARKED_POINTS = 60    # above this, markers hide the line they sit on


def sequential_colors(count: int) -> list[str]:
    """`count` colours along the sequential ramp, earliest lightest."""
    if count <= 0:
        return []
    if count == 1:
        return [SEQUENTIAL[len(SEQUENTIAL) // 2]]
    positions = np.linspace(0, len(SEQUENTIAL) - 1, count)
    return [_interpolate(p) for p in positions]


def _interpolate(position: float) -> str:
    low = int(np.floor(position))
    high = min(low + 1, len(SEQUENTIAL) - 1)
    frac = position - low
    a = _rgb(SEQUENTIAL[low])
    b = _rgb(SEQUENTIAL[high])
    mixed = [round(x + (y - x) * frac) for x, y in zip(a, b)]
    return "#" + "".join(f"{c:02x}" for c in mixed)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16),
            int(hex_color[5:7], 16))


def style_axes(ax) -> None:
    """Recessive chrome: hairline solid grid, muted ticks, no box."""
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.75, linestyle="-")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
        ax.spines[side].set_linewidth(0.75)
    ax.tick_params(colors=INK_MUTED, labelcolor=INK_SECONDARY, labelsize=8,
                   length=3, width=0.75)
    ax.xaxis.label.set_color(INK_SECONDARY)
    ax.yaxis.label.set_color(INK_SECONDARY)
    ax.xaxis.label.set_fontsize(9)
    ax.yaxis.label.set_fontsize(9)
    ax.title.set_color(INK)
    ax.title.set_fontsize(10)


def style_legend(legend) -> None:
    if legend is None:
        return
    legend.get_frame().set_facecolor(SURFACE)
    legend.get_frame().set_edgecolor(GRID)
    legend.get_frame().set_linewidth(0.75)
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
        text.set_fontsize(8)


def line_kwargs(color: str, points: int) -> dict:
    """The one line style every series uses."""
    kwargs = {"color": color, "linewidth": LINE_WIDTH,
              "solid_joinstyle": "round", "solid_capstyle": "round"}
    if points <= MAX_MARKED_POINTS:
        kwargs.update(marker="o", markersize=MARKER_SIZE,
                      markerfacecolor=color, markeredgecolor=SURFACE,
                      markeredgewidth=MARKER_EDGE)
    return kwargs
