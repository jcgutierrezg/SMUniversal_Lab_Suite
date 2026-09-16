"""
Reading a saved CSV back into runs.

What a file holds
-----------------
`core.run_store.build_sample_csv` writes a `#` header - title, file
details, then an optional `--- calculated ---` block - and a long-form
table with one row per reading and each run's values repeated on every
row. This module undoes that: rows are grouped back into runs by
`record_id`, and each column is filed either as a **setting** (one value
for the whole run) or a **reading** (a value per row).

The per-sample summary has the same `#` header and a plain table, and is
returned as rows rather than runs.

Only the current layout is read
-------------------------------
Saved data is taken to start at schema 2, decided on 2026-09-16: there
is no older data anyone wants plotted, so there are no fallbacks for
files without `record_id` or without a `schema` line. Such a file is
refused with a message saying why, rather than half-read. A file from a
*newer* schema is read, with a warning, because an additive change is
the usual kind and refusing would make the plotter the first thing to
break after every format change.

Empty cells stay where they are
-------------------------------
A sentinel reaches the file as an empty cell in its own column, and it
is read back as NaN in that position rather than dropped. Dropping it
would shift every later reading of that column against the rest of the
row - a number of the right shape attached to the wrong current. See
docs/faults/03-sentinels-as-data.md.
"""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field

import numpy as np

from smuniversal_lab_suite.core.run_store import FILE_SCHEMA
from smuniversal_lab_suite.plotter.detect import (
    SUMMARY,
    Detection,
    ExperimentKind,
    detect,
)

#: The oldest layout this plotter reads. Data before it is not supported.
MIN_SCHEMA = 2

CALCULATED_MARKER = "--- calculated ---"


class UnreadableFile(ValueError):
    """The file is not one this suite wrote, in a layout this reads."""


def to_number(text: str) -> float | None:
    """A cell as a float, or None when it is not a plain number.

    `float()` alone is too generous for data read back from a file: it
    accepts `1_000` and surrounding whitespace, neither of which the
    suite writes, so a text cell such as a dataset label could be read
    as a quantity.
    """
    stripped = text.strip()
    if not stripped or stripped != text or "_" in stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def _setting_value(text: str) -> float | str | None:
    if text == "":
        return None
    number = to_number(text)
    return text if number is None else number


@dataclass
class StoredRun:
    """One run, as saved.

    `settings` maps a column to its single value for the run: a float
    when it reads as a number, the text otherwise, None when empty.
    `readings` maps a column to an array, one entry per reading - float
    with NaN for an empty cell when every filled cell is a number, the
    raw text otherwise.
    """

    record_id: str
    settings: dict[str, float | str | None]
    readings: dict[str, np.ndarray]
    path: str = ""

    def __len__(self) -> int:
        for values in self.readings.values():
            return len(values)
        return 0

    def number(self, key: str) -> float | None:
        """A setting as a finite float, or None."""
        value = self.settings.get(key)
        if isinstance(value, float) and math.isfinite(value):
            return value
        return None

    def text(self, key: str) -> str:
        """A setting as display text; empty when absent."""
        value = self.settings.get(key)
        if value is None:
            return ""
        if isinstance(value, float):
            return format_number(value)
        return value

    def series(self, key: str) -> np.ndarray | None:
        """A numeric reading column, or None if absent or not numeric."""
        values = self.readings.get(key)
        if values is None or values.dtype.kind != "f":
            return None
        return values

    @property
    def label(self) -> str:
        """What the operator called this run, as the results table did."""
        return self.text("dataset") or self.text("meas_number") \
            or self.record_id


@dataclass
class StoredFile:
    """A whole file: its header, its detected experiment and its runs."""

    path: str
    title: str
    schema: int
    header: dict[str, str]
    calculated: dict[str, str]
    columns: list[str]
    detection: Detection
    runs: list[StoredRun] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def kind(self) -> ExperimentKind:
        return self.detection.kind

    @property
    def sample(self) -> str:
        return self.header.get("sample", "")

    @property
    def is_summary(self) -> bool:
        return self.kind is SUMMARY


def format_number(value: float) -> str:
    """A float for display: integers without a trailing `.0`."""
    if math.isfinite(value) and value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.6g}"


def _split_header(text: str):
    """The `#` lines, and the offset where the table starts.

    The table is handed to `csv` as one string rather than line by line,
    because a quoted cell may contain a newline and splitting on lines
    first would tear that row in two.
    """
    lines = []
    offset = 0
    while offset < len(text):
        end = text.find("\n", offset)
        end = len(text) if end < 0 else end + 1
        line = text[offset:end].rstrip("\r\n")
        if not line.startswith("#"):
            break
        lines.append(line[1:].strip())
        offset = end
    return lines, text[offset:]


def _unique_columns(names, warnings):
    """Column names with repeats kept apart as `name#2`, `name#3`...

    A dict keyed by header name keeps only the last of two same-named
    columns, silently. Both are kept instead, and the file says so.
    """
    seen: dict[str, int] = {}
    out = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        if seen[name] == 1:
            out.append(name)
        else:
            out.append(f"{name}#{seen[name]}")
    for name, count in seen.items():
        if count > 1:
            warnings.append(
                f"Column '{name}' appears {count} times; the later "
                f"copies are shown as '{name}#2'"
                + (" and onwards." if count > 2 else "."))
    return out


def parse(text: str, path: str = "") -> StoredFile:
    """Read a saved file's text. Raises `UnreadableFile`."""
    header_lines, body = _split_header(text)
    if not header_lines:
        raise UnreadableFile(
            "No '#' header: this is not a file the suite saved.")

    title = header_lines[0]
    header: dict[str, str] = {}
    calculated: dict[str, str] = {}
    notes: list[str] = []
    target = header
    for line in header_lines[1:]:
        if line == CALCULATED_MARKER:
            target = calculated
        elif ": " in line:
            key, value = line.split(": ", 1)
            target[key.strip()] = value.strip()
        elif line:
            notes.append(line)

    schema_text = header.get("schema")
    if schema_text is None:
        raise UnreadableFile(
            "No 'schema' line in the header. Files from before schema "
            f"{MIN_SCHEMA} are not read by the plotter.")
    try:
        schema = int(schema_text)
    except ValueError:
        raise UnreadableFile(
            f"The header's schema is '{schema_text}', not a number."
        ) from None
    if schema < MIN_SCHEMA:
        raise UnreadableFile(
            f"Schema {schema} is older than the plotter reads "
            f"({MIN_SCHEMA} onwards).")

    warnings: list[str] = []
    if schema > FILE_SCHEMA:
        warnings.append(
            f"Written with schema {schema}, newer than this software "
            f"({FILE_SCHEMA}). Columns it does not know are still shown.")
    if header.get("build_id", "").endswith(".dirty"):
        warnings.append(
            "Saved by code with uncommitted changes (build_id ends "
            "'.dirty'): what ran is not in the repository history.")
    elif header.get("build_id", "").endswith("+unknown"):
        warnings.append(
            "The saving software could not tell which build it was "
            "(build_id 'unknown').")

    table = list(csv.reader(io.StringIO(body)))
    table = [row for row in table if row]
    if not table:
        raise UnreadableFile("The header is there but the table is empty.")
    columns = _unique_columns(table[0], warnings)
    detection = detect(title, path, columns)

    stored = StoredFile(path=path, title=title, schema=schema,
                        header=header, calculated=calculated,
                        columns=columns, detection=detection, notes=notes,
                        warnings=warnings)

    width = len(columns)
    records = []
    for number, row in enumerate(table[1:], start=2):
        if len(row) != width:
            raise UnreadableFile(
                f"Table row {number} has {len(row)} cells for {width} "
                f"columns.")
        records.append(dict(zip(columns, row)))

    if stored.is_summary:
        stored.rows = records
        return stored

    if "record_id" not in columns:
        raise UnreadableFile(
            "No 'record_id' column, so rows cannot be grouped into runs.")
    stored.runs = _group_runs(records, columns, detection.kind, path)
    return stored


def _group_runs(records, columns, kind, path):
    grouped: dict[str, list[dict[str, str]]] = {}
    for record in records:
        grouped.setdefault(record["record_id"], []).append(record)

    # A reading column is one the experiment declares, or one whose value
    # changes within any run. The second catches a column this plotter
    # has never heard of; the first catches a declared one that happens
    # to hold one value throughout.
    varying = {
        column for column in columns
        if any(len({r[column] for r in rows}) > 1
               for rows in grouped.values())
    }
    reading_columns = [c for c in columns
                       if c in varying or c in kind.reading_columns]
    setting_columns = [c for c in columns if c not in reading_columns]

    runs = []
    for record_id, rows in grouped.items():
        settings = {c: _setting_value(rows[0][c]) for c in setting_columns}
        readings = {c: _column_array([r[c] for r in rows])
                    for c in reading_columns}
        runs.append(StoredRun(record_id=record_id, settings=settings,
                              readings=readings, path=path))
    return runs


def _column_array(cells: list[str]) -> np.ndarray:
    numbers = [to_number(cell) for cell in cells]
    filled = [n for n, cell in zip(numbers, cells) if cell != ""]
    if filled and all(n is not None for n in filled):
        return np.array([math.nan if n is None else n for n in numbers],
                        dtype=float)
    return np.array(cells, dtype=object)


def load(path: str) -> StoredFile:
    """Read a saved file from disk. Raises `UnreadableFile` or OSError."""
    # `utf-8-sig` so a file re-saved by Excel, which adds a byte-order
    # mark, still starts with '#'.
    with open(path, encoding="utf-8-sig", newline="") as handle:
        text = handle.read()
    return parse(text, path)
