"""
Immutable run parameter snapshots (review §14, group B1).

Why this exists
---------------
Worker threads currently read Tk variables while a run is in progress,
and some values - a sample name, a geometry - have historically been
read when the run *finished* rather than when it started. Two failures
follow, and neither announces itself:

* the operator adjusts a field to set up the next measurement, and the
  one still running silently changes behaviour or metadata;
* Tk is not thread-safe, so reading a variable from a worker is
  undefined behaviour that usually works.

4PP already fixed one instance of this by hand - `_sweep_params()`
captures the geometry with the rest of the form rather than re-reading it
in `_finish_run()`, and the comment there records why. This module turns
that one-off into the mechanism.

The rule
--------
**Everything the worker needs is read once, on the Run press, on the UI
thread, into a frozen object. The worker gets that object and nothing
else.** After the snapshot is taken, no amount of typing in the window
can reach the running measurement.

The analogy
-----------
A works order, not a whiteboard. The whiteboard is what the shop floor
is currently planning; the works order is the printed copy that went out
with the job, and the job is built to the paper in the traveller even if
somebody has since wiped the board.

Immutability, actually
----------------------
`@dataclass(frozen=True)` stops you rebinding a field. It does *not*
stop you appending to a list one of those fields points at, and a
snapshot holding a live list is not a snapshot. So every sequence field
is converted to a tuple in `__post_init__`, and
`tests/test_parameters.py` walks every field of every parameter class
and asserts nothing mutable survives. That test is the one to keep: the
failure it guards against is a field added later that looks frozen and
is not.

Units
-----
Fields are SI base units and say so in their names, per `core.units`.
Where a downstream module wants something else - `fourpp_math` takes
millimetres and micrometres, because the Ossila correction tables are
published that way - the conversion happens in a named boundary method
on the parameter class and nowhere else. See
`FourPointProbeParameters.as_math_geometry()`.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field, fields, replace

from core.identity import SampleRef


#: Bumped when the *shape* of a stored snapshot changes in a way that a
#: reader would need to know about. Wave 7 (§55) writes this into files;
#: it is declared now so that the first file written already has one,
#: rather than needing a migration to acquire it later.
PARAMETERS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunParameters:
    """What every run records regardless of experiment.

    Subclass this per experiment and add the experiment's own fields.
    Do not add mutable defaults; see the note on immutability above.
    """

    sample: SampleRef
    dataset: str = "run"
    captured_at: str = field(
        default_factory=lambda: datetime.datetime.now().isoformat())
    schema_version: int = PARAMETERS_SCHEMA_VERSION

    # ---- identity passthroughs ----
    @property
    def sample_id(self):
        return self.sample.sample_id

    @property
    def sample_label(self):
        """The label **as it was at Run press**, not as it is now."""
        return self.sample.label

    # ---- conversion at the boundary ----
    def to_metadata(self, exclude=()):
        """A flat dict for `run_store.Run(metadata=...)` and the CSV.

        Scalars only: nested objects and sequences are left out, because
        a CSV column holding `(0.001, 0.002, 0.003)` is not data anybody
        can filter on. Sequence-valued parameters belong in the readings
        table, one row each, which is the shape `build_sample_csv`
        already writes.

        `sample` is flattened into `sample_id` and `sample_label` so both
        reach the file - the identifier for provenance, the label for the
        human reading it.
        """
        out = {"sample_id": self.sample_id, "sample_label": self.sample_label}
        for f in fields(self):
            if f.name in ("sample",) or f.name in exclude:
                continue
            value = getattr(self, f.name)
            if isinstance(value, (str, int, float, bool)) or value is None:
                out[f.name] = value
        return out

    def replacing(self, **changes):
        """A *new* snapshot with some fields changed.

        There is no in-place edit and there should not be. If a run's
        parameters need to differ, that is a different run.
        """
        return replace(self, **changes)

    def describe(self):
        """One line for the console log, in declaration order."""
        parts = []
        for f in fields(self):
            if f.name in ("sample", "captured_at", "schema_version"):
                continue
            value = getattr(self, f.name)
            if isinstance(value, float):
                parts.append(f"{f.name}={value:g}")
            elif isinstance(value, tuple):
                parts.append(f"{f.name}=[{len(value)}]")
            else:
                parts.append(f"{f.name}={value}")
        return f"{self.sample} " + " ".join(parts)


@dataclass(frozen=True)
class FourPointProbeParameters(RunParameters):
    """One Ossila four-point-probe sweep, exactly as requested.

    4PP is Wave 3's pilot experiment, so this is the only concrete
    parameter class Wave 2 ships. Writing the other three now would mean
    writing them against an API that has not yet met an experiment;
    Waves 3 and 5 add them once the shape has been proven against real
    wiring.

    Geometry is stored in metres. The panel asks for W and L in
    millimetres and t in micrometres because that is what the operator
    reads off a caliper, and `fourpp_math` wants those same units
    because the Ossila correction tables are published in them. Both of
    those are boundaries; between them, this object holds metres like
    everything else in the suite. `as_math_geometry()` is the single
    place the conversion back happens.
    """

    mode: str = "triangular"

    # the sweep
    currents_a: tuple = ()
    middle_start_n: int = 0
    middle_len_n: int = 0
    delay_s: float = 0.0
    reversals_n: int = 1
    compliance_v: float = 0.0

    # the sample
    width_m: float = 0.0
    length_m: float = 0.0
    thickness_m: float = 0.0

    def __post_init__(self):
        # A frozen dataclass forbids rebinding, so the tuple conversion
        # goes through object.__setattr__. This is the documented way to
        # normalise a field in a frozen dataclass, not a way around the
        # freezing: it runs once, during construction, before anything
        # else can see the object.
        object.__setattr__(self, "currents_a", tuple(self.currents_a))

    # ---- derived, not stored ----
    @property
    def points_n(self):
        """How many source levels the sweep will visit."""
        return len(self.currents_a)

    @property
    def readings_n(self):
        """Total readings expected: one per level per reversal.

        Handed to `RunContext.expect()` so the completion gate can tell
        a short run from a complete one.
        """
        return self.points_n * self.reversals_n

    @property
    def middle_slice(self):
        """The straight-line portion of a triangular sweep, as a slice.

        The approach and return legs are measured but excluded from the
        fit; keeping the arithmetic here means no caller recomputes
        `middle_start + middle_len` and gets it wrong by one.
        """
        return slice(self.middle_start_n,
                     self.middle_start_n + self.middle_len_n)

    # ---- the units boundary ----
    def as_math_geometry(self):
        """Geometry in the units `fourpp_math.sheet_resistance` expects.

        Returns `(width_mm, length_mm, thickness_um)`. This is the only
        conversion out of SI in the 4PP path, and it exists so that
        `experiment.py` never multiplies by 1000 in line with a call.
        A conversion written inline at a call site is a conversion that
        gets copied to a second call site with one factor changed.
        """
        return (self.width_m * 1e3, self.length_m * 1e3,
                self.thickness_m * 1e6)


@dataclass(frozen=True)
class VanDerPauwParameters(RunParameters):
    """One Van der Pauw position, measured at both polarities.

    Added in Wave 5a-i, when Van der Pauw was wired onto the run
    lifecycle. The shape follows `FourPointProbeParameters`, which had
    two waves of real use behind it by then, rather than inventing a
    second convention.

    One field deserves its own note. `position` is the switch-box
    setting, 1 to 4, and it lives in the *parameters* rather than being
    read from a Tk variable as the run goes. That is the point of a
    snapshot: the operator confirms position 3 in a dialog, the run
    starts, and if they then click the position spinner while it is
    measuring, the run must still be the position-3 run it said it was.

    Thickness is in metres, like every other length in the suite.
    `vdp_math.resistivity()` wants centimetres, because that is the unit
    resistivity is quoted in; `as_math_thickness_cm()` is the single
    place that conversion happens.
    """

    position: int = 1

    # the source
    level_a: float = 0.0
    points_n: int = 0
    delay_s: float = 0.0
    compliance_v: float = 0.0
    voltage_range_v: float = None

    # Integration time and output-off mode, recorded because the same
    # sample reads differently under a different NPLC, and a file that
    # does not say which was used cannot be compared with another one.
    nplc: float = None
    high_z: bool = None

    # the sample
    thickness_m: float = 0.0

    # ---- derived, not stored ----
    @property
    def readings_n(self):
        """Total readings expected: `points_n` at each polarity.

        Handed to `RunContext.expect()`. A block that returns three of
        its five readings and averages them into a perfectly plausible
        resistance is the failure this makes visible.
        """
        return self.points_n * 2

    @property
    def position_label(self):
        """`Pos3` - the spelling used by the results table, the
        calculation boxes and `core.calculation.require_set()`."""
        return f"Pos{self.position}"

    # ---- the units boundary ----
    def as_math_thickness_cm(self):
        """Thickness in the centimetres `vdp_math.resistivity()` takes."""
        return self.thickness_m * 1e2
