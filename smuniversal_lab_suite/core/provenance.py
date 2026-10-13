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
import ast
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
#: **Both base classes are named, and the second is not optional.** When
#: `BaseInstrument` was split out of `BaseSMU`, the software sweep, the
#: sentinel handling and the readback grading went with it. A list
#: naming only `base_smu.py` after that split would have gone on
#: answering - it would simply have stopped covering the sweep engine,
#: so a change to the thing that steps every software sweep would mark
#: nothing stale and no page would say anything had happened. That is
#: fault 31 exactly: a stamp that stops moving reads identically to one
#: with nothing to report. `tests/test_instrument_contract.py` fails if
#: a base class is ever left out of this list.
#:
#: What is compared is what each file *does* - see `code_fingerprint`.
#: A comment or a docstring edited in a base class leaves every driver
#: current; a statement changed there marks every driver that inherits
#: it stale, which is the point of naming the bases at all. A checkup
#: costs three minutes; a driver wrongly believed current costs a
#: dataset. For the rare change a person can see is harmless and the
#: digest cannot, the escape hatch is `bench_revalidated` in the note's
#: frontmatter, which requires a written reason - see
#: docs/reference/schema.md.
#:
#: It lives here rather than in `tools/build_docs.py` because two things
#: now read it: the checkup, which stamps a fingerprint into its report,
#: and the docs build, which compares one. Two copies of this list would
#: drift, and the symptom would be a driver reported current against a
#: dependency set nobody had checked.
#: And they are named **per fleet**, because the two do not share a
#: contract below `BaseInstrument`.
#:
#: A load's behaviour comes from `base_load.py` and none of it from
#: `base_smu.py`. Fingerprinting every driver against the union got
#: this wrong in both directions at once: a change to the load
#: contract - the sign convention, the headroom guard - would have
#: marked nothing stale, while an edit to a source-measure unit's
#: compliance handling would have marked the load stale for a file it
#: does not inherit. The first is fault 31 again, and it was live for
#: exactly one checkup.
SHARED_CODE_PATHS_BY_FLEET = {
    "smu": ["drivers/base_instrument.py", "drivers/base_smu.py"],
    "load": ["drivers/base_instrument.py", "drivers/base_load.py"],
    "supply": ["drivers/base_instrument.py", "drivers/base_supply.py"],
}

#: Every base class in any fleet, for callers that want the whole
#: set rather than one fleet's. Derived, so a fleet added above cannot
#: be left out of it.
SHARED_CODE_PATHS = sorted(
    {path for paths in SHARED_CODE_PATHS_BY_FLEET.values() for path in paths})


def code_paths_for(driver_path, fleet="smu"):
    """The files a checkup of `driver_path` is actually about.

    `fleet` picks which base classes count - see
    `SHARED_CODE_PATHS_BY_FLEET`. It defaults to `"smu"` because that is
    what every caller meant before there was a second fleet, and because
    a wrong default there is the conservative direction: an SMU
    fingerprinted against the SMU bases is correct, and the only way to
    get a load's is to say so.

    An unknown fleet falls back to the union rather than to nothing. A
    digest over too many files over-reports staleness; one over too few
    under-reports it, and under-reporting is how a driver comes to be
    believed current against code nobody checked.

    A `None` driver path - a frozen build, where the module has no file
    on disk - yields the shared paths alone rather than raising. The
    fingerprint is then honestly narrower, not absent.
    """
    shared = SHARED_CODE_PATHS_BY_FLEET.get(fleet, SHARED_CODE_PATHS)
    paths = {p for p in (driver_path, *shared) if p}
    return sorted(paths)


#: How much of the digest is recorded. Twelve hex characters is the
#: same width git uses for a short sha and is legible in a frontmatter
#: field; the odds of two different driver files colliding across the
#: lifetime of this repository are not worth the other fifty-two.
FINGERPRINT_LENGTH = 12

#: The package root, which every code path here is relative to -
#: `smuniversal_lab_suite` in a checkout, the installed package
#: otherwise. Package-relative rather than repository-relative because
#: an installed copy has no repository, and a fingerprint has to mean
#: the same files in both. The checkup and the docs build anchor their
#: paths here too.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


#: The definitions whose first statement, if it is a bare string, is a
#: docstring.
_DOCUMENTED = (ast.Module, ast.ClassDef, ast.FunctionDef,
               ast.AsyncFunctionDef)


def _canonical(node):
    """A syntax tree as text, with nothing in it but structure.

    Written out by hand rather than with `ast.dump`, whose format has
    changed between Python versions: a fingerprint that moved because
    the interpreter was upgraded would mark the whole fleet stale with
    nothing changed. Fields that are empty or absent are left out for
    the same reason - a later Python that grows a new optional field on
    a node leaves every existing tree reading as it did.

    Line numbers and columns are not fields, so where a statement sits
    in the file is not part of this.
    """
    if isinstance(node, ast.AST):
        parts = [type(node).__name__]
        for name in node._fields:
            value = getattr(node, name, None)
            if value is None or value == []:
                continue
            parts.append(f"{name}={_canonical(value)}")
        return "(" + " ".join(parts) + ")"
    if isinstance(node, list):
        return "[" + " ".join(_canonical(item) for item in node) + "]"
    # A constant. The type is written beside the value because `1` and
    # `1.0` and `True` are different programs and compare equal.
    return f"{type(node).__name__}:{node!r}"


def operative_source(raw):
    """What a Python file *does*, as bytes, with what it merely *says*
    taken out.

    Comments, docstrings, blank lines, line breaks and the choice of
    quotes are all gone; every statement, name, number and string that
    the interpreter acts on is still there. Two files that give the same
    result here run identically, and a commissioning record is a claim
    about how a driver runs.

    Only a docstring is dropped - a bare string that is the first
    statement of a module, class or function. A string anywhere else is
    an argument, a message or a value, and changing one changes what the
    instrument is sent or what the operator is told.

    Anything that does not parse as Python is returned as it came, line
    endings aside. A file this cannot read is compared byte for byte,
    which is the strict direction to fail in.
    """
    text = raw.replace(b"\r\n", b"\n")
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return text
    for node in ast.walk(tree):
        if not isinstance(node, _DOCUMENTED) or not node.body:
            continue
        first = node.body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            del node.body[0]
    return _canonical(tree).encode("utf-8")


def code_fingerprint(paths, root=None):
    """A digest of what the files a checkup was about *do*.

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
    and this answers it directly.

    **It is the code that is compared, not the bytes.** Until
    2026-10-13 this hashed each file as it stood, so a comment
    corrected in a driver marked its instrument stale and sent someone
    to the bench to re-prove what had not changed. That made the
    cheapest improvement to a driver - writing down what a bench
    session had just found - cost a second bench session, and the
    predictable result was findings kept out of the files they were
    about. Each Python file is now reduced to what it does before it is
    hashed: see `operative_source`.

    Two consequences worth knowing:

    * No git is consulted, so this works on a zip download, on a shallow
      clone, and on a bench machine with no history. The shallow-clone
      guard that used to be needed here is gone.
    * A comment, a docstring or a reformatting leaves the digest where
      it was. Anything the interpreter acts on moves it - a statement, a
      default, a constant, the text of a command or of a message - and
      so does commenting a line *out*, because the statement is then
      gone.

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
        # NUL-separated, and the path is hashed as well as the content.
        # Without separators, moving a character from the end of one
        # path to the start of the next file's contents would produce
        # the same digest; with the path included, two drivers that
        # happen to be identical are still distinguishable.
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(operative_source(raw) if rel.endswith(".py")
                      else raw.replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()[:FINGERPRINT_LENGTH]


_VERSION_FIELD = re.compile(r"^v?\d+(\.\d+)+", re.IGNORECASE)

#: A whole whitespace-separated token that is unmistakably a version:
#: a V, then dotted digits. Stricter than _VERSION_FIELD on purpose - it
#: is searched for anywhere in a reply that has no SCPI fields, where a
#: bare "1.1" could be a model or a hardware revision.
_VERSION_TOKEN = re.compile(r"^v\d+(\.\d+)+$", re.IGNORECASE)


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
        # No SCPI fields at all. The Multicomp Pro 72-13200 answers
        # `Multicomp Pro 72-13200 V3.30 SN:00028215` - space-separated,
        # so its 2026-09-16 checkup recorded no firmware though the
        # reply names it. Only a token that is plainly a version is
        # taken; anything less stays None rather than a guess.
        if len(fields) == 1:
            for token in fields[0].split():
                if _VERSION_TOKEN.match(token):
                    return token
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
