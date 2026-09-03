"""The shared validators. See house rule 6.

Two layers, on purpose.

**Tables** prove the cases somebody thought of, and they double as
documentation: the table of rejected integer inputs *is* the
specification of what "must be a whole number" means here.

**Properties** prove the cases nobody thought of. Hypothesis generates
input, and when it finds a failure it shrinks it to the smallest text
that still fails - so a bug surfaces as `'0.5'` rather than as whatever
40-character string happened to trigger it. That shrinking is the whole
reason for the dependency; a hand-rolled random sweep finds the same
bugs and reports them unreadably.

The property that matters most is the one the rule is about:

    for any text, `whole_number` either returns an int whose float value
    equals the parsed float, or raises. It never returns a number that
    is not the number the operator typed.

Truncation is precisely the violation of that, which is why it is
phrased as an invariant rather than as a list of decimals to try.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.validation import (
    ValidationError,
    label,
    number,
    one_of,
    positive_number,
    si_level,
    whole_number,
)


# ------------------------------------------------------------------
# whole_number - rejecting, not truncating
# ------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("2", 2),
    ("2.0", 2),
    ("  7  ", 7),
    ("+3", 3),
    ("-4", -4),
    ("1e3", 1000),        # 1000.0 is an integer, and is meant as one
    ("0", 0),
    ("2.000000", 2),
])
def test_whole_number_accepts_integral_input(text, expected):
    assert whole_number(text, "Points") == expected


@pytest.mark.parametrize("text", [
    "2.5",               # the exact case the rule names
    "1.9999",
    "-0.5",
    "0.1",
    "1e-3",
    "3/2",
    "two",
    "",
    "   ",
    "nan",
    "inf",
    "-inf",
    "0x10",
    "1_000",       # float() accepts it as 1000; the operator is not
                   # writing Python and '1_5' would parse as fifteen
])
def test_whole_number_rejects_non_integral_input(text):
    with pytest.raises(ValidationError):
        whole_number(text, "Points")


def test_whole_number_never_truncates_silently():
    """The regression this wave exists to prevent.

    `int(float('2.5'))` is 2. Anything that returns 2 here has
    reintroduced the defect, whatever route it took.
    """
    with pytest.raises(ValidationError) as excinfo:
        whole_number("2.5", "Reversals")
    message = str(excinfo.value)
    assert "Reversals" in message
    assert "whole number" in message
    # and it must tell the operator what to do instead of rounding for
    # them, since the point is that the software will not choose
    assert "2" in message and "3" in message


def test_whole_number_error_names_the_field():
    err = None
    try:
        whole_number("2.5", "Reversals")
    except ValidationError as e:
        err = e
    assert err is not None
    assert err.field == "Reversals"
    assert err.value == "2.5"


@pytest.mark.parametrize("text, kwargs", [
    ("1", dict(minimum=2)),
    ("5", dict(maximum=4)),
    ("3", dict(even=True)),
    ("4", dict(odd=True)),
    ("3", dict(even_above_one=True)),
    ("7", dict(even_above_one=True)),
])
def test_whole_number_bounds_and_parity_reject(text, kwargs):
    with pytest.raises(ValidationError):
        whole_number(text, "Field", **kwargs)


@pytest.mark.parametrize("text, kwargs", [
    ("2", dict(minimum=2)),
    ("4", dict(maximum=4)),
    ("4", dict(even=True)),
    ("3", dict(odd=True)),
    ("1", dict(even_above_one=True)),     # 4PP: a single reversal is fine
    ("2", dict(even_above_one=True)),
    ("6", dict(even_above_one=True)),
])
def test_whole_number_bounds_and_parity_accept(text, kwargs):
    assert whole_number(text, "Field", **kwargs) == int(float(text))


def test_reason_reaches_the_operator():
    """A parity rule the operator cannot see the point of gets ignored.

    4PP's even-reversals rule protects the cancellation of thermal
    offsets; a message that only says "must be even" invites the
    operator to pick a different even number without understanding why
    it mattered.
    """
    with pytest.raises(ValidationError) as excinfo:
        whole_number("3", "Reversals", even_above_one=True,
                     reason="so that each polarity is measured the same "
                            "number of times.")
    assert "each polarity" in str(excinfo.value)


# ------------------------------------------------------------------
# number / positive_number
# ------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("2.5", 2.5),
    ("-1e-6", -1e-6),
    (" 0.001 ", 0.001),
    ("3", 3.0),
])
def test_number_accepts_finite_floats(text, expected):
    assert number(text, "Delay") == pytest.approx(expected)


@pytest.mark.parametrize("text", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_number_rejects_non_finite(text):
    """`float('nan')` succeeds, and a nan settle time would propagate
    through an entire run without raising anywhere."""
    with pytest.raises(ValidationError):
        number(text, "Delay")


def test_positive_number_zero_policy():
    assert positive_number("0", "Delay", allow_zero=True) == 0.0
    with pytest.raises(ValidationError):
        positive_number("0", "Voltage limit")
    with pytest.raises(ValidationError):
        positive_number("-1", "Voltage limit")


def test_exclusive_and_inclusive_bounds_differ():
    assert number("0", "F", minimum=0.0) == 0.0
    with pytest.raises(ValidationError):
        number("0", "F", minimum_exclusive=0.0)


# ------------------------------------------------------------------
# decimal comma - decision 5a, reject rather than guess
# ------------------------------------------------------------------
@pytest.mark.parametrize("text", ["0,5", "1,000", "2,5e3", "-3,25"])
def test_decimal_comma_is_rejected_not_guessed(text):
    """'0,5' is a half on one keyboard and '1,000' is a thousand on
    another. A validator that picks one is silently wrong on the other,
    which is the same failure wearing different clothes."""
    with pytest.raises(ValidationError) as excinfo:
        number(text, "Delay")
    assert "full stop" in str(excinfo.value)


def test_unicode_minus_is_accepted():
    """U+2212 arrives by copy-paste from datasheets and spreadsheets.

    Unlike a comma it is unambiguous, so normalising it is not a guess.
    """
    assert number("\u22125", "Start") == -5.0
    assert whole_number("\u22123", "Points") == -3


# ------------------------------------------------------------------
# si_level
# ------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("100u", 100e-6),
    ("100 \u00b5A", 100e-6),
    ("300 mV", 0.3),
    ("1.5", 1.5),
    ("1e-4", 1e-4),
])
def test_si_level_parses_prefixes(text, expected):
    assert si_level(text, "Level") == pytest.approx(expected)


def test_si_level_auto():
    assert si_level("AUTO", "Range", allow_auto=True) is None
    with pytest.raises(ValidationError):
        si_level("AUTO", "Range")


def test_si_level_applies_bounds():
    with pytest.raises(ValidationError):
        si_level("0", "Voltage limit", minimum_exclusive=0.0)
    assert si_level("300 mV", "Voltage limit",
                    minimum_exclusive=0.0) == pytest.approx(0.3)


# ------------------------------------------------------------------
# label / one_of
# ------------------------------------------------------------------
def test_label_trims_and_defaults():
    assert label("  ITO 3 ", "Sample") == "ITO 3"
    assert label("", "Sample", default="sample") == "sample"
    with pytest.raises(ValidationError):
        label("   ", "Sample")


def test_label_length_is_bounded():
    with pytest.raises(ValidationError):
        label("x" * 200, "Sample")


def test_one_of_guards_a_drifted_variable():
    assert one_of("list", "Sweep mode", ("triangular", "list")) == "list"
    with pytest.raises(ValidationError):
        one_of("spiral", "Sweep mode", ("triangular", "list"))


# ------------------------------------------------------------------
# properties
# ------------------------------------------------------------------
_TEXT = st.text(max_size=24)


@given(_TEXT)
@settings(max_examples=400, deadline=None)
def test_whole_number_never_returns_a_different_number(text):
    """The invariant, stated as a property.

    Whatever the input, `whole_number` either raises or returns exactly
    the number that was typed. There is no input for which it returns a
    rounded, truncated or otherwise adjusted value - which is the one
    thing `int(float(x))` could not promise.
    """
    try:
        result = whole_number(text, "Field")
    except ValidationError:
        return
    assert isinstance(result, int)
    # Cross-checked against the module's own float validator rather than
    # against a reimplementation of its normalisation, so this stays a
    # statement about behaviour and not a copy of the code under test.
    assert float(result) == number(text, "Field")


@given(st.floats(allow_nan=False, allow_infinity=False,
                 min_value=-1e12, max_value=1e12))
@settings(max_examples=300, deadline=None)
def test_number_round_trips_its_own_repr(value):
    """Anything formatted by Python must be readable back by us.

    Values reach these fields from `.set()` calls elsewhere in the app
    as well as from typing, so a float the application itself wrote must
    never be input the application then rejects.
    """
    assert number(repr(value), "Field") == pytest.approx(value, rel=1e-12,
                                                         abs=1e-18)


@given(st.integers(min_value=-10**9, max_value=10**9))
@settings(max_examples=300, deadline=None)
def test_whole_number_accepts_every_integer_in_both_spellings(value):
    assert whole_number(str(value), "Field") == value
    assert whole_number(f"{value}.0", "Field") == value


@given(_TEXT, st.sampled_from(["Points", "Reversals", "Delay"]))
@settings(max_examples=300, deadline=None)
def test_every_rejection_names_its_field(text, field):
    """A dialog that does not say which box is wrong makes the operator
    check all of them."""
    for validator in (whole_number, number, positive_number):
        try:
            validator(text, field)
        except ValidationError as err:
            assert err.field == field
            assert field in str(err)


@given(st.floats(min_value=1e-9, max_value=1e3,
                 allow_nan=False, allow_infinity=False))
@settings(max_examples=200, deadline=None)
def test_si_level_agrees_with_plain_number_when_no_prefix(value):
    text = repr(value)
    assert si_level(text, "Level") == pytest.approx(number(text, "Level"))
