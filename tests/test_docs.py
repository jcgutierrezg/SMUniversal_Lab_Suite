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

#: The four documents this vault replaces. They are full of counts that
#: were true when written, which is the entire argument for the rewrite
#: - linting them now would mean fixing prose that is about to be
#: deleted. `docs-retire-v1` removes the files; the exemption is
#: self-clearing, because `test_the_legacy_exemptions_are_still_needed`
#: fails the moment one of these no longer exists.
LEGACY = (
    "HANDOFF.md",
    "PORTING_NOTES.md",
    "INSTRUMENTS.md",
    "WAVE_PLAN.md",
)

#: Prose that is *about* the rule, or quotes a historical claim in order
#: to explain why it was wrong, is not itself a live claim.
COUNT_EXEMPT = LEGACY + (
    "tests/test_docs.py",
    "tests/README.md",
    "docs/reference/schema.md",
    "README.md",
    "LAB54_DEVELOPMENT_REVIEW_AND_WORKFLOW.md",
)


def test_the_legacy_exemptions_are_still_needed():
    """The exemption list clears itself.

    Every entry names a file scheduled for deletion. When one goes, this
    fails until the entry goes with it - so the exemption cannot outlive
    the thing it was excusing, which is how a temporary allowance
    becomes permanent.
    """
    missing = [name for name in LEGACY if not (ROOT / name).exists()]
    assert not missing, (
        "these are exempted from the documentation lints but no longer "
        f"exist - remove them from LEGACY: {missing}"
    )


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


def test_every_wikilink_resolves():
    """A link to a note that does not exist is a dead end in the vault.

    Obsidian renders an unresolved link in a different colour and does
    nothing else about it, so a broken one survives indefinitely.
    """
    names = {p.stem for p in _markdown_files()}
    broken = []
    for path in _markdown_files():
        rel = path.relative_to(ROOT).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for target in re.findall(r"\[\[([^\]|#]+)", line):
                stem = target.strip().split("/")[-1]
                if stem and stem not in names:
                    broken.append(f"{rel}:{n}: [[{target}]]")

    assert not broken, "unresolved wikilinks:\n  " + "\n  ".join(broken)


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
