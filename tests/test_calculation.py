"""
Calculation integrity: coherent inputs, provenance, staleness, versions.

No Tk here, deliberately. Everything in `core/calculation.py` is
arithmetic-free bookkeeping, so it can be tested in the fast shared
process rather than costing a subprocess of its own. That is not an
accident of the design - a calculation layer that needed a window to
test would be a calculation layer entangled with its panel, which is
what house rule 10 is about.

What each section guards
------------------------
A. the method table and its versions
B. the mixed-sample refusal
C. required and complete input sets
D. the provenance chain on a derived result
E. staleness detection
"""
import pytest

from core.calculation import (
    CALCULATION_SCHEMA_VERSION,
    METHODS,
    CalculationInput,
    CalculationRefused,
    InputValue,
    SourceRow,
    UnknownMethod,
    UpstreamResult,
    compact_row_ids,
    derive,
    require_set,
    signature,
    tag,
    upstream_signature_items,
    validate,
    version_of,
)
from core.identity import SampleRegistry, reading_id
from core.run_store import Run, RunStore
from core.units import um_to_m


# --------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------
def make_input(method="fourpp_sheet_resistance", sample_id="smp-A",
               sample_label="film_A", values=None, sources=(), required=(),
               upstream=()):
    return CalculationInput(
        method=method,
        sample_id=sample_id,
        sample_label=sample_label,
        values=values if values is not None else {
            "resistance_ohm": InputValue(1000.0, "\u03a9", "1000"),
            "thickness_m": InputValue(1.8e-4, "m", "180"),
        },
        sources=sources,
        required=required,
        upstream=upstream,
    )


def source(run_id="ossila_4pp-0001-20260808T120000", sample_id="smp-A",
           label="film_A", readings=3, position="", polarity=""):
    return SourceRow(
        run_id=run_id, sample_id=sample_id, sample_label=label,
        row_ids=tuple(reading_id(run_id, i) for i in range(readings)),
        position=position, polarity=polarity)


# --------------------------------------------------------------------
# A. the method table
# --------------------------------------------------------------------
def test_every_method_has_a_version_and_a_description(check):
    for name, entry in METHODS.items():
        check(f"{name} is a (version, description) pair", len(entry) == 2,
              str(entry))
        check(f"{name} version is a positive int",
              isinstance(entry[0], int) and entry[0] >= 1, str(entry[0]))
        check(f"{name} says what it computes", bool(entry[1].strip()))


def test_tag_is_a_name_welded_to_a_version():
    """The spelling is `vdp_resistivity:1`, not a dict or a tuple."""
    assert tag("vdp_resistivity") == f"vdp_resistivity:{version_of('vdp_resistivity')}"
    assert tag("hall_mobility").count(":") == 1


def test_an_unregistered_method_is_refused_loudly():
    """A typo must not produce an unversioned result.

    The failure this prevents is quiet: a result stored with a method
    name nobody registered is a result nobody can reproduce later, and
    it looks identical to a good one in the CSV.
    """
    with pytest.raises(UnknownMethod):
        version_of("hall_coeficient")          # one 'f'
    with pytest.raises(UnknownMethod):
        validate(make_input(method="not_a_method"))


# --------------------------------------------------------------------
# B. mixed samples
# --------------------------------------------------------------------
def test_a_source_from_another_sample_is_refused(check):
    calc = make_input(sample_id="smp-A", sample_label="film_A",
                      sources=(source(sample_id="smp-B", label="film_B"),))
    with pytest.raises(CalculationRefused) as caught:
        validate(calc)

    message = str(caught.value)
    # The requirement is that it *explains the specific
    # incompatibility*. A refusal that does not name both samples
    # leaves
    # the operator guessing which of the two is wrong.
    check("names the sample the measurement came from", "film_B" in message,
          message)
    check("names the sample being calculated", "film_A" in message, message)


def test_same_sample_passes():
    calc = make_input(sources=(source(), source(run_id="ossila_4pp-0002-x")))
    validate(calc)                              # must not raise


def test_a_renamed_sample_is_still_the_same_sample():
    """Identity, not label, is what the check rests on.

    Renaming a sample between measuring it and calculating must not
    refuse the calculation - the material on the stage did not change.
    This is the whole reason the check compares `sample_id`.
    """
    registry = SampleRegistry()
    ref = registry.ref("film_A")
    measured = source(sample_id=ref.sample_id, label=ref.label)

    renamed = registry.rename(ref.sample_id, "film_A (repolished)")
    calc = make_input(sample_id=renamed.sample_id, sample_label=renamed.label,
                      sources=(measured,))
    validate(calc)


def test_repeated_runs_refused_when_distinct_ones_are_expected(check):
    twice = source()
    calc = make_input(sources=(twice, twice))
    validate(calc)                              # fine by default
    with pytest.raises(CalculationRefused) as caught:
        validate(calc, distinct_runs=True)
    check("names the repeated run", twice.run_id in str(caught.value),
          str(caught.value))


# --------------------------------------------------------------------
# C. complete input sets
# --------------------------------------------------------------------
def test_missing_required_value_is_refused(check):
    calc = make_input(required=("resistance_ohm", "width_m"))
    with pytest.raises(CalculationRefused) as caught:
        validate(calc)
    check("names the missing field", "width_m" in str(caught.value),
          str(caught.value))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_value_is_refused(bad):
    """A NaN multiplies through every correction without complaining and
    arrives in the CSV as `nan`. Caught at the door instead."""
    calc = make_input(values={"resistance_ohm": InputValue(bad, "\u03a9")},
                      required=("resistance_ohm",))
    with pytest.raises(CalculationRefused):
        validate(calc)


def test_require_set_reports_missing_duplicate_and_unexpected(check):
    """The complete-set report, for the position sets.

    Written now with tests and no caller, the same way Wave 2 built the
    validators before an experiment used them. Missing and duplicated
    are reported separately because at the bench they mean different
    things: missing is an unfinished measurement, duplicate is the
    wrong row ticked.
    """
    expected = {"Pos1", "Pos2", "Pos3", "Pos4"}

    require_set([source(run_id=f"r{n}", position=f"Pos{n}") for n in (1, 2, 3, 4)],
                expected)                       # complete: must not raise

    with pytest.raises(CalculationRefused) as missing:
        require_set([source(run_id=f"r{n}", position=f"Pos{n}")
                     for n in (1, 2, 3)], expected)
    check("missing position is named", "Pos4" in str(missing.value),
          str(missing.value))

    with pytest.raises(CalculationRefused) as duplicate:
        require_set([source(run_id="r1", position="Pos1"),
                     source(run_id="r2", position="Pos1"),
                     source(run_id="r3", position="Pos3"),
                     source(run_id="r4", position="Pos4")], expected)
    check("duplicate is reported as such",
          "more than one" in str(duplicate.value), str(duplicate.value))


def test_completed_runs_only_is_structural_not_checked():
    """The rule is "completed source runs only". Nothing in
    `validate()` checks it, and that is correct rather than an
    omission.

    A run reaches `RunStore` exactly one way - through
    `RunContext.commit()`, which the completion gate has to pass first.
    So an uncommitted run has no store key and cannot be copied into a
    calculation at all. This asserts the property that makes the check
    unnecessary; re-implementing the gate here would be two statements
    of one rule, which is how they drift apart.
    """
    store = RunStore()
    assert store.get("never-added") is None

    store.add("item-1", Run(sample="film_A",
                            metadata={"run_id": "r1", "sample_id": "smp-A"},
                            readings=[{"point": 1}]))
    assert store.get("item-1").metadata["run_id"] == "r1"


# --------------------------------------------------------------------
# D. the provenance chain
# --------------------------------------------------------------------
def test_derived_result_carries_the_full_chain(check):
    src = source(readings=4)
    calc = make_input(sources=(src,))
    result = derive(calc, outputs={"sheet_resistance_ohm_sq": 4532.36})

    check("has a result id", result.result_id.startswith("res-"),
          result.result_id)
    check("names the method and version",
          result.method_tag == tag("fourpp_sheet_resistance"),
          result.method_tag)
    check("keeps the sample identifier", result.sample_id == "smp-A")
    check("keeps the label as it was at calculation",
          result.sample_label_at_calculation == "film_A")
    check("names the source run", result.source_run_ids == (src.run_id,))
    check("names every source row", len(result.source_row_ids) == 4,
          str(result.source_row_ids))
    check("stamps the time", bool(result.calculated_at))
    check("carries a schema version",
          result.schema_version == CALCULATION_SCHEMA_VERSION)


def test_a_result_cannot_be_edited_after_the_fact(check):
    """Frozen, including the mappings hanging off it.

    `@dataclass(frozen=True)` alone would leave `outputs` a live dict
    that any caller could rewrite - a provenance record you can edit is
    not evidence of anything. Same trap `core/parameters.py` documents.
    """
    result = derive(make_input(), outputs={"sheet_resistance_ohm_sq": 1.0})

    with pytest.raises(Exception):
        result.result_id = "res-forged"
    with pytest.raises(Exception):
        result.outputs["sheet_resistance_ohm_sq"] = 2.0
    check("outputs survived the attempt",
          result.outputs["sheet_resistance_ohm_sq"] == 1.0)


def test_hand_typed_values_are_recorded_as_such(check):
    """A calculation with no source run must say so rather than be
    silently indistinguishable from a measured one."""
    result = derive(make_input(sources=()), outputs={"rs": 1.0})
    meta = result.to_metadata()
    check("no source runs claimed", result.source_run_ids == ())
    check("the header says why", "typed by hand" in meta["source_run_ids"],
          meta["source_run_ids"])


def test_typed_text_survives_the_si_round_trip(check):
    """Wave 3 measured this: 180 um -> m -> um gives 179.99999999999997,
    and that residue was reaching the CSV header. No arithmetic fixes
    it, so the typed text is carried alongside the SI value."""
    typed = InputValue(um_to_m(180), "m", "180")
    check("SI value is what it is", typed.value == um_to_m(180))
    check("but the header shows what was typed", "180" == typed.display())

    # The two halves of Wave 3's measurement, as executable statements.
    # Multiplying by 1e-6 is the spelling that produced the reported
    # 179.99999999999997; core/units.py divides instead, which is better
    # and still not exact - 7.7 um is one of the 161 values in 0.1-500
    # that survive the divide and come back changed.
    check("multiplying by 1e-6 loses 180 um on the way back",
          (180 * 1e-6) * 1e6 != 180.0, repr((180 * 1e-6) * 1e6))
    check("dividing is better but not lossless either",
          um_to_m(7.7) * 1e6 != 7.7, repr(um_to_m(7.7) * 1e6))
    check("which is why the text is carried, not recomputed",
          InputValue(um_to_m(7.7), "m", "7.7").display() == "7.7")


def test_row_ids_compact_without_hiding_a_gap(check):
    run = "ossila_4pp-0007-20260808T143012"
    contiguous = tuple(reading_id(run, i) for i in range(30))
    check("a full run collapses to a range",
          compact_row_ids(contiguous) == f"{run}#0001-0030",
          compact_row_ids(contiguous))

    gapped = contiguous[:3] + contiguous[10:12]
    compacted = compact_row_ids(gapped)
    check("a gapped selection is written out instead",
          "-" not in compacted.replace(run, ""), compacted)
    check("and every row is still named", compacted.count("#") == 5, compacted)
    check("nothing at all is stated plainly",
          compact_row_ids(()) == "(none)")


def test_metadata_block_is_flat_strings_for_the_csv_header(check):
    result = derive(make_input(sources=(source(),)),
                    outputs={"sheet_resistance_ohm_sq": 4532.36},
                    notes=("sample is thicker than the table",))
    meta = result.to_metadata()

    for key in ("result_id", "calculation_method", "sample_id",
                "source_run_ids", "source_row_ids", "calculated_at"):
        check(f"header carries {key}", key in meta, str(sorted(meta)))
    check("inputs are prefixed", "input_resistance_ohm" in meta,
          str(sorted(meta)))
    check("outputs are prefixed", "result_sheet_resistance_ohm_sq" in meta,
          str(sorted(meta)))
    check("notes are carried", "thicker" in meta.get("calculation_notes", ""))
    check("no value would break the '# key: value' header format",
          not any("\n" in str(v) for v in meta.values()))


# --------------------------------------------------------------------
# E. staleness
# --------------------------------------------------------------------
def test_a_changed_input_makes_a_result_stale(check):
    calc = make_input()
    result = derive(calc, outputs={"rs": 1.0})

    same = signature({"resistance_ohm": "1000", "thickness_m": "180",
                      "_sample": "film_A"})
    check("unchanged inputs are not stale", not result.is_stale(same))

    changed = signature({"resistance_ohm": "1000", "thickness_m": "200",
                         "_sample": "film_A"})
    check("an edited thickness is stale", result.is_stale(changed))


def test_changing_the_sample_makes_a_result_stale():
    """The dangerous edit: none of the displayed numbers move when the
    sample name changes, so nothing on screen would otherwise say the
    result no longer describes what the panel describes."""
    result = derive(make_input(), outputs={"rs": 1.0})
    other = signature({"resistance_ohm": "1000", "thickness_m": "180",
                       "_sample": "film_B"})
    assert result.is_stale(other)


def test_retyping_the_same_number_is_not_a_change(check):
    """`180` and `180.0` are the same input.

    Without this, a result would flick to stale every time somebody
    clicked into a box and retyped what was already there - and a
    warning that cries wolf is a warning that gets ignored, which
    defeats the point of marking a result stale at all.
    """
    result = derive(make_input(), outputs={"rs": 1.0})
    retyped = signature({"resistance_ohm": "1000.0", "thickness_m": "180.00",
                         "_sample": "film_A"})
    check("equivalent text is not stale", not result.is_stale(retyped))


def test_signature_tolerates_half_typed_input():
    """It runs on every keystroke, so it meets `18` on the way to `180`
    and an empty box on the way to anything. It must compare, not
    parse."""
    partial = signature({"thickness_m": "18", "_sample": ""})
    empty = signature({"thickness_m": "", "_sample": ""})
    assert partial != empty
    assert signature({"thickness_m": "  180 "}) == signature({"thickness_m": 180.0})


# --------------------------------------------------------------------
# F. results feeding other results
# --------------------------------------------------------------------
def upstream(result_id="res-20260813-11111111", sample_id="smp-A",
             label="film_A", supplies="sheet_resistance",
             runs=("vanderpauw-0001-20260813T090000",
                   "vanderpauw-0002-20260813T090500")):
    return UpstreamResult(
        result_id=result_id, method_tag="vdp_sheet_resistance:1",
        sample_id=sample_id, sample_label=label, supplies=supplies,
        run_ids=runs)


def test_an_upstream_result_from_another_sample_is_refused(check):
    """The mixed-sample gate, one indirection out.

    The mixed-sample check that already covers measured runs has to
    cover carried-over results too, or it is defeated by the number
    arriving through a box instead of a table row. A Hall carrier
    density computed against another film's sheet resistance is
    arithmetically perfect and physically meaningless - the same fault
    wearing a different hat.
    """
    calc = make_input(sample_id="smp-B", sample_label="film_B",
                      upstream=(upstream(),))
    with pytest.raises(CalculationRefused) as excinfo:
        validate(calc)
    message = str(excinfo.value)
    check("names the sample it came from", "film_A" in message, message)
    check("names the sample being calculated", "film_B" in message, message)
    check("names which input it filled", "sheet_resistance" in message, message)


def test_an_upstream_result_from_the_same_sample_passes():
    validate(make_input(upstream=(upstream(),)))


def test_upstream_runs_are_not_merged_into_the_calculations_own(check):
    """The bill-of-materials rule.

    Van der Pauw's runs are behind Hall's sheet resistance; they are not
    behind Hall's voltages. A header that listed them together would
    claim measurements the calculation never looked at, and - worse -
    `require_set()` would see Van der Pauw's positions among Hall's
    eight combinations and refuse a complete set as unexpected.
    """
    calc = make_input(sources=(source(),), upstream=(upstream(),))
    check("own runs stay own", calc.source_run_ids == (source().run_id,),
          calc.source_run_ids)
    check("upstream runs are reachable separately",
          calc.upstream_run_ids == upstream().run_ids, calc.upstream_run_ids)
    check("no overlap",
          not set(calc.source_run_ids) & set(calc.upstream_run_ids))
    check("the upstream result is named",
          calc.source_result_ids == (upstream().result_id,))


def test_recalculating_upstream_makes_a_result_stale(check):
    """H4: the result *id* is in the signature, not only the number.

    Recalculating Van der Pauw and getting a numerically identical sheet
    resistance would otherwise leave a Hall result citing a result the
    operator never used. The number is the same; the provenance is not,
    and the provenance is what the header claims.
    """
    values = {"resistance_ohm": InputValue(1000.0, "\u03a9", "1000"),
              "thickness_m": InputValue(1.8e-4, "m", "180")}
    first = derive(make_input(values=values, upstream=(upstream(),)),
                   outputs={"rs": 1.0})
    same_numbers_new_result = make_input(
        values=values,
        upstream=(upstream(result_id="res-20260813-22222222"),))

    check("a new upstream result is stale",
          first.is_stale(same_numbers_new_result.input_signature()))
    check("the same one is not",
          not first.is_stale(
              make_input(values=values,
                         upstream=(upstream(),)).input_signature()))
    reasons = first.stale_because(same_numbers_new_result.input_signature())
    check("says which upstream moved",
          any("upstream" in r for r in reasons), reasons)


def test_no_upstream_adds_no_signature_fields(check):
    """Why Van der Pauw, the IV sweep and the 4PP are untouched by this.

    `upstream_signature_items({})` is empty, so a calculation with no
    carried-over inputs has exactly the fields it had before. Were it to
    add a constant field instead, every experiment's panel-side
    signature would have to gain the same key on the same day or the
    results would read as permanently stale - the Wave 5a-i failure,
    reintroduced across four experiments at once.
    """
    check("empty in, empty out", upstream_signature_items(()) == {})
    plain = make_input().input_signature()
    with_upstream = make_input(upstream=(upstream(),)).input_signature()
    check("no extra fields without upstream",
          set(dict(plain)) == {"resistance_ohm", "thickness_m", "_sample"},
          sorted(dict(plain)))
    check("one extra field with it",
          set(dict(with_upstream)) - set(dict(plain))
          == {"_upstream_sheet_resistance"},
          sorted(dict(with_upstream)))


def test_the_header_names_the_upstream_result_and_its_runs(check):
    """What somebody opening the CSV in six months actually reads."""
    result = derive(make_input(sources=(source(),), upstream=(upstream(),)),
                    outputs={"rs": 1.0})
    meta = result.to_metadata()
    line = meta.get("input_sheet_resistance_from", "")
    check("the upstream result id is there", upstream().result_id in line, line)
    check("its method and version are there",
          "vdp_sheet_resistance:1" in line, line)
    check("its runs are there",
          all(r in line for r in upstream().run_ids), line)
    check("and they are not in source_run_ids",
          not any(r in meta["source_run_ids"] for r in upstream().run_ids),
          meta["source_run_ids"])


def test_an_upstream_result_survives_the_freeze(check):
    """Frozen like the rest of the chain - a provenance record that can
    be edited afterwards is not evidence."""
    result = derive(make_input(upstream=(upstream(),)), outputs={"rs": 1.0})
    check("tuple, not list", isinstance(result.upstream, tuple))
    with pytest.raises(Exception):
        result.upstream = ()
