"""
Shared validators for operator-typed fields (review §24).

Why this exists
---------------
Five call sites across two experiments read integer fields as
`int(float(text))`. Typing `2.5` into the 4PP reversals box does not
produce an error; it produces a two-reversal measurement, silently, and
the operator gets a different experiment from the one they asked for.
Averaging two readings instead of two-and-a-half is not obviously
wrong - which is exactly what makes it dangerous, because nothing in the
data says the request was ignored.

Truncation is the wrong default in a laboratory. `int(float(x))` answers
"what is the nearest integer I can get away with"; the right question is
"did the operator ask for something this field can express?", and the
right answer to `2.5` reversals is a dialog box.

The analogy
-----------
A torque wrench that cannot be set to 2.5 Nm should refuse the setting.
It should not quietly set itself to 2 and let you tighten the bolt
believing otherwise.

What is *not* in scope
----------------------
Seven `int(float(...))` calls live in drivers, parsing SCPI error codes
like `-113,"Undefined header"`. Those are correct: the instrument
returns its own integer as a float-formatted string and truncation is
the intended reading. This module is for **operator input only**. Do not
route driver reply parsing through it.

Errors
------
Every failure raises `ValidationError`, which carries the field name as
well as the message so a caller can highlight the offending box rather
than only showing a dialog. `str(err)` is written for that dialog: it
names the field, says what was typed, and says what would be accepted.

Using it
--------
::

    from core.validation import whole_number, positive_number, si_level

    reversals = whole_number(self.reversals_var.get(), "Reversals",
                             minimum=1, even_above_one=True,
                             reason="so that each polarity is measured "
                                    "the same number of times")
    delay_s   = positive_number(self.delay_var.get(), "Delay",
                                allow_zero=True)
    limit_v   = si_level(self.compliance_var.get(), "Voltage limit",
                         unit="V", minimum_exclusive=0.0)
"""
from __future__ import annotations

import math
import unicodedata


class ValidationError(ValueError):
    """One field rejected, with the field named.

    A `ValueError` subclass on purpose: the experiments already catch
    `ValueError` around their form-reading code and show it in a dialog,
    so these messages reach the operator through the existing path
    without any experiment being modified. Wave 3 can then start
    catching `ValidationError` specifically to highlight `err.field`.
    """

    def __init__(self, field, message, value=None):
        self.field = field
        self.value = value
        super().__init__(f"{field}: {message}")


# --------------------------------------------------------------------
# text normalisation
# --------------------------------------------------------------------
#: U+2212 MINUS SIGN and the two common unicode dashes. These arrive by
#: copy-paste from a datasheet, a spreadsheet or a chat message, and a
#: minus sign is unambiguous - normalising it costs nothing and saves a
#: baffling "not a number" on text that visibly reads as a number.
_MINUS_LOOKALIKES = "\u2212\u2012\u2013\u2014\u2015\u2796"


def _normalise(text, field):
    """Trim, fold unicode minus signs, and reject what cannot be meant.

    Returns cleaned text. Raises `ValidationError` for blank input and
    for a decimal comma.
    """
    if text is None:
        raise ValidationError(field, "is required but was not given.")
    s = unicodedata.normalize("NFKC", str(text)).strip()
    for ch in _MINUS_LOOKALIKES:
        s = s.replace(ch, "-")
    s = s.replace("\u00a0", "")           # non-breaking space, from web copy

    if not s:
        raise ValidationError(field, "is required but was left blank.")

    # Decision 5a: never guess. '0,5' is half on a Spanish keyboard and
    # '1,000' is a thousand on an English one, and a validator that
    # picks one is a validator that is silently wrong on the other. The
    # §24 failure being fixed here is exactly "quietly gave them a
    # different number", so guessing would reintroduce it in a new
    # costume.
    if "," in s:
        raise ValidationError(
            field,
            f"{s!r} contains a comma. Use a full stop as the decimal "
            f"separator - write 0.5, not 0,5.",
            value=text)

    # Python's own float() accepts underscores as digit separators, so
    # '1_000' would quietly parse as a thousand. The operator is not
    # writing Python, and '1_5' would parse as fifteen, which is the
    # same class of silent ten-fold error the comma rule exists to
    # avoid. Rejected for the same reason and with the same phrasing.
    if "_" in s:
        raise ValidationError(
            field,
            f"{s!r} contains an underscore. Write digits only - "
            f"1000, not 1_000.",
            value=text)
    return s


def _to_float(text, field):
    """Parse cleaned text as a finite float, or raise."""
    s = _normalise(text, field)
    try:
        value = float(s)
    except (TypeError, ValueError):
        raise ValidationError(field, f"{s!r} is not a number.",
                              value=text) from None

    # float() happily accepts 'inf', '-inf' and 'nan'. None of the three
    # is a setting any instrument can take, and 'nan' in particular
    # would propagate through a whole run without raising anywhere.
    if math.isnan(value):
        raise ValidationError(field, "must be a number, not 'nan'.", value=text)
    if math.isinf(value):
        raise ValidationError(field, "must be a finite number.", value=text)
    return value


# --------------------------------------------------------------------
# the validators
# --------------------------------------------------------------------
def number(text, field, *, minimum=None, maximum=None,
           minimum_exclusive=None, maximum_exclusive=None):
    """A finite float, optionally bounded.

    `minimum` / `maximum` are inclusive; the `_exclusive` forms are not.
    Both are offered because "at least 2 points" and "greater than zero
    volts" are different requirements and expressing the second as
    `minimum=1e-12` would be a lie about where the boundary is.
    """
    value = _to_float(text, field)
    _check_bounds(value, field, text, minimum, maximum,
                  minimum_exclusive, maximum_exclusive)
    return value


def positive_number(text, field, *, allow_zero=False, maximum=None):
    """A finite float above zero. `allow_zero` admits exactly 0.0.

    The common case - a delay, a compliance limit, a thickness - phrased
    so the call site reads as the requirement rather than as arithmetic.
    """
    if allow_zero:
        return number(text, field, minimum=0.0, maximum=maximum)
    return number(text, field, minimum_exclusive=0.0, maximum=maximum)


def whole_number(text, field, *, minimum=None, maximum=None,
                 even=False, odd=False, even_above_one=False, reason=""):
    """An integer, **rejecting** non-integral input rather than truncating.

    This is the §24 fix. `2.5` raises; `2.0` and `2` and `2e0` are all
    the integer two, because they are.

    `even` / `odd` / `even_above_one` express parity requirements.
    `even_above_one` is 4PP's rule: one reversal is a valid single
    measurement, but any count above one must be even or the average is
    weighted towards whichever polarity ran first.

    `reason` is appended to a parity or bound failure, so the dialog can
    explain *why* rather than only *what*. Passing it is optional and
    worth doing: "Reversals must be even" invites the operator to try
    again with a different even number; adding the reason tells them
    what the rule protects.
    """
    value = _to_float(text, field)

    if not float(value).is_integer():
        raise ValidationError(
            field,
            f"must be a whole number; {_shown(text)} is not. "
            f"Values are not rounded - enter {int(value)} or "
            f"{int(value) + 1} explicitly.",
            value=text)

    result = int(value)
    _check_bounds(result, field, text, minimum, maximum, None, None, reason)

    if even and result % 2:
        raise ValidationError(field, _with_reason(
            f"must be an even number; {result} is odd.", reason), value=text)
    if odd and not result % 2:
        raise ValidationError(field, _with_reason(
            f"must be an odd number; {result} is even.", reason), value=text)
    if even_above_one and result > 1 and result % 2:
        raise ValidationError(field, _with_reason(
            f"must be 1 or an even number; {result} is odd.", reason),
            value=text)

    return result


def si_level(text, field, *, unit=None, minimum=None, maximum=None,
             minimum_exclusive=None, maximum_exclusive=None,
             allow_auto=False):
    """A source level typed with an optional SI prefix: '100u', '300 mV'.

    Delegates the parsing to `core.limits.parse_si`, which is the one
    place in the suite that decides what '100u' means, and adds this
    module's normalisation, bounds and error phrasing around it.

    Returns a float in **base units** - amps or volts, never milli
    anything - per the rule in `core.units`.

    `allow_auto=True` returns None for the literal text 'AUTO', which is
    how the Hall and Van der Pauw range fields already spell "let the
    instrument choose".
    """
    from core.limits import parse_si  # local: core.limits is a peer

    s = _normalise(text, field)
    if allow_auto and s.upper() == "AUTO":
        return None

    try:
        value = float(parse_si(s))
    except (TypeError, ValueError):
        suffix = f" (for example 100u, 1.5m, or 0.001{unit or ''})" if unit \
            else " (for example 100u or 1.5m)"
        raise ValidationError(
            field, f"{s!r} is not a level this field understands{suffix}.",
            value=text) from None

    if math.isnan(value) or math.isinf(value):
        raise ValidationError(field, "must be a finite level.", value=text)

    _check_bounds(value, field, text, minimum, maximum,
                  minimum_exclusive, maximum_exclusive)
    return value


def label(text, field, *, default=None, maximum_length=64):
    """A human-readable name: a sample label, a dataset name.

    Trimmed, never blank. Distinct from an identifier - see
    `core.identity`. A label is what the operator reads; it is editable
    and need not be unique, which is precisely why it cannot also serve
    as the key that ties a result to a sample.
    """
    if text is None or not str(text).strip():
        if default is not None:
            return default
        raise ValidationError(field, "is required but was left blank.")
    s = unicodedata.normalize("NFKC", str(text)).strip()
    if len(s) > maximum_length:
        raise ValidationError(
            field,
            f"is {len(s)} characters; the maximum is {maximum_length}.",
            value=text)
    return s


def one_of(text, field, choices, *, default=None):
    """A value from a fixed set - a sweep mode, a source function.

    Guards against a Tk variable that has drifted from the options its
    dropdown offers, which is otherwise discovered as a KeyError deep in
    a worker thread.
    """
    if text is None or not str(text).strip():
        if default is not None:
            return default
        raise ValidationError(field, "is required but was left blank.")
    s = str(text).strip()
    if s not in choices:
        listed = ", ".join(repr(c) for c in choices)
        raise ValidationError(
            field, f"{s!r} is not one of: {listed}.", value=text)
    return s


# --------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------
def _shown(text):
    """The operator's own text in the message, so they can see the typo.

    Falls back to repr of the cleaned value if the original is not
    printable, which keeps the message useful without letting an
    arbitrary string mangle the dialog.
    """
    s = str(text).strip()
    return repr(s) if s else "a blank value"


def _with_reason(message, reason):
    return f"{message} {reason.strip()}" if reason else message


def _check_bounds(value, field, text, minimum, maximum,
                  minimum_exclusive=None, maximum_exclusive=None, reason=""):
    if minimum is not None and value < minimum:
        raise ValidationError(field, _with_reason(
            f"must be at least {minimum:g}; {value:g} is below it.", reason),
            value=text)
    if minimum_exclusive is not None and value <= minimum_exclusive:
        raise ValidationError(field, _with_reason(
            f"must be greater than {minimum_exclusive:g}; got {value:g}.",
            reason), value=text)
    if maximum is not None and value > maximum:
        raise ValidationError(field, _with_reason(
            f"must be at most {maximum:g}; {value:g} is above it.", reason),
            value=text)
    if maximum_exclusive is not None and value >= maximum_exclusive:
        raise ValidationError(field, _with_reason(
            f"must be less than {maximum_exclusive:g}; got {value:g}.",
            reason), value=text)
