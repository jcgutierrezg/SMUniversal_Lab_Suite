"""
Which code, and which firmware, a bench report actually describes.

Two gaps, the same shape, both found the hard way in August 2026.

**The code.** A GSM-20H10 checkup was clean on 2026-08-06 and had six
failures on 2026-08-18. Working out what changed in between meant
bisecting git by hand, because neither report recorded the commit it
ran at. That took five rounds of hypotheses - three of them wrong - to
establish something a `git rev-parse HEAD` in the header would have
answered in one line. `docs/open/checkup-owed.md` already derives
staleness from git history, but it can only compare a *date* against a
commit; a report that names its commit can be compared exactly.

**The firmware.** Every bench finding recorded for the GSM-20H10 -
`OUTP?` answering 0 with the output live, a source-autorange command
resetting the compliance, the reset defaults, the reading time - is a
claim about **firmware V1.16**, and nothing anywhere said so. GW Instek
publish V1.30. Upgrading would silently invalidate the note, and
nothing in the suite would notice, because the staleness machinery
watches the code and not the instrument.

A finding is about a version of the code *and* a version of the
instrument. Recording one and not the other was never defensible; it
just took a firmware upgrade being on the table to make it obvious.
"""
import re
import subprocess


def head_commit(root=None):
    """`(sha, dirty)` for the working tree, or `(None, False)`.

    `dirty` matters more than it looks. A report taken from a tree with
    uncommitted changes describes code that exists nowhere else, so the
    sha alone would be a lie by omission - it names a commit that does
    not contain what ran.

    Returns `None` rather than raising when git is unavailable or this
    is not a checkout. A bench tool must still produce its report from
    a zip download; it just cannot say which commit.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=10)
        if sha.returncode != 0:
            return (None, False)
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root, capture_output=True, text=True, timeout=10)
        dirty = bool(status.returncode == 0 and status.stdout.strip())
        return (sha.stdout.strip(), dirty)
    except (OSError, subprocess.SubprocessError):
        return (None, False)


#: Version-ish fields inside an `*IDN?` reply. Deliberately loose: the
#: replies in this lab are
#:
#:   KEITHLEY INSTRUMENTS INC.,MODEL 2401,4084766,A01 Aug 25 2011 ...
#:   Keithley Instruments Inc., Model 2611A, 1314733, 2.2.2
#:   GWInstek,GSM-20H10,GEW852313,V1.16
#:   Keysight Technologies,B2901A,MY51142365,3.1.1645.5820
#:   Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
#:
#: - five vendors, five shapes, and the miniSMU carries two version-like
#: fields. So this reports what it found rather than parsing a grammar
#: that does not exist.
_VERSION_FIELD = re.compile(r"^v?\d+(\.\d+)+", re.IGNORECASE)


def firmware_from_idn(idn):
    """The firmware-looking part of an `*IDN?` reply, or `None`.

    SCPI puts the firmware in the fourth comma-separated field, and
    most instruments here honour that. The 2401 does not - its fourth
    field is `A01 Aug 25 2011 12:57:43/A02  /T/K`, which is a firmware
    revision with a build date welded on - so the whole field is kept
    when it does not look like a bare version.

    Kept verbatim rather than normalised. `V1.16` and `1.16` are the
    same firmware, but a note that says `V1.16` should be greppable
    against a report that says `V1.16`, and normalising invents a
    spelling neither the instrument nor the manual uses.
    """
    if not idn:
        return None
    fields = [f.strip() for f in str(idn).split(",")]
    if len(fields) < 4:
        return None
    tail = fields[3]
    if not tail:
        return None
    first = tail.split()[0] if tail.split() else tail
    return first if _VERSION_FIELD.match(first) else tail


def describe(idn=None, root=None):
    """Everything a report should say about where it came from.

    Returned as a dict so both the JSON and the Markdown render the
    same facts, and neither can drift from the other by being written
    twice.
    """
    sha, dirty = head_commit(root)
    return {
        "commit": sha,
        "dirty": dirty,
        "firmware": firmware_from_idn(idn),
    }


def as_markdown_lines(provenance):
    """The provenance rows for a report header.

    Absent values are still printed, saying so. A missing row reads as
    an oversight; `not a git checkout` reads as a fact about how the
    report was taken.
    """
    sha = provenance.get("commit")
    if sha:
        commit = f"`{sha[:12]}`" + (
            " **plus uncommitted changes**" if provenance.get("dirty") else "")
    else:
        commit = "not a git checkout"
    firmware = provenance.get("firmware") or "not reported in `*IDN?`"
    return [
        f"- **Code:** {commit}",
        f"- **Firmware:** {firmware}",
    ]
