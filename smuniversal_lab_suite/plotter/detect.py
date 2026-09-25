"""
Which experiment wrote this file.

Three independent clues, in order of trust
------------------------------------------
1. **The title line.** `build_sample_csv` writes the experiment's
   `CSV_TITLE` as the first `#` line. It is written by the code, not
   typed by anyone, so an exact match is the strongest evidence there
   is.
2. **The file name.** Saves are named `<sample>_<CSV_SLUG>.csv`. A
   person can rename a file, so this ranks below the title - but it is
   still a deliberate choice somebody made.
3. **The columns.** A handful of column names that only one experiment
   writes. This survives both a renamed file and an edited title.

All three are evaluated every time, not just until one matches. When
they disagree - a Hall file renamed `_iv_sweep.csv` - the highest-ranked
clue decides and the disagreement is reported next to the plot. A tool
that silently picked one would draw an IV view of Hall data and say
nothing, which is the failure this module exists to prevent.

Why the titles are copied here rather than imported
---------------------------------------------------
Importing the experiment classes would pull in Tk, every panel and,
through them, the driver registry - to read five strings. The copies
are pinned instead: `tests/test_plotter_detect.py` fails if any of them
stops matching the experiment's own `CSV_TITLE` or `CSV_SLUG`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ExperimentKind:
    """Everything the plotter needs to know about one experiment's files.

    `signature` is a set of columns that together occur in this
    experiment's files and no other's. `reading_columns` are the columns
    that hold a value per reading rather than per run; the reader also
    finds those by looking for values that vary within a run, but a
    column that happens not to vary - every reading clamped, or none -
    is still a reading and must not be shown as a run setting.
    """

    key: str
    name: str
    csv_title: str
    csv_slug: str
    signature: frozenset[str]
    reading_columns: frozenset[str]


IV_SWEEP = ExperimentKind(
    key="iv_sweep",
    name="IV sweep",
    csv_title="IV sweep",
    csv_slug="iv_sweep",
    signature=frozenset({"points_returned", "fitted", "sweep_kind"}),
    reading_columns=frozenset({"point", "voltage_V", "current_A"}),
)

FIXED_SOURCE = ExperimentKind(
    key="fixed_source",
    name="Fixed source",
    csv_title="Fixed sourcing vs time",
    csv_slug="fixed_source",
    signature=frozenset({"sample_index", "time_s", "interval_achieved_s"}),
    # The per-sample trip flag is `compliance_tripped` from schema 3. A
    # schema 2 file wrote it as a second column named `compliance`,
    # beside the run's limit, and the reader keeps that one apart as
    # `compliance#2` - so both spellings are readings.
    reading_columns=frozenset({
        "sample_index", "reading_id", "time_s", "read_s", "voltage_V",
        "current_A", "compliance#2", "compliance_tripped", "stage_temp_C",
    }),
)

OSSILA_4PP = ExperimentKind(
    key="ossila_4pp",
    name="Ossila 4-point probe",
    csv_title="Ossila 4-point probe - sheet resistance",
    csv_slug="ossila_4pp",
    signature=frozenset({"sheet_resistance_ohm_sq", "cancelled_offset_V"}),
    reading_columns=frozenset({
        "point", "timestamp", "current_A", "voltage_V",
        "cancelled_offset_V", "resistance_at_point_ohm",
    }),
)

VAN_DER_PAUW = ExperimentKind(
    key="vanderpauw",
    name="Van der Pauw",
    csv_title="Van der Pauw - sheet resistance",
    csv_slug="vanderpauw",
    signature=frozenset({"R_ave_ohm", "polarity"}),
    reading_columns=frozenset({
        # `level_A` is each sweep point's commanded current, since the
        # runs became sweeps; older files have none.
        "point", "polarity", "level_A", "timestamp", "voltage_V",
        "current_A", "resistance_ohm", "error",
    }),
)

HALL = ExperimentKind(
    key="hall",
    name="Hall effect",
    csv_title="Hall effect - carrier density and mobility",
    csv_slug="hall",
    signature=frozenset({"V_plus_V", "V_minus_V", "current_polarity"}),
    reading_columns=frozenset({
        "point", "current_polarity", "level_A", "timestamp", "voltage_V",
        "current_A", "error",
    }),
)

#: The per-sample summary. Not an experiment, but it is a file the suite
#: writes and the plotter opens, so it is detected the same way.
SUMMARY = ExperimentKind(
    key="summary",
    name="Sample summary",
    csv_title="Sample summary",
    csv_slug="summary",
    signature=frozenset({"measurement", "quantity", "value", "unit",
                         "source"}),
    reading_columns=frozenset(),
)

#: A file with the suite's header that no clue identifies. It still
#: opens: the columns are offered for plotting by hand.
UNRECOGNISED = ExperimentKind(
    key="unrecognised",
    name="Unrecognised",
    csv_title="",
    csv_slug="",
    signature=frozenset(),
    reading_columns=frozenset(),
)

EXPERIMENT_KINDS = (IV_SWEEP, FIXED_SOURCE, OSSILA_4PP, VAN_DER_PAUW, HALL)
KNOWN_KINDS = EXPERIMENT_KINDS + (SUMMARY,)


@dataclass(frozen=True)
class Detection:
    """The verdict, and the evidence behind it.

    `method` is the clue that decided: `title`, `file name`, `columns`
    or `none`. `notes` holds every disagreement between clues, in words
    fit to show beside the plot.
    """

    kind: ExperimentKind
    method: str
    notes: tuple[str, ...] = ()

    @property
    def recognised(self) -> bool:
        return self.kind is not UNRECOGNISED


def _by_title(title: str) -> ExperimentKind | None:
    for kind in KNOWN_KINDS:
        if title == kind.csv_title:
            return kind
    return None


def _by_file_name(path: str) -> ExperimentKind | None:
    stem = os.path.splitext(os.path.basename(path))[0]
    # A second save under the same name gets a suffix from
    # `unique_filename()`, so match the slug anywhere after the sample
    # name rather than only at the very end. Longest slug first, so a
    # future slug that ends in another one cannot be shadowed by it.
    for kind in sorted(KNOWN_KINDS, key=lambda k: -len(k.csv_slug)):
        marker = f"_{kind.csv_slug}"
        at = stem.rfind(marker)
        if at <= 0:
            continue
        rest = stem[at + len(marker):]
        if rest == "" or not rest[0].isalnum():
            return kind
    return None


def _by_columns(columns) -> ExperimentKind | None:
    present = set(columns)
    matches = [k for k in KNOWN_KINDS if k.signature <= present]
    # Two signatures matching at once would mean the signatures are no
    # longer distinctive. Better to say "unrecognised" than to guess.
    return matches[0] if len(matches) == 1 else None


def detect(title: str, path: str, columns) -> Detection:
    """Decide which experiment wrote a file from its three clues."""
    clues = (
        ("title", _by_title(title)),
        ("file name", _by_file_name(path)),
        ("columns", _by_columns(columns)),
    )
    found = [(method, kind) for method, kind in clues if kind is not None]
    if not found:
        return Detection(UNRECOGNISED, "none", (
            "No title, file name or column set identifies the "
            "experiment. Columns can still be plotted by hand.",))

    method, kind = found[0]
    notes = []
    for other_method, other in found[1:]:
        if other is not kind:
            notes.append(
                f"The {other_method} suggests {other.name}, but the "
                f"{method} says {kind.name}; shown as {kind.name}.")
    if method != "title":
        notes.append(
            f"Title '{title}' is not one this plotter knows; identified "
            f"by {method}.")
    return Detection(kind, method, tuple(notes))
