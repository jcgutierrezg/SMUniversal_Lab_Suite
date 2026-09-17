"""
Getting data back out of the plotter, for another program.

Two exports, both pure text so they are tested without a window:

* `build_readings_csv` - every reading of the ticked runs, one row per
  reading, with the run's name, sample, source file and `record_id` on
  each row. Long form, like the files the suite saves, because that is
  what filters and pivots in Excel, and what Origin imports as columns.
* `build_compare_table` - the Compare tab: one row per setting, one
  column per run. Tab-separated for the clipboard, where a paste into a
  spreadsheet or a lab notebook splits into cells; comma-separated when
  saved to a file.

What an export is not
---------------------
It is not a saved measurement. It has no `schema` line, so the plotter
refuses to open it as one, and its `#` header says which files it came
from and which software wrote it. A copy that could be mistaken for the
original file would be a second, unverifiable source for the same
numbers.
"""
from __future__ import annotations

import csv
import datetime
import io
import os

import numpy as np

from smuniversal_lab_suite.core.version import build_id
from smuniversal_lab_suite.plotter import describe
from smuniversal_lab_suite.plotter.session import Series

#: Written before each reading's own columns, in this order.
RUN_COLUMNS = ("run", "sample", "experiment", "source_file", "record_id")


def _cell(value) -> str:
    """A reading as text: full precision, blank for a missing value."""
    if isinstance(value, float):
        return "" if not np.isfinite(value) else repr(float(value))
    return "" if value is None else str(value)


def build_readings_csv(series: list[Series], view_title: str = "") -> str:
    """Every reading of `series`, long form, as CSV text."""
    columns: list[str] = []
    for s in series:
        for key in s.run.readings:
            if key not in columns:
                columns.append(key)

    files = []
    for s in series:
        name = os.path.basename(s.file.path)
        if name not in files:
            files.append(name)

    header = [
        "# CSV plotter export - not a saved measurement",
        f"# exported: {datetime.datetime.now().isoformat()}",
        f"# build_id: {build_id()}",
        f"# runs: {len(series)}",
        f"# source_files: {' '.join(files)}",
    ]
    if view_title:
        header.append(f"# plotted_as: {view_title}")
    header.append("#")

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(RUN_COLUMNS) + columns)
    for s in series:
        base = [s.label, s.run.text("sample_label") or s.file.sample,
                s.file.kind.name, os.path.basename(s.file.path),
                s.run.record_id]
        for index in range(len(s.run)):
            row = []
            for key in columns:
                values = s.run.readings.get(key)
                row.append(_cell(values[index]) if values is not None
                           else "")
            writer.writerow(base + row)
    return "\n".join(header) + "\n" + buffer.getvalue()


def build_compare_table(series: list[Series], delimiter: str = "\t",
                        only_differences: bool = False) -> str:
    """The Compare tab as text: settings down, runs across."""
    rows = describe.compare_rows([(s.file, s.run) for s in series])
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    writer.writerow(["setting", "differs"] + [s.label for s in series])
    for _key, label, texts, differs in rows:
        if only_differences and not differs:
            continue
        writer.writerow([label, "yes" if differs else ""] + texts)
    return buffer.getvalue()


def write_text(path: str, text: str) -> None:
    """Write through a temporary file, so a failed export leaves no
    half-written file behind; LF endings, as every file here uses."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    os.replace(tmp, path)
