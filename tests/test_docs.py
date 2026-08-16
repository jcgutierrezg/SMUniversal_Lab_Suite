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

import re
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
    "bench_revalidated", "reading_time", "resolution", "best_for",
}

MAINTENANCE_VALUES = {"active", "on-request"}


def _markdown_files() -> list[Path]:
    out = []
    for path in ROOT.rglob("*.md"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith((".venv/", "build/", "dist/", "node_modules/")):
            continue
        out.append(path)
    return sorted(out)


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

def test_a_pages_content_does_not_depend_on_when_the_code_last_moved():
    """Generated pages must not embed a date that every commit changes.

    They did. The stale reason named the date `git log -1` reported for
    the driver, so **any patch touching a driver file - even a comment -
    made the committed pages stale the moment it was committed**, and CI
    went red on a change that had nothing to do with the pages.

    It survived a clean-checkout verification because `git apply` leaves
    files uncommitted, so `git log` still reported the old date. The
    local check could not have failed.

    So this asks the question directly: render the same note against two
    different post-checkup commit dates and require identical output.
    The status is a *comparison* and is stable; the date is not, and
    does not belong in a committed artefact.
    """
    from datetime import date
    import unittest.mock as mock

    note, (meta, body) = next(
        (n, v) for n, v in build_docs.load_notes(physical_only=True).items()
        if v[0].get("last_bench") and v[0].get("bench_ever")
    )

    rendered = []
    for moved in (date(2026, 8, 15), date(2027, 3, 1)):
        with mock.patch.object(build_docs, "last_changed", return_value=moved), \
             mock.patch.object(build_docs, "repo_is_shallow", return_value=False):
            rendered.append(build_docs.render_bench_instrument(meta, body, note))

    assert rendered[0] == rendered[1], (
        f"{note.name}'s bench page changes when the driver's last commit "
        "date changes. A generated, committed page must depend on the "
        "staleness comparison, not on when the commit happened."
    )


def test_generated_pages_match_a_fresh_build():
    """A generated file that has been hand-edited fails the suite.

    Same mechanism as `tests/golden/*.json`: the artefact is committed
    so it renders on GitHub and on a bench machine with no Python, and
    the test is what stops the committed copy and the generator
    disagreeing.
    """
    if build_docs.repo_is_shallow():
        pytest.skip(
            "shallow clone: `git log -1 -- <file>` reports HEAD for every "
            "path, so the derived bench status cannot be computed. CI sets "
            "fetch-depth: 0."
        )
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
    from datetime import date

    asked = []

    def fake_last_changed(paths):
        asked.extend(paths)
        # only the shared base class moved; the driver's own file did not
        return (date(2026, 9, 1) if "base_smu" in " ".join(paths)
                else date(2026, 1, 1))

    monkeypatch.setattr(build_docs, "last_changed", fake_last_changed)
    monkeypatch.setattr(build_docs, "repo_is_shallow", lambda: False)

    status, reason = build_docs.bench_status({
        "bench_ever": True,
        "last_bench": "2026-08-14",
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


def test_a_driver_unchanged_since_its_checkup_reads_as_commissioned():
    """The other half of the same probe.

    Asked where the interesting answer is the correct one: if
    `bench_status` returned `stale` unconditionally, every assertion
    above would still pass, because the whole fleet is stale today.
    """
    from datetime import date
    import unittest.mock as mock

    with mock.patch.object(build_docs, "last_changed",
                           return_value=date(2026, 1, 1)), \
         mock.patch.object(build_docs, "repo_is_shallow", return_value=False):
        status, _ = build_docs.bench_status({
            "bench_ever": True,
            "last_bench": "2026-08-14",
            "driver": "drivers/keithley_2611a.py",
            "bench_revalidated": None,
        })
    assert status == "commissioned", status


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
    """
    for note, (meta, _body) in build_docs.load_notes(physical_only=True).items():
        status, _ = build_docs.bench_status(meta)
        if status == "commissioned":
            continue
        page = build_docs.bench_page_path(note)
        text = page.read_text(encoding="utf-8")
        assert "never met the instrument" in text or "has changed since" in text, (
            f"{page.name} carries no verification warning despite "
            f"status={status!r}"
        )


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
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith((".venv/", "build/", "dist/")):
            continue
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
