"""What the checkup sources, and the thresholds its checks use.

The nominal probe levels, `probe_levels_for()` which reconciles them
with each driver's own envelope, and the constants the tiers judge
their readings against.
"""


# ---------------------------------------------------------------------
# Probe levels
# ---------------------------------------------------------------------
#
# These four are the *nominal* request, not the levels. They are small
# enough to be harmless into an open circuit and well clear of the noise
# floor on the instruments they were chosen against, and that is all
# they are: a starting point that `probe_levels_for()` reconciles
# against each driver's own declared envelope before anything is sent.
#
# They used to be the levels, applied unchanged to every instrument in
# the registry, and one instrument proved that cannot work. The U2722A
# has no autorange, so an all-AUTO current axis lands on R120mA where
# one count is 7.32 uA - and a module-wide 1 uA probe is a seventh of a
# count there, which the driver correctly refuses because the sign of
# what comes out is not the sign that was asked for. The checkup was
# therefore **structurally unable to pass** on that instrument: not
# because anything was wrong with it, but because the tool was asking
# for a configuration that instrument does not have.
#
# A commissioning tool that cannot pass on a working instrument is worse
# than no tool, for the same reason a tool that invents failures is: it
# teaches people to read past its output.
PROBE_VOLTAGE = 0.1          # V, nominal
PROBE_CURRENT = 1e-6         # A, nominal
PROBE_COMPLIANCE_I = 1e-4    # A, nominal
PROBE_COMPLIANCE_V = 1.0     # V, nominal


class ProbeLevels:
    """The four levels this checkup will actually source, per driver.

    Each carries the reason it is what it is, because the report has to
    be able to say *why* an instrument was probed at 73 uA when the tool
    nominally asks for 1 uA. A level with no stated provenance in a
    commissioning report is a number somebody will later assume was
    chosen for their instrument.

    A level can move twice, at two different times, and the two are not
    the same event:

      * **clamped**, here, before anything is sent - the nominal is
        outside what the model *declares*, and comes down to the
        model's ceiling.
      * **substituted**, in tier 3, after the ranging plan has been
        carried out - the nominal is below what the instrument can
        express on the range it actually landed on, and goes up to that
        floor. Nothing before the plan runs can know this.

    `describe()` reports what was **used**, not what was asked for, and
    marks any level that is not the nominal. The 2026-09-04 round is
    the reason it has to: the U2722A sourced 73.2 uA while its tier 1
    row read "source 0.1 V / 1e-06 A ... used unchanged", and the tier 1
    row is the part of a commissioning report people read.
    """

    #: Unit per level, so a substitution note can name its own axis.
    UNITS = {"voltage": ("source voltage", "V"),
             "current": ("source current", "A"),
             "compliance_v": ("voltage compliance", "V"),
             "compliance_i": ("current compliance", "A")}

    __slots__ = ("voltage", "current", "compliance_v", "compliance_i",
                 "_envelope_notes", "substitutions")

    def __init__(self, voltage, current, compliance_v, compliance_i,
                 notes=()):
        self.voltage = float(voltage)
        self.current = float(current)
        self.compliance_v = float(compliance_v)
        self.compliance_i = float(compliance_i)
        self._envelope_notes = tuple(notes)
        #: quantity -> (planned level, level used, why it moved). Empty
        #: until tier 3 finds a range that cannot express a level.
        self.substitutions = {}

    def substitute(self, quantity, value, reason):
        """Record that `quantity` was sourced at `value`, not as planned.

        Kept as a method rather than a bare attribute write so that the
        old level survives: a report that shows only the substituted
        number cannot be compared against another instrument's, and a
        report that shows only the nominal is the bug this exists for.
        """
        planned = getattr(self, quantity)
        setattr(self, quantity, float(value))
        self.substitutions[quantity] = (planned, float(value), reason)

    @property
    def notes(self):
        """Why the four levels are what they are, in run order.

        Envelope clamps first, then any tier 3 substitution. The
        "nothing moved" sentence is generated rather than stored,
        because it is only true until a substitution makes it false -
        and it used to be stored, which is how a report came to say a
        level was "used unchanged" beside a level that was not.
        """
        moved = tuple(reason for _, _, reason in self.substitutions.values())
        if self._envelope_notes or moved:
            return self._envelope_notes + moved
        return ("no nominal level is outside this model's declared "
                "envelope, and none had to be substituted for one the "
                "active range could express, so all four are the "
                "nominal values",)

    def _shown(self, quantity):
        """One level with its unit, saying so when it is not the nominal."""
        _, unit = self.UNITS[quantity]
        value = getattr(self, quantity)
        moved = self.substitutions.get(quantity)
        if moved is None:
            return f"{value:.6g} {unit}"
        return (f"{value:.6g} {unit} in place of the nominal "
                f"{moved[0]:.6g} {unit}")

    def describe(self):
        return (f"source {self._shown('voltage')} / "
                f"{self._shown('current')}, "
                f"compliance {self._shown('compliance_i')} / "
                f"{self._shown('compliance_v')}")

    def as_dict(self):
        return {"voltage": self.voltage, "current": self.current,
                "compliance_v": self.compliance_v,
                "compliance_i": self.compliance_i,
                "notes": list(self.notes),
                "substituted": {q: {"planned": planned, "used": used}
                                for q, (planned, used, _)
                                in self.substitutions.items()}}


def probe_levels_for(driver):
    """Reconcile the nominal probe against one instrument's envelope.

    Every level is clamped into what the model declares it can do, in
    the one direction that fails safe: **downward, to the widest range
    the model has**. A probe above that is a request the instrument
    cannot carry out - the compliance would be refused or clamped, and
    every check downstream would then be measuring the clamp rather than
    the instrument.

    Two things this function deliberately does **not** do.

    It does not round a compliance onto a declared range. That was the
    first draft and it is wrong in exactly the case it was written for:
    the U2722A's narrowest voltage range is 2 V, so rounding a 1 V
    nominal onto a range would probe at the range's full scale - where
    the compliance and the range rail are the same number, and where the
    "is the limit in force?" check cannot tell them apart. That is fault
    25, arriving through the probe rather than through the comparison.
    A compliance need only be *settable*, and where an instrument's
    windows make a value unsettable the driver refuses it and the
    checkup reports the refusal, which is a better answer than a probe
    that quietly moved.

    It does not compute a sub-count floor. That depends on the range the
    ranging plan lands on, which is not known until the plan has been
    carried out, and is asked of the instrument at that point instead -
    see `Checkup._resolve_source_level`. A floor guessed from the model
    alone would be right on one range and wrong on five.
    """
    limits = getattr(type(driver), "LIMITS", None)
    notes = []

    if limits is None:
        return ProbeLevels(
            PROBE_VOLTAGE, PROBE_CURRENT, PROBE_COMPLIANCE_V,
            PROBE_COMPLIANCE_I,
            ["this driver declares no LIMITS, so there was no envelope "
             "to clamp the nominal probe against"])

    resolved = {}
    for key, nominal, ranges, maximum, what, unit in (
            ("compliance_i", PROBE_COMPLIANCE_I, limits.current_ranges,
             limits.max_current, "current compliance", "A"),
            ("compliance_v", PROBE_COMPLIANCE_V, limits.voltage_ranges,
             limits.max_voltage, "voltage compliance", "V"),
            ("current", PROBE_CURRENT, limits.current_ranges,
             limits.max_current, "source current", "A"),
            ("voltage", PROBE_VOLTAGE, limits.voltage_ranges,
             limits.max_voltage, "source voltage", "V")):
        value, note = _clamp_to_ceiling(nominal, ranges, maximum, what, unit)
        resolved[key] = value
        if note:
            notes.append(note)

    # No "nothing moved" note is appended here. Whether a level survives
    # to be sourced unchanged is not known until the ranging plan has
    # run and the instrument has been asked what it can express on the
    # range it landed on; `ProbeLevels.notes` says so once, at the end,
    # rather than promising it here and being contradicted in tier 3.
    return ProbeLevels(resolved["voltage"], resolved["current"],
                       resolved["compliance_v"], resolved["compliance_i"],
                       notes)


def _clamp_to_ceiling(nominal, ranges, maximum, what, unit):
    """`(value, note)`, where the note is empty when nothing moved."""
    ceiling = max(ranges) if ranges else maximum
    if maximum:
        ceiling = min(ceiling, maximum)
    if nominal <= ceiling:
        return (nominal, "")
    return (ceiling,
            f"the nominal {what} of {nominal:.6g} {unit} is beyond this "
            f"model's {ceiling:.6g} {unit} ceiling and is clamped to it")

# The window in which a reading counts as "the output is at its
# compliance", as a fraction of the requested limit. Both edges are
# decisions rather than tuned numbers, and both were set from measured
# hardware on 2026-08-21:
#
#   floor  - below this the output never got there. A settled reading
#            under it means something is drawing the current away.
#   ceiling- above this the limit is NOT being enforced at the value
#            that was asked for. The U2722A sat at -2.0 V against a 1 V
#            limit, because the limit had been refused and the range
#            rail was bounding the output instead; the check tested only
#            the floor and recorded it as a pass. An output beyond its
#            own compliance is the one reading that proves the
#            compliance is not working, and it must be the loudest
#            result the probe can produce, not the quietest.
#
# The ceiling has to allow overshoot, because a healthy clamp does
# overshoot: the miniSMU settles at 1.023x its limit with the
# compliance working correctly. 1.25 sits clear of that and a factor of
# two below a limit that is simply not in force.
COMPLIANCE_FLOOR = 0.8
COMPLIANCE_CEILING = 1.25

# Two consecutive readings closer together than this are treated as the
# same reading, and the output as settled. Chosen against the ramp it
# has to distinguish: the GSM-20H10 climbs about 0.23 V per poll at the
# probe current, roughly forty times this, while the noise on a settled
# reading is far below it - the U2722A is the coarsest instrument here
# and one count on its 2 V range is 122 uV.
#
# Expressed as a fraction of the compliance in force, because it is a
# fraction of the compliance that it has to mean: an instrument whose
# envelope moved the compliance would otherwise get a settle window
# calibrated for somebody else's limit. `SETTLE_TOLERANCE_V` is the
# nominal value, kept because it is the number the paragraph above was
# measured against; `Checkup._settle_tolerance()` is what the run uses.
SETTLE_TOLERANCE_FRACTION = 0.005
SETTLE_TOLERANCE_V = PROBE_COMPLIANCE_V * SETTLE_TOLERANCE_FRACTION

#: Readings timed for the per-reading figure, after a warm-up read that
#: is taken and discarded. Named because two places have to agree on it:
#: the headline timing and the fast-end point of the aperture fit, which
#: is a difference between them and is only meaningful if both ends were
#: measured the same way.
TIMED_READINGS = 5

#: How many commands an error names as its possible cause. A group in
#: this tool is a handful of writes; a cap this size only bites on a
#: driver method that sends a great many, where a full list would be
#: unreadable anyway.
COMMANDS_LISTED_WITH_AN_ERROR = 12

# Sourcing 0.1 V into an open circuit should draw essentially nothing.
# The threshold is loose because the 2611A's low ranges and the
# miniSMU's autoranging both have offsets at this level; what it is
# really catching is a reading that came back in the wrong units, from
# the wrong quantity, or as a compliance-clamped value.
OPEN_CIRCUIT_MAX_A = 1e-5

SWEEP_POINTS = 5
