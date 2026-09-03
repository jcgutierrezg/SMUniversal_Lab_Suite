"""
Structured calculation inputs, provenance and method versions.

Full treatment in `docs/architecture/calculation-provenance.md`;
the house rule is `docs/rules/10-provenance.md`.

Why this exists
---------------
Every calculation in this suite currently begins by reading strings out
of entry boxes and ends by writing strings into labels. Between those
two points the numbers are real, but nothing anywhere records *which
measurements they came from*. Three failures follow, and all three
produce a plausible number rather than an error:

* a sheet resistance copied from sample A is calculated against the
  geometry now typed for sample B (the mixed-sample gate);
* a derived value is filed against whichever sample name happens to be
  in the box when Save is pressed, rather than the one that was measured
  (the provenance binding);
* a result stays on screen, and reaches the saved file, after the inputs
  under it have been edited (the staleness gate).

The analogy
-----------
A calibration certificate. The number on it is worth nothing on its own;
what makes it usable is that it names the instrument, the standard, the
date and the procedure revision. Strip those off and you have a number
that looks exactly as authoritative and cannot be checked by anybody.
`DerivedResult` is that certificate, and it is issued by the same
operation that computes the number so the two cannot be separated.

What this module is not
-----------------------
It does no arithmetic. The physics stays in `hall_math`, `vdp_math`,
`iv_math` and `fourpp_math`, which are under a bit-identical-to-the
notebook guard and are not touched by this wave. This module wraps those
functions: it checks the inputs are a coherent set before they go in,
and it labels what comes out.

Note on `InputValue`
--------------------
`core/units.py` deliberately refused to introduce a value-with-unit
object, because every expression in the maths modules would have grown a
`.value`. That reasoning still holds and this does not contradict it:
`InputValue` lives strictly *above* the maths. It is unwrapped at the
call boundary, exactly like `FourPointProbeParameters.as_math_geometry()`
unwraps SI into the millimetres the Ossila tables are published in. No
`InputValue` is ever passed to a function in an experiment's math
module.

The typed text is carried alongside the SI number for a specific reason
measured: converting 180 µm to metres and back gives
179.99999999999997, and that residue was reaching the CSV header. No
arithmetic fixes it. Keeping what the operator actually typed means the
header can report `180` while the calculation uses the SI float, and
neither has to lie about the other.
"""
from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from types import MappingProxyType

from core.identity import new_result_id

#: Bumped when the *shape* of a stored `DerivedResult` changes in a way
#: a reader would need to know about. Stored files carry it - see
#: `docs/reference/schema.md` - so every file written has had one.
CALCULATION_SCHEMA_VERSION = 1


# --------------------------------------------------------------------
# the method table: every equation carries a version
# --------------------------------------------------------------------
#: method name -> (version, what it computes).
#:
#: One table, in one file, deliberately. The alternative - each maths
#: module declaring its own version - would put the version next to the
#: equation, which reads better but means `core` importing `experiments`
#: to collect them, reversing the layering rule - nothing in `core/`
#: imports from `experiments/` - for a lookup table of seven rows.
#:
#: **Bump a version when the number a method returns changes for an
#: input it already accepted.** Not when a docstring is rewritten, not
#: when an argument is renamed, and not when a new failure mode is
#: caught - only when a historical result would come out different.
#: `tests/test_calculation_golden.py` is what forces the question: it
#: holds a known dataset per method, and a formula change that does not
#: bump the version fails it.
METHODS = {
    "fourpp_sheet_resistance": (1, "Ossila 4PP: R -> Rs with the "
                                   "thickness and geometry corrections"),
    "vdp_sheet_resistance": (1, "Van der Pauw: Rh, Rv -> Rs"),
    "vdp_resistivity": (1, "Van der Pauw: Rs, thickness -> rho"),
    "hall_voltage": (1, "Hall: eight measured voltages -> V_H"),
    "hall_sheet_carrier_density": (1, "Hall: I, B, V_H -> n_s"),
    "hall_mobility": (1, "Hall: n_s, Rs -> mu"),
    "hall_bulk_carrier_density": (1, "Hall: n_s, thickness -> n"),
    "hall_resistivity": (1, "Hall: Rs, thickness -> rho"),
    "iv_linear_fit": (1, "IV sweep: sourced/measured -> slope, R^2"),
}


class UnknownMethod(KeyError):
    """A calculation named a method that is not in `METHODS`."""


def version_of(method):
    """The registered version of `method`. Raises `UnknownMethod`."""
    try:
        return METHODS[method][0]
    except KeyError:
        raise UnknownMethod(
            f"{method!r} is not a registered calculation method; add it to "
            f"core.calculation.METHODS. Known: {sorted(METHODS)}") from None


def tag(method):
    """`'hall_coefficient:1'` - a method name welded to its version."""
    return f"{method}:{version_of(method)}"


# --------------------------------------------------------------------
# refusal
# --------------------------------------------------------------------
class CalculationRefused(ValueError):
    """The inputs are not a coherent set, so no number was produced.

    The requirement is not "refuses mixed samples" - it is
    "rejects them **and explains the specific incompatibility**". A
    dialog reading "invalid input" tells the operator to try again;
    one reading "this resistance was measured on ITO_1, the geometry is
    set for ITO_2" tells them what to do. So the reason is a required
    argument, not an optional one.
    """

    def __init__(self, reason, detail=""):
        self.reason = str(reason)
        self.detail = str(detail)
        super().__init__(
            self.reason + (f"\n\n{self.detail}" if self.detail else ""))


# --------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------
@dataclass(frozen=True)
class InputValue:
    """One number going into a calculation, with its unit and origin.

    `text` is what the operator typed, when it was typed. Empty when the
    value came from a measurement rather than a keyboard - see the note
    on the round trip at the top of this module.
    """

    value: float
    unit: str = ""
    text: str = ""

    @property
    def is_finite(self):
        return isinstance(self.value, (int, float)) and math.isfinite(
            float(self.value))

    def display(self):
        """The typed text if there was one, else the number."""
        return self.text or f"{self.value:.9g}"

    def __str__(self):
        return f"{self.display()} {self.unit}".strip()


@dataclass(frozen=True)
class SourceRow:
    """A completed measurement that a calculation is drawing on.

    `row_ids` is the set of raw readings used, in `core.identity`'s
    `<run_id>#0042` form. For a fitted resistance that is every reading
    in the run; the fit is not attributable to any one of them.
    """

    run_id: str
    sample_id: str
    sample_label: str = ""
    row_ids: tuple = ()
    position: str = ""
    polarity: str = ""

    def __post_init__(self):
        object.__setattr__(self, "row_ids", tuple(self.row_ids))


@dataclass(frozen=True)
class UpstreamResult:
    """A `DerivedResult` from one calculation feeding another.

    Hall needs a sheet resistance it cannot measure. Van der Pauw
    produces one, with its own provenance chain already attached. So the
    thing crossing between them is not a measurement and not a bare
    number - it is a *result*, and it arrives with a lineage of its own.

    Why this is a separate field from `sources` rather than four more
    `SourceRow`s. A bill of materials: when a sub-assembly goes into a
    product you cite its part number and its own BOM stays attached to
    it. Paste its screws into your parts list instead and nobody can
    tell afterwards which screws belong to which assembly. Concretely,
    folding Van der Pauw's four runs into Hall's `sources` would make
    `require_set()` see Pos1-4 among the eight Hall combinations and
    refuse them as unexpected, and would leave a header claiming eight
    Hall voltages came from twelve runs.

    `supplies` names the input this result fills - `"sheet_resistance"`
    - so the saved header can say which box the number went into rather
    than merely that something upstream existed.
    """

    result_id: str
    method_tag: str
    sample_id: str
    sample_label: str = ""
    supplies: str = ""
    run_ids: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "run_ids", tuple(self.run_ids))

    @classmethod
    def of(cls, result, supplies):
        """Build one from the `DerivedResult` that is being consumed."""
        return cls(
            result_id=result.result_id,
            method_tag=result.method_tag,
            sample_id=result.sample_id,
            sample_label=result.sample_label_at_calculation,
            supplies=supplies,
            run_ids=tuple(result.source_run_ids),
        )


@dataclass(frozen=True)
class ProvidedValue:
    """What one experiment hands another when asked for a quantity.

    The number, the unit, and the result it came out of - kept together
    so the receiving side cannot take the number and forget the lineage,
    which is the whole failure this wave exists to prevent.

    `stage_temps_c` is the stage temperature each contributing run
    recorded. It is here rather than fetched later because the receiver
    has no business reaching into another experiment's run store, and
    because it is the one comparison that survives the session strip:
    sample name and thickness are shared there and can no longer
    disagree, but the stage may genuinely have drifted between the two
    measurements, and that is physics rather than a typo.
    """

    name: str
    value: float
    unit: str
    result: "DerivedResult"
    stage_temps_c: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "stage_temps_c", tuple(self.stage_temps_c))

    def as_upstream(self):
        return UpstreamResult.of(self.result, supplies=self.name)


def upstream_signature_items(upstream):
    """The staleness fields contributed by a set of upstream results.

    **One function, deliberately, called from both sides.** The panel
    samples its widgets to build a current signature; the calculation
    builds its own from the input object; and the two must produce
    identical field names or the result reads as permanently stale and
    its numbers stop reaching the file with nothing on screen to say
    why. That bug shipped once, with `thickness_m` against
    `thickness_um`. Two call sites computing the same thing separately
    is how it happened, so there is only one.

    Empty in, empty out - an experiment with no upstream results gets no
    extra fields, which is why Van der Pauw, the IV sweep and the 4PP
    are untouched by this.

    The result *id* is in the signature, not just the value it supplied.
    Recalculating Van der Pauw and getting a numerically identical sheet
    resistance would otherwise leave a Hall result citing a result the
    operator never used. Provenance is an input like any other.
    """
    return {f"_upstream_{u.supplies or u.method_tag}": u.result_id
            for u in upstream}


@dataclass(frozen=True)
class CalculationInput:
    """Everything one calculation needs, checked as a set.

    Built on the UI thread from widgets, then handed to `validate()` and
    `derive()`. The calculation panel never passes raw table rows down;
    this is the structured object house rule 10 asks for, and the only
    thing the derivation sees.
    """

    method: str
    sample_id: str
    sample_label: str = ""
    values: dict = field(default_factory=dict)
    sources: tuple = ()
    required: tuple = ()
    upstream: tuple = ()

    def __post_init__(self):
        # Frozen stops rebinding; it does not stop somebody appending to
        # a list this points at. Same reasoning as core/parameters.py.
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "required", tuple(self.required))
        object.__setattr__(self, "upstream", tuple(self.upstream))

    # ---- convenience ----
    def value(self, name):
        """The bare SI float for `name`, for handing to a math module."""
        return self.values[name].value

    @property
    def source_run_ids(self):
        return tuple(s.run_id for s in self.sources)

    @property
    def source_row_ids(self):
        return tuple(r for s in self.sources for r in s.row_ids)

    @property
    def source_result_ids(self):
        return tuple(u.result_id for u in self.upstream)

    @property
    def upstream_run_ids(self):
        """Runs behind the upstream results - kept apart from this
        calculation's own `source_run_ids` on purpose. They are one
        indirection further away, and a header that merged them would
        claim measurements this calculation never looked at."""
        return tuple(r for u in self.upstream for r in u.run_ids)

    def input_signature(self):
        """The fingerprint staleness is judged against.

        The sample is in it as well as the numbers. Changing which
        sample the panel refers to invalidates a result just as surely
        as changing a thickness does, and it is the change most likely
        to go unnoticed because the displayed numbers do not move.
        """
        items = dict(self.values)
        items["_sample"] = self.sample_label or self.sample_id
        items.update(upstream_signature_items(self.upstream))
        return signature(items)


# --------------------------------------------------------------------
# validation: mixed samples, provenance, complete sets
# --------------------------------------------------------------------
def validate(calc, *, distinct_runs=False):
    """Refuse an incoherent input set before any arithmetic happens.

    Raises `CalculationRefused`. The checks, in the order a wrong answer
    is most likely to come from:

    1. the method is registered, so the result can be versioned;
    2. every required value is present and finite;
    3. every source measurement belongs to the sample being calculated
       (the mixed-sample check);
    4. optionally, that no run is used twice where distinct runs are
       expected - Van der Pauw's four positions, Hall's eight
       polarity combinations.

    Note what is *not* checked here: that the source runs completed.
    That is guaranteed structurally rather than by inspection - a run
    only reaches `RunStore` through `RunContext.commit()`, and the
    commit gate refuses an incomplete run. `test_calculation.py` asserts
    the property; it does not re-implement the gate.
    """
    version_of(calc.method)          # raises UnknownMethod if unregistered

    missing = [name for name in calc.required if name not in calc.values]
    if missing:
        raise CalculationRefused(
            "Some values this calculation needs are missing.",
            "Missing: " + ", ".join(sorted(missing)))

    unusable = [name for name in calc.required
                if not calc.values[name].is_finite]
    if unusable:
        raise CalculationRefused(
            "Some values this calculation needs are not usable numbers.",
            "Check: " + ", ".join(sorted(unusable)))

    foreign = [s for s in calc.sources if s.sample_id != calc.sample_id]
    if foreign:
        other = foreign[0]
        raise CalculationRefused(
            "These measurements are from a different sample.",
            f"The measurement was taken on "
            f"'{other.sample_label or other.sample_id}', but the "
            f"calculation is set up for "
            f"'{calc.sample_label or calc.sample_id}'.\n\n"
            f"A calculation that mixes samples is arithmetically fine "
            f"and scientifically meaningless, so it is refused rather "
            f"than warned about.")

    # The mixed-sample check again, one indirection out. A sheet
    # resistance measured on
    # ITO_1 and fed into a Hall calculation set up for ITO_2 is the
    # original mixed-sample fault wearing a different hat: the number
    # arrives through a box rather than through a table row, and is
    # every bit as arithmetically perfect and physically meaningless.
    #
    # This is the check that survives the session strip, which makes
    # the sample name shared between the two tabs, so they cannot
    # disagree at any one instant - but the operator can still calculate
    # Van der Pauw, rename the sample, and calculate Hall, and then the
    # Rs in the box belongs to a sample nobody is measuring any more.
    foreign_upstream = [u for u in calc.upstream if u.sample_id != calc.sample_id]
    if foreign_upstream:
        other = foreign_upstream[0]
        raise CalculationRefused(
            "A value carried over from another calculation belongs to a "
            "different sample.",
            f"{other.supplies or 'A value'} came from "
            f"'{other.sample_label or other.sample_id}' "
            f"({other.method_tag}), but this calculation is set up for "
            f"'{calc.sample_label or calc.sample_id}'.\n\n"
            f"Recalculate it for this sample, or clear the box and enter "
            f"a value measured on it.")

    if distinct_runs:
        seen = {}
        for source in calc.sources:
            seen.setdefault(source.run_id, 0)
            seen[source.run_id] += 1
        repeated = sorted(k for k, n in seen.items() if n > 1)
        if repeated:
            raise CalculationRefused(
                "The same measurement has been used more than once.",
                "This calculation needs a separate run for each input. "
                "Repeated: " + ", ".join(repeated))


def require_set(sources, expected, *, what="position"):
    """Check the source set is exactly `expected`.

    Used by Van der Pauw (Pos1-4) and Hall (the eight polarity/position
    combinations). Written now, in this wave, with tests; wired up in
    the wave that gives those two experiments their run lifecycle - the
    same order the validators were built in, before an experiment
    called them.

    `expected` is a set of the keys `key_of` produces. Missing and
    duplicated are reported separately because they mean different
    things at the bench: missing is an unfinished measurement, duplicate
    is the wrong row ticked.
    """
    def key_of(source):
        if what == "position":
            return source.position
        if what == "polarity":
            return source.polarity
        return f"{source.position}{source.polarity}"

    found = {}
    for source in sources:
        found.setdefault(key_of(source), []).append(source.run_id)

    expected = set(expected)
    missing = sorted(expected - set(found))
    extra = sorted(set(found) - expected)
    duplicated = sorted(k for k, runs in found.items() if len(runs) > 1)

    problems = []
    if missing:
        problems.append("missing " + ", ".join(missing))
    if extra:
        problems.append("unexpected " + ", ".join(extra))
    if duplicated:
        problems.append("more than one of " + ", ".join(duplicated))

    if problems:
        raise CalculationRefused(
            "The selected measurements are not a complete set.",
            f"Expected exactly one each of "
            f"{', '.join(sorted(expected))} - {'; '.join(problems)}.")


# --------------------------------------------------------------------
# staleness
# --------------------------------------------------------------------
def signature(values):
    """A comparable fingerprint of the inputs a result was built from.

    Takes raw widget text as readily as parsed numbers: anything that
    looks like a number is normalised to a float so that `180` and
    `180.0` are the same input, and anything else is compared as
    stripped text. That matters because this is called from a Tk trace
    on every keystroke, long before the value is valid enough to parse
    properly.

    Deliberately not a hash. A tuple compares just as well, costs
    nothing at this size, and when a result is unexpectedly stale the
    two tuples can be printed side by side and the differing field read
    straight off - which a pair of hex digests cannot do.
    """
    out = []
    for name in sorted(values):
        raw = values[name]
        if isinstance(raw, InputValue):
            raw = raw.text or raw.value
        try:
            out.append((name, float(raw)))
        except (TypeError, ValueError):
            out.append((name, str(raw).strip()))
    return tuple(out)


def signature_difference(recorded, current):
    """What changed between two signatures, in words.

    Returns a list of short strings naming each field that moved, for
    the console log. Staleness is otherwise a bare boolean, and "this
    result is stale" without "because the thickness went from 180 to
    900" sends the operator hunting.

    It also catches a failure mode that is not staleness at all. If the
    two signatures share no field names, the code that built the result
    and the code that samples the widgets have drifted apart - the
    result then reads as permanently stale and its numbers silently stop
    reaching the file, with nothing on screen to say why. That is a
    programming error rather than an operator action, and it is named
    as one here so it shows up in the log as such. Found exactly this
    way once: the Van der Pauw calculation stored `thickness_m`
    and the trace sampled `thickness_um`.
    """
    recorded, current = dict(recorded), dict(current)
    if recorded and current and not (set(recorded) & set(current)):
        return [f"signature fields do not match at all: recorded "
                f"{sorted(recorded)}, sampled {sorted(current)} - this is a "
                f"wiring fault, not an edit"]

    out = []
    for name in sorted(set(recorded) | set(current)):
        was, now = recorded.get(name, "(absent)"), current.get(name, "(absent)")
        if was != now:
            out.append(f"{name}: {was} -> {now}")
    return out


# --------------------------------------------------------------------
# the result, and the chain back to its measurements
# --------------------------------------------------------------------
@dataclass(frozen=True)
class DerivedResult:
    """A calculated value and the chain back to the measurements.

    The field list is the provenance chain, with `signature` added for
    staleness. Frozen: a
    result is a statement about a moment, and editing one after the fact
    is how a provenance chain stops being evidence.
    """

    result_id: str
    method: str
    version: int
    sample_id: str
    sample_label_at_calculation: str
    outputs: dict
    inputs: dict = field(default_factory=dict)
    source_run_ids: tuple = ()
    source_row_ids: tuple = ()
    upstream: tuple = ()
    notes: tuple = ()
    signature: tuple = ()
    calculated_at: str = ""
    schema_version: int = CALCULATION_SCHEMA_VERSION

    def __post_init__(self):
        object.__setattr__(self, "inputs", MappingProxyType(dict(self.inputs)))
        object.__setattr__(self, "outputs",
                           MappingProxyType(dict(self.outputs)))
        object.__setattr__(self, "source_run_ids", tuple(self.source_run_ids))
        object.__setattr__(self, "source_row_ids", tuple(self.source_row_ids))
        object.__setattr__(self, "upstream", tuple(self.upstream))
        object.__setattr__(self, "notes", tuple(self.notes))
        object.__setattr__(self, "signature", tuple(self.signature))
        if not self.calculated_at:
            object.__setattr__(self, "calculated_at",
                               datetime.datetime.now().isoformat())

    @property
    def method_tag(self):
        return f"{self.method}:{self.version}"

    @property
    def source_result_ids(self):
        """Results this one was built on top of. A chain, not a list:
        each of these carries its own runs and its own upstream."""
        return tuple(u.result_id for u in self.upstream)

    def is_stale(self, current_signature):
        """True if the inputs have moved since this was calculated.

        The caller supplies the current signature rather than this
        object reaching back for it, because the inputs live in Tk
        variables and a frozen dataclass has no business reading those.
        """
        return tuple(current_signature) != self.signature

    def stale_because(self, current_signature):
        """Which inputs moved, for the log. See `signature_difference`."""
        return signature_difference(self.signature, current_signature)

    @property
    def signature_fields(self):
        """The field names this result's freshness is judged on."""
        return tuple(name for name, _ in self.signature)

    def to_metadata(self):
        """The flat block that goes into the saved CSV header.

        Provenance first, then the inputs, then the outputs - reading
        order for somebody opening the file in six months who needs to
        know what they are looking at before they look at it.
        """
        out = {
            "result_id": self.result_id,
            "calculation_method": self.method_tag,
            "calculated_at": self.calculated_at,
            "calculation_schema_version": self.schema_version,
            "sample_id": self.sample_id,
            "sample_label_at_calculation": self.sample_label_at_calculation,
            "source_run_ids": (" ".join(self.source_run_ids)
                               or "(none - value typed by hand)"),
            "source_row_ids": compact_row_ids(self.source_row_ids),
        }
        # Kept as their own lines rather than merged into
        # `source_run_ids`. The runs behind an upstream result are one
        # indirection further out, and somebody reading this header in
        # six months needs to be able to tell "Hall measured these four
        # runs" from "and took a sheet resistance that came from those
        # four other ones".
        for item in self.upstream:
            key = f"input_{item.supplies}_from" if item.supplies \
                else "input_carried_over_from"
            out[key] = (f"{item.result_id} ({item.method_tag}, runs: "
                        f"{' '.join(item.run_ids) or 'none - typed by hand'})")
        for name, item in self.inputs.items():
            out[f"input_{name}"] = str(item)
        for name, value in self.outputs.items():
            out[f"result_{name}"] = value
        if self.notes:
            out["calculation_notes"] = " ".join(self.notes)
        return out


def compact_row_ids(row_ids):
    """`run-0007-...#0001-0030` rather than thirty near-identical ids.

    Reading identifiers are `<run_id>#NNNN`, so a run's worth of them
    differ only in the last four digits. Written out in full they make
    the CSV header unreadable, which is a real cost: a header nobody
    scrolls through is a provenance chain nobody checks. Contiguous
    runs of readings from one run collapse to a range; anything
    irregular is written out so the compaction cannot hide a gap.
    """
    if not row_ids:
        return "(none)"

    by_run = {}
    for row_id in row_ids:
        run_id, _, index = str(row_id).rpartition("#")
        if not run_id or not index.isdigit():
            by_run.setdefault(None, []).append(str(row_id))
            continue
        by_run.setdefault(run_id, []).append(int(index))

    parts = []
    for run_id, indices in by_run.items():
        if run_id is None:
            parts.extend(indices)
            continue
        indices = sorted(indices)
        contiguous = indices == list(range(indices[0], indices[0] + len(indices)))
        if len(indices) > 2 and contiguous:
            parts.append(f"{run_id}#{indices[0]:04d}-{indices[-1]:04d}")
        else:
            parts.extend(f"{run_id}#{i:04d}" for i in indices)
    return " ".join(parts)


def derive(calc, outputs, *, notes=(), when=None):
    """Issue a `DerivedResult` for a validated `CalculationInput`.

    Validation is *not* repeated here. Call `validate()` first: keeping
    them separate means a caller that wants extra checks - Van der
    Pauw's four distinct positions, say - can run them between the two
    rather than having to pass a growing bag of flags into one
    do-everything function.
    """
    return DerivedResult(
        result_id=new_result_id(when),
        method=calc.method,
        version=version_of(calc.method),
        sample_id=calc.sample_id,
        sample_label_at_calculation=calc.sample_label,
        inputs=dict(calc.values),
        outputs=dict(outputs),
        source_run_ids=calc.source_run_ids,
        source_row_ids=calc.source_row_ids,
        upstream=calc.upstream,
        notes=tuple(notes),
        signature=calc.input_signature(),
    )
