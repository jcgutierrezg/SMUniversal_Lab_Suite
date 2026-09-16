"""
Detecting which experiment wrote a file, and keeping the plotter's copy
of each experiment's title and slug honest.
"""
import pytest

from smuniversal_lab_suite.experiments.fixed_source.experiment import (
    FixedSourceExperiment,
)
from smuniversal_lab_suite.experiments.hall.experiment import HallExperiment
from smuniversal_lab_suite.experiments.iv_sweep.experiment import (
    IVSweepExperiment,
)
from smuniversal_lab_suite.experiments.ossila_4pp.experiment import (
    Ossila4PPExperiment,
)
from smuniversal_lab_suite.experiments.vanderpauw.experiment import (
    VanDerPauwExperiment,
)
from smuniversal_lab_suite.plotter.detect import (
    EXPERIMENT_KINDS,
    FIXED_SOURCE,
    HALL,
    IV_SWEEP,
    KNOWN_KINDS,
    OSSILA_4PP,
    UNRECOGNISED,
    VAN_DER_PAUW,
    detect,
)

PAIRS = [
    (IV_SWEEP, IVSweepExperiment),
    (FIXED_SOURCE, FixedSourceExperiment),
    (OSSILA_4PP, Ossila4PPExperiment),
    (VAN_DER_PAUW, VanDerPauwExperiment),
    (HALL, HallExperiment),
]


def test_every_experiment_kind_is_paired_with_an_experiment():
    """A kind added without a pairing below would go unpinned."""
    assert {kind for kind, _ in PAIRS} == set(EXPERIMENT_KINDS)


@pytest.mark.parametrize("kind, experiment", PAIRS,
                         ids=[k.key for k, _ in PAIRS])
def test_the_copied_title_and_slug_match_the_experiment(check, kind,
                                                        experiment):
    check("title", kind.csv_title == experiment.CSV_TITLE,
          f"{kind.csv_title!r} != {experiment.CSV_TITLE!r}")
    check("slug", kind.csv_slug == experiment.CSV_SLUG,
          f"{kind.csv_slug!r} != {experiment.CSV_SLUG!r}")


@pytest.mark.parametrize("kind", KNOWN_KINDS, ids=lambda k: k.key)
def test_each_clue_identifies_the_kind_on_its_own(check, kind):
    columns = sorted(kind.signature | kind.reading_columns)
    by_title = detect(kind.csv_title, "renamed.csv", ["record_id"])
    by_name = detect("edited title", f"sample_{kind.csv_slug}.csv",
                     ["record_id"])
    by_columns = detect("edited title", "renamed.csv", columns)
    check("title", (by_title.kind, by_title.method) == (kind, "title"))
    check("file name", (by_name.kind, by_name.method) == (kind, "file name"))
    check("columns", (by_columns.kind, by_columns.method) == (kind, "columns"),
          by_columns)


def test_all_clues_agreeing_leaves_no_notes(check):
    found = detect(IV_SWEEP.csv_title, "filmA_iv_sweep.csv",
                   sorted(IV_SWEEP.signature))
    check("iv", found.kind is IV_SWEEP)
    check("no notes", found.notes == (), found.notes)


def test_a_renamed_file_is_shown_by_its_title_and_the_clash_reported(check):
    found = detect(HALL.csv_title, "bar_iv_sweep.csv", sorted(HALL.signature))
    check("the title wins", found.kind is HALL and found.method == "title")
    check("the clash is reported",
          any("file name suggests IV sweep" in n for n in found.notes),
          found.notes)


@pytest.mark.parametrize("name, kind", [
    ("filmA_iv_sweep_1.csv", IV_SWEEP),
    ("filmA_iv_sweep_12.csv", IV_SWEEP),
    ("hallbar_hall.csv", HALL),
    ("hallbar_vanderpauw.csv", VAN_DER_PAUW),
    ("my_hall_sample_fixed_source.csv", FIXED_SOURCE),
    ("hallway.csv", None),
    ("_hall.csv", None),
])
def test_file_names_with_save_suffixes(name, kind):
    found = detect("edited title", name, ["record_id"])
    if kind is None:
        assert found.kind is UNRECOGNISED
    else:
        assert found.kind is kind


def test_no_clue_at_all_is_unrecognised_not_a_guess(check):
    found = detect("Something else", "data.csv", ["a", "b"])
    check("unrecognised", found.kind is UNRECOGNISED and not found.recognised)
    check("and says so", found.notes, found.notes)


def test_no_signature_is_contained_in_another_kinds_columns():
    """A signature inside another kind's declared columns would make
    column detection ambiguous for that kind's files."""
    for kind in KNOWN_KINDS:
        for other in KNOWN_KINDS:
            if other is kind:
                continue
            assert not kind.signature <= (other.signature
                                          | other.reading_columns), (
                kind.key, other.key)
