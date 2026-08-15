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

#: Counts of things the repository already knows. `HANDOFF.md` carried
#: five of these and every one had gone wrong. Its own house rules say
#: not to write them; this is that rule, enforced.
COUNT_PATTERN = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|twenty-\w+|thirty-\w+|\d{1,3})\s+"
    r"(?:hand-written\s+|registered\s+|separate\s+)?"
    r"(drivers?|instruments?|experiments?|test files?|source-measure units?)\b",
    re.IGNORECASE,
)

#: A count describing something that *happened* is history, not a live
#: claim, and history must stay writable: "four of the six drivers
#: returned the sentinel as data" is a finding, and rewording it to
#: avoid a number would lose the finding. The escape is per line and
#: visible in the source, so using it is a choice somebody made rather
#: than a default.
COUNT_ESCAPE = "<!-- count-ok -->"

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
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if COUNT_ESCAPE in line:
                continue
            match = COUNT_PATTERN.search(line)
            if match:
                offenders.append(f"{rel}:{n}: {match.group(0)!r}")

    assert not offenders, (
        "these state a count that goes stale on the next patch. Link to "
        "the generated table instead, or mark the line "
        f"{COUNT_ESCAPE} if it is describing history:\n  "
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
        text = path.read_text(encoding="utf-8")
        for name in gone:
            if f"{name}(" in text:
                offenders.append(f"{rel}: {name}()")

    assert not offenders, (
        "these describe driver methods that no longer exist:\n  "
        + "\n  ".join(offenders)
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
