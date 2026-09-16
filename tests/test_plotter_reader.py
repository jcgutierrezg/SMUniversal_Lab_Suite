"""
The plotter's reader, against text the real file builders produce.

Files are built with `core.run_store.build_sample_csv` and
`build_sample_summary` rather than typed out, so a change to what the
suite writes reaches these tests instead of leaving them passing against
a layout nobody saves any more. The few hand-edited cases start from a
built file and change one thing.
"""
import math

import pytest

from smuniversal_lab_suite.core.run_store import (
    FILE_SCHEMA,
    Run,
    build_sample_csv,
    build_sample_summary,
)
from smuniversal_lab_suite.plotter.detect import HALL, IV_SWEEP, SUMMARY
from smuniversal_lab_suite.plotter.reader import (
    UnreadableFile,
    load,
    parse,
    to_number,
)


def _iv_run(dataset, slope, points=5, record_id=None):
    readings = [{"point": i + 1, "voltage_V": 0.1 * i,
                 "current_A": 0.1 * i * slope}
                for i in range(points)]
    return Run("filmA", {"meas_number": 1, "dataset": dataset,
                         "mode": "source_voltage", "points_returned": points,
                         "fitted": "yes", "sweep_kind": "hardware",
                         "resistance_ohm": 1 / slope},
               readings, record_id=record_id)


def _iv_text(runs, calculated=None):
    return build_sample_csv("filmA", runs, "IV sweep", calculated)


def _replace_header(text, key, value):
    lines = text.split("\n")
    out = []
    for line in lines:
        if line.startswith(f"# {key}: "):
            if value is not None:
                out.append(f"# {key}: {value}")
        else:
            out.append(line)
    return "\n".join(out)


def test_rows_are_grouped_back_into_runs(check):
    text = _iv_text([_iv_run("fwd", 1e-3), _iv_run("rev", 2e-3, points=3)])
    stored = parse(text, "filmA_iv_sweep.csv")

    check("the experiment is recognised", stored.kind is IV_SWEEP)
    check("two runs", len(stored.runs) == 2, len(stored.runs))
    fwd, rev = stored.runs
    check("labels are the datasets", (fwd.label, rev.label) == ("fwd", "rev"))
    check("each run keeps its own readings", (len(fwd), len(rev)) == (5, 3))
    check("per-run values are settings",
          fwd.number("resistance_ohm") == pytest.approx(1000.0))
    check("text settings stay text", fwd.text("mode") == "source_voltage")
    check("readings are numeric arrays",
          fwd.series("current_A") is not None
          and fwd.series("current_A")[4] == pytest.approx(4e-4))
    check("the sample comes from the header", stored.sample == "filmA")
    check("the schema is read", stored.schema == FILE_SCHEMA)


def test_the_calculated_block_is_kept_apart_from_the_file_details(check):
    text = _iv_text([_iv_run("fwd", 1e-3)],
                    calculated={"resistance_ohm": "1000.2"})
    stored = parse(text, "filmA_iv_sweep.csv")
    check("calculated", stored.calculated == {"resistance_ohm": "1000.2"},
          stored.calculated)
    check("not mixed into the details",
          "resistance_ohm" not in stored.header)
    check("details present", "build_id" in stored.header
          and "save_id" in stored.header)


def test_an_empty_cell_is_nan_in_its_own_position(check):
    run = _iv_run("fwd", 1e-3)
    run.readings[2]["current_A"] = ""
    stored = parse(_iv_text([run]))
    current = stored.runs[0].series("current_A")
    check("still numeric", current is not None)
    check("NaN where the blank was", math.isnan(current[2]), current)
    check("neighbours untouched",
          current[1] == pytest.approx(1e-4) and current[3] == pytest.approx(3e-4),
          current)
    check("nothing dropped", len(current) == 5)


def test_a_declared_reading_column_that_never_varies_is_still_a_reading(check):
    readings = [{"point": i + 1, "current_polarity": "pos", "voltage_V": 0.1,
                 "current_A": 1e-4, "error": ""} for i in range(3)]
    run = Run("bar", {"position": 1, "V_plus_V": 0.1, "V_minus_V": -0.1},
              readings)
    stored = parse(build_sample_csv("bar", [run],
                                    "Hall effect - carrier density and "
                                    "mobility"))
    check("hall", stored.kind is HALL)
    only = stored.runs[0]
    check("`error` is a reading", "error" in only.readings, list(only.readings))
    check("the constant voltage is a reading too",
          "voltage_V" in only.readings)
    check("position is a setting", only.number("position") == 1.0)


def test_repeated_column_names_are_both_kept(check):
    readings = [{"time_s": 0.1 * i, "compliance": "no"} for i in range(3)]
    run = Run("s", {"compliance": 0.01}, readings)
    stored = parse(build_sample_csv("s", [run], "Fixed sourcing vs time"))
    check("columns kept apart",
          stored.columns.count("compliance") == 1
          and "compliance#2" in stored.columns, stored.columns)
    only = stored.runs[0]
    check("the limit is the setting", only.number("compliance") == 0.01)
    check("the per-reading flag is its own column",
          list(only.readings.get("compliance#2", [])) == ["no"] * 3)
    check("and the file says so",
          any("appears 2 times" in w for w in stored.warnings),
          stored.warnings)


def test_line_endings_do_not_matter(check):
    text = _iv_text([_iv_run("fwd", 1e-3)])
    lf = parse(text)
    crlf = parse(text.replace("\n", "\r\n"))
    check("same runs", len(lf.runs) == len(crlf.runs) == 1)
    check("same readings",
          list(lf.runs[0].series("voltage_V"))
          == list(crlf.runs[0].series("voltage_V")))
    check("same header", lf.header == crlf.header)


def test_a_quoted_newline_does_not_split_a_row(check):
    run = _iv_run("fwd", 1e-3, points=2)
    run.metadata["ended_detail"] = "line one\nline two"
    stored = parse(_iv_text([run]))
    check("one run of two readings",
          len(stored.runs) == 1 and len(stored.runs[0]) == 2)
    check("the text survives",
          stored.runs[0].text("ended_detail") == "line one\nline two")


def test_the_summary_is_read_as_rows(check):
    text = build_sample_summary("bar", "smp-1", [
        ("Van der Pauw - sheet resistance",
         [("Sheet resistance", "4530.9", "Ω/□", "res-1")]),
        ("Hall effect - carrier density and mobility", None),
    ])
    stored = parse(text, "bar_summary.csv")
    check("summary", stored.kind is SUMMARY and stored.is_summary)
    check("rows, not runs", len(stored.rows) == 2 and not stored.runs)
    check("not calculated is kept",
          stored.rows[1]["quantity"] == "not calculated")
    check("free text lines are notes",
          any(n.startswith("Headline results only") for n in stored.notes))


@pytest.mark.parametrize("schema", [None, "1", "two"])
def test_a_file_outside_the_supported_layouts_is_refused(schema):
    text = _replace_header(_iv_text([_iv_run("fwd", 1e-3)]), "schema",
                           schema)
    with pytest.raises(UnreadableFile):
        parse(text)


def test_a_newer_schema_is_read_with_a_warning(check):
    text = _replace_header(_iv_text([_iv_run("fwd", 1e-3)]), "schema",
                           str(FILE_SCHEMA + 1))
    stored = parse(text)
    check("read", len(stored.runs) == 1)
    check("warned", any("newer" in w for w in stored.warnings),
          stored.warnings)


@pytest.mark.parametrize("build, phrase", [
    ("0.1.0+g5e7308eff34a.dirty", "uncommitted"),
    ("0.1.0+unknown", "could not tell"),
])
def test_an_unreproducible_build_is_flagged(check, build, phrase):
    text = _replace_header(_iv_text([_iv_run("fwd", 1e-3)]), "build_id",
                           build)
    stored = parse(text)
    check("flagged", any(phrase in w for w in stored.warnings),
          stored.warnings)


def test_a_clean_build_is_not_flagged(check):
    text = _replace_header(_iv_text([_iv_run("fwd", 1e-3)]), "build_id",
                           "0.1.0+g5e7308eff34a")
    check("no warning", parse(text).warnings == [])


@pytest.mark.parametrize("mangle", [
    lambda t: "\n".join(line for line in t.split("\n")
                        if not line.startswith("#")),
    lambda t: t.replace("record_id,", "row_id,", 1),
    lambda t: t.rstrip("\n") + ",extra\n",
    lambda t: "\n".join(line for line in t.split("\n")
                        if line.startswith("#")),
])
def test_a_broken_file_is_refused_not_half_read(mangle):
    with pytest.raises(UnreadableFile):
        parse(mangle(_iv_text([_iv_run("fwd", 1e-3)])))


def test_a_byte_order_mark_from_excel_is_tolerated(check, tmp_path):
    path = tmp_path / "filmA_iv_sweep.csv"
    path.write_text(_iv_text([_iv_run("fwd", 1e-3)]), encoding="utf-8-sig")
    stored = load(str(path))
    check("read", stored.kind is IV_SWEEP and len(stored.runs) == 1)


@pytest.mark.parametrize("text, expected", [
    ("1.5", 1.5), ("-2e-3", -2e-3), ("21", 21.0),
    ("", None), ("yes", None), ("1_000", None), (" 1", None),
])
def test_only_plain_numbers_are_numbers(text, expected):
    assert to_number(text) == expected
