"""Frozen run-parameter snapshots and the units convention.

The units rule is house rule 5, `docs/rules/05-si-inside.md`.

The wave plan states the proof for this module in one line:

  *build a params object, mutate every source variable, assert the
  snapshot is unchanged.*

`test_snapshot_is_immune_to_later_edits` is that, done exhaustively -
it walks every field rather than checking the two somebody remembered.
`assert_snapshot_immune` is factored out because Waves 3 and 5 need the
same proof for the other three experiments and should not each rewrite
it.

The second half of the file is the units check. It is a meta-test in
the spirit of `test_meta.py`: rather than asserting that some particular
field is in metres, it asserts that *no numeric field anywhere* fails to
say what unit it is in. A convention a test cannot check is a convention
that drifts on the first busy afternoon.
"""
import dataclasses

import pytest

from core import units
from core.identity import SampleRegistry
from core.parameters import (
    PARAMETERS_SCHEMA_VERSION,
    FourPointProbeParameters,
    RunParameters,
)

# every concrete parameter class Wave 2 ships. Waves 3 and 5 add the
# other experiments here; the meta-tests below then cover them with no
# further edits, which is the point of listing them in one place.
PARAMETER_CLASSES = [RunParameters, FourPointProbeParameters]


def _sample():
    return SampleRegistry().ref("ITO 3")


def _fourpp(**overrides):
    values = dict(
        sample=_sample(),
        dataset="run",
        mode="triangular",
        currents_a=[-1e-3, 0.0, 1e-3],
        middle_start_n=1,
        middle_len_n=2,
        delay_s=0.25,
        reversals_n=4,
        compliance_v=0.3,
        width_m=10e-3,
        length_m=20e-3,
        thickness_m=100e-9,
    )
    values.update(overrides)
    return FourPointProbeParameters(**values)


# ------------------------------------------------------------------
# immutability - the wave plan's stated proof
# ------------------------------------------------------------------
def assert_snapshot_immune(snapshot, mutate):
    """Take a before-picture, run `mutate`, assert nothing moved.

    Shared with Waves 3 and 5, where `mutate` will be "set every Tk
    variable in the panel to a different value". Compares field by field
    rather than with `==` so a failure names the field that moved.
    """
    before = {f.name: getattr(snapshot, f.name)
              for f in dataclasses.fields(snapshot)}
    mutate()
    moved = [name for name, value in before.items()
             if getattr(snapshot, name) != value]
    assert not moved, f"snapshot changed after the source did: {moved}"


def test_snapshot_is_immune_to_later_edits():
    """A snapshot is immune to later edits.

    The source list is mutated in place *and* rebound, because those are
    two different bugs: a frozen dataclass stops the second on its own
    and does nothing about the first.
    """
    currents = [-1e-3, 0.0, 1e-3]
    params = _fourpp(currents_a=currents)

    def mutate():
        currents.append(99.0)          # in-place, through the shared list
        currents[0] = 42.0
        currents.clear()

    assert_snapshot_immune(params, mutate)
    assert params.currents_a == (-1e-3, 0.0, 1e-3)


def test_every_field_refuses_assignment():
    """Walks the fields rather than spot-checking two of them, so a
    field added later is covered without anyone remembering to."""
    params = _fourpp()
    for f in dataclasses.fields(params):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(params, f.name, None)


@pytest.mark.parametrize("cls", PARAMETER_CLASSES)
def test_no_parameter_field_holds_a_mutable_container(cls):
    """A frozen dataclass stops rebinding, not mutation.

    A field holding a live list is not a snapshot, it is a view of the
    thing the operator is still editing. This is the check that catches
    a field added in a later wave that looks frozen and is not.
    """
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name == "sample":
            kwargs["sample"] = _sample()
        elif f.default is dataclasses.MISSING and \
                f.default_factory is dataclasses.MISSING:  # pragma: no cover
            pytest.skip(f"{cls.__name__}.{f.name} has no default to build from")
    instance = cls(**kwargs)
    bad = [f.name for f in dataclasses.fields(instance)
           if isinstance(getattr(instance, f.name), (list, dict, set,
                                                     bytearray))]
    assert not bad, (
        f"{cls.__name__} holds mutable container(s) in {bad}; convert them "
        f"to a tuple/frozenset in __post_init__ or the snapshot is a view, "
        f"not a copy")


def test_replacing_makes_a_new_object():
    params = _fourpp()
    other = params.replacing(delay_s=1.0)
    assert params.delay_s == 0.25        # the original is untouched
    assert other.delay_s == 1.0
    assert other is not params


# ------------------------------------------------------------------
# identity carried by the snapshot
# ------------------------------------------------------------------
def test_snapshot_keeps_the_label_it_captured():
    """Renaming the sample must not relabel a run already recorded."""
    registry = SampleRegistry()
    params = _fourpp(sample=registry.ref("ITO 3"))
    registry.rename(params.sample_id, "ITO 3 (contact redone)")

    assert params.sample_label == "ITO 3"
    assert registry.ref("ITO 3 (contact redone)").sample_id == params.sample_id


def test_metadata_carries_both_identifier_and_label():
    meta = _fourpp().to_metadata()
    assert meta["sample_id"].startswith("smp-")
    assert meta["sample_label"] == "ITO 3"
    assert meta["schema_version"] == PARAMETERS_SCHEMA_VERSION


def test_metadata_leaves_sequences_out():
    """A CSV column holding `(0.001, 0.002, 0.003)` is not something
    anyone can filter or group by. Sequence-valued parameters belong in
    the readings table, one row each."""
    meta = _fourpp().to_metadata()
    assert "currents_a" not in meta
    assert "sample" not in meta
    assert all(isinstance(v, (str, int, float, bool)) or v is None
               for v in meta.values())


# ------------------------------------------------------------------
# 4PP derived values and the units boundary
# ------------------------------------------------------------------
def test_expected_reading_count():
    params = _fourpp(currents_a=[1, 2, 3, 4], reversals_n=4)
    assert params.points_n == 4
    assert params.readings_n == 16


def test_middle_slice_matches_the_triangular_middle():
    params = _fourpp(currents_a=[0, 1, 2, 3, 4], middle_start_n=1,
                     middle_len_n=3)
    assert params.currents_a[params.middle_slice] == (1, 2, 3)


def test_geometry_converts_only_at_the_boundary():
    """SI inside, `fourpp_math`'s mm/µm at the single named boundary.

    The panel asks for mm and µm because that is what a caliper reads;
    the correction tables are published in mm and µm too. Between those
    two edges the suite holds metres, and this is the one place that
    converts back.
    """
    params = _fourpp(width_m=10e-3, length_m=20e-3, thickness_m=100e-9)
    width_mm, length_mm, thickness_um = params.as_math_geometry()
    assert width_mm == pytest.approx(10.0)
    assert length_mm == pytest.approx(20.0)
    assert thickness_um == pytest.approx(0.1)


def test_geometry_round_trips_through_the_boundary():
    params = _fourpp(width_m=1.5e-3, length_m=7.25e-3, thickness_m=3.4e-6)
    w_mm, l_mm, t_um = params.as_math_geometry()
    assert units.mm_to_m(w_mm) == pytest.approx(params.width_m)
    assert units.mm_to_m(l_mm) == pytest.approx(params.length_m)
    assert units.um_to_m(t_um) == pytest.approx(params.thickness_m)


# ------------------------------------------------------------------
# the units convention, made executable
# ------------------------------------------------------------------
#: Fields that carry no physical quantity. Listed explicitly so that
#: adding one is a deliberate act rather than a silent exemption.
UNITLESS_FIELDS = {"sample", "dataset", "mode", "captured_at",
                   "schema_version"}


@pytest.mark.parametrize("cls", PARAMETER_CLASSES)
def test_every_numeric_field_declares_its_unit(cls):
    """House rule 5, enforced instead of documented.

    A field called `thickness` is a promise with no terms - metres,
    millimetres or microns depending on which panel it came from. This
    is the test that makes `thickness_m` the only spelling that gets
    past review, and it covers experiments added in later waves for
    free, provided they are listed in `PARAMETER_CLASSES`.
    """
    undeclared = []
    for f in dataclasses.fields(cls):
        if f.name in UNITLESS_FIELDS:
            continue
        if units.unit_of(f.name) is None:
            undeclared.append(f.name)
    assert not undeclared, (
        f"{cls.__name__}: field(s) {undeclared} do not name their unit. "
        f"Add a suffix from core.units.UNIT_SUFFIXES (use '_n' for a "
        f"dimensionless count), or add the field to UNITLESS_FIELDS if it "
        f"genuinely carries no quantity.")


def test_unit_of_reads_the_longest_suffix_first():
    """`sheet_resistance_ohm_sq` is ohms per square, not ohms.

    Longest-first matching is not a detail: getting it backwards
    mislabels exactly the quantities most worth labelling correctly.
    """
    assert units.unit_of("sheet_resistance_ohm_sq") == "\u03a9/sq"
    assert units.unit_of("contact_resistance_ohm") == "\u03a9"
    assert units.unit_of("source_current_a") == "A"
    assert units.unit_of("points_n") == ""          # declared dimensionless
    assert units.unit_of("thickness") is None       # undeclared


def test_label_reads_as_a_column_heading():
    assert units.label("source_current_a") == "Source current (A)"
    assert units.label("thickness_m") == "Thickness (m)"
    assert units.label("mode") == "Mode"


@pytest.mark.parametrize("forward, back", units.INVERSE_PAIRS)
def test_conversions_round_trip(forward, back):
    """Covers the mA/A, µm/m and gauss/tesla pairs."""
    to_base = units.CONVERSIONS[forward]
    from_base = units.CONVERSIONS[back]
    for value in (0.0, 1.0, 2.54, 1e-6, 1234.5, -7.25):
        assert from_base(to_base(value)) == pytest.approx(value, abs=1e-12)


def test_every_conversion_is_registered():
    """A conversion added to the module without an entry in CONVERSIONS
    is a conversion nothing tests."""
    registered = set(units.CONVERSIONS.values())
    exported = {value for name, value in vars(units).items()
                if callable(value) and "_to_" in name
                and not name.startswith("_")}
    missing = sorted(f.__name__ for f in exported - registered)
    assert not missing, f"not listed in units.CONVERSIONS: {missing}"


def test_gauss_to_tesla_is_the_factor_hall_needs():
    """Lab magnets are quoted in gauss; the Hall equations want tesla.
    A factor of 10 000 wrong here is a carrier density 10 000x wrong and
    nothing in the output looks unusual."""
    assert units.gauss_to_tesla(5000) == pytest.approx(0.5)
    assert units.tesla_to_gauss(0.5) == pytest.approx(5000)
