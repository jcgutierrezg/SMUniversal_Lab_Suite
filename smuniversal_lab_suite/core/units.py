"""
The unit convention, stated once.

The rule itself is house rule 5, `docs/rules/05-si-inside.md`:
SI inside, convert only at the edges, and every numeric field names
its unit.

Why this exists
---------------
Unit ambiguity is not a bug you find in a code review; it is a bug you
find six months later in a plot that looks slightly wrong. A float
called `thickness` is a promise with no terms: metres, millimetres or
microns, depending on which entry box it came from and who wrote that
panel.

Nothing here converts anything the rest of the suite could not already
do with a multiplication. What it provides is a **place the rule is
written down and a way to check the rule is being kept** - the suffix
table below, and `unit_of()`, which `tests/test_parameters.py` uses to
assert that every numeric field of every parameter object names its
unit.

The rule, in three lines
------------------------
1. **Internally, everything is SI base.** Amps, volts, seconds, metres,
   tesla, ohms, kelvin. No millimetres, no gauss, no milliseconds.
2. **Every numeric field name ends in its unit suffix** - `settle_s`,
   `thickness_m`, `field_t`. A bare `thickness` is not allowed to exist
   below the UI layer.
3. **Convert at the boundary, never in between.** The UI parses what the
   operator typed into SI on the way in; the export writes SI out and
   records the unit in the header. Between those two points every number
   is already in base units and nothing multiplies by anything.

The analogy
-----------
This is the same discipline as a workshop that keeps one set of metric
tooling on the bench. Nobody checks whether a bolt is imperial before
picking up a spanner, because the question was settled once, at the
door, rather than repeatedly and unreliably at each job.

The counting suffix
-------------------
Not every number has a unit. Point counts, repetitions and reversals are
dimensionless, and calling them `points_m` would be worse than useless.
Those take `_n` - "a count of" - which is still an explicit statement
that the field carries no unit rather than an omission that might mean
anything. Ratios take `_ratio`, and unitless correction factors `_factor`.

What is deliberately absent
---------------------------
There is no `Quantity` class carrying a value and a unit together.
It is the more rigorous option of the two,
but it would mean every arithmetic expression in `vdp_math`, `hall_math`
and `fourpp_math` growing a `.value`, and those modules are the ones
under a bit-identical-to-the-notebook guard. A naming convention that a
test can enforce buys most of the safety for none of that risk.
"""
from __future__ import annotations

# --------------------------------------------------------------------
# the suffix table
# --------------------------------------------------------------------
#: suffix -> (SI base unit symbol, human name).
#:
#: To add a quantity to the suite, add it here first. A parameter field
#: whose suffix is not in this table fails `test_parameters.py`, which is
#: the point: it forces the question "what unit is this in?" to be
#: answered at the moment the field is written rather than at the bench.
UNIT_SUFFIXES = {
    "a": ("A", "amperes"),
    "v": ("V", "volts"),
    "s": ("s", "seconds"),
    "m": ("m", "metres"),
    "t": ("T", "tesla"),
    "ohm": ("\u03a9", "ohms"),
    "ohm_sq": ("\u03a9/sq", "ohms per square"),
    "k": ("K", "kelvin"),
    "c": ("\u00b0C", "degrees Celsius"),
    "w": ("W", "watts"),
    "hz": ("Hz", "hertz"),
    "per_m3": ("m^-3", "per cubic metre"),
    "per_m2": ("m^-2", "per square metre"),
    "m2_vs": ("m^2/(V.s)", "square metres per volt second"),
    # dimensionless, but still declared rather than omitted
    "n": ("", "a count"),
    "ratio": ("", "a ratio"),
    "factor": ("", "a factor"),
    "nplc": ("NPLC", "power line cycles"),
}

#: Longest-first, so `sheet_resistance_ohm_sq` matches `ohm_sq` and not
#: `sq`. A dict is insertion-ordered but not length-ordered, and getting
#: this wrong would mis-report the unit of exactly the fields most worth
#: getting right.
_SUFFIXES_LONGEST_FIRST = sorted(UNIT_SUFFIXES, key=len, reverse=True)

#: Fields that hold text, identifiers, flags or modes have no unit and
#: are not expected to carry a suffix. Named explicitly rather than
#: inferred from the annotation, so adding a `str` field does not
#: silently widen the exemption.
NON_NUMERIC_TYPES = (str, bool, type(None))


def unit_of(field_name):
    """The SI unit a field name declares, or None if it declares none.

    >>> unit_of("source_current_a")
    'A'
    >>> unit_of("points_n")
    ''
    >>> unit_of("thickness")      # returns None - no declaration
    """
    name = field_name.lower()
    for suffix in _SUFFIXES_LONGEST_FIRST:
        if name.endswith("_" + suffix) or name == suffix:
            return UNIT_SUFFIXES[suffix][0]
    return None


def describe(field_name):
    """Human phrasing for an error message: 'amperes', 'a count'..."""
    name = field_name.lower()
    for suffix in _SUFFIXES_LONGEST_FIRST:
        if name.endswith("_" + suffix) or name == suffix:
            return UNIT_SUFFIXES[suffix][1]
    return None


def label(field_name):
    """A field name as a person would read it: 'Source current (A)'.

    Used at the UI and export boundary so a column heading and the field
    behind it cannot disagree about units.
    """
    name = field_name
    unit = unit_of(name)
    stem = name
    for suffix in _SUFFIXES_LONGEST_FIRST:
        if name.lower().endswith("_" + suffix):
            stem = name[: -(len(suffix) + 1)]
            break
    words = stem.replace("_", " ").strip()
    words = (words[:1].upper() + words[1:]) if words else words
    return f"{words} ({unit})" if unit else words


# --------------------------------------------------------------------
# boundary conversions
# --------------------------------------------------------------------
# Only for use at the UI and export edges. Nothing in an experiment
# worker, a driver or a maths module should call these: by the time a
# number reaches those it is already in base units.
#
# `core.limits.parse_si` remains the parser for operator-typed levels
# ('100u', '300 mV'). These are for fields where the unit is fixed by
# the widget's label rather than typed - a thickness box marked "nm", a
# field box marked "gauss".

# Divide by the whole power of ten rather than multiplying by its
# reciprocal. Both are correct to within a rounding step, but they are
# not equally good in practice, and the difference was measured on
# the values people actually type - integers and one or two decimals:
#
#     180 um -> metres -> back      *1e-6 then *1e6 : fails for 28.7%
#                                   /1e6  then *1e6 : fails for  2.9%
#
# "Fails" means the value that comes back is one unit in the last place
# away from the one that went in, so a thickness typed as 180 is written
# into the CSV header as 179.99999999999997. Scientifically irrelevant;
# legible enough to matter when somebody opens the file.
#
# The residue is inherent. No pairing of constants round-trips every
# double exactly, and there is no arrangement of this arithmetic that
# removes the last 2.9%. See docs/rules/09-compare-with-tolerance.md -
# a value that has
# been converted and converted back should be compared with a tolerance,
# never with `==`.
def mm_to_m(value):
    return value / 1e3


def um_to_m(value):
    return value / 1e6


def nm_to_m(value):
    return value / 1e9


def m_to_mm(value):
    return value * 1e3


def m_to_um(value):
    return value * 1e6


def m_to_nm(value):
    return value * 1e9


def ms_to_s(value):
    return value * 1e-3


def s_to_ms(value):
    return value * 1e3


def gauss_to_tesla(value):
    """1 T = 10 000 G. Lab magnets are quoted in gauss far more often
    than in tesla, and the Hall equations want tesla."""
    return value * 1e-4


def tesla_to_gauss(value):
    return value * 1e4


def mtesla_to_tesla(value):
    return value * 1e-3


def celsius_to_kelvin(value):
    return value + 273.15


def kelvin_to_celsius(value):
    return value - 273.15


#: Every conversion above as (from_unit, to_unit) -> callable, so a test
#: can walk the whole set and assert each one round-trips. A conversion
#: added below without an entry here is not covered, which
#: `tests/test_parameters.py` reports.
CONVERSIONS = {
    ("mm", "m"): mm_to_m,
    ("um", "m"): um_to_m,
    ("nm", "m"): nm_to_m,
    ("m", "mm"): m_to_mm,
    ("m", "um"): m_to_um,
    ("m", "nm"): m_to_nm,
    ("ms", "s"): ms_to_s,
    ("s", "ms"): s_to_ms,
    ("gauss", "t"): gauss_to_tesla,
    ("t", "gauss"): tesla_to_gauss,
    ("mt", "t"): mtesla_to_tesla,
    ("c", "k"): celsius_to_kelvin,
    ("k", "c"): kelvin_to_celsius,
}

#: Pairs that are inverses of one another, for the round-trip test.
INVERSE_PAIRS = [
    (("mm", "m"), ("m", "mm")),
    (("um", "m"), ("m", "um")),
    (("nm", "m"), ("m", "nm")),
    (("ms", "s"), ("s", "ms")),
    (("gauss", "t"), ("t", "gauss")),
    (("c", "k"), ("k", "c")),
]
