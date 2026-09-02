"""
What an instrument said when it was asked to confirm its own state.

Every setting this suite sends is a *request*. Until something reads it
back, the only evidence that the instrument is in the state the software
believes it is in is that the write did not raise - and a wrong SCPI
header does not raise, it is logged and ignored while the previous
setting stays in force. That is fault 11, and it is the mechanism behind
most of this project's silent wrong answers.

`apply_ranges()` reported what it *sent*. So did every compliance
setter. The half that could hurt a sample - the compliance - grew a
readback on 2026-08-20; the range half did not, and on the GSM-20H10 a
refused measurement range leaves a narrower one in force with nothing
noticing (`SENS:CURR:DC:RANG?` reading `1.050000E-05` after `1E-4` was
asked for).

This module is the vocabulary for the answer.

---------------------------------------------------------------------
The five states, and why there are five rather than two
---------------------------------------------------------------------
A boolean cannot express this domain. "Did not disagree" is not
"agreed", and the difference between them is the difference between a
measurement and a plausible number.

  ``UNSUPPORTED`` - the instrument genuinely cannot report this. Not a
        fault and not a gap: the U2722A has no compliance-trip query at
        all, and several drivers have no range query whose spelling
        anybody has confirmed. Renders as a **skip**, which is what this
        project already uses for a model difference.

  ``UNREADABLE`` - the driver can ask and did ask, and no usable answer
        came back. A dropped reply, an unparseable one, a query the
        instrument logged and ignored. Renders as a **warn**: something
        is wrong with the asking, and nobody should read the run as
        confirmed.

  ``UNVERIFIED`` - an answer came back and agreed, but this readback has
        never been checked against a value the instrument was known to
        hold. It exists because of `OUTP?` on the GSM-20H10, which
        returns 0 with the output demonstrably on and 10 V flowing: a
        readback that lies is *worse* than none, because it produces
        confident reassurance about the exact thing it exists to verify.
        Renders as a **warn**, never a pass.

  ``CONFIRMED`` - read back, trusted, and it matched. The only state
        that renders as a **pass**.

  ``MISMATCHED`` - read back, and it disagreed with what was requested.
        Renders as a **fail**, loudly, on every subject this module
        covers. A compliance or a range that is not the one the software
        asked for is the bound on what reaches the sample and the person
        at the fixture, and it must not be discovered from the data
        afterwards.

---------------------------------------------------------------------
Disagreement is never downgraded by doubt
---------------------------------------------------------------------
The rule that is easy to get backwards, and that the previous
`verify_compliance()` had backwards: an unverified readback that
*disagrees* is reported as ``MISMATCHED``, not as ``UNVERIFIED``.

Trust governs what agreement is worth, and nothing else. If the readback
is honest, the instrument is holding a value nobody chose. If the
readback is dishonest, the suite is steering a sample using a query that
lies. Both need a human, immediately, and there is no third reading of
the observation under which everything is fine.

The old ordering checked `COMPLIANCE_READBACK_TRUSTED` before comparing,
so an untrusted driver reporting 12 mA against a requested 100 uA - the
exact 120-fold widening the U2722A bench session watched happen - came
out as a skip.

---------------------------------------------------------------------
Absence of evidence never renders as a pass
---------------------------------------------------------------------
Three of the five states are neither pass nor fail, and that is
deliberate: the generated bench status already distinguishes
*stale* / *failing* / *unverified* for exactly this reason, and a
checkup line has the same obligation. A report that cannot tell "nobody
asked" from "asked and it was fine" is the report that made five of
seven instruments read clean in the 2026-08-18 round, where clean meant
*none observed*.
"""

#: The instrument cannot report this at all.
UNSUPPORTED = "unsupported"
#: Asked, and no usable answer came back.
UNREADABLE = "unreadable"
#: Answered and agreed, but the readback itself has never been checked
#: against hardware.
UNVERIFIED = "unverified"
#: Answered, trusted, and agreed.
CONFIRMED = "confirmed"
#: Answered and disagreed with what was requested. A safety event.
MISMATCHED = "mismatched"

#: Every state, in increasing order of how much is known.
STATES = (UNSUPPORTED, UNREADABLE, UNVERIFIED, CONFIRMED, MISMATCHED)

#: How each state renders in a checkup report.
#:
#: Only `CONFIRMED` is a pass. `MISMATCHED` is a fail on every subject
#: this module covers - there is no readback here whose disagreement is
#: cosmetic.
SEVERITY = {
    UNSUPPORTED: "skip",
    UNREADABLE: "warn",
    UNVERIFIED: "warn",
    CONFIRMED: "pass",
    MISMATCHED: "fail",
}

#: Default fractional agreement. Generous on purpose, and for a measured
#: reason: instruments round, and the GSM-20H10 returns `1.050000e-04`
#: for a 100 uA range's full scale. A check tight enough to call that a
#: mismatch would cry wolf on every instrument that reports full scale
#: rather than the value it was handed.
DEFAULT_TOLERANCE = 0.01


class Readback:
    """One answer to "are you in the state I asked for?".

    Deliberately not a bare `(verdict, detail)` tuple, which is what the
    compliance check used and which made the trust rule easy to get
    wrong at each call site. Carrying the numbers means the caller can
    say *how far* out a mismatch was without re-deriving it, and the
    severity mapping lives in one place instead of in a dict per caller.
    """

    __slots__ = ("subject", "state", "requested", "reported", "unit",
                 "detail")

    def __init__(self, subject, state, detail, requested=None,
                 reported=None, unit=""):
        if state not in STATES:
            raise ValueError(f"Unknown readback state: {state!r}")
        self.subject = subject
        self.state = state
        self.detail = detail
        self.requested = requested
        self.reported = reported
        self.unit = unit

    @property
    def severity(self):
        """"pass" / "warn" / "fail" / "skip", for a checkup Result."""
        return SEVERITY[self.state]

    @property
    def is_safety_event(self):
        """True when the instrument is not in the state it was asked for.

        Named rather than left as `state == MISMATCHED` at each call
        site, because the callers are the places that decide how loud to
        be and they should not each be re-deciding what counts.
        """
        return self.state == MISMATCHED

    def as_dict(self):
        return {"subject": self.subject, "state": self.state,
                "detail": self.detail, "requested": self.requested,
                "reported": self.reported, "unit": self.unit}

    def __repr__(self):
        return f"<Readback {self.subject}: {self.state} - {self.detail}>"


def agrees(requested, reported, tolerance=DEFAULT_TOLERANCE):
    """Fractional comparison, with zero handled exactly.

    Zero is its own case because a fraction of zero is not a tolerance:
    a power limit of 0 means *disabled*, and 1 mW is not "0 W within one
    percent", it is the ceiling being enabled behind the software's
    back. So a requested zero demands a reported zero.
    """
    if requested is None or reported is None:
        return False
    if requested == 0:
        return reported == 0
    return abs(abs(reported) - abs(requested)) / abs(requested) <= tolerance


def compare(subject, requested, reported, *, supported, trusted,
            unit="", tolerance=DEFAULT_TOLERANCE, error=None,
            unsupported_detail=None, matcher=None, mismatch_note=None):
    """Turn a readback attempt into one of the five states.

    `supported` says whether this driver implements the query at all -
    which is a property of the driver, not of the reply, and is why a
    `None` from a driver that never implemented the reader is
    ``UNSUPPORTED`` while a `None` from one that did is ``UNREADABLE``.
    Collapsing those two would hide a query that has started failing
    behind seven drivers that never had one.

    `trusted` says whether the readback has been checked at the bench
    against a value the instrument was known to hold. It gates
    ``CONFIRMED`` and nothing else; see the module docstring.

    `matcher` replaces the default fractional comparison for subjects
    where "the same value" is not what agreement means. A **range** is
    the case that forced it: an instrument reports a range by its full
    scale, and the Keithley and GW Instek families put full scale 5%
    above the nominal decade - `1.050000E-04` for the 100 uA range - so
    a fractional test tight enough to catch a range that was silently
    narrowed would call every correct answer a mismatch.

    `mismatch_note` is appended to a mismatch detail, for a subject
    whose disagreement has more than one meaning worth naming.
    """
    if not supported:
        return Readback(subject, UNSUPPORTED,
                        unsupported_detail or
                        "this instrument does not report it",
                        requested=requested, unit=unit)
    if error is not None:
        return Readback(subject, UNREADABLE,
                        f"the query failed: {error}",
                        requested=requested, unit=unit)
    if reported is None:
        return Readback(subject, UNREADABLE,
                        "asked, and no usable answer came back",
                        requested=requested, unit=unit)

    shown_requested = _show(requested, unit)
    shown_reported = _show(reported, unit)

    matched = (matcher(requested, reported) if matcher is not None
               else agrees(requested, reported, tolerance))
    if not matched:
        return Readback(
            subject, MISMATCHED,
            f"asked for {shown_requested}, instrument reports "
            f"{shown_reported}"
            + (f". {mismatch_note}" if mismatch_note else "")
            + ("" if trusted else
               " - and this readback has never been verified, so either "
               "the instrument is holding a value nobody chose or the "
               "query itself is answering dishonestly. Both need "
               "checking before anything is sourced"),
            requested=requested, reported=reported, unit=unit)

    if not trusted:
        return Readback(
            subject, UNVERIFIED,
            f"reports {shown_reported} against {shown_requested}, but "
            f"this readback has never been checked against a value this "
            f"instrument was known to hold, so the agreement is not "
            f"evidence",
            requested=requested, reported=reported, unit=unit)

    return Readback(subject, CONFIRMED, shown_reported,
                    requested=requested, reported=reported, unit=unit)


def _show(value, unit):
    if value is None:
        return "nothing"
    try:
        text = f"{float(value):.6g}"
    except (TypeError, ValueError):
        return f"{value}"
    return f"{text} {unit}".strip()
