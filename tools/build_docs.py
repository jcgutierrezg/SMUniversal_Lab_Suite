#!/usr/bin/env python
"""Generate the derived documentation pages.

Why this exists
---------------
Four claims in the old documents rotted silently because a human had to
remember to update them: how many drivers there are, what each one's
envelope is, which have met hardware, and which deviations exist. Each
was true when written. None announced itself when it stopped being true
- `HANDOFF.md` said "five hand-written drivers" while the registry held
nine, and "every driver except the 2450's has been run against its
instrument" thirty-six hours after Wave 6 modified all nine.

So the derived pages are not written. They are computed from the two
things that cannot drift from the code: the driver classes themselves,
and git history.

    drivers/*.py  LIMITS + capability declarations
          |
          +--> instrument note frontmatter (generated block)
          |          |
          |          +--> bench/choosing-an-smu.md      capability matrix
          |          +--> docs/open/checkup-owed.md     verification status
          |
    git log -1 -- <driver>, <base_smu.py>
          |
          +--> "has this driver changed since its last checkup?"

Usage
-----
    uv run python tools/build_docs.py            # write the generated files
    uv run python tools/build_docs.py --check    # fail if they are stale

`--check` is what `tests/test_docs.py` runs. A generated file that has
been hand-edited fails the suite, which is the same mechanism the golden
files use for the maths.

What is scanned
---------------
Only files the repository tracks, through `owned_files()`. A generated
page must depend on the repository and on nothing else about the machine
that built it, and a plain walk of `ROOT` does not: a tool cache and a
set of agent worktrees, both sitting untracked inside the checkout, have
each changed a generated page and turned the suite red.

What is NOT generated
---------------------
Judgement. `bench/choosing-an-smu.md` carries a hand-written guidance
section between two markers, and this tool preserves whatever is between
them. Numbers are computed; "use the 2635B for high-resistance samples"
is a person's opinion and stays one.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import provenance  # noqa: E402  (needs the path insert above)

DOCS = ROOT / "docs"
BENCH = ROOT / "bench"
INSTRUMENTS = DOCS / "instruments"
EXPERIMENTS = DOCS / "experiments"

#: The shared files every driver's verification also depends on, and the
#: digest of the code a checkup was about. Both come from
#: `core.provenance` so that the tool which *stamps* a fingerprint into
#: a report and the tool which *compares* one cannot disagree - a second
#: implementation here would pass its own tests whether or not it
#: matched the real one, which is this project's most repeated fault.
SHARED_DEPENDENCIES = provenance.SHARED_CODE_PATHS

GEN_BEGIN = "# --- generated from code by tools/build_docs.py: do not hand-edit"
GEN_END = "# --- end generated ---"

KEEP_BEGIN = "<!-- keep:begin -->"
KEEP_END = "<!-- keep:end -->"


# --------------------------------------------------------------------------
# Which files are the project's, and how they are written
#
# Both halves answer the same question: a generated page must depend on
# the repository and on nothing else about the machine that built it.
# --------------------------------------------------------------------------

#: Directory names that can sit inside a checkout without being part of
#: the project: tool caches, virtual environments, build output, editor
#: state, and the agent worktrees `.claude/` holds.
#:
#: Consulted only by the fallback walk. The index is the real answer;
#: this list exists so that a checkout with no git available degrades to
#: something narrower than "everything on disk" rather than back to the
#: defect.
NOT_PROJECT_DIRS = frozenset({
    ".git", ".claude", ".venv", "venv", "env", ".env",
    "build", "dist", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis",
    ".tox", ".nox", ".eggs", "htmlcov", "site-packages",
    ".uv-cache", ".cache", ".idea", ".vscode", ".obsidian",
    "checkups", "tmp", "temp",
})


def owned_files(pattern: str = "*", root: Path = ROOT) -> list[Path]:
    """Every file under `root` matching `pattern` that the project owns.

    `root.rglob(pattern)` answers a different question - what is *lying
    in the directory* - and the two diverged twice. A `.uv-cache/` left
    inside the checkout contributed a Pygments source file to
    `docs/reference/review-index.md`; agent worktrees under `.claude/`
    put a second complete copy of the tree inside `ROOT`, and fifteen
    copies of this repository's own `README.md` were reported as
    hard-coded-count offences. Neither is in any commit, and both turned
    the suite red on one machine and not another.

    The question asked here is the git index's instead: **tracked files
    only**. The consequence is worth stating rather than discovering - a
    new module is invisible to the generator until it is `git add`-ed.
    That is the right way round. These pages are committed artifacts
    compared byte-for-byte by `tests/test_docs.py`, so deriving them
    from the index means the page in a commit describes the code in that
    commit and cannot describe scratch work that never left one machine.

    This does read git, which `core.provenance` documents as a thing a
    bench tool cannot depend on. The two are not in tension: provenance
    refuses to depend on git for *history*, because a report must still
    be produced from a zip download. Listing files is not history, and
    the fallback below covers the same case.

    Falls back to a filtered walk where git cannot answer. Filtered, not
    open: an unfiltered fallback would be the original defect wearing a
    fallback's clothes.
    """
    listed = _tracked_files(pattern, root)
    if listed is None:
        listed = _walk_files(pattern, root)
    return sorted(listed)


def _tracked_files(pattern: str, root: Path) -> list[Path] | None:
    """Paths in the git index, or None if git cannot say.

    `-z` because a path is bytes with a newline permitted in it, and a
    line-split listing would silently split one such path into two
    nonexistent ones.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", pattern],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    # A file deleted from the working tree but not yet from the index is
    # still listed. It cannot be read and has nothing to contribute.
    return [path for path in (root / name
                              for name in result.stdout.split("\0") if name)
            if path.is_file()]


def _walk_files(pattern: str, root: Path) -> list[Path]:
    out = []
    for path in root.rglob(pattern):
        if not path.is_file():
            continue
        # `parts[:-1]` is the directories only: a *file* called `build`
        # is the project's, a directory called `build` is not.
        if any(part in NOT_PROJECT_DIRS
               for part in path.relative_to(root).parts[:-1]):
            continue
        out.append(path)
    return out


def write_lf(path: Path, text: str) -> None:
    """Write generated text with LF endings, whatever the platform.

    `Path.write_text` uses text mode, which translates `\\n` to `\\r\\n`
    on Windows. `.gitattributes` pins these files to LF, so a rebuild on
    a bench machine left every generated page showing as modified with
    no content change - enough, once, to block a `git switch`.

    Reading cannot see it: `read_text` decodes with universal newlines,
    so a CRLF copy of a page compares equal to the LF text meant to
    replace it. That is why the guard is here, at the write, and why
    `is_current` below compares bytes.
    """
    path.write_text(text, encoding="utf-8", newline="\n")


def is_current(path: Path, text: str) -> bool:
    """True when `path` already holds exactly `text`, byte for byte.

    Bytes rather than decoded text, and for one reason: a page already
    on disk in CRLF *is* stale - it is not what this tool produces - and
    a text-mode comparison calls it identical. Every `--check` run that
    was supposed to catch the CRLF rebuild passed for that reason.
    """
    return path.exists() and path.read_bytes() == text.encode("utf-8")


def banner(source: str = "docs/") -> str:
    """The do-not-edit header, naming the note it was built from.

    Parameterised because a page generated from `docs/experiments/` that
    tells the reader to edit `docs/instruments/` sends them to the wrong
    file - a small wrongness, but the kind that trains people to ignore
    the banner.
    """
    return (
        "<!-- GENERATED by tools/build_docs.py - do not edit this file.\n"
        f"     Edit the source note in {source} instead, then\n"
        "     run: uv run python tools/build_docs.py -->\n"
    )


BANNER = banner()


# --------------------------------------------------------------------------
# A very small frontmatter reader/writer
#
# Deliberately not PyYAML. Adding a dependency to parse four kinds of
# scalar would put a third-party parser between the documentation and
# the test that guards it, and `uv.lock` is checked with --locked in CI.
# The subset here is stated in docs/reference/schema.md and the schema
# test refuses anything outside it, so the parser cannot silently
# mis-read a construct it does not support: it raises instead.
# --------------------------------------------------------------------------

class FrontmatterError(ValueError):
    """A note's frontmatter is missing, malformed, or uses unsupported YAML."""


def _scalar(text: str):
    """Parse one scalar. Returns str, bool, int, float or None."""
    text = text.strip()
    if text in ("null", "~", ""):
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(p) for p in inner.split(",")]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    if any(ch in text for ch in "{}&*!|>%@`"):
        raise FrontmatterError(
            f"unsupported YAML construct in frontmatter: {text!r}. "
            "The supported subset is in docs/reference/schema.md."
        )
    return text


def read_frontmatter(path: Path) -> tuple[dict, str]:
    """Split a note into (frontmatter dict, body). Raises if absent."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise FrontmatterError(f"{path.relative_to(ROOT)} has no frontmatter block")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise FrontmatterError(f"{path.relative_to(ROOT)} frontmatter is not closed")
    block, body = text[4:end], text[end + 5:]

    data: dict = {}
    key = None
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith((" ", "\t")) and raw.lstrip().startswith("- "):
            if key is None:
                raise FrontmatterError(f"{path.name}: list item before any key")
            data.setdefault(key, [])
            if not isinstance(data[key], list):
                raise FrontmatterError(f"{path.name}: '{key}' is both scalar and list")
            data[key].append(_scalar(raw.lstrip()[2:]))
            continue
        if ":" not in raw:
            raise FrontmatterError(f"{path.name}: cannot parse line {raw!r}")
        key, _, value = raw.partition(":")
        key = key.strip()
        if key in data:
            raise FrontmatterError(
                f"{path.name}: '{key}' is declared twice. YAML would take "
                "the last one silently, so a hand-written value shadowed "
                "by a generated one reads as correct while meaning "
                "something else."
            )
        data[key] = [] if not value.strip() else _scalar(value)
    return data, body


def _dump_scalar(value) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    text = str(value)
    if text != text.strip() or ":" in text or text.startswith(("[", "-", "#")):
        return f'"{text}"'
    return text


# --------------------------------------------------------------------------
# Facts from the code
# --------------------------------------------------------------------------

def driver_facts() -> dict[str, dict]:
    """Capability facts for every registered driver, keyed by class name.

    Read from the classes rather than from a list here, so a driver
    added to `KNOWN_DRIVERS` appears without anyone remembering.
    """
    from drivers.base_smu import BaseSMU
    from drivers.registry import KNOWN_DRIVERS

    facts = {}
    for cls in KNOWN_DRIVERS:
        limits = cls.LIMITS
        nplc = getattr(cls, "NPLC_RANGE", None)
        module = sys.modules[cls.__module__]
        facts[cls.__name__] = {
            # NB: `driver_class` is deliberately NOT emitted here. It is
            # the hand-written key that links a note to its driver, and a
            # generated copy would be parsed second and silently shadow
            # it - so a note pointing at a driver that does not exist
            # would still resolve. Found by mutation.
            "driver": str(Path(module.__file__).relative_to(ROOT).as_posix()),
            "model_ids": list(cls.MODEL_IDS),
            "max_voltage_v": float(limits.max_voltage),
            "max_current_a": float(limits.max_current),
            "voltage_ranges_n": len(limits.voltage_ranges),
            "current_ranges_n": len(limits.current_ranges),
            "power_envelope_n": len(limits.power_envelope),
            "sweep_kind": getattr(cls, "SWEEP_KIND", "software"),
            "nplc_min": None if not nplc else float(nplc[0]),
            "nplc_max": None if not nplc else float(nplc[1]),
            "high_z_off": bool(getattr(cls, "HIGH_Z_OFF", False)),
            "ovp": bool(getattr(cls, "OVP_CHOICES", None)),
            "remote_sense_control": bool(getattr(cls, "REMOTE_SENSE_CONTROL", True)),
            # A driver that inherits BaseSMU's stub cannot report
            # compliance. Asked by identity rather than by name, because
            # a driver could define the method and still not implement
            # it - and "not reported" is the answer that matters at the
            # bench either way.
            "compliance_trip": (
                cls.compliance_tripped is not BaseSMU.compliance_tripped
            ),
        }
    return facts


# --------------------------------------------------------------------------
# Facts from git
# --------------------------------------------------------------------------

def bench_status(meta: dict) -> tuple[str, str]:
    """Derive (status, reason) for one driver. Never hand-written.

    Four states:

    * `unverified` - this driver has never met its instrument. The 2450
      is here because the hardware belongs to another lab.
    * `failing` - it was checked, the code has not moved since, and the
      checkup **failed**. A date alone could not say this, so a checkup
      that failed used to render exactly like one that passed.
    * `stale` - it was checked, and the code has changed since. The
      checkup's answers were about code that no longer exists.
    * `commissioned` - checked, passed, unchanged since.

    Staleness is a comparison of **content**, not of commit dates. See
    `core.provenance.code_fingerprint` for why: a commit date is rewritten
    by `git am`, by a rebase, and by a squash-merge, so the date rule
    reported a change when nothing had changed and turned `main` red on
    the first CI run after a merge.
    """
    if meta.get("bench_ever") is not True:
        return "unverified", "never run against its instrument"

    revalidated = meta.get("bench_revalidated")
    if revalidated:
        return "commissioned", f"revalidated by inspection: {revalidated}"

    when = meta.get("last_bench")
    if not when:
        return "stale", "passed a checkup, but the date was not recorded"

    recorded = meta.get("bench_code")
    if not recorded:
        return "stale", (f"the {when} checkup did not record which code "
                         "it ran")

    current = provenance.code_fingerprint(
        provenance.code_paths_for(meta["driver"]), root=str(ROOT))
    if current is None:
        return "unknown", "the driver file this note names is missing"

    # `fail` is the only value that means failing. An unrecognised value
    # is not treated as a pass: a typo in a frontmatter field must not
    # be the thing that promotes a failing driver to commissioned.
    result = str(meta.get("bench_result") or "").strip().lower()
    failed = result != "pass"

    if current != recorded:
        # Deliberately not naming the new fingerprint. These reasons are
        # rendered into committed, byte-checked pages, so a value that
        # changes on every edit to a driver would make the pages stale
        # the instant they were built. The comparison is what matters
        # and it is stable: once stale, stale until somebody checks it.
        if failed:
            return "stale", (f"the code has changed since the {when} "
                             "checkup, which was failing when it ran")
        return "stale", f"the code has changed since the {when} checkup"

    if failed:
        return "failing", (meta.get("bench_result_note")
                           or f"the {when} checkup failed")
    return "commissioned", f"checked {when}, unchanged since"


# --------------------------------------------------------------------------
# Generators
# --------------------------------------------------------------------------

def instrument_notes() -> list[Path]:
    return sorted(INSTRUMENTS.glob("*.md"))


def load_notes(physical_only: bool = False) -> dict[Path, tuple[dict, str]]:
    """Every instrument note, or only the ones describing real hardware.

    `DummySMU` is a registered driver and must have a note - the
    bijection test insists, so demo mode cannot quietly diverge from the
    real drivers. But it is not an instrument: listing it in a chooser
    table aimed at the bench would offer a simulated SMU as a
    measurement option, and putting it in the checkup-owed list would
    demand a bench session for a thing that has no bench.
    """
    notes = {p: read_frontmatter(p) for p in instrument_notes()
             if not p.name.startswith("_")}
    if physical_only:
        notes = {p: v for p, v in notes.items() if v[0].get("physical") is not False}
    return notes


def sync_frontmatter(write: bool = True) -> list[str]:
    """Write the code-derived block into each instrument note.

    Returns the list of notes whose generated block was out of date.
    """
    facts = driver_facts()
    stale = []
    for path, (meta, body) in load_notes().items():
        cls = meta.get("driver_class")
        if cls not in facts:
            continue
        text = path.read_text(encoding="utf-8")
        rebuilt = _rebuild_generated_block(text, facts[cls])
        if not is_current(path, rebuilt):
            stale.append(str(path.relative_to(ROOT).as_posix()))
            if write:
                write_lf(path, rebuilt)
    return stale


def _rebuild_generated_block(text: str, facts: dict) -> str:
    """Replace the generated span of a note's frontmatter, in place.

    Anchored on two markers and asserted to find both. A silent
    no-match that writes the file back unchanged is the exact failure
    this project has been bitten by before, so it raises instead.
    """
    lines = [f"{key}: {_dump_scalar(value)}" for key, value in facts.items()]
    block = "\n".join([GEN_BEGIN, *lines, GEN_END])

    start = text.find(GEN_BEGIN)
    end = text.find(GEN_END)
    if start == -1 or end == -1:
        raise FrontmatterError(
            "instrument note is missing the generated-block markers "
            f"({GEN_BEGIN!r} / {GEN_END!r})"
        )
    return text[:start] + block + text[end + len(GEN_END):]


def _preserved(path: Path) -> str:
    """The hand-written span of a generated file, if it already exists."""
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    start, end = text.find(KEEP_BEGIN), text.find(KEEP_END)
    if start == -1 or end == -1:
        return ""
    return text[start + len(KEEP_BEGIN):end].strip("\n")


def _si(value: float, unit: str) -> str:
    for scale, prefix in ((1e-12, "p"), (1e-9, "n"), (1e-6, "u"),
                          (1e-3, "m"), (1.0, ""), (1e3, "k")):
        if abs(value) < scale * 1000:
            return f"{value / scale:g} {prefix}{unit}"
    return f"{value:g} {unit}"


def render_chooser() -> str:
    """The capability matrix, plus a preserved block of human guidance."""
    rows = []
    for path, (meta, _) in sorted(load_notes(physical_only=True).items()):
        status, _reason = bench_status(meta)
        # `fails` is louder than `re-check` on purpose. Stale means
        # nobody has confirmed it lately; failing means somebody has,
        # and it did not work.
        mark = {"commissioned": "yes", "stale": "**re-check**",
                "failing": "**fails**", "unverified": "**never**",
                "unknown": "?"}[status]
        rows.append((
            meta.get("title") or path.stem.replace("-", " "),
            _si(meta["max_voltage_v"], "V"),
            _si(meta["max_current_a"], "A"),
            meta.get("reading_time") or "-",
            "hardware" if meta["sweep_kind"] == "hardware" else "software",
            "4-wire only" if not meta["remote_sense_control"] else "switchable",
            "yes" if meta["compliance_trip"] else "no",
            mark,
        ))

    head = ("| Instrument | Max V | Max I | Per reading | Sweep | Sensing "
            "| Reports compliance | Verified |")
    sep = "|---|---|---|---|---|---|---|---|"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)

    return (
        f"{BANNER}\n"
        "# Choosing an SMU\n\n"
        "Every number below comes from the driver's own declarations, so "
        "this table cannot disagree with the software.\n\n"
        "**Read the Verified column first.** `fails` means the driver "
        "was run against the instrument and did not pass - read its note "
        "before using it. `re-check` means the driver "
        "has been modified since it was last run against the instrument: "
        "the measurement may be fine, but nobody has confirmed it. "
        "`never` means it has never met hardware at all. Run "
        "`uv run tools/smu_checkup.py --address <addr>` before trusting "
        "either.\n\n"
        f"{head}\n{sep}\n{body}\n\n"
        "Per-instrument detail, including what each one gets wrong, is in "
        "`bench/instruments/`.\n\n"
        "---\n\n"
        f"{KEEP_BEGIN}\n"
        "## Which instrument for which measurement\n\n"
        "*(Written by hand. Everything above is generated; this section is "
        "preserved across rebuilds.)*\n"
        f"{KEEP_END}\n"
    )


def render_checkup_owed() -> str:
    """Which drivers need a bench session, and why."""
    lines = []
    for path, (meta, _) in sorted(load_notes(physical_only=True).items()):
        status, reason = bench_status(meta)
        if status == "commissioned":
            continue
        lines.append(
            f"| {meta.get('title') or path.stem} | `{meta['driver']}` | "
            f"{status} | {reason} |"
        )

    body = "\n".join(lines) if lines else "| - | - | - | nothing owed |"
    return (
        f"{BANNER}\n"
        "# Checkup owed\n\n"
        "A driver is *commissioned* only while the code that was checked "
        "is the code that is running.\n\n"
        "This compares a digest of the driver's **contents** against the "
        "`bench_code` each note recorded at its last checkup - nobody "
        "maintains it, no git history is consulted, and it cannot claim "
        "a driver is current when the file has changed.\n\n"
        "*failing* is not *stale*. Stale means nobody has checked "
        "recently; failing means somebody has, and it did not pass.\n\n"
        "| Instrument | Driver | Status | Why |\n|---|---|---|---|\n"
        f"{body}\n\n"
        "Run `uv run tools/smu_checkup.py --address <addr> --trace`, then "
        "copy `last_bench`, `bench_code` and `bench_result` from the "
        "report header into the instrument's note and rebuild.\n"
    )


#: Counts of things the repository already knows, and the per-line
#: escape for prose that is recording history rather than claiming a
#: present fact. Lives here rather than in the test so that the test
#: proving the escape is per-line exercises the same code the real
#: check does - a reimplementation in the test would pass whether or
#: not the real one worked, which is how it was first written.
COUNT_PATTERN = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|twenty-\w+|thirty-\w+|\d{1,3})\s+"
    r"(?:hand-written\s+|registered\s+|separate\s+)?"
    r"(drivers?|instruments?|experiments?|test files?|source-measure units?)\b",
    re.IGNORECASE,
)

LINT_ESCAPE = "<!-- lint-ok -->"


def find_hardcoded_counts(text: str) -> list[tuple[int, str]]:
    """Line numbers and matches for counts stated in prose.

    Per line, deliberately: an escape on line 40 does not excuse line
    90. A file-level opt-out would be added once and then inherited by
    everything written into that file afterwards.
    """
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if LINT_ESCAPE in line:
            continue
        match = COUNT_PATTERN.search(line)
        if match:
            out.append((n, match.group(0)))
    return out


def find_mentions(text: str, names: list[str]) -> list[tuple[int, str]]:
    """Line numbers where any of `names` is mentioned as a live call."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if LINT_ESCAPE in line:
            continue
        for name in names:
            if f"{name}(" in line:
                out.append((n, name))
    return out


DEVIATION_RE = re.compile(r"DEVIATION\s+(\d+)")

REVIEW = ROOT / "LAB54_DEVELOPMENT_REVIEW_AND_WORKFLOW.md"
REVIEW_SECTION_RE = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)
REVIEW_CITATION_RE = re.compile(r"(?:review )?§(\d+)|\b(?:group|issue) ([AB]\d+)")

#: Where each cited review section's reasoning now lives. Hand-written,
#: because "which note carries this" is a judgement, and required to be
#: complete by `tests/test_docs.py` - a citation appearing in the source
#: with no entry here fails the suite.
#:
#: The review itself is scheduled for deletion once Wave 7 closes. When
#: it goes, 185 citations across the source lose their referent, and for
#: several modules that citation is the *only* recorded reason the module
#: exists. This table is what stops that being a loss.
REVIEW_CARRIED_BY = {
    7: "docs/architecture/run-lifecycle.md",
    8: "docs/architecture/run-lifecycle.md",
    10: "docs/architecture/run-lifecycle.md",
    11: "docs/architecture/run-lifecycle.md",
    12: "docs/architecture/run-lifecycle.md",
    14: "docs/architecture/core-modules.md",
    15: "docs/architecture/calculation-provenance.md",
    16: "docs/architecture/calculation-provenance.md",
    17: "docs/architecture/calculation-provenance.md",
    18: "docs/architecture/calculation-provenance.md",
    20: "docs/architecture/sweeps-and-transports.md",
    24: "docs/rules/06-validate-operator-input.md",
    25: "docs/rules/03-no-auto-save.md",
    42: "docs/workflow/packaging.md",
    26: "docs/architecture/core-modules.md",
    27: "docs/architecture/calculation-provenance.md",
    28: "docs/architecture/calculation-provenance.md",
    33: "docs/architecture/core-modules.md",
    36: "docs/architecture/core-modules.md",
    53: "docs/rules/10-provenance.md",
    54: "docs/rules/05-si-inside.md",
    55: "docs/rules/03-no-auto-save.md",
    "A2": "docs/architecture/run-lifecycle.md",
    "A6": "docs/architecture/run-lifecycle.md",
    "A9": "docs/architecture/ownership.md",
    "A10": "docs/architecture/run-lifecycle.md",
    "B1": "docs/rules/05-si-inside.md",
    "B2": "docs/rules/08-ui-is-a-queue.md",
    "B3": "docs/architecture/calculation-provenance.md",
    "B4": "docs/architecture/calculation-provenance.md",
    "B5": "docs/architecture/calculation-provenance.md",
    "B6": "docs/architecture/calculation-provenance.md",
    "B7": "docs/architecture/calculation-provenance.md",
    "B8": "docs/architecture/calculation-provenance.md",
}


def review_sections() -> dict[int, str]:
    """Section number -> heading, read from the review itself."""
    if not REVIEW.exists():
        return {}
    return {int(n): title.strip()
            for n, title in REVIEW_SECTION_RE.findall(
                REVIEW.read_text(encoding="utf-8"))}


def review_citations() -> dict[object, list[str]]:
    """Every §N / group XN cited from the source, and where."""
    found: dict[object, list[str]] = {}
    for path in owned_files("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for section, group in REVIEW_CITATION_RE.findall(line):
                key = int(section) if section else group
                found.setdefault(key, []).append(f"`{rel}`:{n}")
    return found


def render_review_index() -> str:
    sections = review_sections()
    cited = review_citations()

    def sort_key(k):
        return (0, k, "") if isinstance(k, int) else (1, 0, str(k))

    rows = []
    for key in sorted(cited, key=sort_key):
        label = f"§{key}" if isinstance(key, int) else str(key)
        title = sections.get(key, "issue group" if not isinstance(key, int) else "—")
        carried = REVIEW_CARRIED_BY.get(key)
        target = f"`{carried}`" if carried else "**unmapped**"
        places = ", ".join(sorted(set(cited[key]))[:4])
        extra = "" if len(set(cited[key])) <= 4 else f" +{len(set(cited[key])) - 4} more"
        rows.append(f"| {label} | {title} | {target} | {places}{extra} |")

    return (
        f"{banner()}\n"
        "# Review index\n\n"
        "`LAB54_DEVELOPMENT_REVIEW_AND_WORKFLOW.md` is cited from source "
        "comments throughout the repository as `review §N`, `group B3` and "
        "similar. For several modules **that citation is the only recorded "
        "reason the module exists** - `core/units.py` says its convention "
        "comes from §54 and nothing else says why.\n\n"
        "The review is scheduled for deletion once Wave 7 closes. This "
        "table is what stops that being a loss: every cited section, its "
        "heading, and the note that now carries its reasoning.\n\n"
        "Generated from the review's own headings and a grep of the "
        "source, so it cannot miss a citation. The *mapping* is "
        "hand-written in `REVIEW_CARRIED_BY`, and a citation with no entry "
        "there fails the test suite.\n\n"
        "| Cited as | Review heading | Reasoning now lives in | Cited from |\n"
        "|---|---|---|---|\n"
        + "\n".join(rows) + "\n"
    )


def render_deviation_index() -> str:
    """Every `# DEVIATION n` marker in the source, and where it sits.

    The prose ledger lives with each instrument and experiment. This is
    the lookup table for the other direction: given a number in a
    commit message or an old conversation, which file carries it.
    """
    found: dict[int, list[str]] = {}
    for path in owned_files("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in DEVIATION_RE.finditer(line):
                found.setdefault(int(match.group(1)), []).append(f"`{rel}`:{n}")

    rows = "\n".join(
        f"| {number} | {', '.join(places)} |"
        for number, places in sorted(found.items())
    )
    return (
        f"{BANNER}\n"
        "# Deviation index\n\n"
        "Deviation numbers are permanent and global. They are cited from "
        "source comments, commit messages and past conversations, so they "
        "are never renumbered - only the note that explains them moves.\n\n"
        "This table lists the markers **in the code**. A deviation with no "
        "row here is documented but not marked at a call site, which is "
        "normal for the ones describing a whole driver.\n\n"
        "| Deviation | Marked at |\n|---|---|\n"
        f"{rows}\n"
    )


# --------------------------------------------------------------------------
# Bench-page extraction
#
# Not wired to any real content yet - the instrument notes are stubs
# until docs-instruments-v1. The function is here, and unit-tested
# against a fixture, so the mechanism is proven before it is adopted.
# Same shape as Wave 6d-i: build the capability, prove it in isolation,
# adopt it in the next patch.
# --------------------------------------------------------------------------

BENCH_MARKER = "<!-- bench -->"

MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+\.md)(#[^)]*)?\)")


def retarget_links(text: str, source: Path, destination: Path) -> str:
    """Rewrite relative links for a section moved to another folder.

    Links are relative Markdown - `[Hall](../instruments/hall.md)` -
    because that is what renders as navigation on GitHub, in Obsidian
    and through pandoc alike. The cost of relative over wiki-style is
    that a path is only correct from the folder it was written in, and
    extraction moves sections from `docs/` to `bench/`.

    So the generator recomputes them. Two rules:

    * **A bench page links to a bench page** where the target has one.
      The audience of `bench/` is somebody taking a measurement, and
      sending them into the developer notes for a fact that has a bench
      page is a worse answer than the one next door.
    * Otherwise the link points back into `docs/`, which is correct and
      simply more detail than they asked for.

    A link that cannot be resolved is left exactly as written rather
    than guessed at, and `tests/test_docs.py` fails on it - a silently
    rewritten wrong path is the failure this whole layer exists to
    avoid.
    """
    def repl(match: re.Match) -> str:
        label, rel, frag = match.group(1), match.group(2), match.group(3) or ""
        target = (source.parent / rel).resolve()
        if not target.exists():
            return match.group(0)

        try:
            note = target.relative_to(DOCS)
        except ValueError:
            note = None

        if note is not None and note.parent.name in ("instruments", "experiments"):
            bench_twin = bench_page_path(target)
            if bench_twin.exists():
                target = bench_twin

        moved = os.path.relpath(target, destination.parent).replace(os.sep, "/")
        return f"[{label}]({moved}{frag})"

    return MD_LINK.sub(repl, text)


def extract_bench_sections(body: str) -> str:
    """Return the `## ` sections of `body` marked for the bench pages.

    Extraction, deliberately, not summarisation. A generator that
    shortened would be making judgements about what a bench scientist
    needs to know, and the things most worth carrying across - the
    interlock is jumpered, this driver has never met hardware - are
    exactly the ones a shortener would drop as detail.
    """
    out: list[str] = []
    keeping = False
    for line in body.splitlines():
        if line.startswith("## "):
            keeping = BENCH_MARKER in line
            if keeping:
                out.append(line.replace(BENCH_MARKER, "").rstrip())
            continue
        if line.startswith("# "):
            keeping = False
            continue
        if keeping:
            out.append(line)
    return "\n".join(out).strip("\n")


# --------------------------------------------------------------------------

def render_bench_instrument(meta: dict, body: str, note: Path) -> str:
    """One bench page for one instrument, from its marked sections.

    The two audiences do not differ by *detail level* - they differ by
    question. The note answers "why does the driver send this"; the
    bench page answers "what does this mean for my measurement". So
    this extracts whole marked sections rather than shortening: a
    generator that condensed would be making judgements about what a
    bench scientist needs, and the facts most worth carrying across -
    the interlock is jumpered, this driver has not been re-checked since
    the code changed - are exactly the ones a shortener drops as detail.
    """
    status, reason = bench_status(meta)
    warning = ""
    if status == "failing":
        # First, and worded as a present-tense fact rather than a
        # caution. The other two say "nobody has checked"; this one says
        # "somebody has, and it did not pass", which is a different
        # instruction to the person standing at the fixture.
        warning = (
            "> **This driver fails its own checkup.** "
            f"{reason.capitalize()}. Read the note before using it, and "
            "treat any measurement it produces as unconfirmed.\n\n"
        )
    elif status == "stale":
        warning = (
            "> **This driver has changed since it was last checked against "
            f"the instrument.** {reason.capitalize()}. The measurement may "
            "be fine; nobody has confirmed it. Run "
            "`uv run tools/smu_checkup.py --address <addr>` first.\n\n"
        )
    elif status == "unverified":
        warning = (
            "> **This driver has never met the instrument.** "
            f"{reason.capitalize()}. Nothing below has been confirmed at a "
            "bench.\n\n"
        )

    idn = meta.get("idn")
    identity = f"```\n{idn}\n```\n\n" if idn else ""

    facts = [
        ("Maximum voltage", _si(meta["max_voltage_v"], "V")),
        ("Maximum current", _si(meta["max_current_a"], "A")),
        ("Per reading", meta.get("reading_time") or "not characterised"),
        ("Resolution", meta.get("resolution") or "not characterised"),
        ("Sweep", "on the instrument" if meta["sweep_kind"] == "hardware"
                  else "stepped from the PC"),
        ("Sensing", "4-wire only, by wiring"
                    if not meta["remote_sense_control"] else "2-wire or 4-wire"),
        ("Reports hitting compliance", "yes" if meta["compliance_trip"] else "no"),
        ("Best for", meta.get("best_for") or "-"),
    ]
    table = "\n".join(f"| {label} | {value} |" for label, value in facts)

    return (
        f"{banner('docs/instruments/')}\n"
        f"# {meta['title']}\n\n"
        f"{warning}"
        f"{identity}"
        "| | |\n|---|---|\n"
        f"{table}\n\n"
        f"{retarget_links(extract_bench_sections(body), note, bench_page_path(note))}\n"
    )


def experiment_notes() -> dict[Path, tuple[dict, str]]:
    return {p: read_frontmatter(p) for p in sorted(EXPERIMENTS.glob("*.md"))
            if not p.name.startswith("_")}


#: Values of an experiment note's `origin` that mean "there was no
#: original", rather than naming one. A small closed set, so a typo
#: falls through to the port wording and is noticed, instead of being
#: silently treated as a new experiment.
NO_ORIGINAL = {"new experiment", "none", "no original script"}


def render_bench_experiment(meta: dict, body: str, note: Path) -> str:
    """One bench page for one experiment, from its marked sections.

    Same extraction as the instrument pages. No verification banner:
    an experiment has no bench status - it is the *driver* that is
    checked against an instrument, and the consequences an operator
    needs here are about what the measurement means, not about whether
    the code has moved since somebody last confirmed it.
    """
    origin = meta.get("origin")
    # "Ported from `New experiment`" is a false sentence, and it is the
    # generator asserting it rather than anyone writing it - which makes
    # it exactly the kind of claim this tool exists to prevent. Every
    # note until now described a port, so the template said so
    # unconditionally; the first experiment with no original made that
    # assumption visible.
    #
    # Matched on the value rather than on a second front-matter key,
    # because a key like `ported: false` would be a second place to
    # record one fact, and the two would eventually disagree.
    if not origin:
        provenance = ""
    elif origin.strip().lower() in NO_ORIGINAL:
        provenance = "*New experiment - no original script.*\n\n"
    else:
        provenance = f"*Ported from `{origin}`.*\n\n"
    return (
        f"{banner('docs/experiments/')}\n"
        f"# {meta['title']}\n\n"
        f"{provenance}"
        f"{retarget_links(extract_bench_sections(body), note, bench_page_path(note))}\n"
    )


def bench_page_path(note: Path) -> Path:
    """Where a note's bench page goes.

    The `-bench` suffix is not decoration: identical basenames in two
    folders make an Obsidian wikilink ambiguous, and the ugliness is
    better on the generated file nobody links to by hand.
    """
    folder = "experiments" if note.parent.name == "experiments" else "instruments"
    return BENCH / folder / f"{note.stem}-bench.md"


GENERATED = {
    BENCH / "choosing-an-smu.md": render_chooser,
    DOCS / "open" / "checkup-owed.md": render_checkup_owed,
    DOCS / "reference" / "deviation-index.md": render_deviation_index,
    DOCS / "reference" / "review-index.md": render_review_index,
}


def build(check: bool = False) -> list[str]:
    """Write (or verify) every generated file. Returns what was stale."""
    stale = sync_frontmatter(write=not check)

    wanted = set()
    pages = [(note, render_bench_instrument(meta, body, note))
             for note, (meta, body) in load_notes(physical_only=True).items()]
    pages += [(note, render_bench_experiment(meta, body, note))
              for note, (meta, body) in experiment_notes().items()]

    for note, text in pages:
        target = bench_page_path(note)
        wanted.add(target)
        if not is_current(target, text):
            stale.append(str(target.relative_to(ROOT).as_posix()))
            if not check:
                target.parent.mkdir(parents=True, exist_ok=True)
                write_lf(target, text)

    # A note deleted or made non-physical must not leave its bench page
    # behind. An orphan here is the same failure as the orphaned
    # temp_panel.py that survived Wave 0b: still present, still
    # plausible, describing something that is gone.
    for folder in ("instruments", "experiments"):
        existing = BENCH / folder
        if not existing.is_dir():
            continue
        for path in existing.glob("*-bench.md"):
            if path not in wanted:
                stale.append(f"{path.relative_to(ROOT).as_posix()} (orphaned)")
                if not check:
                    path.unlink()

    for path, render in GENERATED.items():
        keep = _preserved(path)
        text = render()
        if keep:
            start = text.find(KEEP_BEGIN) + len(KEEP_BEGIN)
            end = text.find(KEEP_END)
            text = text[:start] + "\n" + keep + "\n" + text[end:]
        if not is_current(path, text):
            stale.append(str(path.relative_to(ROOT).as_posix()))
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                write_lf(path, text)
    return stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if any generated file is stale")
    args = parser.parse_args()

    stale = build(check=args.check)
    if args.check:
        if stale:
            print("Generated documentation is out of date:")
            for name in stale:
                print(f"  {name}")
            print("\nRun: uv run python tools/build_docs.py")
            return 1
        print("Generated documentation is up to date.")
        return 0

    if stale:
        print("Rewrote:")
        for name in stale:
            print(f"  {name}")
    else:
        print("Nothing to do.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
