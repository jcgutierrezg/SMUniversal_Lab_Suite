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
import hashlib
import os
import re
import subprocess

#: How many modified paths a report lists before it stops naming them.
#: Enough to see what happened; not so many that a report taken beside
#: an untidy working tree becomes mostly `git status` output.
DIRTY_PATHS_LISTED = 20


def head_commit(root=None):
    """`(sha, dirty, paths)` for the working tree.

    `dirty` matters more than it looks. A report taken from a tree with
    uncommitted changes describes code that exists nowhere else, so the
    sha alone would be a lie by omission - it names a commit that does
    not contain what ran.

    `paths` is the reason a flag alone is not enough. On 2026-08-21 a
    checkup came back `dirty: True` from a tree its operator had just
    hard-reset and believed clean, and neither of us could tell from the
    report whether that mattered. It turned out to be scratch `.txt`
    files from a SCPI debugging session sitting beside the code, which
    changes nothing about what ran - but a modified driver would have
    looked exactly the same, and that would have made the whole report
    unattributable. A flag that is sometimes alarming and sometimes not,
    with no way to tell which, gets ignored - and the time it is
    ignored is the time it was the real thing.

    So the report records the paths. Ignored files are excluded, since
    `checkups/` and `*.patch` are gitignored and the tool writes its own
    output there: a report that flagged its own previous run would be
    permanently dirty and permanently uninformative.

    Returns `(None, False, [])` rather than raising when git is
    unavailable or this is not a checkout. A bench tool must still
    produce its report from a zip download; it just cannot say which
    commit.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=10)
        if sha.returncode != 0:
            return (None, False, [])
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root, capture_output=True, text=True, timeout=10)
        if status.returncode != 0:
            return (sha.stdout.strip(), False, [])
        lines = [line for line in status.stdout.splitlines() if line.strip()]
        return (sha.stdout.strip(), bool(lines), lines)
    except (OSError, subprocess.SubprocessError):
        return (None, False, [])


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
#: Every driver's verification depends on more than its own file. A
#: change to the shared base class changes the software sweep, the
#: sentinel handling and `apply_ranges()` for every driver that inherits
#: them, so a checkup taken before that change no longer covers them.
#:
#: Deliberately conservative: this over-reports (a docstring edit to
#: base_smu.py marks the whole fleet stale) and never under-reports. A
#: checkup costs three minutes; a driver wrongly believed current costs
#: a dataset. If the over-reporting ever bites, the escape hatch is
#: `bench_revalidated` in the note's frontmatter, which requires a
#: written reason - see docs/reference/schema.md.
#:
#: It lives here rather than in `tools/build_docs.py` because two things
#: now read it: the checkup, which stamps a fingerprint into its report,
#: and the docs build, which compares one. Two copies of this list would
#: drift, and the symptom would be a driver reported current against a
#: dependency set nobody had checked.
SHARED_CODE_PATHS = ["drivers/base_smu.py"]


def code_paths_for(driver_path):
    """The files a checkup of `driver_path` is actually about.

    A `None` driver path - a frozen build, where the module has no file
    on disk - yields the shared paths alone rather than raising. The
    fingerprint is then honestly narrower, not absent.
    """
    paths = {p for p in (driver_path, *SHARED_CODE_PATHS) if p}
    return sorted(paths)


#: How much of the digest is recorded. Twelve hex characters is the
#: same width git uses for a short sha and is legible in a frontmatter
#: field; the odds of two different driver files colliding across the
#: lifetime of this repository are not worth the other fifty-two.
FINGERPRINT_LENGTH = 12

#: Repository root, for callers that do not pass one.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def code_fingerprint(paths, root=None):
    """A digest of the *content* of the files a checkup was about.

    This exists because the obvious alternative does not work. Staleness
    was derived from `git log -1 --format=%cs` on each driver: if the
    driver's last commit is newer than the note's `last_bench`, the
    checkup described code that no longer runs.

    A commit date is not a property of the tree. `git am` sets it to
    when the patch was applied; a rebase sets it to the rebase; a
    GitHub squash-merge sets **both** author and committer date to the
    instant of the merge. So the same bytes answer differently depending
    on when they were merged, and the failure is the worst kind: the
    committed pages and a fresh build disagree, CI goes red on `main`,
    and nothing in the tree has changed. That is not hypothetical - it
    is what this function was written in response to.

    Content has none of those problems. The question the note is really
    asking is "is the code that was checked the code that is running",
    which is a question about bytes, and this answers it directly.

    Two consequences worth knowing:

    * No git is consulted, so this works on a zip download, on a shallow
      clone, and on a bench machine with no history. The shallow-clone
      guard that used to be needed here is gone.
    * A comment-only edit still changes the digest and still marks the
      driver stale. That is the same behaviour the date rule had, and it
      is the conservative direction: over-reporting sends someone to the
      bench, under-reporting ships a number nobody checked.

    Line endings are normalised to LF before hashing. `.gitattributes`
    already pins `*.py` to LF in the working tree, so this changes
    nothing on a correct checkout - it stops a machine with a broken one
    from reporting the whole fleet stale over invisible bytes.

    Returns `None` if any named file is missing, so the caller can say
    "unknown" rather than inventing a digest for a file that is not
    there.
    """
    digest = hashlib.sha256()
    base = root or _ROOT
    for rel in sorted(paths):
        try:
            with open(os.path.join(base, rel), "rb") as handle:
                raw = handle.read()
        except OSError:
            return None
        # NUL-separated, and the path is hashed as well as the bytes.
        # Without separators, moving a character from the end of one
        # path to the start of the next file's contents would produce
        # the same digest; with the path included, two drivers that
        # happen to be identical are still distinguishable.
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw.replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()[:FINGERPRINT_LENGTH]


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


def describe(idn=None, root=None, code_paths=None):
    """Everything a report should say about where it came from.

    Returned as a dict so both the JSON and the Markdown render the
    same facts, and neither can drift from the other by being written
    twice.

    `code_paths` names the files this report is about - the driver and
    whatever it shares with the others. The resulting fingerprint is
    what `docs/instruments/<name>.md` records as `bench_code`, so the
    value pasted into a note is one the bench measured rather than one
    somebody computed afterwards from a tree that may have moved.
    """
    sha, dirty, paths = head_commit(root)
    return {
        "commit": sha,
        "dirty": dirty,
        # Capped, and the count kept whole, so a report beside an untidy
        # tree stays readable without pretending there were fewer.
        "dirty_paths": paths[:DIRTY_PATHS_LISTED],
        "dirty_count": len(paths),
        "firmware": firmware_from_idn(idn),
        "code_fingerprint": (code_fingerprint(code_paths, root)
                             if code_paths else None),
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
    # The line a bench operator copies into the instrument note. Named
    # after the field it goes into, because a digest with no home is a
    # number people skip past.
    fingerprint = provenance.get("code_fingerprint")
    rows = [
        f"- **Code:** {commit}",
        f"- **Firmware:** {firmware}",
    ]
    if fingerprint:
        rows.append(f"- **`bench_code`:** `{fingerprint}`")

    # Named, not just counted. The question a reader has is "does this
    # affect what ran", and `core/`, `drivers/` or `tools/` in this list
    # answers it differently from a stray scratch file beside the repo.
    paths = provenance.get("dirty_paths") or []
    if paths:
        total = provenance.get("dirty_count", len(paths))
        rows.append("- **Uncommitted when this ran:**")
        rows.extend(f"    - `{line}`" for line in paths)
        if total > len(paths):
            rows.append(f"    - ...and {total - len(paths)} more")
    return rows
