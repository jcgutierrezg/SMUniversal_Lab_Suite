"""
The plotter's exports, and reloading a session as it is saved again.
"""
import csv
import io
import math
import os

import pytest
from plotter_files import (
    FIXED_TITLE,
    fixed_run,
    iv_run,
    stored,
    write,
)

from smuniversal_lab_suite.plotter import export
from smuniversal_lab_suite.plotter.reader import UnreadableFile, load, parse
from smuniversal_lab_suite.plotter.session import (
    Session,
    snapshot_base,
    snapshot_number,
)


def _ticked(*files):
    session = Session()
    for f in files:
        session.add(f)
    for _f, run in session.visible_runs():
        session.tick(run.record_id)
    return session.ticked_series()


def _table(text):
    body = [line for line in text.splitlines() if not line.startswith("#")]
    return list(csv.DictReader(io.StringIO("\n".join(body))))


# ------------------------------------------------------------------
# readings export
# ------------------------------------------------------------------
def test_every_reading_of_every_ticked_run_is_exported(check):
    iv = stored([iv_run("fwd", points=5), iv_run("rev", points=3,
                                                  minutes=1)])
    fs = stored([fixed_run("hold", samples=4, minutes=2)],
                title=FIXED_TITLE, path="filmA_fixed_source.csv")
    series = _ticked(iv, fs)
    text = export.build_readings_csv(series, "Saved value by run")
    rows = _table(text)

    check("one row per reading", len(rows) == 5 + 3 + 4, len(rows))
    check("named by run", {r["run"] for r in rows}
          == {s.label for s in series})
    check("with its source file and record id",
          all(r["source_file"] and r["record_id"].startswith("rec-")
              for r in rows))
    check("experiment named",
          {r["experiment"] for r in rows} == {"IV sweep", "Fixed source"})
    check("columns from both experiments",
          {"voltage_V", "time_s", "compliance_tripped"}
          <= set(rows[0]), list(rows[0]))
    check("a column a run does not have is blank, not invented",
          all(r["time_s"] == "" for r in rows if r["experiment"] == "IV sweep"))
    check("the header says what it is",
          text.startswith("# CSV plotter export - not a saved measurement"))
    check("and how it was plotted", "# plotted_as: Saved value by run" in text)


def test_numbers_keep_full_precision_and_blanks_stay_blank(check):
    run = iv_run(points=3)
    run.readings[1]["current_A"] = ""
    run.readings[2]["current_A"] = 1.0 / 3.0
    rows = _table(export.build_readings_csv(_ticked(stored([run]))))
    check("blank stays blank", rows[1]["current_A"] == "", rows[1])
    check("full precision",
          float(rows[2]["current_A"]) == 1.0 / 3.0, rows[2]["current_A"])


def test_an_export_cannot_be_mistaken_for_a_saved_measurement():
    text = export.build_readings_csv(_ticked(stored([iv_run()])))
    with pytest.raises(UnreadableFile):
        parse(text, "filmA_iv_sweep.csv")


# ------------------------------------------------------------------
# compare table
# ------------------------------------------------------------------
def test_the_compare_table_pastes_as_cells(check):
    series = _ticked(stored([iv_run("a", sensing="2-wire"),
                             iv_run("b", minutes=1)]))
    text = export.build_compare_table(series)
    lines = text.splitlines()
    check("tab separated", lines[0].split("\t")[:2] == ["setting", "differs"],
          lines[0])
    check("a column per run", len(lines[0].split("\t")) == 2 + 2)
    sensing = next(line.split("\t") for line in lines
                   if line.startswith("Sensing"))
    check("differences marked in words", sensing[1] == "yes", sensing)

    only = export.build_compare_table(series, ",", only_differences=True)
    rows = list(csv.reader(io.StringIO(only)))
    check("only differing rows when asked",
          all(row[1] == "yes" for row in rows[1:]), rows)


# ------------------------------------------------------------------
# reload
# ------------------------------------------------------------------
@pytest.mark.parametrize("name, base, number", [
    ("filmA_iv_sweep.csv", "filmA_iv_sweep", 0),
    ("filmA_iv_sweep_1.csv", "filmA_iv_sweep", 1),
    ("filmA_iv_sweep_12.csv", "filmA_iv_sweep", 12),
    ("wafer_ossila_4pp.csv", "wafer_ossila_4pp", 0),
])
def test_snapshot_names(name, base, number):
    assert (snapshot_base(name), snapshot_number(name)) == (base, number)


def test_reload_picks_up_a_later_save_and_keeps_the_ticks(check, tmp_path):
    first = iv_run("fwd")
    path = write(tmp_path, "filmA_iv_sweep.csv", [first])
    session = Session()
    session.add(load(path))
    session.tick(first.record_id)
    colour = session.ticked_series()[0].color

    # The operator measures again and presses Save: a snapshot holding
    # both runs lands beside the first file, as `_1`.
    second = iv_run("rev", minutes=1)
    write(tmp_path, "filmA_iv_sweep_1.csv", [first, second])
    write(tmp_path, "filmB_iv_sweep.csv", [iv_run("other")])

    new_files, problems = session.reload(load)
    check("the later save is opened",
          [os.path.basename(f.path) for f in new_files]
          == ["filmA_iv_sweep_1.csv"], new_files)
    check("another sample's file is not", len(session.files) == 2)
    check("no problems", problems == [], problems)
    check("the new run is there, the old one once",
          sorted(r.label for _f, r in session.visible_runs())
          == ["fwd", "rev"])
    check("the tick survived with its colour",
          [(s.run.record_id, s.color) for s in session.ticked_series()]
          == [(first.record_id, colour)])


def test_reload_does_not_reopen_an_older_save(check, tmp_path):
    write(tmp_path, "filmA_iv_sweep.csv", [iv_run("old")])
    newer = write(tmp_path, "filmA_iv_sweep_1.csv", [iv_run("new")])
    session = Session()
    session.add(load(newer))
    new_files, _problems = session.reload(load)
    check("nothing added", new_files == [] and len(session.files) == 1)


def test_a_file_that_cannot_be_reread_keeps_its_open_copy(check, tmp_path):
    run = iv_run("kept")
    path = write(tmp_path, "filmA_iv_sweep.csv", [run])
    session = Session()
    session.add(load(path))
    session.tick(run.record_id)

    # A save caught half-written: the header is there, the table is not.
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# IV sweep\n# schema: 3\n")
    _new, problems = session.reload(load)
    check("reported", len(problems) == 1 and "kept the copy" in problems[0],
          problems)
    check("still open and ticked",
          [s.run.label for s in session.ticked_series()] == ["kept"])


def test_a_reread_file_with_changed_runs_drops_only_what_vanished(
        check, tmp_path):
    keep, gone = iv_run("keep"), iv_run("gone", minutes=1)
    path = write(tmp_path, "filmA_iv_sweep.csv", [keep, gone])
    session = Session()
    session.add(load(path))
    session.tick(keep.record_id)
    session.tick(gone.record_id)

    write(tmp_path, "filmA_iv_sweep.csv", [keep])
    session.reload(load)
    check("the vanished run is unticked",
          [s.run.label for s in session.ticked_series()] == ["keep"])


def test_relative_change_refuses_a_zero_reference(check):
    import numpy as np

    from smuniversal_lab_suite.plotter.views import relative_change

    values, ref = relative_change(np.array([0.0, 1.0]), "first")
    check("no percentage of zero", values is None and ref == 0.0)
    values, ref = relative_change(np.array([math.nan, 2.0, 3.0]), "first")
    check("a blank first reading uses the first there is",
          ref == 2.0 and values[2] == 50.0, (ref, values))
    values, ref = relative_change(np.array([1.0, 3.0]), "mean")
    check("against the mean", ref == 2.0 and list(values) == [-50.0, 50.0])

