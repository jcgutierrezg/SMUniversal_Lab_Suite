"""Invariants for the documentation, made executable.

Why this file exists
--------------------
The documents this replaces did not rot because nobody cared. They
rotted because every invariant in them was a thing a person had to
remember, and the failures were silent - prose that has stopped being
true looks exactly like prose that is still true.

Four of them, all found by reading the repo against its own docs:

* `HANDOFF.md` said "drift between five hand-written drivers" and
  "Twenty-nine test files"; the registry held nine drivers and `tests/`
  held sixty-two.
* `INSTRUMENTS.md` opened with "Five source-measure units, all
  commissioned against real hardware" and then said, three hundred
  lines later, that the 2635B was not commissioned.
* `INSTRUMENTS.md` printed a fabricated `*IDN?` string for the 2635B in
  a code block formatted identically to the real ones.
* `HANDOFF.md` described the 2450's source/measure range ambiguity as
  an open defect needing "a wave of its own". Wave 6d had closed it.

Each of those is now either generated or asserted here. The rule the
whole file is built on: **a documentation claim that a machine can
check should not be written by a human.**

These are cheap, fast, and they have no Tk in them, so they run in the
shared process.
"""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import build_docs  # noqa: E402

DOCS = ROOT / "docs"
BENCH = ROOT / "bench"

#: Every field an instrument note must declare. Absence is a failure
#: rather than a default, because a default here would be a claim
#: nobody made - `bench_ever` defaulting to False would quietly mark a
#: commissioned driver unverified, and defaulting to True would do the
#: far worse opposite.
REQUIRED_INSTRUMENT_FIELDS = {
    "type", "title", "driver_class", "idn", "idn_confirmed", "physical",
    "maintenance", "bench_ever", "last_bench", "bench_notes",
    "bench_code", "bench_result", "bench_result_note",
    "bench_revalidated", "reading_time", "resolution", "best_for",
}

BENCH_RESULT_VALUES = {"pass", "fail"}

MAINTENANCE_VALUES = {"active", "on-request"}


def _markdown_files() -> list[Path]:
    """Every Markdown file the repository owns.

    Through `build_docs.owned_files` rather than a walk written here,
    and rather than a second copy of the exclusion logic: the test and
    the generator must agree on what "the repository's files" means, or
    a page can be built from one set and checked against another.

    The walk this replaces excluded four directory names by prefix and
    swept up everything else. Agent worktrees under `.claude/` put a
    complete second copy of the tree inside `ROOT`, and this file's
    hard-coded-count check reported fifteen offences - every one of them
    a copy of this repository's own `README.md`.
    """
    return build_docs.owned_files("*.md")


# ---------------------------------------------------------------------------
# The bijection: drivers and their notes
# ---------------------------------------------------------------------------

def test_every_driver_has_a_note_and_every_note_has_a_driver():
    """A driver added without a note, or a note left behind by a deleted
    driver, both fail here.

    This is the same mechanism as `LEDGER` in `test_driver_contract.py`:
    the cost of adding an instrument includes deciding what to say about
    it, and that cost is collected at the point of adding rather than at
    the bench six months later.
    """
    from drivers.registry import KNOWN_DRIVERS

    declared = {cls.__name__ for cls in KNOWN_DRIVERS}
    documented = {meta["driver_class"]
                  for meta, _ in build_docs.load_notes().values()}

    assert declared == documented, (
        f"drivers with no note: {sorted(declared - documented)}; "
        f"notes with no driver: {sorted(documented - declared)}"
    )


def test_instrument_notes_declare_every_required_field():
    for path, (meta, _body) in build_docs.load_notes().items():
        missing = REQUIRED_INSTRUMENT_FIELDS - set(meta)
        assert not missing, f"{path.name} is missing {sorted(missing)}"
        assert meta["type"] == "instrument", path.name
        assert meta["maintenance"] in MAINTENANCE_VALUES, (
            f"{path.name}: maintenance={meta['maintenance']!r}, "
            f"expected one of {sorted(MAINTENANCE_VALUES)}"
        )


def test_an_unconfirmed_idn_is_not_presented_as_a_real_one():
    """`idn_confirmed: false` must not sit next to a plausible string.

    `INSTRUMENTS.md` printed `...,MODEL 2635B,4001234,4.0.2` - invented
    serial, wrong case, wrong firmware - inside a code block styled
    exactly like the seven real ones, with a parenthetical caveat two
    lines below. The caveat is not what a reader copying a string sees.
    A guess must be `null`, not a well-formed lie.
    """
    for path, (meta, _body) in build_docs.load_notes().items():
        if meta["idn_confirmed"] is False:
            assert meta["idn"] is None, (
                f"{path.name} carries an *IDN? string it has not confirmed. "
                "An unconfirmed identity is null, never an example."
            )


def test_a_commissioning_claim_carries_its_evidence():
    """`bench_ever: true` requires a note saying what was actually run."""
    for path, (meta, _body) in build_docs.load_notes().items():
        if meta["bench_ever"] is True:
            assert meta["bench_notes"], (
                f"{path.name} claims a bench session with no record of it"
            )


def test_a_bench_session_records_whether_it_passed():
    """`bench_ever: true` must say what the last checkup actually did.

    Before `bench_result` existed, a note recorded only *when* the
    instrument was last checked, and everything downstream inferred that
    a recorded date meant a clean run. It did not: the U2722A was
    checked on 2026-08-21 and failed four checks, and under the old
    schema it would have rendered `Verified: yes` in the chooser.

    A date says a session happened. It cannot say how it went.
    """
    for path, (meta, _body) in build_docs.load_notes().items():
        if meta["bench_ever"] is not True:
            continue
        result = meta.get("bench_result")
        assert result in BENCH_RESULT_VALUES, (
            f"{path.name}: bench_result={result!r}, expected one of "
            f"{sorted(BENCH_RESULT_VALUES)}"
        )


def test_a_failing_checkup_says_what_failed():
    """`bench_result: fail` requires a reason, rendered where it is read.

    The reason goes into `checkup-owed.md`'s **Why** column, so someone
    deciding which instrument to use sees it without opening the note.
    A bare `fail` would tell them to avoid an instrument without telling
    them what for, which is how a usable instrument gets abandoned and
    an unusable one gets argued back into service.
    """
    for path, (meta, _body) in build_docs.load_notes().items():
        if meta.get("bench_result") != "fail":
            continue
        note = meta.get("bench_result_note")
        assert isinstance(note, str) and len(note.strip()) > 10, (
            f"{path.name}: bench_result is 'fail' but bench_result_note "
            f"is {note!r}. Say what failed."
        )


def test_a_passing_checkup_carries_no_failure_reason():
    """`bench_result` and `bench_result_note` must agree with each other.

    Found by mutation: flipping the U2722A's `bench_result` from `fail`
    to `pass` — a lie about what the checkup returned — passed the
    entire suite, because nothing in the repository knows what any
    checkup actually found. The reports are gitignored, so no test can
    verify the claim itself.

    What a test *can* catch is the realistic version of that mistake:
    editing one of the two fields and not the other. A note recording
    why the checkup failed, beside a claim that it passed, is a
    contradiction on its face and is now a failure.
    """
    for path, (meta, _body) in build_docs.load_notes().items():
        if meta.get("bench_result") != "pass":
            continue
        assert not meta.get("bench_result_note"), (
            f"{path.name} claims the checkup passed but still records "
            f"why it failed: {meta['bench_result_note']!r}. One of the "
            "two is out of date."
        )


def test_a_recorded_bench_code_looks_like_a_fingerprint():
    """`bench_code` must be a digest, not a note to self.

    It is compared for equality against a freshly computed one, so any
    value that is not a digest can only ever compare unequal - which
    renders as *stale* forever and looks exactly like a driver that
    really has moved. A wrong format here fails quietly and permanently,
    so it is checked at the point it is written.
    """
    from core.provenance import FINGERPRINT_LENGTH

    for path, (meta, _body) in build_docs.load_notes().items():
        value = meta.get("bench_code")
        if value is None:
            assert meta["bench_ever"] is not True or not meta["last_bench"], (
                f"{path.name} records a bench date but no bench_code, so "
                "nothing can tell whether that checkup still applies"
            )
            continue
        assert (isinstance(value, str)
                and len(value) == FINGERPRINT_LENGTH
                and all(c in "0123456789abcdef" for c in value)), (
            f"{path.name}: bench_code={value!r} is not a "
            f"{FINGERPRINT_LENGTH}-character hex digest"
        )


def test_the_revalidation_escape_hatch_requires_a_reason():
    """Waving a driver through must cost a sentence, not a keystroke.

    `bench_revalidated` exists because the staleness check deliberately
    over-reports: a docstring edit to `base_smu.py` marks the whole
    fleet stale. The hatch is real and it is meant to be used - but a
    bare `true` would let anyone silence the check without saying why,
    which is how the original "every driver has been run against its
    instrument" claim outlived its truth.
    """
    for path, (meta, _body) in build_docs.load_notes().items():
        value = meta.get("bench_revalidated")
        if value is None:
            continue
        assert isinstance(value, str) and len(value.strip()) > 10, (
            f"{path.name}: bench_revalidated must be a written reason "
            "naming the commit and why it does not affect the checkup, "
            f"not {value!r}"
        )


# ---------------------------------------------------------------------------
# The generated pages
# ---------------------------------------------------------------------------

def test_a_pages_content_does_not_depend_on_git_at_all(monkeypatch):
    """Generated pages must not depend on anything a merge rewrites.

    They did. Staleness came from `git log -1 --format=%cs` on each
    driver, and a commit date is not a property of the tree: `git am`
    sets it to when the patch was applied, a rebase sets it to the
    rebase, and a GitHub squash-merge sets **both** author and committer
    date to the instant of the merge. So the same bytes answered
    differently depending on when they were merged - the committed pages
    and a fresh build disagreed, and `main` went red with nothing in the
    tree changed.

    It also survived clean-checkout verification, because `git apply`
    leaves files uncommitted and `git log` still reported the old date.
    The local check could not have failed.

    So this asks the question at the root rather than at the symptom: it
    makes any subprocess call from `build_docs` explode, and requires
    every bench page to render anyway. Discriminating - under the old
    date rule this raises rather than merely differing.
    """
    def no_subprocesses(*args, **kwargs):
        raise AssertionError(
            "build_docs shelled out while rendering a bench page. "
            "Anything git reports about a commit is rewritten by a "
            "rebase or a squash-merge and cannot decide the content of "
            "a committed file."
        )

    monkeypatch.setattr(build_docs.provenance.subprocess, "run",
                        no_subprocesses)

    notes = {n: v for n, v in
             build_docs.load_notes(physical_only=True).items()
             if v[0].get("last_bench") and v[0].get("bench_ever")}
    assert notes, "no note carries a bench date; this test would pass vacuously"

    for note, (meta, body) in notes.items():
        page = build_docs.render_bench_instrument(meta, body, note)
        assert page.strip(), f"{note.name} rendered empty"


def test_generated_pages_match_a_fresh_build():
    """A generated file that has been hand-edited fails the suite.

    Same mechanism as `tests/golden/*.json`: the artefact is committed
    so it renders on GitHub and on a bench machine with no Python, and
    the test is what stops the committed copy and the generator
    disagreeing.

    This used to skip on a shallow clone, because per-file commit dates
    are meaningless when history is truncated - which meant the check
    that catches a hand-edited page was off by default anywhere someone
    had not set `fetch-depth: 0`. Staleness is computed from file
    contents now, so there is nothing to skip for and the check runs
    everywhere.
    """
    stale = build_docs.build(check=True)
    assert not stale, (
        "these are out of date - run `uv run python tools/build_docs.py`: "
        f"{stale}"
    )


def test_generated_files_say_so_in_their_first_line():
    """Anyone opening one in an editor is told not to bother."""
    for path in build_docs.GENERATED:
        assert path.exists(), f"{path} has never been generated"
        assert "GENERATED" in path.read_text(encoding="utf-8").splitlines()[0]


def test_the_preserved_block_survives_a_rebuild():
    """Human judgement inside a generated file is not overwritten.

    Note the full rebuild in the `finally`. `build(check=False)` writes
    *every* generated file, not just the one under test, so a test that
    calls it leaves the working tree reflecting whatever the code said
    at that moment. Harmless in a clean run and actively confusing
    during a mutation pass, where it wrote pages from mutated code that
    then outlived the mutation - a failure that looked intermittent and
    was not.

    The chooser table is computed, but "use the 2635B for
    high-resistance samples" is an opinion and has to live somewhere. It
    lives between two markers in the generated file, which only works if
    a rebuild genuinely keeps it - so this asserts the round trip rather
    than trusting the marker to be honoured.
    """
    path = BENCH / "choosing-an-smu.md"
    original = path.read_text(encoding="utf-8")
    sentinel = "SENTINEL-DO-NOT-LOSE-ME"
    start = original.find(build_docs.KEEP_BEGIN) + len(build_docs.KEEP_BEGIN)
    end = original.find(build_docs.KEEP_END)
    try:
        path.write_text(
            original[:start] + f"\n{sentinel}\n" + original[end:],
            encoding="utf-8",
        )
        build_docs.build(check=False)
        assert sentinel in path.read_text(encoding="utf-8"), (
            "a rebuild destroyed the hand-written section"
        )
    finally:
        path.write_text(original, encoding="utf-8")
        build_docs.build(check=False)


def test_bench_extraction_takes_marked_sections_whole():
    """Extraction, not summarisation - proven on a fixture.

    Nothing adopts this yet; the instrument notes are stubs until
    `docs-instruments-v1`. Proving the mechanism before anything depends
    on it is the 6d-i pattern: a capability with no callers, tested in
    isolation, adopted separately.
    """
    body = (
        "## Reset defaults overridden\n"
        "format.asciiprecision, raised to 16.\n"
        "\n"
        "## The interlock is jumpered on this bench <!-- bench -->\n"
        "200 V can stay live on an open fixture.\n"
        "Second line, kept.\n"
        "\n"
        "## D13. No channel alias\n"
        "Internal reasoning nobody at the bench needs.\n"
    )
    out = build_docs.extract_bench_sections(body)

    assert "interlock is jumpered" in out
    assert "Second line, kept." in out, "a marked section must come across whole"
    assert "asciiprecision" not in out
    assert "channel alias" not in out
    assert build_docs.BENCH_MARKER not in out, "the marker must not be published"


# ---------------------------------------------------------------------------
# Claims a human should not be writing
# ---------------------------------------------------------------------------

#: The pattern, the escape and both scanners live in
#: `tools/build_docs.py`. Imported rather than restated so that the test
#: proving the escape is per-line exercises the real code - the first
#: version reimplemented the scan here and passed whether or not the
#: real one worked, which a mutation pass caught.
COUNT_PATTERN = build_docs.COUNT_PATTERN
LINT_ESCAPE = build_docs.LINT_ESCAPE

#: The four documents this vault replaced were exempted from the lints
#: while they still existed, on the grounds that linting prose about to
#: be deleted was wasted work. The exemption was self-clearing - a test
#: asserted each file still existed, so it could not outlive its
#: subject - and `docs-retire-v1` deleted all four, which is why it is
#: gone rather than commented out.

#: Prose that is *about* the rule, or quotes a historical claim in order
#: to explain why it was wrong, is not itself a live claim.
COUNT_EXEMPT = (
    "tests/test_docs.py",
    "tests/README.md",
    "docs/reference/schema.md",
    "README.md",
    "LAB54_DEVELOPMENT_REVIEW_AND_WORKFLOW.md",
)


def test_the_documents_this_vault_replaced_are_gone():
    """Two copies of one fact is the failure this rebuild was for.

    `HANDOFF.md` survives as a short router; the other three are
    deleted. If one comes back, the lints stop covering it and the
    drift starts again - `INSTRUMENTS.md` had claimed every driver was
    commissioned while contradicting itself three hundred lines later.
    """
    for name in ("PORTING_NOTES.md", "INSTRUMENTS.md", "WAVE_PLAN.md"):
        assert not (ROOT / name).exists(), (
            f"{name} is back. Its content lives in docs/ now; two copies "
            "of one fact is what this rebuild removed."
        )

    router = (ROOT / "HANDOFF.md").read_text(encoding="utf-8")
    assert len(router.splitlines()) < 120, (
        "HANDOFF.md is a router, not content. It reached 1,846 lines "
        "once and stopped being readable; keep it short enough that "
        "nobody is tempted to add reference material to it."
    )


def test_every_cited_review_section_says_where_its_reasoning_went():
    """`LAB54...md` is scheduled for deletion after Wave 7.

    185 citations across the source point into it, and for several
    modules that citation is the only recorded reason the module exists
    - `core/units.py` cites §54 for its unit convention and nothing else
    says why. A citation with no entry in `REVIEW_CARRIED_BY` is one
    whose reasoning has nowhere to go.
    """
    cited = set(build_docs.review_citations())
    unmapped = sorted(
        (str(k) for k in cited - set(build_docs.REVIEW_CARRIED_BY)),
        key=str,
    )
    assert not unmapped, (
        "these review sections are cited from the source but not mapped "
        f"to a note in REVIEW_CARRIED_BY: {unmapped}"
    )

    missing = [target for target in build_docs.REVIEW_CARRIED_BY.values()
               if not (ROOT / target).exists()]
    assert not missing, f"REVIEW_CARRIED_BY points at absent notes: {missing}"


def test_no_document_hardcodes_a_count_the_repo_can_derive():
    offenders = []
    for path in _markdown_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in COUNT_EXEMPT:
            continue
        for n, found in build_docs.find_hardcoded_counts(
                path.read_text(encoding="utf-8")):
            offenders.append(f"{rel}:{n}: {found!r}")

    assert not offenders, (
        "these state a count that goes stale on the next patch. Link to "
        "the generated table instead, or mark the line "
        f"{LINT_ESCAPE} if it is describing history:\n  "
        + "\n  ".join(offenders)
    )


def test_every_markdown_link_resolves():
    """A link to a file that does not exist is a dead end.

    Stronger than the wiki-style check it replaces, which matched on
    *filename* alone: `[[keithley-2611a]]` resolved whichever folder it
    was written in, so a link naming the right file in the wrong place
    could not fail. A relative path either points at a file or it does
    not.
    """
    broken = []
    for path in _markdown_files():
        rel = path.relative_to(ROOT).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for _label, target, _frag in build_docs.MD_LINK.findall(line):
                if target.startswith(("http://", "https://", "#")):
                    continue
                if not (path.parent / target).exists():
                    broken.append(f"{rel}:{n}: {target}")

    assert not broken, "unresolved links:\n  " + "\n  ".join(broken)


# ---------------------------------------------------------------------------
# Commands, and the branch state that is not a document's to hold
#
# These two scanners live here rather than in `tools/build_docs.py`
# alongside the count lint, and the reason is worth stating: the
# generator generates nothing from either of them. The count lint is
# there because the *page builder* and the *checker* must agree on one
# pattern or a page can be built under one rule and checked under
# another. Nothing here is in that position, and putting a pure test
# lint into the generator has a real cost - the review index records
# citation line numbers in `build_docs.py`, so inserting a function
# there rewrites a committed generated page that this change has no
# business touching.
# ---------------------------------------------------------------------------

#: A path this repository could own, as it appears on a command line.
#: Anchored so a version suffix or a URL tail cannot produce a truncated
#: match, and deliberately narrow on the extension: a token with no
#: extension is an argument, not a file.
COMMAND_PATH = re.compile(
    r"(?<![\w./-])"
    r"[A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:py|md|json|toml|cfg|ini|ya?ml)"
    r"(?![\w/])"
)

#: A fenced line that actually runs something. Restricting the scan to
#: these is what keeps it free of false positives: prose names files in
#: the abstract constantly (`drivers/<model>.py`, a file being described
#: as deleted), while a command line is a literal instruction that
#: either works when pasted or does not.
COMMAND_LINE = re.compile(
    r"^\s*(?:[$>]\s+)?(?:xvfb-run\s+-a\s+)?"
    r"(?:uv\s+run\s+(?:python3?\s+|pytest\s+)?"
    r"|uv\s+tool\s+run\s+[\w-]+\s+"
    r"|python3?\s+(?:-m\s+\w+\s+)?"
    r"|pytest\s+"
    r"|py\s+)"
)

#: Not a path anybody can check: a placeholder, a glob, or a shell
#: substitution. Each is a deliberate stand-in rather than a claim.
_NOT_A_REAL_PATH = ("<", ">", "*", "$", "{", "...")

#: Where a command line's bare filename is allowed to resolve. A
#: document demonstrating pytest's import-order behaviour writes
#: `pytest test_rs_handoff.py` as it would be run from inside `tests/`,
#: and that is a real file correctly named. Requiring a directory
#: component instead would have been the easy fix and the wrong one: it
#: would stop the scan checking exactly the bare names most likely to be
#: mistyped.
_COMMAND_ROOTS = (ROOT, ROOT / "tests", ROOT / "tools")

#: Assembled from fragments rather than written out. The scan reads
#: Markdown only, so a literal here is harmless today - and would
#: silently become bait for the real check the day anybody widens it to
#: source files, which is precisely how the two baits at the bottom of
#: this file were discovered to be necessary.
_ABSENT_TEST = "tests/test_" + "hall_hand" + "off.py"


def find_command_paths(text: str) -> list[tuple[int, str]]:
    """(line number, path) for every repo file named on a command line.

    The failure this exists for: `README.md` told the reader to run
    `uv run pytest tests/test_hall_handoff.py`, and there is no such
    file - the one holding those tests is `test_rs_handoff.py`. Nothing
    could catch it, because a command inside a document is prose as far
    as every other check here is concerned, and it was surrounded by two
    dozen commands that did work.

    A command line is the one kind of documentation with a mechanically
    checkable meaning: paste it and it either runs or it does not. So it
    is checked.
    """
    out: list[tuple[int, str]] = []
    fenced = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced or LINT_ESCAPE in line or not COMMAND_LINE.match(line):
            continue
        for match in COMMAND_PATH.finditer(line):
            found = match.group(0)
            if not any(ch in found for ch in _NOT_A_REAL_PATH):
                out.append((n, found))
    return out


#: A branch named as a thing that currently exists. `-b` and a
#: placeholder are exempt because neither asserts anything about the
#: remote; a bare name does.
BRANCH_STATE = re.compile(
    r"git\s+(?:checkout|switch)\s+(?!-)(?P<checkout>[A-Za-z0-9_./-]+)"
    r"|\bon\s+branch\s+[`*_]*(?P<named>[A-Za-z0-9_./-]+)"
)


def find_branch_state(text: str) -> list[tuple[int, str]]:
    """(line number, branch) for every live branch claim in a document.

    A checked-in file naming the branch the work is on is stale the
    moment that branch merges, and a reader cannot tell a stale sentence
    from a current one. This project has the failure twice over: the
    router told readers to check out a branch that had since been merged
    and deleted, and two readers of two checkouts then reached
    *opposite* conclusions about whether it still existed, because a
    remote-tracking ref survives in an unpruned checkout long after the
    branch is gone.

    So the answer is not a fresher branch name - that is the same defect
    with a newer value in it. Git is the only thing that knows, and it
    is never out of date. Documents point at it instead.

    Line-wise, like every other lint here, and that has one known blind
    spot worth stating rather than discovering: a claim wrapped across a
    line break ("is on branch\\n`wave8`") is invisible to it. The
    `git checkout` line is what catches that case, and the historical
    example carried both.
    """
    out: list[tuple[int, str]] = []
    for n, line in enumerate(text.splitlines(), 1):
        if LINT_ESCAPE in line:
            continue
        for match in BRANCH_STATE.finditer(line):
            name = match.group("checkout") or match.group("named")
            if name and not any(ch in name for ch in _NOT_A_REAL_PATH):
                out.append((n, name))
    return out


def _missing_command_paths(documents) -> list[str]:
    """Every command path in `documents` that names no file in the tree.

    `documents` is an iterable of `(where, text)`. Taking the documents
    as an argument rather than reading the repository inside is what
    lets the proof below run the *real* scan over a document that is
    wrong on purpose - fault 19 is the whole reason this file's newer
    checks are shaped this way. A version that walked `ROOT` internally
    could only ever assert that a corrected tree is correct.
    """
    missing = []
    for where, text in documents:
        for n, target in find_command_paths(text):
            if not any((base / target).exists() for base in _COMMAND_ROOTS):
                missing.append(f"{where}:{n}: {target}")
    return missing


def test_every_command_in_the_docs_names_a_file_that_exists():
    """A command that cannot be pasted is worse than no command.

    `README.md` listed two dozen individual test invocations, one of
    which named `tests/test_hall_handoff.py`. That file has never
    existed under that name - the handoff tests live in
    `test_rs_handoff.py` - and the reader who pasted the line got a
    pytest collection error about their own checkout. Twenty-three
    working neighbours are exactly what stops anyone suspecting the
    document.

    Every other check here reads a command as prose. This one reads it
    as a command.
    """
    documents = [(path.relative_to(ROOT).as_posix(),
                  path.read_text(encoding="utf-8"))
                 for path in _markdown_files()]
    missing = _missing_command_paths(documents)

    assert not missing, (
        "these documents tell the reader to run a file that is not in "
        "the repository:\n  " + "\n  ".join(missing)
    )


def test_the_command_scan_catches_a_file_that_is_not_there():
    """The constructed failure, without which the test above proves
    nothing about anything but today's tree.

    Three things have to hold at once, and the third is the one that
    would rot quietly: the scan reaches a fenced command line, it
    recognises a path that is absent, and it does **not** fire on the
    working command sitting next to it or on the placeholder paths this
    vault writes all over its prose.
    """
    doc = (
        "Run the suite:\n"
        "\n"
        "```powershell\n"
        "uv run python run_tests.py --all\n"
        f"uv run pytest {_ABSENT_TEST}\n"
        "```\n"
        "\n"
        "Then edit `drivers/<model>.py` and rebuild `tests/golden/*.json`.\n"
        "\n"
        "```powershell\n"
        "uv run python tools/build_docs.py\n"
        "```\n"
    )
    found = _missing_command_paths([("fabricated.md", doc)])

    assert found == [f"fabricated.md:5: {_ABSENT_TEST}"], found

    scanned = [target for _n, target in find_command_paths(doc)]
    assert "run_tests.py" in scanned and "tools/build_docs.py" in scanned, (
        f"the scan is not reaching real command lines at all: {scanned}"
    )
    assert not [t for t in scanned if "<" in t or "*" in t], (
        f"a placeholder path was read as a claim about a real file: {scanned}"
    )


def test_prose_outside_a_command_block_is_not_read_as_a_command():
    """The other half of the same boundary.

    A document discussing a file it does not have - recording that
    something was deleted, or naming the file a reader should create -
    is making no checkable claim. A lint that fired on those would be
    switched off within a week, and a lint that is off catches nothing.
    """
    doc = (
        "`experiments/vanderpauw/panels/temp_panel.py` was deleted in Wave 0b.\n"
        "\n"
        "    uv run pytest tests/test_not_written_yet.py\n"
        "\n"
        "Create `drivers/my_new_smu.py`, then run the suite.\n"
    )
    assert find_command_paths(doc) == []


def test_no_document_carries_live_branch_state():
    """A branch name in a checked-in file is a claim git already owns.

    `HANDOFF.md` told readers that the current work was on a branch and
    to check it out. By the time the audit read it, that branch had been
    merged into `main` and deleted on the remote - and the two people
    who checked disagreed about whether it still existed, because a
    remote-tracking ref survives in an unpruned checkout long after the
    branch is gone.

    That disagreement is the argument. A claim two readers of the same
    repository resolve differently cannot be maintained by care, and
    replacing it with today's correct branch name is the same defect
    with a fresher value. `git fetch --prune` answers it exactly.
    """
    offenders = []
    for path in _markdown_files():
        rel = path.relative_to(ROOT).as_posix()
        for n, branch in find_branch_state(
                path.read_text(encoding="utf-8")):
            offenders.append(f"{rel}:{n}: {branch}")

    assert not offenders, (
        "these name a git branch as a thing that currently exists. Point "
        "at `git fetch --prune` instead, or mark the line "
        f"{LINT_ESCAPE} if it is recording history:\n  "
        + "\n  ".join(offenders)
    )


def test_the_branch_state_scan_catches_the_text_it_was_written_for():
    """Run against what `HANDOFF.md` actually said, not a paraphrase.

    Quoted verbatim from the version this replaced, because a scan
    tuned against a paraphrase of the failure proves only that it
    recognises the paraphrase.
    """
    was_in_handoff = (
        "**`main` is not the whole picture right now.** Wave 8 is on branch\n"
        "**`wave8`** and is not merged. It carries the transport work.\n"
        "\n"
        "```powershell\n"
        "git fetch origin\n"
        "git checkout wave8\n"
        "```\n"
    )
    found = find_branch_state(was_in_handoff)

    assert [branch for _n, branch in found] == ["wave8"], found
    assert found[0][0] == 6, (
        f"the checkout instruction is on line 6, reported at {found[0][0]}"
    )

    # The blind spot, asserted rather than left to be discovered. The
    # prose half of the same claim wrapped across a line break, so a
    # line-wise scan cannot see it. That is a real limit on this check
    # and not a reason to distrust it: the instruction underneath is the
    # half a reader acts on, and a document that tells nobody to do
    # anything about a branch is the shape being asked for anyway.
    assert "is on branch" in was_in_handoff.splitlines()[0]
    assert find_branch_state(was_in_handoff.splitlines()[0]) == [], (
        "the wrapped prose claim is now caught, so this comment is "
        "describing a limitation the scan no longer has"
    )
    assert find_branch_state("Wave 8 is on branch `wave8`, not merged.\n") == [
        (1, "wave8")
    ], "the same claim on one line must be caught"

    replaced_by = (
        "Ask the remote, which is the only thing that knows:\n"
        "\n"
        "```powershell\n"
        "git fetch --prune\n"
        "git branch -r\n"
        "```\n"
    )
    assert find_branch_state(replaced_by) == [], (
        "the replacement text trips the same lint, so the lint is "
        "objecting to talking about git rather than to claiming state"
    )

    assert find_branch_state(
        "git checkout -b audit/my-work origin/main\n") == [], (
        "creating a branch asserts nothing about which branches exist"
    )

    assert find_branch_state(
        f"Wave 8 is on branch `wave8`. {LINT_ESCAPE}\n") == [], (
        "the per-line escape must work here as it does for the other lints"
    )


def test_no_wiki_style_links_remain():
    """`[[double brackets]]` render as literal text on GitHub.

    Obsidian resolves them; nothing else does - not GitHub, not pandoc
    for the eventual PDF. Since the repository is read on GitHub far
    more than in the vault, and Obsidian handles relative Markdown links
    perfectly well, there is no case where the wiki form is better and
    two where it is worse.

    It also rewrote files behind our backs: Obsidian normalises link
    format on index, so with the vault open it silently reformatted
    whichever notes did not match its setting.
    """
    offenders = []
    for path in _markdown_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel == "tests/test_docs.py":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "[[" in line and "]]" in line:
                offenders.append(f"{rel}:{n}")

    assert not offenders, (
        "these use wiki-style links, which do not render on GitHub. Use "
        "a relative Markdown link instead:\n  " + "\n  ".join(offenders)
    )


def test_a_relocated_section_keeps_its_links_pointing_somewhere_real():
    """Extraction moves a section between folders; relative paths move
    with it.

    This is the one real cost of relative links over the wiki form, and
    it is paid by the generator rather than by whoever writes a note:
    `retarget_links` recomputes each path from the destination, and
    prefers the target's bench page where one exists, because a reader
    of `bench/` sent into the developer notes got a worse answer than
    the one next door.
    """
    source = DOCS / "experiments" / "van-der-pauw.md"
    destination = build_docs.bench_page_path(source)
    moved = build_docs.retarget_links(
        "see [Hall](hall.md) and [the checkup](../open/checkup-owed.md)",
        source, destination,
    )

    assert "(hall-bench.md)" in moved, (
        f"a bench page should link to its counterpart's bench page: {moved}"
    )
    assert "(../../docs/open/checkup-owed.md)" in moved, (
        f"a target with no bench page should point back into docs/: {moved}"
    )

    for target in build_docs.MD_LINK.findall(moved):
        assert (destination.parent / target[1]).exists(), (
            f"retargeted link does not resolve: {target[1]}"
        )


def test_the_docs_do_not_reference_deleted_methods():
    """Prose describing code that no longer exists.

    `HANDOFF.md` spends thirty lines on `set_current_range()` /
    `set_voltage_range()` and the contract ambiguity between them,
    concluding it needs "a wave of its own". Wave 6d-ii deleted both
    methods and fixed it. The document is describing a defect the code
    no longer has - and it is the section a new reader would use to
    decide whether to trust the 2450.

    Exempted in the legacy files precisely because that is what
    `docs-instruments-v1` is for; enforced everywhere the rewrite has
    reached.
    """
    import ast

    defined = set()
    for path in (ROOT / "drivers").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)

    watched = ["set_current_range", "set_voltage_range"]
    gone = [name for name in watched if name not in defined]
    assert gone, (
        "this guard watches methods Wave 6d-ii deleted. If they are back, "
        "the guard needs rewriting rather than deleting."
    )

    offenders = []
    for path in _markdown_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in COUNT_EXEMPT:
            continue
        for n, name in build_docs.find_mentions(
                path.read_text(encoding="utf-8"), gone):
            offenders.append(f"{rel}:{n}: {name}()")

    assert not offenders, (
        "these describe driver methods that no longer exist. Mark the "
        f"line {LINT_ESCAPE} if it is recording the deletion "
        "deliberately:\n  " + "\n  ".join(offenders)
    )


def test_staleness_consults_the_shared_base_class(monkeypatch):
    """A change to `base_smu.py` alone must mark a driver stale.

    This test exists because a mutation pass caught its absence. Emptying
    `SHARED_DEPENDENCIES` changed nothing, because right now every
    driver's *own* file also moved in Wave 6 - so every other assertion
    here was true whether or not the shared dependency was consulted.
    That is the non-discriminating probe, arriving in a test rather than
    in a driver.

    The realistic case it protects is the one that has already happened
    once: `apply_ranges()`, the software sweep and the sentinel handling
    all live in `BaseSMU`, so a change there alters what several drivers
    do without touching their files at all.
    """
    asked = []

    def fake_fingerprint(paths, root=None):
        asked.extend(paths)
        # The recorded digest below is "recorded"; anything else differs.
        return "0123456789ab"

    monkeypatch.setattr(build_docs.provenance, "code_fingerprint",
                        fake_fingerprint)

    status, reason = build_docs.bench_status({
        "bench_ever": True,
        "last_bench": "2026-08-14",
        "bench_code": "recorded0000",
        "bench_result": "pass",
        "driver": "drivers/keithley_2611a.py",
        "bench_revalidated": None,
    })

    assert "drivers/base_smu.py" in asked, (
        "the staleness check never asked about the shared base class"
    )
    assert status == "stale", (
        f"a change to BaseSMU after the checkup must invalidate it, got "
        f"{status!r} ({reason})"
    )


def test_a_real_edit_to_the_shared_base_class_changes_the_fingerprint(tmp_path):
    """The half of the same question that a mock cannot answer.

    The test above proves `base_smu.py` is *consulted*. It would pass
    just as well if the digest ignored the file's contents - which is
    the whole failure mode being designed out here. So this one hashes
    real files, edits the shared one, and requires the digest to move.
    """
    from core.provenance import code_fingerprint

    (tmp_path / "drivers").mkdir()
    driver = tmp_path / "drivers" / "example.py"
    shared = tmp_path / "drivers" / "base_smu.py"
    driver.write_text("class Example: pass\n", encoding="utf-8")
    shared.write_text("class BaseSMU: pass\n", encoding="utf-8")

    paths = ["drivers/base_smu.py", "drivers/example.py"]
    before = code_fingerprint(paths, root=str(tmp_path))

    shared.write_text("class BaseSMU:\n    pass  # a comment\n",
                      encoding="utf-8")
    after = code_fingerprint(paths, root=str(tmp_path))

    assert before and after and before != after, (
        "editing the shared base class left the fingerprint unchanged, "
        f"so a checkup would stay 'commissioned' through it: {before}"
    )


def test_the_fingerprint_ignores_line_endings_but_not_content(tmp_path):
    """CRLF must not mark the fleet stale; a real edit must.

    `.gitattributes` pins `*.py` to LF, so on a correct checkout this
    never comes up. It comes up on a machine whose checkout is not
    correct, where the alternative is every driver reported stale over
    bytes nobody can see.

    The second half is what stops the normalisation being a hole: the
    same test proves a one-character change still moves the digest.
    """
    from core.provenance import code_fingerprint

    (tmp_path / "drivers").mkdir()
    target = tmp_path / "drivers" / "base_smu.py"
    paths = ["drivers/base_smu.py"]

    target.write_bytes(b"a = 1\nb = 2\n")
    unix = code_fingerprint(paths, root=str(tmp_path))
    target.write_bytes(b"a = 1\r\nb = 2\r\n")
    windows = code_fingerprint(paths, root=str(tmp_path))
    target.write_bytes(b"a = 1\nb = 3\n")
    edited = code_fingerprint(paths, root=str(tmp_path))

    assert unix == windows, "line endings alone changed the fingerprint"
    assert unix != edited, "a changed value left the fingerprint alone"


def test_a_missing_driver_file_is_unknown_rather_than_current(tmp_path):
    """A digest over files that are not there must not read as a match.

    `None` propagates to `unknown`. Returning an empty-input digest
    instead would be a fixed value that two notes could both match,
    which is a plausible-looking answer to a question nobody could
    answer - the exact shape this repository exists to refuse.
    """
    from core.provenance import code_fingerprint

    assert code_fingerprint(["drivers/not_here.py"],
                            root=str(tmp_path)) is None


def test_a_driver_unchanged_since_its_checkup_reads_as_commissioned():
    """The other half of the same probe.

    Asked where the interesting answer is the correct one: if
    `bench_status` returned `stale` unconditionally, every assertion
    above would still pass, because the whole fleet is stale today.
    """
    import unittest.mock as mock

    with mock.patch.object(build_docs.provenance, "code_fingerprint",
                           return_value="recorded0000"):
        status, _ = build_docs.bench_status({
            "bench_ever": True,
            "last_bench": "2026-08-14",
            "bench_code": "recorded0000",
            "bench_result": "pass",
            "driver": "drivers/keithley_2611a.py",
            "bench_revalidated": None,
        })
    assert status == "commissioned", status


def test_a_failing_checkup_does_not_read_as_commissioned():
    """The state a date could not express.

    Same fingerprint, same date, same everything except how the checkup
    went - and the two must not render alike. Under the previous schema
    they did, because nothing recorded the result.
    """
    import unittest.mock as mock

    common = {
        "bench_ever": True,
        "last_bench": "2026-08-21",
        "bench_code": "recorded0000",
        "driver": "drivers/keysight_u2722a.py",
        "bench_revalidated": None,
    }
    with mock.patch.object(build_docs.provenance, "code_fingerprint",
                           return_value="recorded0000"):
        passed, _ = build_docs.bench_status({**common,
                                             "bench_result": "pass"})
        failed, reason = build_docs.bench_status({
            **common, "bench_result": "fail",
            "bench_result_note": "four checks fail with -222"})

    assert passed == "commissioned", passed
    assert failed == "failing", failed
    assert "-222" in reason, (
        f"the failure reason is not carried into the render: {reason!r}"
    )


def test_an_unrecognised_bench_result_is_not_treated_as_a_pass():
    """A typo must fail safe.

    `bench_resutl: pass`, or `bench_result: passed`, leaves the field
    unrecognised. Reading anything-but-`fail` as a pass would let a
    misspelling promote a failing driver to commissioned - a silent
    upgrade in exactly the direction that costs a dataset.
    """
    import unittest.mock as mock

    with mock.patch.object(build_docs.provenance, "code_fingerprint",
                           return_value="recorded0000"):
        status, _ = build_docs.bench_status({
            "bench_ever": True,
            "last_bench": "2026-08-21",
            "bench_code": "recorded0000",
            "bench_result": "passed",       # not one of the two values
            "driver": "drivers/keithley_2611a.py",
            "bench_revalidated": None,
        })
    assert status == "failing", status


def test_a_failing_driver_whose_code_moved_reads_as_stale():
    """Precedence, stated once so it cannot be inferred two ways.

    A failure is a fact about the code that was checked. When that code
    has since changed, the honest answer is that nobody knows - so the
    status is `stale`, and the reason says it was failing when it ran
    rather than dropping that on the floor.
    """
    import unittest.mock as mock

    with mock.patch.object(build_docs.provenance, "code_fingerprint",
                           return_value="something else"):
        status, reason = build_docs.bench_status({
            "bench_ever": True,
            "last_bench": "2026-08-21",
            "bench_code": "recorded0000",
            "bench_result": "fail",
            "bench_result_note": "four checks fail with -222",
            "driver": "drivers/keysight_u2722a.py",
            "bench_revalidated": None,
        })
    assert status == "stale", status
    assert "failing when it ran" in reason, reason


def test_a_bench_date_with_no_fingerprint_is_stale():
    """A note from before this field existed must not claim currency.

    The migration case: `last_bench` set, `bench_code` absent. Nothing
    can compare, so nothing may claim the checkup still applies.
    """
    status, reason = build_docs.bench_status({
        "bench_ever": True,
        "last_bench": "2026-08-14",
        "bench_code": None,
        "bench_result": "pass",
        "driver": "drivers/keithley_2611a.py",
        "bench_revalidated": None,
    })
    assert status == "stale", status
    assert "which code" in reason, reason


def test_every_real_instrument_publishes_something_to_the_bench():
    """A note with no marked section produces a bench page that is a bare
    table, which is worse than no page: it looks like the whole story.

    The section that matters is "what this means for your data" - the
    consequences an operator has to know and cannot see in the numbers.
    Every physical instrument has at least one, including the 2450,
    whose consequence is "nothing here has been confirmed".
    """
    thin = []
    for note, (meta, body) in build_docs.load_notes(physical_only=True).items():
        if build_docs.BENCH_MARKER not in body:
            thin.append(note.name)
    assert not thin, (
        "these instrument notes mark nothing for the bench pages, so "
        f"their generated page is a table and nothing else: {thin}"
    )


def test_a_bench_page_warns_when_its_driver_is_not_current():
    """The warning is the reason the bench pages exist at all.

    A colleague choosing an instrument must be told that the code has
    moved since anyone checked it - that is the fact the old documents
    could not carry, because prose saying "all commissioned" was written
    once and never revisited.

    Keyed by status rather than or-chained across two phrases, because
    the or-chain passed a page that carried the *wrong* warning. Adding
    `failing` was the case that exposed it: a failing driver rendering a
    stale banner would have satisfied "either phrase is present", and
    "nobody has checked this lately" is the opposite of what a failing
    checkup means.
    """
    expected = {
        "unverified": "never met the instrument",
        "stale": "has changed since",
        "failing": "fails its own checkup",
    }
    seen = set()
    for note, (meta, _body) in build_docs.load_notes(physical_only=True).items():
        status, _ = build_docs.bench_status(meta)
        if status == "commissioned":
            continue
        assert status in expected, (
            f"{note.name}: status {status!r} has no bench-page warning "
            "defined. A status a reader never sees is worse than none."
        )
        page = build_docs.bench_page_path(note)
        text = page.read_text(encoding="utf-8")
        assert expected[status] in text, (
            f"{page.name} carries no {status!r} warning despite "
            f"status={status!r}"
        )
        seen.add(status)

    assert seen, "no instrument is uncommissioned; this test passed vacuously"


def test_an_orphaned_bench_page_is_removed():
    """A page left behind by a deleted note describes something gone.

    Same failure as the orphaned `temp_panel.py` that survived Wave 0b's
    zip: still present, still plausible, and caught only by a test.
    """
    orphan = build_docs.BENCH / "instruments" / "keithley-9999-bench.md"
    orphan.write_text("stale\n", encoding="utf-8")
    try:
        stale = build_docs.build(check=True)
        assert any("orphaned" in entry for entry in stale), (
            "an orphaned bench page was not reported"
        )
        build_docs.build(check=False)
        assert not orphan.exists(), "an orphaned bench page was not removed"
    finally:
        if orphan.exists():
            orphan.unlink()
        build_docs.build(check=False)


def test_the_lint_escape_is_per_line_not_per_file():
    """An escape on one line must not excuse the rest of the file.

    Written because the obvious implementation - `if ESCAPE in text` -
    reads identically at a glance and would let the first use silently
    disable the check for everything added afterwards. A mutation pass
    confirmed the file-level version passes every other assertion here.
    """
    text = (f"Four drivers did the thing. {LINT_ESCAPE}\n"
            "There are five drivers.\n")
    offenders = [n for n, _ in build_docs.find_hardcoded_counts(text)]

    assert offenders == [2], (
        "the escape must cover only its own line; got offenders at "
        f"{offenders}"
    )


#: Every field an experiment note must declare.
REQUIRED_EXPERIMENT_FIELDS = {"type", "title", "module", "origin"}


def test_every_experiment_package_has_a_note_and_every_note_a_package():
    """The same bijection the drivers have, for `experiments/`.

    An experiment added without a note fails here, and so does a note
    whose package has been renamed or removed - which is the direction
    that rots quietly, because a note describing a folder that no longer
    exists reads exactly like one that does.
    """
    packages = {p.name for p in (ROOT / "experiments").iterdir()
                if p.is_dir() and (p / "experiment.py").exists()}
    documented = {meta["module"].split("/")[-1]
                  for meta, _ in build_docs.experiment_notes().values()}

    assert packages == documented, (
        f"experiments with no note: {sorted(packages - documented)}; "
        f"notes with no experiment: {sorted(documented - packages)}"
    )


def test_experiment_notes_declare_every_required_field():
    for path, (meta, _body) in build_docs.experiment_notes().items():
        missing = REQUIRED_EXPERIMENT_FIELDS - set(meta)
        assert not missing, f"{path.name} is missing {sorted(missing)}"
        assert meta["type"] == "experiment", path.name
        assert (ROOT / meta["module"]).is_dir(), (
            f"{path.name}: module={meta['module']!r} is not a directory"
        )


def test_a_marked_section_always_reaches_a_bench_page():
    """`<!-- bench -->` must never be decorative.

    It was, briefly: the experiment notes marked sections while the
    generator built bench pages for instruments only, so four notes
    carried a marker that produced nothing. Nothing failed, because
    marking-and-discarding looks identical to not marking. This walks
    every note that has a marker and requires its content to appear in
    the corresponding generated page.
    """
    sources = dict(build_docs.load_notes(physical_only=True))
    sources.update(build_docs.experiment_notes())

    for note, (_meta, body) in sources.items():
        extracted = build_docs.extract_bench_sections(body)
        if not extracted:
            continue
        page = build_docs.bench_page_path(note)
        assert page.exists(), f"{note.name} marks sections but {page} is absent"
        published = page.read_text(encoding="utf-8")
        first = extracted.splitlines()[0]
        assert first in published, (
            f"{note.name} marks a section that does not appear in "
            f"{page.name}: {first!r}"
        )


def test_a_generated_page_points_at_the_note_it_came_from():
    """The do-not-edit banner must name the right folder.

    An experiment page telling the reader to edit `docs/instruments/`
    sends them to the wrong file. Small, but it is how people learn to
    stop reading the banner.
    """
    for note in list(build_docs.load_notes(physical_only=True)) + \
            list(build_docs.experiment_notes()):
        page = build_docs.bench_page_path(note)
        head = page.read_text(encoding="utf-8")[:400]
        expected = f"docs/{note.parent.name}/"
        assert expected in head, (
            f"{page.name} points somewhere other than {expected}"
        )


#: House rules and faults are cited by number from source comments, from
#: commit messages and from past conversations, so the numbers are
#: permanent. These guard the two directions that rot: a number cited in
#: code with no note behind it, and a numbering sequence with a hole in
#: it that makes the next author guess what to use.
RULE_CITATION = re.compile(r"house rule (\d+)", re.IGNORECASE)
FAULT_CITATION = re.compile(r"\bfault (\d+)\b", re.IGNORECASE)


def _numbered(folder: str, key: str) -> dict[int, Path]:
    out = {}
    for path in (DOCS / folder).glob("*.md"):
        if path.name.startswith("_"):
            continue
        meta, _ = build_docs.read_frontmatter(path)
        out[int(meta[key])] = path
    return out


def test_rule_and_fault_numbers_are_a_gapless_sequence():
    """A hole in the sequence is a note somebody deleted.

    The numbers are permanent and cited from outside the repository, so a
    rule is never renumbered - a retired one keeps its number and says it
    is retired. That means a gap can only mean a note went missing, and
    the next author picking "the next number" would silently reuse one.
    """
    for folder, key in (("rules", "rule"), ("faults", "fault")):
        numbers = sorted(_numbered(folder, key))
        assert numbers == list(range(1, len(numbers) + 1)), (
            f"docs/{folder}/ is not a gapless sequence from 1: {numbers}"
        )


def test_the_filename_number_matches_the_frontmatter_number():
    """`15-limit-before-range.md` must not declare `fault: 12`.

    Both are used: the filename orders the folder and is what a wikilink
    names, the frontmatter is what the guards read. Two numbers for one
    thing is the same failure as a name written in two places.
    """
    for folder, key in (("rules", "rule"), ("faults", "fault")):
        for number, path in _numbered(folder, key).items():
            assert path.name.startswith(f"{number:02d}-"), (
                f"{path.name} declares {key}: {number}"
            )


def test_every_rule_or_fault_cited_in_the_source_has_a_note():
    """A citation pointing at nothing is the LAB54 problem in miniature.

    Source comments cite these by number - "house rule 12", "fault 4" -
    and those citations are often the only recorded reason a line of code
    is shaped the way it is. A number with no note behind it is a
    reference to reasoning nobody can now retrieve.
    """
    rules = set(_numbered("rules", "rule"))
    faults = set(_numbered("faults", "fault"))

    dangling = []
    for path in build_docs.owned_files("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            for match in RULE_CITATION.finditer(line):
                if int(match.group(1)) not in rules:
                    dangling.append(f"{rel}:{n}: house rule {match.group(1)}")
            for match in FAULT_CITATION.finditer(line):
                if int(match.group(1)) not in faults:
                    dangling.append(f"{rel}:{n}: fault {match.group(1)}")

    assert not dangling, (
        "these cite a rule or fault with no note behind it:\n  "
        + "\n  ".join(dangling)
    )


def test_every_module_under_core_appears_in_the_module_map():
    """`core-modules.md` is the answer to "why does this file exist".

    It only works if it is complete - a module missing from it is
    invisible in the one place someone would look, and `core/` has
    already grown to the point where several files look like dead code
    from the outside.
    """
    documented = (DOCS / "architecture" / "core-modules.md").read_text(
        encoding="utf-8")
    missing = []
    for folder in ("core", "core/gui", "core/transports", "devices"):
        for path in sorted((ROOT / folder).glob("*.py")):
            if path.name == "__init__.py":
                continue
            rel = path.relative_to(ROOT).as_posix()
            if f"`{rel}`" not in documented:
                missing.append(rel)

    assert not missing, (
        "these modules are not in docs/architecture/core-modules.md:\n  "
        + "\n  ".join(missing)
    )


def test_every_tool_appears_in_the_tools_note():
    documented = (DOCS / "architecture" / "tools.md").read_text(encoding="utf-8")
    missing = [p.name for p in sorted((ROOT / "tools").glob("*.py"))
               if p.name != "__init__.py" and p.name not in documented]
    assert not missing, (
        f"these tools are not in docs/architecture/tools.md: {missing}"
    )


# ---------------------------------------------------------------------------
# The tool itself
# ---------------------------------------------------------------------------

def test_a_missing_generated_marker_raises_rather_than_writing_unchanged():
    """The silent-no-match failure, refused explicitly.

    A `str_replace` whose anchor matches nothing, followed by writing
    the file back unchanged, has cost this project real debugging time
    more than once. The generator anchors on two markers, so it can hit
    exactly that failure - and must not.
    """
    with pytest.raises(build_docs.FrontmatterError):
        build_docs._rebuild_generated_block("no markers here", {"a": 1})


def test_frontmatter_refuses_a_key_declared_twice(tmp_path):
    """Last-one-wins is the quiet failure YAML is worst at.

    `driver_class` used to be both hand-written and emitted into the
    generated block. The generated copy parsed second and shadowed the
    hand-written one, so a note pointing at a driver that does not exist
    still resolved to the right driver - and the bijection test passed
    against a note that was wrong. Found by mutation, not by reading.
    """
    note = tmp_path / "dupe.md"
    note.write_text("---\ntitle: a\ntitle: b\n---\n\nbody\n", encoding="utf-8")
    with pytest.raises(build_docs.FrontmatterError):
        build_docs.read_frontmatter(note)


def test_frontmatter_refuses_yaml_it_cannot_parse():
    """A hand-rolled parser must fail loudly on the subset it lacks.

    The alternative - quietly mis-reading a construct - would put wrong
    numbers into the generated pages with nothing to say so, which is
    the whole failure class this file exists to close.
    """
    with pytest.raises(build_docs.FrontmatterError):
        build_docs._scalar("{inline: mapping}")


def test_the_generator_runs_from_the_command_line():
    """`--check` is what a person runs before opening a PR."""
    proc = subprocess.run(
        [sys.executable, "tools/build_docs.py", "--check"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode in (0, 1), proc.stderr
    assert "documentation" in proc.stdout.lower()


def test_the_minismu_range_list_matches_the_vendor_library():
    """`LIMITS.current_ranges` against `minismu_py.CURRENT_RANGE_LIMITS`.

    This driver is the only one whose range table has an authoritative
    machine-readable source, so the check is free and worth making
    executable rather than leaving as a sentence in a note. A range list
    that does not match the instrument is fault 16: the level gets
    clamped to the nearest real range and the derived quantity is
    computed from a current that was never sourced - no error, plausible
    number.

    Skipped rather than failed if the library is absent, because the
    documentation suite must not become the thing that needs hardware
    drivers installed to run.
    """
    minismu_py = pytest.importorskip("minismu_py")
    limits = getattr(minismu_py, "CURRENT_RANGE_LIMITS", None)
    if limits is None:
        pytest.skip("this version of minismu_py does not publish the range table")

    from drivers.undalogic_minismu import UndalogicMiniSMU

    declared = sorted(UndalogicMiniSMU.LIMITS.current_ranges)
    published = sorted(limits.values())
    assert declared == pytest.approx(published), (
        "the driver's current ranges disagree with the vendor library: "
        f"declared {declared}, published {published}"
    )


# ---------------------------------------------------------------------------
# The scan's scope, and the bytes it writes
#
# One rule, asserted from two directions: a generated page must depend
# on the repository and on nothing else about the machine that built it.
# Not on files that happen to be lying in the checkout, and not on which
# platform's text mode wrote it.
#
# Both halves are constructed failures. A test run against a tidy tree
# would pass whether or not either fix exists - fault 19 - so each of
# these builds the offending condition first and checks that the old
# behaviour would have been caught by it.
# ---------------------------------------------------------------------------

#: A name no real folder in this project would take, so a leftover from
#: an interrupted run is recognisable. It is harmless if it does survive:
#: an untracked directory is precisely what nothing scans any more.
JUNK_DIR = "_not_the_projects_files"

#: The bait, assembled from fragments and never written as a literal.
#:
#: This file is part of the source the two generators grep. Spelling a
#: citation or a deviation number out here would put it into the real
#: `review-index.md` and `deviation-index.md` - the exact failure these
#: tests exist to prevent, arriving through the front door. Found by
#: writing them as literals first: two unrelated tests went red.
_CITATION_BAIT = "review §" + "7 and gro" + "up B3"
_DEVIATION_BAIT = "DEVIA" + "TION 987"
_COUNT_BAIT = "This claims there are nine drivers."


@pytest.fixture
def junk_in_the_checkout():
    """An untracked directory inside `ROOT`, holding plausible bait.

    Inside the repository on purpose. `tmp_path` is somewhere else
    entirely, and somewhere else is not where `.uv-cache` and the agent
    worktrees were - the whole defect is that a scan of `ROOT` cannot
    tell the project's files from whatever shares the directory with
    them.
    """
    folder = ROOT / JUNK_DIR
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    try:
        (folder / "vendored.py").write_text(
            f"# {_CITATION_BAIT}\n"
            f"# {_DEVIATION_BAIT} - a marker in a file no commit contains\n",
            encoding="utf-8", newline="\n")
        (folder / "vendored.md").write_text(
            f"# Copy\n\n{_COUNT_BAIT}\n", encoding="utf-8", newline="\n")
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_the_bait_would_have_been_picked_up_by_the_old_scan(
        check, junk_in_the_checkout):
    """The discriminating half. Without it the tests below are
    assertions that a tidy tree is tidy.

    Two things have to hold for those to mean anything: the old scan
    reached these files, and the patterns still recognise what is in
    them. `ROOT.rglob` with the excluded prefixes is reproduced here
    rather than described, so it is the real former behaviour.
    """
    def old_scan(suffix):
        return [p for p in ROOT.rglob(f"*{suffix}")
                if not p.relative_to(ROOT).as_posix().startswith(
                    (".venv/", "build/", "dist/", "node_modules/"))]

    check("the old .py scan reached it",
          junk_in_the_checkout / "vendored.py" in old_scan(".py"))
    check("the old .md scan reached it",
          junk_in_the_checkout / "vendored.md" in old_scan(".md"))

    source = (junk_in_the_checkout / "vendored.py").read_text(encoding="utf-8")
    check("the citation bait is still a citation",
          build_docs.REVIEW_CITATION_RE.findall(source) == [("7", ""), ("", "B3")],
          build_docs.REVIEW_CITATION_RE.findall(source))
    check("the deviation bait is still a marker",
          [m.group(1) for m in build_docs.DEVIATION_RE.finditer(source)] == ["987"])

    bait = (junk_in_the_checkout / "vendored.md").read_text(encoding="utf-8")
    check("the count bait still trips the lint",
          bool(build_docs.find_hardcoded_counts(bait)))


def test_the_python_scan_ignores_files_the_repository_does_not_own(
        junk_in_the_checkout):
    """`.uv-cache/` gave the review index a Pygments citation; agent
    worktrees under `.claude/` gave it copies of this repository.

    Both are untracked, so neither is the project's. Asserted on the
    rendered pages and not only on the file list, because it is the
    pages that get committed and byte-compared.
    """
    assert junk_in_the_checkout / "vendored.py" not in \
        build_docs.owned_files("*.py")

    cited = build_docs.review_citations()
    from_junk = [where for places in cited.values() for where in places
                 if JUNK_DIR in where]
    assert not from_junk, from_junk

    assert "987" not in build_docs.render_deviation_index()


def test_the_markdown_scan_ignores_files_the_repository_does_not_own(
        junk_in_the_checkout):
    """The same defect in the test suite rather than in the generator.

    With agent worktrees present, the hard-coded-count check reported
    fifteen failures, every one a copy of this repository's own
    `README.md`, `tests/README.md` or
    `LAB54_DEVELOPMENT_REVIEW_AND_WORKFLOW.md`. A fix that repaired the
    generator and left the test walking the same tree would have fixed
    nothing.
    """
    assert junk_in_the_checkout / "vendored.md" not in _markdown_files()


def test_the_fallback_walk_is_narrower_than_the_tree():
    """Where git cannot answer, the scan must still not sweep the world.

    A fallback that walked everything would be the original defect
    wearing a fallback's clothes. This is not hypothetical on a
    developer's machine: `.venv/` alone holds an order of magnitude more
    `.py` files than the project does.
    """
    walked = build_docs._walk_files("*.py", ROOT)
    everything = [p for p in ROOT.rglob("*.py") if p.is_file()]
    assert len(walked) < len(everything), (
        "nothing in this checkout is being excluded, so this cannot say "
        "whether the exclusion list works"
    )
    for path in walked:
        assert not set(path.relative_to(ROOT).parts[:-1]) & \
            build_docs.NOT_PROJECT_DIRS, path


def test_a_page_written_by_the_generator_has_no_carriage_returns(tmp_path):
    """At byte level, through the tool's own writer.

    Text-mode comparison is why this went unnoticed for so long: the
    existing byte-equality guard reads with universal newlines, so a
    CRLF page compares equal to the LF text meant to replace it. Reading
    the committed pages would prove nothing either - `.gitattributes`
    checks them out as LF whatever the generator did. The failure only
    exists at the moment of writing, so that is where it is asked.

    On Windows `Path.write_text` without `newline` produced 44 CRLF
    pairs and no LF bytes in `review-index.md`. On Linux it produced LF
    and this test could not have failed, which is why the source check
    below exists as well: that one discriminates on every platform.
    """
    for name, render in (("review index", build_docs.render_review_index),
                         ("deviation index", build_docs.render_deviation_index),
                         ("chooser", build_docs.render_chooser)):
        target = tmp_path / "page.md"
        build_docs.write_lf(target, render())
        data = target.read_bytes()
        assert b"\r" not in data, (
            f"the {name} was written with carriage returns: "
            f"{data[:200]!r}"
        )
        assert b"\n" in data, f"the {name} rendered as a single line"


#: The tools that write files the repository tracks. `.gitattributes`
#: pins those to LF, so a write in platform text mode rewrites every
#: line of every file it touches when run on Windows.
#:
#: `smu_checkup.py` and `bench_probes.py` are deliberately absent: their
#: output is gitignored, so nothing compares it byte-for-byte and the
#: platform's own convention is the reasonable one there.
GENERATORS_WRITING_TRACKED_FILES = ("build_docs.py", "make_goldens.py")


@pytest.mark.parametrize("tool", GENERATORS_WRITING_TRACKED_FILES)
def test_no_generator_write_relies_on_the_platform(check, tool):
    """Every write site in these tools must name its line endings.

    A source check rather than a behavioural one, and deliberately: the
    behavioural version above cannot fail on Linux, so on its own it
    would let a new `write_text` reach a Windows bench machine with CI
    green. There are only ever a handful of write sites, and each one
    either names its endings or is the bug.

    Parsed rather than grepped. A `write_text` call spanning two lines -
    which is the normal shape once it carries three keywords - has the
    keyword on the line the grep is not looking at, so a line-wise
    version reported the one correct call in `make_goldens.py` as an
    offender and would have been fixed by weakening it.
    """
    path = ROOT / "tools" / tool
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def is_a_text_write(node):
        if not isinstance(node, ast.Call):
            return False
        if isinstance(node.func, ast.Attribute):
            return node.func.attr == "write_text"
        # `open(path, "w")`. Mode is the second positional argument, and
        # a mode with `b` in it is bytes, where `newline` has no meaning.
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            mode = next((a.value for a in node.args[1:2]
                         if isinstance(a, ast.Constant)), "r")
            return "b" not in str(mode) and any(c in str(mode) for c in "wxa")
        return False

    calls = [node for node in ast.walk(tree) if is_a_text_write(node)]
    check(f"{tool}: there are write sites to check at all", bool(calls),
          "with none, the assertion below holds of any file")

    offenders = [f"line {node.lineno}" for node in calls
                 if not any(kw.arg == "newline" for kw in node.keywords)]
    check(f"{tool}: every write site names its endings", not offenders,
          "these use text mode's platform default, which is CRLF on "
          "Windows:\n  " + "\n  ".join(offenders))


def test_a_crlf_page_is_reported_as_stale(tmp_path):
    """`--check` must not call a CRLF copy of a page up to date.

    This is what let the CRLF pages persist: `read_text` normalises, so
    the staleness comparison said identical and the rebuild that would
    have fixed them never ran. Once stale is judged on bytes, a CRLF
    page is stale - which is correct, because it is not what the tool
    produces.
    """
    page = tmp_path / "page.md"
    text = "# Title\n\nline one\nline two\n"

    page.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert page.read_text(encoding="utf-8") == text, (
        "the premise has changed: text-mode reading no longer hides the "
        "difference, and this test is no longer about anything"
    )
    assert not build_docs.is_current(page, text)

    build_docs.write_lf(page, text)
    assert build_docs.is_current(page, text)


# ---------------------------------------------------------------------------
# Tables, and the status line that must not fall behind the work
# ---------------------------------------------------------------------------
#: A Markdown table is the one construct in these documents that fails
#: *invisibly*. A truncated one renders as a heading with nothing under
#: it, which reads on GitHub as "there is nothing to report" rather than
#: as damage - and that is exactly how `docs/plan.md` came to carry a
#: `## Status` heading, a header row, a bare `|`, and no status at all
#: for the whole of the documentation rebuild. Nothing was wrong enough
#: to notice; the page simply stopped saying anything.
#:
#: Same principle as every other lint here: the claim "this table is
#: intact" is one a machine can check.


def _table_blocks(text: str) -> list[tuple[int, list[str]]]:
    """Every run of consecutive pipe-leading lines, with its 1-based start."""
    lines = text.splitlines()
    blocks: list[tuple[int, list[str]]] = []
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            start = i + 1
            block: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            blocks.append((start, block))
        else:
            i += 1
    return blocks


def _cells(line: str) -> list[str]:
    """Split one table row into cells.

    Two things have to survive this, both of which occur in the vault
    and both of which a naive `split("|")` gets wrong:

    * `\\|` - a literal pipe inside a cell, used by `schema.md` to write
      an either/or of two literal values;
    * a trailing `<!-- lint-ok -->` after the closing pipe, which
      `migration-status.md` uses to exempt a line that is quoting the
      old documents rather than making a live claim.

    Getting either wrong would make this lint fire on correct tables,
    and a lint that cries wolf gets the escape hatch applied to it until
    it stops meaning anything.
    """
    text = line.strip()
    if text.endswith(LINT_ESCAPE):
        text = text[: -len(LINT_ESCAPE)].strip()
    placeholder = "\x00"
    text = text.replace(r"\|", placeholder)
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [c.replace(placeholder, r"\|") for c in text.split("|")]


_SEPARATOR = re.compile(r"^:?-{1,}:?$")


def test_every_markdown_table_is_intact():
    """Header row, separator row, at least one body row, square columns.

    The "at least one body row" clause is the one that matters. A table
    with a header and a separator and nothing else is syntactically
    valid Markdown and renders as an empty grid, so it cannot be caught
    by reading the rendered page either.
    """
    offenders = []
    for path in _markdown_files():
        rel = path.relative_to(ROOT).as_posix()
        for start, block in _table_blocks(path.read_text(encoding="utf-8")):
            where = f"{rel}:{start}"
            if len(block) < 3:
                offenders.append(
                    f"{where}: {len(block)} row(s) - a table needs a header, "
                    f"a separator and at least one body row")
                continue
            width = len(_cells(block[0]))
            separator = _cells(block[1])
            if not all(_SEPARATOR.match(c.strip()) for c in separator):
                offenders.append(
                    f"{where}: second row is not a separator: {block[1].strip()!r}")
                continue
            for n, row in enumerate(block, start):
                if len(_cells(row)) != width:
                    offenders.append(
                        f"{rel}:{n}: {len(_cells(row))} cells, header has "
                        f"{width}: {row.strip()!r}")

    assert not offenders, (
        "malformed tables - these render as an empty or ragged grid rather "
        "than as an error:\n  " + "\n  ".join(offenders)
    )


#: `## Wave 6d-ii`, `## Wave 7a` - the whole label, not a number. A wave
#: lands in lettered parts, so "7a is done" is not "7 is done" and a
#: numeric comparison would demand the plan overclaim.
_WAVE_HEADING = re.compile(r"^##\s+(Wave\s+\S+)\s*$", re.MULTILINE)

#: The row in `docs/plan.md` that this check holds to account.
_LAST_LANDED = re.compile(r"\|\s*last landed\s*\|\s*(Wave\s+\S+?)\s*\|")


def test_the_plan_records_the_newest_wave_the_changelog_does():
    """`plan.md`'s "last landed" against `CHANGELOG.md`'s newest wave.

    These two files answer the same question from opposite ends - one
    says where the work has got to, the other records each thing as it
    was done - and they are edited at different moments. The changelog
    entry is written when the work lands; the plan is updated when
    someone remembers. That gap is the whole reason `WAVE_PLAN.md` ended
    up disagreeing with itself.

    `CHANGELOG.md` is newest-first and append-only by its own
    declaration, so "newest" is a position in the file rather than a
    number - which is what makes this work across `6d-i`, `6d-ii` and
    `7a` without needing to know how the labels sort.
    """
    plan = (DOCS / "plan.md").read_text(encoding="utf-8")
    match = _LAST_LANDED.search(plan)
    assert match, (
        "docs/plan.md no longer has a `| last landed | Wave N |` row. If "
        "the status table has been restructured, this check needs "
        "restructuring with it rather than deleting - that table was "
        "silently truncated once already, and nothing noticed for a "
        "whole wave."
    )
    claimed = match.group(1)

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    recorded = _WAVE_HEADING.findall(changelog)
    assert recorded, "CHANGELOG.md has no `## Wave ...` headings to check against"
    assert claimed in recorded, (
        f"docs/plan.md says the last landed wave is {claimed!r}, which has "
        f"no entry in CHANGELOG.md. Newest recorded is {recorded[0]!r}."
    )

    newer = recorded[: recorded.index(claimed)]
    assert not newer, (
        f"docs/plan.md says the last landed wave is {claimed!r}, but "
        f"CHANGELOG.md records {newer} above it. Update the status table."
    )
