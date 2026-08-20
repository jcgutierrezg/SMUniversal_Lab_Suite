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
    sha, dirty = head_commit()
    if sha is None:
        pytest.skip("not a git checkout; nothing to record")

    check("the sha is a full hex commit id",
          len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), sha)
    check("dirtiness is a bool, not a string", isinstance(dirty, bool))

    reported = subprocess.run(["git", "status", "--porcelain"],
                              capture_output=True, text=True)
    check("and it agrees with git",
          dirty == bool(reported.stdout.strip()),
          f"said {dirty}, git says {bool(reported.stdout.strip())}")


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
