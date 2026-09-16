"""
What each experiment's data is drawn as.

A view is a named way of drawing ticked runs onto a Matplotlib `Figure`.
Views are offered by experiment: an IV file offers I-V curves and the
resistance drawn from them, a Fixed source file offers its trace against
time and the timing behind it. The window lists only the views that fit
every ticked run.

No Tk here, and no pyplot: views draw onto a `Figure` they are handed,
so the tests render them headless and the window hosts the same figure
in its canvas.

Rules every view keeps
----------------------
* **One y-scale per panel.** Two quantities in different units go in
  stacked panels sharing the x-axis, never on a second y-axis - a
  twin axis lets the reader compare two scales that were chosen to make
  the lines cross.
* **A value is not dropped silently.** Points left out - a zero current
  on a log axis, a blank reading - are counted and the count is returned
  as a note shown under the plot.
* **Identity is never colour alone.** Two or more runs get a legend; a
  status marker, such as a compliance trip, gets its own shape and its
  own legend entry.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Callable

import numpy as np
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import (
    EngFormatter,
    LogLocator,
    MaxNLocator,
    NullFormatter,
)

from smuniversal_lab_suite.plotter import detect, style
from smuniversal_lab_suite.plotter.session import Series


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    default: bool = False


@dataclass(frozen=True)
class View:
    key: str
    title: str
    kinds: frozenset[str]
    draw: Callable[[Figure, list[Series], dict[str, bool]], list[str]]
    options: tuple[Option, ...] = ()
    description: str = ""


class Notes:
    """Collects what a view left out, worded for the operator."""

    def __init__(self):
        self.lines: list[str] = []

    def add(self, text: str) -> None:
        if text not in self.lines:
            self.lines.append(text)


# ------------------------------------------------------------------
# shared drawing helpers
# ------------------------------------------------------------------
UNIT_NAMES = {"V": "Voltage", "A": "Current", "Ω": "Resistance",
              "s": "Time", "°C": "Stage temperature"}


def _panels(fig: Figure, count: int):
    axes = fig.subplots(count, 1, sharex=True, squeeze=False)[:, 0]
    for ax in axes:
        style.style_axes(ax)
    return list(axes)


def _eng_axis(axis, unit: str) -> None:
    axis.set_major_formatter(EngFormatter(unit=unit, places=None, sep=" "))
    if axis.get_scale() == "linear":
        # Engineering labels are wide (`-400 mV`); matplotlib's default
        # tick count lets them run into each other on a narrow canvas.
        axis.set_major_locator(MaxNLocator(nbins=6))


def _plot(ax, x, y, series: Series, points=None):
    points = len(x) if points is None else points
    (line,) = ax.plot(x, y, label=series.label,
                      **style.line_kwargs(series.color, points))
    # Read by the window's hover layer, which names the run under the
    # pointer. A gid rather than the label, because the label is also
    # what the legend reads.
    line.set_gid(series.label)
    return line


def _finish(fig: Figure, series: list[Series], axes, proxies=()):
    """Legend on the top panel when there is more than one thing to name.

    Run names are listed for two to eight runs. Anything else on the
    plot with a label - a status marker, a reference line - and the
    `proxies`, which name marker shapes, are always listed, because
    those are the entries a single run's plot cannot do without.
    """
    top = axes[0]
    names = {s.label for s in series}
    handles, labels = top.get_legend_handles_labels()
    many = len(series) > len(style.CATEGORICAL)
    if many:
        top.set_title(f"{len(series)} runs, coloured by time: lightest is "
                      f"earliest", loc="left", fontsize=8,
                      color=style.INK_SECONDARY)
    pairs = [(h, lab) for h, lab in zip(handles, labels)
             if not (many and lab in names)]
    pairs += list(proxies)
    extras = [lab for _h, lab in pairs if lab not in names]
    if not pairs or (len(series) < 2 and not extras):
        return
    handles, labels = zip(*pairs)
    if len(pairs) > 4:
        # Beside the plot rather than on it: "best" still lands on data
        # once there are enough entries to need a real box, and a legend
        # that hides a curve makes the reader move it to see the data.
        legend = top.legend(handles, labels, loc="upper left",
                            bbox_to_anchor=(1.01, 1.0), borderaxespad=0)
    else:
        legend = top.legend(handles, labels, loc="best")
    style.style_legend(legend)


def _count_nan(*arrays) -> int:
    mask = np.zeros(len(arrays[0]), dtype=bool)
    for values in arrays:
        mask |= ~np.isfinite(values)
    return int(mask.sum())


def _run_time(series: Series):
    text = series.run.text("run_timestamp")
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return None


# ------------------------------------------------------------------
# IV sweep
# ------------------------------------------------------------------
def _iv_arrays(series: Series, notes: Notes):
    voltage = series.run.series("voltage_V")
    current = series.run.series("current_A")
    if voltage is None or current is None:
        notes.add(f"{series.label}: no numeric voltage and current "
                  f"columns; not drawn.")
        return None
    blanks = _count_nan(voltage, current)
    if blanks:
        notes.add(f"{series.label}: {blanks} blank reading(s) left out.")
    return voltage, current


def _iv_fit_current(series: Series, voltage: np.ndarray):
    """The saved fit, redrawn as current against voltage.

    The fit is of measured against sourced, so its meaning depends on
    the mode: I = sV + b when voltage was sourced, V = sI + b when
    current was. Redrawn from the saved slope and intercept rather than
    refitted, so the line shown is the one the result came from.
    """
    run = series.run
    slope = run.number("fit_slope")
    intercept = run.number("fit_intercept")
    mode = run.text("mode")
    if slope is None or intercept is None:
        return None
    finite = voltage[np.isfinite(voltage)]
    if not len(finite):
        return None
    v = np.array([finite.min(), finite.max()])
    if mode == "source_voltage":
        return v, slope * v + intercept
    if mode == "source_current" and slope != 0:
        return v, (v - intercept) / slope
    return None


def draw_iv_curves(fig, series, options):
    notes = Notes()
    (ax,) = _panels(fig, 1)
    fitted = False
    for s in series:
        arrays = _iv_arrays(s, notes)
        if arrays is None:
            continue
        voltage, current = arrays
        _plot(ax, voltage, current, s)
        if options.get("show_fit"):
            line = _iv_fit_current(s, voltage)
            if line is not None:
                ax.plot(*line, color=s.color, linewidth=0.9, alpha=0.7,
                        linestyle="-", zorder=1)
                fitted = True
    if options.get("show_fit") and series and not fitted:
        notes.add("No saved fit on the ticked runs.")
    ax.set_xlabel("Voltage")
    ax.set_ylabel("Current")
    _eng_axis(ax.xaxis, "V")
    _eng_axis(ax.yaxis, "A")
    _finish(fig, series, [ax])
    return notes.lines


def draw_iv_log(fig, series, options):
    notes = Notes()
    (ax,) = _panels(fig, 1)
    for s in series:
        arrays = _iv_arrays(s, notes)
        if arrays is None:
            continue
        voltage, current = arrays
        magnitude = np.abs(current)
        zero = np.isfinite(magnitude) & (magnitude <= 0)
        if zero.any():
            notes.add(f"{s.label}: {int(zero.sum())} reading(s) of exactly "
                      f"0 A cannot be shown on a log axis.")
        _plot(ax, voltage, np.where(zero, np.nan, magnitude), s)
    ax.set_yscale("log")
    ax.set_xlabel("Voltage")
    ax.set_ylabel("|Current|")
    _eng_axis(ax.xaxis, "V")
    _eng_axis(ax.yaxis, "A")
    ax.yaxis.set_minor_formatter(NullFormatter())
    _finish(fig, series, [ax])
    return notes.lines


def draw_iv_point_resistance(fig, series, options):
    notes = Notes()
    (ax,) = _panels(fig, 1)
    for s in series:
        arrays = _iv_arrays(s, notes)
        if arrays is None:
            continue
        voltage, current = arrays
        with np.errstate(divide="ignore", invalid="ignore"):
            resistance = voltage / current
        undefined = np.isfinite(voltage) & np.isfinite(current) \
            & ~np.isfinite(resistance)
        if undefined.any():
            notes.add(f"{s.label}: {int(undefined.sum())} point(s) at 0 A "
                      f"have no V/I.")
        _plot(ax, voltage, resistance, s)
    if options.get("log_y"):
        ax.set_yscale("log")
    ax.set_xlabel("Voltage")
    ax.set_ylabel("V / I")
    _eng_axis(ax.xaxis, "V")
    _eng_axis(ax.yaxis, "Ω")
    if options.get("log_y"):
        ax.yaxis.set_minor_formatter(NullFormatter())
    _finish(fig, series, [ax])
    return notes.lines


def _trend(fig, series, key, unit, ylabel, notes):
    """One saved per-run value against cycle number or run time."""
    (ax,) = _panels(fig, 1)
    cycles = [s.run.number("cycle") for s in series]
    run_ids = {s.run.text("run_id") for s in series}
    by_cycle = all(c is not None for c in cycles) and len(run_ids) == 1
    xs, ys = [], []
    for s, cycle in zip(series, cycles):
        value = s.run.number(key)
        x = cycle if by_cycle else _run_time(s)
        if value is None or x is None:
            notes.add(f"{s.label}: no saved {ylabel.lower()}; left out.")
            continue
        xs.append(x)
        ys.append(value)
        ax.plot([x], [value], linestyle="none", marker="o",
                markersize=style.MARKER_SIZE + 1, markerfacecolor=s.color,
                markeredgecolor=style.SURFACE,
                markeredgewidth=style.MARKER_EDGE, label=s.label,
                gid=s.label)
    # Joined only across the cycles of one run. Between separate runs -
    # perhaps separate samples - a line would draw a trend nobody
    # measured.
    if by_cycle and len(xs) >= 2:
        ax.plot(xs, ys, color=style.AXIS, linewidth=0.9, zorder=1)
    ax.set_xlabel("Cycle" if by_cycle else "Run time")
    ax.set_ylabel(ylabel)
    _eng_axis(ax.yaxis, unit)
    if not by_cycle and xs:
        locator = AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(ConciseDateFormatter(locator))
    _finish(fig, series, [ax])
    return ax


def draw_iv_resistance_trend(fig, series, options):
    notes = Notes()
    _trend(fig, series, "resistance_ohm", "Ω", "Fitted resistance",
           notes)
    return notes.lines


# ------------------------------------------------------------------
# Fixed source
# ------------------------------------------------------------------
def _fs_columns(series: Series):
    """(measured column, sourced column) for a Fixed source run."""
    measured = series.run.text("measured_quantity")
    if measured == "current":
        return "current_A", "voltage_V"
    if measured == "voltage":
        return "voltage_V", "current_A"
    mode = series.run.text("source_mode")
    return ("current_A", "voltage_V") if mode == "voltage" \
        else ("voltage_V", "current_A")


def _tripped(series: Series) -> np.ndarray | None:
    for key in ("compliance_tripped", "compliance#2"):
        values = series.run.readings.get(key)
        if values is not None:
            return np.array([str(v) == "yes" for v in values])
    return None


def _by_unit(fig, series, column_for, notes, extra_panels=()):
    """Stacked panels, one per unit, then any extra panels."""
    units = []
    for s in series:
        unit = column_for(s).rsplit("_", 1)[-1]
        if unit not in units:
            units.append(unit)
    axes = _panels(fig, len(units) + len(extra_panels) or 1)
    by_unit = dict(zip(units, axes))
    for unit, ax in by_unit.items():
        ax.set_ylabel(UNIT_NAMES.get(unit, unit))
        _eng_axis(ax.yaxis, unit)
    if len(units) > 1:
        notes.add("Runs measured different quantities, so they are drawn "
                  "in separate panels.")
    return axes, by_unit


def _time(series: Series, notes: Notes):
    t = series.run.series("time_s")
    if t is None:
        notes.add(f"{series.label}: no time column; not drawn.")
    return t


def draw_fs_trace(fig, series, options, sourced=False):
    notes = Notes()
    temperature = [s for s in series
                   if s.run.series("stage_temp_C") is not None
                   and np.isfinite(s.run.series("stage_temp_C")).any()]
    show_temperature = bool(options.get("show_temperature") and temperature)

    def column_for(s):
        return _fs_columns(s)[1 if sourced else 0]

    axes, by_unit = _by_unit(fig, series, column_for, notes,
                             extra_panels=("temp",) if show_temperature
                             else ())
    trip_drawn = False
    for s in series:
        t = _time(s, notes)
        column = column_for(s)
        y = s.run.series(column)
        if t is None or y is None:
            if t is not None:
                notes.add(f"{s.label}: no numeric {column}; not drawn.")
            continue
        blanks = int((~np.isfinite(y)).sum())
        if blanks:
            notes.add(f"{s.label}: {blanks} sample(s) with no reading.")
        ax = by_unit[column.rsplit("_", 1)[-1]]
        _plot(ax, t, y, s)
        tripped = _tripped(s)
        if not sourced and tripped is not None and tripped.any():
            ax.plot(t[tripped], y[tripped], linestyle="none", marker="x",
                    markersize=style.MARKER_SIZE + 1,
                    markeredgewidth=1.5, color=style.CRITICAL,
                    label=None if trip_drawn else "compliance tripped",
                    zorder=5)
            trip_drawn = True
    if show_temperature:
        ax = axes[-1]
        ax.set_ylabel("Stage temp. (°C)")
        for s in temperature:
            t = s.run.series("time_s")
            if t is not None:
                _plot(ax, t, s.run.series("stage_temp_C"), s)
    elif options.get("show_temperature") and series:
        notes.add("No stage temperature was recorded for the ticked runs.")
    axes[-1].set_xlabel("Time since start")
    _eng_axis(axes[-1].xaxis, "s")
    _finish(fig, series, axes)
    return notes.lines


def draw_fs_sourced(fig, series, options):
    return draw_fs_trace(fig, series, options, sourced=True)


def draw_fs_interval(fig, series, options):
    notes = Notes()
    (ax,) = _panels(fig, 1)
    requested = set()
    for s in series:
        t = _time(s, notes)
        if t is None or len(t) < 2:
            continue
        _plot(ax, t[1:], np.diff(t), s)
        value = s.run.number("interval_requested_s")
        if value is not None:
            requested.add(value)
    for i, value in enumerate(sorted(requested)):
        ax.axhline(value, color=style.INK_MUTED, linewidth=0.9,
                   label="requested interval" if i == 0 else None,
                   zorder=1)
    ax.set_ylabel("Interval since previous sample")
    ax.set_xlabel("Time since start")
    _eng_axis(ax.xaxis, "s")
    _eng_axis(ax.yaxis, "s")
    _finish(fig, series, [ax])
    return notes.lines


def draw_fs_read_time(fig, series, options):
    notes = Notes()
    (ax,) = _panels(fig, 1)
    for s in series:
        t = _time(s, notes)
        read = s.run.series("read_s")
        if t is None:
            continue
        if read is None:
            notes.add(f"{s.label}: no read_s column; not drawn.")
            continue
        _plot(ax, t, read, s)
    ax.set_ylabel("Time taken by the reading")
    ax.set_xlabel("Time since start")
    _eng_axis(ax.xaxis, "s")
    _eng_axis(ax.yaxis, "s")
    _finish(fig, series, [ax])
    return notes.lines


# ------------------------------------------------------------------
# Ossila 4-point probe
# ------------------------------------------------------------------
def _fp_arrays(series: Series, notes: Notes):
    current = series.run.series("current_A")
    voltage = series.run.series("voltage_V")
    if current is None or voltage is None:
        notes.add(f"{series.label}: no numeric current and voltage "
                  f"columns; not drawn.")
        return None
    blanks = _count_nan(current, voltage)
    if blanks:
        notes.add(f"{series.label}: {blanks} blank reading(s) left out.")
    return current, voltage


def _fp_fit(series: Series):
    """(slope, intercept) of V = R*I + b, as saved."""
    slope = series.run.number("fit_slope_ohm")
    intercept = series.run.number("fit_intercept_V")
    if slope is None or intercept is None:
        return None
    return slope, intercept


def _log_axes(ax, which, values, label, notes, unit=""):
    """Switch `which` axes to log, if every value can be shown.

    Ticks keep the engineering labels the linear axis had - `10 nA`, not
    `10^-8` - and minor ticks go unlabelled, which is where the log
    formatter's crowded `2x10^-8` labels came from.
    """
    finite = np.concatenate([v[np.isfinite(v)] for v in values]) \
        if values else np.array([])
    if len(finite) and (finite <= 0).any():
        notes.add(f"Some {label} values are zero or negative, so the "
                  f"axis stays linear.")
        return False
    axis = ax.xaxis if which == "x" else ax.yaxis
    if which == "x":
        ax.set_xscale("log")
    else:
        ax.set_yscale("log")
    axis.set_major_formatter(EngFormatter(unit=unit, sep=" "))
    # Under a decade there may be one major tick or none, and an axis
    # with one label cannot be read. There the minor ticks are labelled;
    # over wider spans they would crowd.
    if len(finite) and finite.max() / finite.min() < 20:
        # Labelled at 2x and 5x only: every minor tick crowds together
        # toward the top of a decade.
        axis.set_minor_locator(LogLocator(base=10, subs=(2.0, 5.0)))
        axis.set_minor_formatter(EngFormatter(unit=unit, sep=" "))
    else:
        axis.set_minor_formatter(NullFormatter())
    return True


def draw_fp_vi(fig, series, options):
    notes = Notes()
    (ax,) = _panels(fig, 1)
    currents = []
    fitted = False
    for s in series:
        arrays = _fp_arrays(s, notes)
        if arrays is None:
            continue
        current, voltage = arrays
        currents.append(current)
        _plot(ax, current, voltage, s)
        fit = _fp_fit(s)
        if options.get("show_fit") and fit is not None:
            finite = current[np.isfinite(current)]
            if len(finite):
                i = np.linspace(finite.min(), finite.max(), 50)
                ax.plot(i, fit[0] * i + fit[1], color=s.color,
                        linewidth=0.9, alpha=0.7, zorder=1)
                fitted = True
    if options.get("show_fit") and series and not fitted:
        notes.add("No saved fit on the ticked runs.")
    logged = options.get("log_axes") and _log_axes(
        ax, "x", currents, "current", notes, "A")
    if logged:
        _log_axes(ax, "y", [s.run.series("voltage_V") for s in series
                            if s.run.series("voltage_V") is not None],
                  "voltage", notes, "V")
    ax.set_xlabel("Current")
    ax.set_ylabel("Voltage")
    if not logged:
        _eng_axis(ax.xaxis, "A")
        _eng_axis(ax.yaxis, "V")
    _finish(fig, series, [ax])
    return notes.lines


def draw_fp_residuals(fig, series, options):
    notes = Notes()
    (ax,) = _panels(fig, 1)
    ax.axhline(0, color=style.AXIS, linewidth=0.9, zorder=1)
    for s in series:
        arrays = _fp_arrays(s, notes)
        fit = _fp_fit(s)
        if arrays is None:
            continue
        if fit is None:
            notes.add(f"{s.label}: no saved fit; not drawn.")
            continue
        current, voltage = arrays
        _plot(ax, current, voltage - (fit[0] * current + fit[1]), s)
    if options.get("log_x"):
        _log_axes(ax, "x", [s.run.series("current_A") for s in series
                            if s.run.series("current_A") is not None],
                  "current", notes, "A")
    else:
        _eng_axis(ax.xaxis, "A")
    ax.set_xlabel("Current")
    ax.set_ylabel("Voltage minus the saved fit")
    _eng_axis(ax.yaxis, "V")
    _finish(fig, series, [ax])
    return notes.lines


def _fp_against_current(fig, series, options, key, unit, ylabel):
    notes = Notes()
    (ax,) = _panels(fig, 1)
    currents = []
    for s in series:
        current = s.run.series("current_A")
        y = s.run.series(key)
        if current is None or y is None:
            notes.add(f"{s.label}: no {key} column; not drawn.")
            continue
        currents.append(current)
        _plot(ax, current, y, s)
    if not (options.get("log_x")
            and _log_axes(ax, "x", currents, "current", notes, "A")):
        _eng_axis(ax.xaxis, "A")
    ax.set_xlabel("Current")
    ax.set_ylabel(ylabel)
    _eng_axis(ax.yaxis, unit)
    _finish(fig, series, [ax])
    return notes.lines


def draw_fp_point_resistance(fig, series, options):
    return _fp_against_current(fig, series, options,
                               "resistance_at_point_ohm", "\u03a9",
                               "V/I at each current")


def draw_fp_offset(fig, series, options):
    return _fp_against_current(fig, series, options, "cancelled_offset_V",
                               "V", "Offset cancelled by reversal")


def draw_fp_sheet_trend(fig, series, options):
    notes = Notes()
    _trend(fig, series, "sheet_resistance_ohm_sq", "\u03a9/\u25a1",
           "Sheet resistance", notes)
    return notes.lines


# ------------------------------------------------------------------
# Van der Pauw and Hall: readings at +I and -I
# ------------------------------------------------------------------
#: Filled for +I, open for -I. The shape difference carries polarity, so
#: the run keeps its colour for both.
POLARITIES = (("pos", "+I", True), ("neg", "\u2212I", False))


def _marker(color, filled, shape="o"):
    return {"marker": shape, "markersize": style.MARKER_SIZE + 0.5,
            "markeredgewidth": 1.2,
            "markerfacecolor": color if filled else style.SURFACE,
            "markeredgecolor": color}


def _polarity_proxies(shape="o"):
    return [(Line2D([], [], linestyle="none",
                    **_marker(style.INK_MUTED, filled, shape)), label)
            for _key, label, filled in POLARITIES]


def _by_polarity(fig, series, options, polarity_key, key, unit, ylabel):
    notes = Notes()
    (ax,) = _panels(fig, 1)
    magnitude = options.get("magnitude")
    for s in series:
        polarity = s.run.readings.get(polarity_key)
        point = s.run.series("point")
        y = s.run.series(key)
        if polarity is None or point is None or y is None:
            notes.add(f"{s.label}: no {key} readings by polarity; not "
                      f"drawn.")
            continue
        blanks = int((~np.isfinite(y)).sum())
        if blanks:
            notes.add(f"{s.label}: {blanks} reading(s) failed and are left "
                      f"out.")
        values = np.abs(y) if magnitude else y
        first = True
        for name, _label, filled in POLARITIES:
            mask = np.array([str(p) == name for p in polarity])
            if not mask.any():
                continue
            (line,) = ax.plot(point[mask], values[mask], color=s.color,
                              linewidth=style.LINE_WIDTH,
                              label=s.label if first else None,
                              **_marker(s.color, filled))
            line.set_gid(f"{s.label} ({_label})")
            first = False
    ax.set_xlabel("Reading number within the polarity")
    ax.xaxis.get_major_locator().set_params(integer=True)
    ax.set_ylabel(f"|{ylabel}|" if magnitude else ylabel)
    _eng_axis(ax.yaxis, unit)
    _finish(fig, series, [ax], proxies=_polarity_proxies())
    return notes.lines


def draw_vdp_readings(fig, series, options):
    return _by_polarity(fig, series, options, "polarity", "resistance_ohm",
                        "\u03a9", "Resistance per reading")


def draw_hall_readings(fig, series, options):
    return _by_polarity(fig, series, options, "current_polarity",
                        "voltage_V", "V", "Voltage per reading")


def _categories(series, key_of):
    """Ordered category labels, and each series' x offset within one.

    Runs of the same category from different samples are spread a
    little either side of the tick rather than drawn on top of each
    other.
    """
    order = []
    for s in series:
        key = key_of(s)
        if key is not None and key not in order:
            order.append(key)
    order.sort()
    samples = []
    for s in series:
        sample = s.run.text("sample_label") or s.file.sample
        if sample not in samples:
            samples.append(sample)
    width = 0.5
    step = width / max(len(samples), 1)
    offsets = {sample: (i - (len(samples) - 1) / 2) * step
               for i, sample in enumerate(samples)}
    return order, offsets


def draw_vdp_positions(fig, series, options):
    notes = Notes()
    (ax,) = _panels(fig, 1)
    order, offsets = _categories(series, lambda s: s.run.number("position"))
    # The average first: each run's legend entry is its first marker,
    # and a filled circle reads as "this run" where a triangle would
    # read as "this run's +I".
    shapes = (("R_ave_ohm", "R average", "o", True),
              ("R_pos_ohm", "R at +I", "^", False),
              ("R_neg_ohm", "R at \u2212I", "v", False))
    for s in series:
        position = s.run.number("position")
        if position is None:
            notes.add(f"{s.label}: no position; not drawn.")
            continue
        sample = s.run.text("sample_label") or s.file.sample
        x = order.index(position) + offsets[sample]
        first = True
        for key, label, shape, filled in shapes:
            value = s.run.number(key)
            if value is None:
                continue
            (line,) = ax.plot([x], [value], linestyle="none",
                              label=s.label if first else None,
                              **_marker(s.color, filled, shape))
            line.set_gid(f"{s.label}: {label}")
            first = False
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([f"Pos{int(p)}" for p in order])
    ax.set_xlim(-0.6, max(len(order) - 0.4, 0.6))
    ax.set_xlabel("Switch-box position")
    ax.set_ylabel("Resistance")
    _eng_axis(ax.yaxis, "\u03a9")
    proxies = [(Line2D([], [], linestyle="none",
                       **_marker(style.INK_MUTED, filled, shape)), label)
               for _key, label, shape, filled in shapes]
    _finish(fig, series, [ax], proxies=proxies)
    return notes.lines


def draw_hall_voltages(fig, series, options):
    notes = Notes()
    (ax,) = _panels(fig, 1)
    magnitude = options.get("magnitude")

    def category(s):
        position = s.run.number("position")
        sign = s.run.text("b_polarity") or s.run.text("field_sign")
        if position is None or not sign:
            return None
        # "+" sorts before "-", which is the order the operator measures.
        return (int(position), sign)

    order, offsets = _categories(series, category)
    ax.axhline(0, color=style.AXIS, linewidth=0.9, zorder=1)
    for s in series:
        key = category(s)
        if key is None:
            notes.add(f"{s.label}: no position or field polarity; not "
                      f"drawn.")
            continue
        sample = s.run.text("sample_label") or s.file.sample
        x = order.index(key) + offsets[sample]
        first = True
        for column, (_name, label, filled) in zip(("V_plus_V", "V_minus_V"),
                                                  POLARITIES):
            value = s.run.number(column)
            if value is None:
                continue
            if magnitude:
                value = abs(value)
            (line,) = ax.plot([x], [value], linestyle="none",
                              label=s.label if first else None,
                              **_marker(s.color, filled))
            line.set_gid(f"{s.label}: V at {label}")
            first = False
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([f"Pos{p} B{sign}" for p, sign in order])
    ax.set_xlim(-0.6, max(len(order) - 0.4, 0.6))
    ax.set_xlabel("Position and field polarity")
    ax.set_ylabel("|Mean voltage|" if magnitude else "Mean voltage")
    _eng_axis(ax.yaxis, "V")
    _finish(fig, series, [ax], proxies=_polarity_proxies())
    return notes.lines


# ------------------------------------------------------------------
# the registry
# ------------------------------------------------------------------
def _kinds(*kinds):
    return frozenset(k.key for k in kinds)


VIEWS: tuple[View, ...] = (
    View("iv_curves", "I–V curves", _kinds(detect.IV_SWEEP),
         draw_iv_curves, (Option("show_fit", "Show saved fit", True),),
         "Current against voltage, whichever was sourced."),
    View("iv_log", "|I| against V (log)", _kinds(detect.IV_SWEEP),
         draw_iv_log, (),
         "Leakage and turn-on: the magnitude of the current on a log "
         "axis."),
    View("iv_point_resistance", "V/I at each point",
         _kinds(detect.IV_SWEEP), draw_iv_point_resistance,
         (Option("log_y", "Log y-axis"),),
         "Where a device stops being ohmic."),
    View("iv_resistance_trend", "Fitted resistance by run",
         _kinds(detect.IV_SWEEP), draw_iv_resistance_trend, (),
         "The saved fit of each run, by cycle within one periodic run or "
         "by time otherwise."),
    View("fs_trace", "Measured against time", _kinds(detect.FIXED_SOURCE),
         draw_fs_trace,
         (Option("show_temperature", "Stage temperature panel", True),),
         "The held level's response, with compliance trips marked."),
    View("fs_sourced", "Sourced against time", _kinds(detect.FIXED_SOURCE),
         draw_fs_sourced,
         (Option("show_temperature", "Stage temperature panel", False),),
         "The source readback: whether the level really held."),
    View("fs_interval", "Sampling interval", _kinds(detect.FIXED_SOURCE),
         draw_fs_interval, (),
         "Time between samples against the requested interval."),
    View("fs_read_time", "Time per reading", _kinds(detect.FIXED_SOURCE),
         draw_fs_read_time, (),
         "How long each reading took the instrument."),
    View("fp_vi", "V against I", _kinds(detect.OSSILA_4PP), draw_fp_vi,
         (Option("show_fit", "Show saved fit", True),
          Option("log_axes", "Log axes")),
         "The averaged reading at each current, with the fit the sheet "
         "resistance came from."),
    View("fp_residuals", "Residuals from the fit",
         _kinds(detect.OSSILA_4PP), draw_fp_residuals,
         (Option("log_x", "Log current axis"),),
         "Curvature or a bad point the straight line hides."),
    View("fp_point_resistance", "V/I at each current",
         _kinds(detect.OSSILA_4PP), draw_fp_point_resistance,
         (Option("log_x", "Log current axis", True),),
         "Where the sample stops being ohmic, or the reading hits its "
         "floor."),
    View("fp_offset", "Cancelled offset", _kinds(detect.OSSILA_4PP),
         draw_fp_offset, (Option("log_x", "Log current axis", True),),
         "The thermal or contact offset that reversal averaging removed."),
    View("fp_sheet_trend", "Sheet resistance by run",
         _kinds(detect.OSSILA_4PP), draw_fp_sheet_trend, (),
         "The saved sheet resistance of each run."),
    View("vdp_positions", "Resistance by position",
         _kinds(detect.VAN_DER_PAUW), draw_vdp_positions, (),
         "R at +I, at \u2212I and their average for each switch-box "
         "position."),
    View("vdp_readings", "Readings by polarity",
         _kinds(detect.VAN_DER_PAUW), draw_vdp_readings, (),
         "Every reading, to see settling within a polarity block."),
    View("hall_voltages", "Voltages by position and field",
         _kinds(detect.HALL), draw_hall_voltages,
         (Option("magnitude", "Magnitudes"),),
         "Mean V at +I and \u2212I for each position and field polarity."),
    View("hall_readings", "Readings by polarity", _kinds(detect.HALL),
         draw_hall_readings, (Option("magnitude", "Magnitudes"),),
         "Every reading, to see settling within a polarity block."),
)


def views_for(series: list[Series]) -> list[View]:
    """The views that can draw every one of these runs."""
    kinds = {s.file.kind.key for s in series}
    if not kinds:
        return []
    return [v for v in VIEWS if kinds <= v.kinds]


def render(fig: Figure, view: View | None, series: list[Series],
           options: dict[str, bool] | None = None) -> list[str]:
    """Clear `fig` and draw `series` with `view`. Returns the notes."""
    fig.clear()
    fig.set_facecolor(style.SURFACE)
    if view is None or not series:
        _message(fig, "Tick runs on the left to plot them."
                 if not series else
                 "No view draws every ticked run: they come from "
                 "different experiments.")
        return []
    chosen = {o.key: o.default for o in view.options}
    chosen.update(options or {})
    try:
        return view.draw(fig, series, chosen)
    finally:
        fig.set_layout_engine("constrained")


def _message(fig: Figure, text: str) -> None:
    fig.text(0.5, 0.5, text, ha="center", va="center",
             color=style.INK_MUTED, fontsize=10, wrap=True)

