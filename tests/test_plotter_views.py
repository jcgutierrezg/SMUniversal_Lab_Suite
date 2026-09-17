"""
The plotter's views and details, drawn headless onto a bare `Figure`.
"""
import numpy as np
import pytest
from matplotlib.figure import Figure
from plotter_files import (
    FIXED_TITLE,
    FOURPP_TITLE,
    HALL_TITLE,
    VDP_TITLE,
    fixed_run,
    fourpp_run,
    hall_run,
    iv_run,
    stored,
    vdp_run,
)

from smuniversal_lab_suite.plotter import describe, style, views
from smuniversal_lab_suite.plotter.session import Session


def _series(files):
    session = Session()
    for f in files:
        session.add(f)
    for _f, run in session.visible_runs():
        session.tick(run.record_id)
    return session.ticked_series()


def _fixed(runs, path="filmA_fixed_source.csv"):
    return stored(runs, title=FIXED_TITLE, path=path)


def _draw(view_key, series, **options):
    fig = Figure()
    view = next(v for v in views.VIEWS if v.key == view_key)
    notes = views.render(fig, view, series, options)
    return fig, notes


def _files_for(kind_key):
    """Two runs of each experiment, built by the real file builder."""
    if kind_key == "iv_sweep":
        return stored([iv_run("a"), iv_run("b", minutes=1)])
    if kind_key == "fixed_source":
        return _fixed([fixed_run("a", temperature=21.0),
                       fixed_run("b", minutes=1)])
    if kind_key == "ossila_4pp":
        return stored([fourpp_run("a"), fourpp_run("b", minutes=1)],
                      title=FOURPP_TITLE, path="wafer_ossila_4pp.csv")
    if kind_key == "vanderpauw":
        return stored([vdp_run(1), vdp_run(2, minutes=1)], title=VDP_TITLE,
                      path="bar_vanderpauw.csv")
    if kind_key == "hall":
        return stored([hall_run(1, "+"), hall_run(1, "-", minutes=1)],
                      title=HALL_TITLE, path="bar_hall.csv")
    raise AssertionError(kind_key)


CASES = [(v.key, next(iter(v.kinds))) for v in views.VIEWS]


@pytest.mark.parametrize("view_key, kind_key", CASES,
                         ids=[k for k, _ in CASES])
def test_every_view_draws_one_axis_per_panel(check, view_key, kind_key):
    series = _series([_files_for(kind_key)])
    fig, notes = _draw(view_key, series)
    check("something drawn", fig.axes and any(ax.lines for ax in fig.axes))
    boxes = [tuple(np.round(ax.get_position().bounds, 6)) for ax in fig.axes]
    check("no twin axes: every panel has its own box",
          len(boxes) == len(set(boxes)), boxes)
    check("notes are text", all(isinstance(n, str) for n in notes))
    check("nothing was left out of clean data", notes == [] or
          view_key in ("iv_log", "iv_point_resistance", "fs_sourced"),
          notes)


@pytest.mark.parametrize("kind_key", sorted({k for _, k in CASES}))
def test_every_experiment_offers_its_views(check, kind_key):
    series = _series([_files_for(kind_key)])
    offered = {v.key for v in views.views_for(series)}
    expected = {v.key for v in views.VIEWS if kind_key in v.kinds}
    check("all of its own, none of another's", offered == expected,
          (offered, expected))


def test_views_are_offered_only_for_their_experiment(check):
    iv = _series([stored([iv_run()])])
    fs = _series([_fixed([fixed_run()])])
    check("iv views for iv, then the comparison",
          [v.key for v in views.views_for(iv)]
          == [v.key for v in views.VIEWS if v.key.startswith("iv")]
          + ["compare_values"])
    check("fixed source views for fixed source",
          all(v.key.startswith(("fs", "compare"))
              for v in views.views_for(fs)))
    check("only the comparison draws both at once",
          [v.key for v in views.views_for(iv + fs)] == ["compare_values"])


# ------------------------------------------------------------------
# comparing across files and experiments
# ------------------------------------------------------------------
def _compare(series, **options):
    return _draw("compare_values", series, **options)


def _points(fig):
    return [line for line in fig.axes[0].lines if line.get_gid()]


def test_the_value_list_offers_what_the_runs_hold(check):
    iv = stored([iv_run()])
    fp = stored([fourpp_run()], title=FOURPP_TITLE,
                path="wafer_ossila_4pp.csv")
    series = _series([iv, fp])
    values = dict(views.quantity_values(series))
    check("curated labels", values.get("resistance_ohm")
          == "Fitted resistance", values)
    check("a 4PP-only value is offered too",
          "sheet_resistance_ohm_sq" in values, values)
    check("counts are not quantities",
          not {"meas_number", "points_returned"} & set(values), values)
    check("text settings are not offered", "mode" not in values)


def test_one_value_compared_across_experiments(check):
    iv = stored([iv_run(resistance=1000.0)])
    fp = stored([fourpp_run(resistance=1010.0, minutes=5)],
                title=FOURPP_TITLE, path="wafer_ossila_4pp.csv")
    fig, notes = _compare(_series([iv, fp]), quantity="resistance_ohm")
    ys = sorted(line.get_ydata()[0] for line in _points(fig))
    check("one point per run", ys == [1000.0, 1010.0], ys)
    check("with its unit on the axis",
          fig.axes[0].yaxis.get_major_formatter().unit == "Ω")
    check("nothing left out", notes == [], notes)


def test_a_run_without_the_value_is_named(check):
    iv = stored([iv_run()])
    fp = stored([fourpp_run(minutes=5)], title=FOURPP_TITLE,
                path="wafer_ossila_4pp.csv")
    fig, notes = _compare(_series([iv, fp]),
                          quantity="sheet_resistance_ohm_sq")
    check("one point", len(_points(fig)) == 1)
    check("the IV run is named as missing",
          any("filmA" in n and "No saved" in n for n in notes), notes)


def test_a_file_result_is_one_point_per_file(check):
    from smuniversal_lab_suite.core.run_store import build_sample_csv
    from smuniversal_lab_suite.plotter.reader import parse

    text = build_sample_csv("bar", [vdp_run(1), vdp_run(2, minutes=1)],
                            VDP_TITLE,
                            calculated={"Rs_ohm_per_sq": "4530.9"})
    series = _series([parse(text, "bar_vanderpauw.csv")])
    check("offered", "file:Rs_ohm_per_sq"
          in dict(views.quantity_values(series)))
    fig, _ = _compare(series, quantity="file:Rs_ohm_per_sq")
    points = _points(fig)
    check("one point for the file, not one per run", len(points) == 1,
          len(points))
    check("named after the file",
          points and points[0].get_gid() == "bar_vanderpauw.csv")
    check("with the unit its name spells",
          fig.axes[0].yaxis.get_major_formatter().unit == "Ω/□")


def test_mixed_units_are_not_given_one(check):
    voltage = iv_run(mode="voltage")
    current = iv_run(mode="current", minutes=1)
    fig, notes = _compare(_series([stored([voltage, current])]),
                          quantity="start")
    check("said", any("different units" in n for n in notes), notes)
    check("and the axis is unitless",
          fig.axes[0].yaxis.get_major_formatter().unit == "")


def test_against_sample_and_temperature(check):
    a = stored([iv_run(minutes=0, stage_temp_C=20.0)])
    b = stored([fixed_run(minutes=1, temperature=30.0)], title=FIXED_TITLE,
               path="filmA_fixed_source.csv")
    series = _series([a, b])
    fig, notes = _compare(series, quantity="compliance",
                          against="temperature")
    xs = sorted(line.get_xdata()[0] for line in _points(fig))
    check("a run setting, and a per-reading log averaged",
          xs == pytest.approx([20.0, 30.25]), xs)

    fig, _ = _compare(series, quantity="compliance", against="sample")
    ticks = [t.get_text() for t in fig.axes[0].get_xticklabels()]
    check("samples as categories", ticks == ["filmA"], ticks)


def test_an_unknown_choice_falls_back_to_the_first(check):
    series = _series([stored([iv_run()])])
    view = next(v for v in views.VIEWS if v.key == "compare_values")
    choice = view.choices[0]
    values, current = views.choice_values(view, choice, series, "gone")
    check("the first value", current == values[0][0], (current, values))


def test_nothing_ticked_draws_a_message_not_an_empty_axis(check):
    fig = Figure()
    views.render(fig, None, [])
    check("no axes", fig.axes == [])
    check("a message", fig.texts and "Tick runs" in fig.texts[0].get_text())


def test_the_fit_is_redrawn_in_the_runs_own_convention(check):
    """Current-sourced: V = R*I + b, so on I-against-V it is I = (V-b)/R."""
    run = iv_run(mode="current", resistance=500.0, fit_intercept=0.01)
    series = _series([stored([run])])[0]
    v, i = views._iv_fit_current(series, np.array([-1.0, 1.0]))
    check("current from the inverted fit",
          np.allclose(i, (v - 0.01) / 500.0), (v, i))

    run = iv_run(mode="voltage", resistance=500.0, fit_intercept=0.01)
    series = _series([stored([run])])[0]
    v, i = views._iv_fit_current(series, np.array([-1.0, 1.0]))
    check("voltage-sourced fit used as it is",
          np.allclose(i, v / 500.0 + 0.01), (v, i))


def test_a_zero_current_on_the_log_view_is_counted_not_hidden(check):
    run = iv_run(points=11)       # the middle point is exactly 0 V, 0 A
    _fig, notes = _draw("iv_log", _series([stored([run])]))
    check("reported", any("0 A cannot be shown" in n for n in notes), notes)


def test_compliance_trips_are_marked_and_named(check):
    run = fixed_run(tripped=(2, 4))
    fig, _notes = _draw("fs_trace", _series([_fixed([run])]))
    ax = fig.axes[0]
    trips = [line for line in ax.lines if line.get_marker() == "x"]
    check("one marker series", len(trips) == 1)
    check("at the tripped samples", len(trips[0].get_xdata()) == 2)
    check("in the status colour", trips[0].get_color() == style.CRITICAL)
    legend = ax.get_legend()
    check("and named in a legend, even for one run",
          legend is not None and "compliance tripped"
          in [t.get_text() for t in legend.get_texts()])


def test_temperature_gets_its_own_panel_sharing_time(check):
    run = fixed_run(temperature=25.0)
    fig, _ = _draw("fs_trace", _series([_fixed([run])]))
    check("two panels", len(fig.axes) == 2)
    check("sharing the time axis",
          fig.axes[0].get_shared_x_axes().joined(fig.axes[0], fig.axes[1]))

    fig, _ = _draw("fs_trace", _series([_fixed([run])]),
                   show_temperature=False)
    check("one panel when switched off", len(fig.axes) == 1)


def test_different_measured_quantities_get_different_panels(check):
    runs = [fixed_run("i", measured="current"),
            fixed_run("v", measured="voltage", minutes=1)]
    fig, notes = _draw("fs_trace", _series([_fixed(runs)]))
    check("two panels", len(fig.axes) == 2, len(fig.axes))
    check("and the reason given",
          any("different quantities" in n for n in notes), notes)


def test_many_runs_have_no_legend_of_names(check):
    runs = [iv_run(f"r{i}", minutes=i)
            for i in range(len(style.CATEGORICAL) + 1)]
    fig, _ = _draw("iv_curves", _series([stored(runs)]))
    ax = fig.axes[0]
    check("no legend", ax.get_legend() is None)
    check("the colour rule is stated", "coloured by time" in ax.get_title(
        loc="left"))


def test_the_trend_joins_cycles_but_not_separate_runs(check):
    cycles = [iv_run(f"c{i}", minutes=i, cycle=i + 1, run_id="periodic")
              for i in range(3)]
    fig, _ = _draw("iv_resistance_trend", _series([stored(cycles)]))
    check("joined across cycles",
          any(len(line.get_xdata()) == 3 for line in fig.axes[0].lines))

    separate = [iv_run(f"s{i}", minutes=i, run_id=f"run{i}")
                for i in range(3)]
    fig, _ = _draw("iv_resistance_trend", _series([stored(separate)]))
    check("not joined across runs",
          all(len(line.get_xdata()) == 1 for line in fig.axes[0].lines))


def test_4pp_residuals_of_a_perfect_fit_are_zero(check):
    fig, notes = _draw("fp_residuals", _series([_files_for("ossila_4pp")]))
    runs = [line for line in fig.axes[0].lines if line.get_gid()]
    check("both runs", len(runs) == 2)
    check("on zero", all(np.allclose(line.get_ydata(), 0.0, atol=1e-15)
                         for line in runs))


def test_a_log_axis_is_refused_rather_than_hiding_points(check):
    run = fourpp_run()
    series = _series([stored([run], title=FOURPP_TITLE,
                             path="wafer_ossila_4pp.csv")])
    fig, notes = _draw("fp_offset", series, log_x=True)
    check("current is positive, so the current axis is log",
          fig.axes[0].get_xscale() == "log")

    negative = fourpp_run()
    negative.readings[0]["current_A"] = -1e-6
    series = _series([stored([negative], title=FOURPP_TITLE,
                             path="wafer_ossila_4pp.csv")])
    fig, notes = _draw("fp_offset", series, log_x=True)
    check("a negative current keeps it linear",
          fig.axes[0].get_xscale() == "linear")
    check("and says why", any("stays linear" in n for n in notes), notes)


def test_vdp_positions_are_named_and_their_shapes_explained(check):
    fig, _ = _draw("vdp_positions", _series([_files_for("vanderpauw")]))
    ax = fig.axes[0]
    ticks = [label.get_text() for label in ax.get_xticklabels()]
    check("one tick per position", ticks == ["Pos1", "Pos2"], ticks)
    legend = [t.get_text() for t in ax.get_legend().get_texts()]
    check("the marker shapes are in the legend",
          {"R at +I", "R average"} <= set(legend), legend)


def test_polarity_is_a_shape_not_a_colour(check):
    fig, _ = _draw("vdp_readings", _series([_files_for("vanderpauw")]))
    lines = [line for line in fig.axes[0].lines if line.get_gid()]
    by_run = {}
    for line in lines:
        by_run.setdefault(line.get_color(), []).append(
            line.get_markerfacecolor())
    check("each run drawn in one colour for both polarities",
          all(len(faces) == 2 for faces in by_run.values()), by_run)
    check("filled for +I, open for −I",
          all(faces[1] == style.SURFACE and faces[0] != style.SURFACE
              for faces in by_run.values()), by_run)
    legend = [t.get_text() for t in fig.axes[0].get_legend().get_texts()]
    check("both named", {"+I", "−I"} <= set(legend), legend)


def test_hall_voltages_by_position_and_field(check):
    series = _series([_files_for("hall")])
    fig, _ = _draw("hall_voltages", series)
    ticks = [label.get_text() for label in fig.axes[0].get_xticklabels()]
    check("position and field on the axis", ticks == ["Pos1 B+", "Pos1 B-"],
          ticks)
    fig, _ = _draw("hall_voltages", series, magnitude=True)
    values = [y for line in fig.axes[0].lines if line.get_gid()
              for y in line.get_ydata()]
    check("magnitudes are all positive", values and min(values) > 0, values)


# ------------------------------------------------------------------
# details
# ------------------------------------------------------------------
@pytest.mark.parametrize("value, unit, text", [
    (1e-4, "A", "100 µA"), (1500.0, "Ω", "1.5 kΩ"),
    (0.0, "V", "0 V"), (21.0, "", "21"), (0.9999994, "", "0.9999994"),
])
def test_engineering_notation(value, unit, text):
    assert describe.eng(value, unit) == text


def test_checks_state_what_the_file_records(check):
    run = iv_run(points_requested=21, compliance_applied=0.02,
                 bias_gap_s=0.25)
    f = stored([run])
    found = describe.run_checks(f, f.runs[0])
    check("short sweep", any("11 of 21 points" in c for c in found), found)
    check("compliance changed",
          any("Compliance applied" in c for c in found), found)
    check("bias interrupted", any("interrupted" in c for c in found), found)


def test_no_check_on_a_clean_run(check):
    f = stored([iv_run()])
    check("none", describe.run_checks(f, f.runs[0]) == [],
          describe.run_checks(f, f.runs[0]))


def test_fixed_source_checks(check):
    run = fixed_run(samples=6, overruns=3, samples_collected=5,
                    ended_by="operator", tripped=(1,))
    f = _fixed([run])
    found = describe.run_checks(f, f.runs[0])
    for phrase in ("3 sample(s) landed late", "1 compliance trip",
                   "5 of 6 samples", "Ended by operator"):
        check(phrase, any(phrase in c for c in found), found)


def test_compare_marks_differences_with_a_tolerance(check):
    a = iv_run("a", nplc=1.0)
    b = iv_run("b", nplc=1.0 + 1e-12, minutes=1, sensing="2-wire")
    f = stored([a, b])
    rows = {key: (label, differs) for key, label, _texts, differs
            in describe.compare_rows([(f, r) for r in f.runs])}
    check("sensing differs", rows["sensing"] == ("Sensing", True))
    check("a float that only differs by rounding does not",
          rows["nplc"][1] is False, rows["nplc"])
    check("dataset differs", rows["dataset"][1] is True)


def test_the_default_value_is_one_every_run_holds(check):
    iv = stored([iv_run()])
    fs = stored([fixed_run(minutes=1)], title=FIXED_TITLE,
                path="filmA_fixed_source.csv")
    series = _series([iv, fs])
    first = views.quantity_values(series)[0][0]
    check("held by both", all(s.run.number(first) is not None
                              for s in series), first)


def test_a_setting_one_experiment_lacks_is_not_a_difference(check):
    iv = stored([iv_run(nplc=1.0)])
    fp = stored([fourpp_run(minutes=1)], title=FOURPP_TITLE,
                path="wafer_ossila_4pp.csv")
    series = _series([iv, fp])
    rows = {key: differs for key, _label, _texts, differs
            in describe.compare_rows([(s.file, s.run) for s in series])}
    check("an IV-only setting is not marked", rows.get("nplc") is False,
          rows.get("nplc"))
    check("a shared setting that disagrees still is",
          rows.get("dataset") is True, rows.get("dataset"))


def test_the_trace_as_percent_change(check):
    a = fixed_run("a", measured="current")
    b = fixed_run("b", measured="voltage", minutes=1)
    series = _series([_fixed([a, b])])
    fig, notes = _draw("fs_trace", series, scale="first",
                       show_temperature=False)
    check("current and voltage share one panel as percentages",
          len(fig.axes) == 1, len(fig.axes))
    first = [line for line in fig.axes[0].lines if line.get_gid()][0]
    check("the first reading is 0 %", first.get_ydata()[0] == 0.0,
          first.get_ydata()[:2])
    check("the reference is stated",
          any("0 % is" in n for n in notes), notes)
    check("labelled as change", "first reading"
          in fig.axes[0].get_ylabel())

    fig, _ = _draw("fs_trace", series)
    check("absolute by default: one panel per quantity", len(fig.axes) == 2)

    fig, _ = _draw("fs_sourced", series, scale="first")
    check("the source readback is never rescaled",
          "%" not in fig.axes[0].get_ylabel())
