"""What a bench report has to say about where it came from.

Two gaps closed on 2026-08-20, both the same shape:

  * a checkup report did not record the **commit** it ran at, so
    comparing a clean 2026-08-06 GSM-20H10 report against a six-failure
    2026-08-18 one meant bisecting git by hand - five rounds of
    hypotheses for something one line in the header answers;
  * no report recorded the instrument's **firmware**, so every finding
    in `docs/instruments/` is a claim about a version nothing names.
    GW Instek publish V1.30 for an instrument running V1.16 here, and
    upgrading would invalidate the note silently.

And one tool that could not tell a measurement from a failure.
"""
import pytest

import io
import subprocess
from contextlib import redirect_stdout

from core.provenance import (as_markdown_lines, describe, firmware_from_idn,
                             head_commit)

# The identity strings of every instrument in this lab, verbatim from
# their 2026-08-18 checkups. Five vendors, five shapes - which is the
# reason `firmware_from_idn` reports what it finds rather than parsing
# a grammar that does not exist.
REAL_IDNS = [
    ("Keithley2401",
     "KEITHLEY INSTRUMENTS INC.,MODEL 2401,4084766,"
     "A01 Aug 25 2011 12:57:43/A02  /T/K",
     "A01 Aug 25 2011 12:57:43/A02  /T/K"),
    ("Keithley2611A",
     "Keithley Instruments Inc., Model 2611A, 1314733, 2.2.2", "2.2.2"),
    ("Keithley2635B",
     "Keithley Instruments Inc., Model 2635B, 4126721, 3.2.2", "3.2.2"),
    ("GWInstekGSM20H10",
     "GWInstek,GSM-20H10,GEW852313,V1.16", "V1.16"),
    ("KeysightB2901A",
     "Keysight Technologies,B2901A,MY51142365,3.1.1645.5820",
     "3.1.1645.5820"),
    ("KeysightU2722A",
     "AGILENT TECHNOLOGIES,U2722A,MY62030002,R1.10-1.12-1.06",
     "R1.10-1.12-1.06"),
    ("UndalogicMiniSMU",
     "Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)",
     "v1.4.6(6b82396)"),
]


def test_every_instrument_in_this_lab_reports_its_firmware(check):
    """All seven, against the strings they actually send.

    Written from the real replies rather than from the SCPI standard,
    because two of them do not follow it. The 2401's fourth field is a
    firmware revision with a build date welded on, and the U2722A's
    starts with an `R`, so a parser expecting a bare dotted version
    would drop both - the two oldest instruments on the bench, and the
    ones whose firmware is least likely to be revisited.
    """
    for name, idn, expected in REAL_IDNS:
        check(f"{name}: {expected}", firmware_from_idn(idn) == expected,
              repr(firmware_from_idn(idn)))


def test_firmware_is_none_when_there_is_nothing_to_report(check):
    """`None`, not a guess and not an empty string.

    A report saying "firmware: not reported in *IDN?" is a fact about
    the instrument. A report saying "firmware: " is an oversight, and
    they must not look the same.
    """
    for idn in (None, "", "nonsense", "one,two,three", "a,b,c,"):
        check(f"{idn!r} yields None", firmware_from_idn(idn) is None,
              repr(firmware_from_idn(idn)))


def test_the_commit_is_recorded_with_its_dirtiness(check):
    """A sha alone would be a lie by omission on a modified tree.

    A report taken from a tree with uncommitted changes describes code
    that exists nowhere else, so naming the commit without saying so
    would point at something that does not contain what ran. That is
    the same gap `git apply` without committing left in the patch
    workflow, one layer up.
    """
    sha, dirty, paths = head_commit()
    if sha is None:
        pytest.skip("not a git checkout; nothing to record")

    check("the sha is a full hex commit id",
          len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), sha)
    check("dirtiness is a bool, not a string", isinstance(dirty, bool))

    reported = subprocess.run(["git", "status", "--porcelain"],
                              capture_output=True, text=True)
    expected = [l for l in reported.stdout.splitlines() if l.strip()]
    check("and it agrees with git",
          dirty == bool(expected),
          f"said {dirty}, git says {bool(expected)}")
    check("the modified paths come back, not just the flag",
          paths == expected,
          f"{paths} vs {expected}")
    check("dirty and the path list agree with each other",
          dirty == bool(paths),
          f"dirty={dirty} with {len(paths)} paths - a flag that can "
          f"disagree with its own evidence is worse than no flag")


def test_provenance_survives_not_being_a_checkout(check):
    """A bench tool must still produce a report from a zip download.

    Refusing to run there would be the wrong trade: the report is worth
    more than the provenance line, and "not a git checkout" is itself a
    useful thing for a report to say.
    """
    lines = as_markdown_lines({"commit": None, "dirty": False,
                               "firmware": None})
    text = "\n".join(lines)
    check("it says so rather than leaving the row out",
          "not a git checkout" in text, text)
    check("and the same for a missing firmware",
          "not reported" in text, text)


def test_a_dirty_tree_is_stated_in_the_header(check):
    """Loudly, in the row itself - not as a flag someone has to notice."""
    text = "\n".join(as_markdown_lines(
        {"commit": "0123456789abcdef0123456789abcdef01234567",
         "dirty": True, "firmware": "V1.16"}))
    check("the short sha is shown", "0123456789ab" in text, text)
    check("and the uncommitted changes are called out",
          "uncommitted" in text, text)

    clean = "\n".join(as_markdown_lines(
        {"commit": "0123456789abcdef0123456789abcdef01234567",
         "dirty": False, "firmware": "V1.16"}))
    check("a clean tree says nothing extra",
          "uncommitted" not in clean, clean)


def test_describe_carries_both_facts(check):
    """One call, both halves, so the JSON and the Markdown cannot drift.

    They would have drifted: the open-circuit flag was in the Markdown
    prose and not the JSON until someone tried to read a report on its
    own, and the JSON is the half people send to someone else.
    """
    got = describe(idn="GWInstek,GSM-20H10,GEW852313,V1.16")
    check("firmware is there", got["firmware"] == "V1.16", repr(got))
    check("commit is there", "commit" in got, repr(got))
    check("dirty is there", "dirty" in got, repr(got))


# ------------------------------------------------------------------
# the timing scan's own reading check
# ------------------------------------------------------------------
def test_the_timing_scan_refuses_to_fit_through_failed_reads(check):
    """It timed `(None, None)` exactly like a real measurement.

    On the GSM-20H10 that produced 10.3 ms flat across a thousandfold
    change in NPLC, a straight-line fit through it, and a printed
    conclusion that the driver's declared aperture was "6493x too
    long" - from a run where every read had failed. The checkup, same
    instrument, same NPLC, measures 75.2 ms.

    Checked through the module's own helpers rather than by driving the
    whole tool, which needs an instrument. What matters is that a blank
    is *counted* and that a spread of nothing reports as nothing.
    """
    import tools.timing_scan as timing_scan

    check("a blank reading is not a number",
          timing_scan._spread([None, None, None]) == 0.0,
          repr(timing_scan._spread([None, None, None])))
    check("one number is not a spread",
          timing_scan._spread([1.0]) == 0.0)
    check("and a real spread is peak-to-peak",
          timing_scan._spread([1.0, 5.0, 3.0]) == 4.0,
          repr(timing_scan._spread([1.0, 5.0, 3.0])))
    check("mixed blanks do not poison the arithmetic",
          timing_scan._spread([1.0, None, 5.0]) == 4.0,
          repr(timing_scan._spread([1.0, None, 5.0])))


# ------------------------------------------------------------------
# the compliance readback, and the checkup check built on it
# ------------------------------------------------------------------
def test_an_untrusted_readback_reports_unverified_not_pass(check):
    """A readback nobody has checked must not answer "fine".

    The GSM-20H10's `OUTP?` returns 0 with the output on and 10 V
    flowing, so at least one state query on that instrument lies - and
    five rounds of reasoning were built on believing it. A compliance
    readback that an instrument answers dishonestly is worse than none:
    it produces confident reassurance about the exact thing it exists
    to verify.

    So the trust flag is three-valued, and `None` - "it answers, nobody
    has checked whether it tells the truth" - reports `unverified`.

    **Trust governs agreement and nothing else.** An unverified readback
    that *disagrees* is a mismatch, not an unverified: either the
    instrument is holding a value nobody chose or the query is answering
    dishonestly, and both need a human before anything is sourced. That
    ordering was the wrong way round until the readback contract landed,
    so an untrusted driver reporting 12 mA against a requested 100 uA -
    the exact 120-fold widening the U2722A bench session watched happen
    - came out as a skip.
    """
    from core import readback as readback_states
    from core.transports.null_transport import NullTransport
    from drivers.base_smu import BaseSMU
    from drivers.dummy_smu import DummySMU

    class Readable(DummySMU):
        COMPLIANCE_READBACK_TRUSTED = None

        def read_current_limit(self):
            return 1e-4

    transport = NullTransport()
    transport.connect("fake")
    driver = Readable(transport)

    answer = driver.verify_compliance("voltage", 1e-4)
    check("an unchecked readback is unverified, not confirmed",
          answer.state == readback_states.UNVERIFIED,
          f"{answer.state}: {answer.detail}")
    check("and it says why", "never been checked" in answer.detail,
          answer.detail)
    check("an unverified agreement is not a pass",
          answer.severity == "warn", answer.severity)

    # The ordering rule, checked before the trusted case so that a
    # regression cannot be hidden by the trusted one passing.
    answer = driver.verify_compliance("voltage", 1e-2)
    check("an UNVERIFIED readback that disagrees is still a mismatch",
          answer.state == readback_states.MISMATCHED,
          f"{answer.state}: {answer.detail}")
    check("and it is a failure, not a warning",
          answer.severity == "fail" and answer.is_safety_event,
          f"{answer.severity}")

    driver.COMPLIANCE_READBACK_TRUSTED = True
    answer = driver.verify_compliance("voltage", 1e-4)
    check("a trusted readback that agrees is confirmed",
          answer.state == readback_states.CONFIRMED, answer.state)
    check("and only that state is a pass", answer.severity == "pass",
          answer.severity)

    answer = driver.verify_compliance("voltage", 1e-2)
    check("a trusted readback that disagrees is a mismatch",
          answer.state == readback_states.MISMATCHED,
          f"{answer.state}: {answer.detail}")
    check("and it names both values",
          "0.0001" in answer.detail and "0.01" in answer.detail,
          answer.detail)

    # A driver that answers nothing but claims it can ask is a different
    # state again from one that never had the query.
    class Silent(DummySMU):
        def read_current_limit(self):
            return None

    check("a driver that cannot read back at all says unsupported",
          DummySMU(transport).verify_compliance("voltage", 1e-4).state
          == readback_states.UNSUPPORTED)
    check("a driver that asks and gets nothing says unreadable",
          Silent(transport).verify_compliance("voltage", 1e-4).state
          == readback_states.UNREADABLE)
    check("and neither renders as a pass",
          DummySMU(transport).verify_compliance("voltage", 1e-4).severity
          != "pass"
          and Silent(transport).verify_compliance("voltage", 1e-4).severity
          != "pass")
    check("and BaseSMU's default is not to claim trust",
          BaseSMU.COMPLIANCE_READBACK_TRUSTED is False)


def test_the_checkup_catches_a_compliance_that_ranging_moved(check):
    """The check that would have saved a week.

    Modelled on what the GSM-20H10 actually does: `apply_ranges` resets
    the compliance to the instrument's floor, silently, with no error
    raised and a clean queue. Before this check existed, that produced
    a clean checkup on any instrument where nothing downstream happened
    to trip over the collapsed value.

    The paired instrument - same fake, compliance left alone - is what
    makes the first half mean anything: without it the test would pass
    against a check that failed unconditionally.
    """
    from core.checkup import Checkup
    from core.transports.null_transport import NullTransport
    from drivers.dummy_smu import DummySMU

    class Collapsing(DummySMU):
        """Ranging resets the compliance, as the GSM-20H10 does."""
        COMPLIANCE_READBACK_TRUSTED = True
        FLOOR = 1e-9

        def __init__(self, transport, collapse=True, **kw):
            super().__init__(transport, **kw)
            self._limit = 0.0
            self._collapse = collapse

        def set_current_limit(self, amps):
            self._limit = amps
            return super().set_current_limit(amps)

        def apply_ranges(self, plan, log=None):
            if self._collapse:
                self._limit = self.FLOOR
            return super().apply_ranges(plan, log=log)

        def read_current_limit(self):
            return self._limit

    transport = NullTransport()
    transport.connect("fake")
    checkup = Checkup(Collapsing(transport, collapse=True),
                      open_circuit=False)
    checkup.run()
    collapsed = next(r for r in checkup.results
                     if r.name == "compliance survives ranging")
    check("a collapsed compliance fails the check",
          collapsed.severity == "fail", f"{collapsed.severity}: "
                                        f"{collapsed.detail}")
    check("and the detail points at the fault note",
          "fault" in collapsed.detail or "23-autorange" in collapsed.detail,
          collapsed.detail)

    transport = NullTransport()
    transport.connect("fake")
    checkup = Checkup(Collapsing(transport, collapse=False),
                      open_circuit=False)
    checkup.run()
    intact = next(r for r in checkup.results
                  if r.name == "compliance survives ranging")
    check("an instrument that leaves it alone passes",
          intact.severity == "pass", f"{intact.severity}: {intact.detail}")
