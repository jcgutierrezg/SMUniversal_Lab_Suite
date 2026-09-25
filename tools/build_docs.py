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
instrument" thirty-six hours after a wave modified all nine.

So the derived pages are not written. They are computed from the two
things that cannot drift from the code: the driver classes themselves,
and git history.

    drivers/*.py  LIMITS + capability declarations
          |
          +--> instrument note frontmatter (generated block)
          |          |
          |          +--> docs/guide/instruments/index.md      comparison matrix
          |          +--> docs/guide/instruments/<name>.md     "at a glance" block
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
Judgement. `docs/guide/instruments/index.md` carries a hand-written guidance
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
#: The installed namespace. Driver paths - a note's `driver` field, the
#: fingerprint inputs - are relative to this, as `core.provenance` holds
#: them, so they mean the same files in a checkout and an installed copy.
PKG = ROOT / "smuniversal_lab_suite"
sys.path.insert(0, str(ROOT))

from smuniversal_lab_suite.core import (
    provenance,  # noqa: E402  (needs the path insert above)
)

DOCS = ROOT / "docs"
GUIDE = DOCS / "guide"
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

#: A relative Markdown link to a page: label, path, optional fragment.
MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+\.md)(#[^)]*)?\)")

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
    ".uv-cache", ".cache", ".idea", ".vscode", "site",
    "checkups", "tmp", "temp",
})

#: Committed, tracked, and still not documentation: directories holding
#: a tool's own output. Excluded from `owned_files` rather than from the
#: walk, because unlike the names above these *are* in the index.
GENERATED_DIRS = frozenset({"graphify-out"})


def owned_files(pattern: str = "*", root: Path = ROOT) -> list[Path]:
    """Every file under `root` matching `pattern` that the project owns.

    `root.rglob(pattern)` answers a different question - what is *lying
    in the directory* - and the two diverged twice. A `.uv-cache/` left
    inside the checkout contributed a Pygments source file to a
    generated page; agent worktrees under `.claude/`
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
    return sorted(path for path in listed if not _is_generated(path, root))


def _is_generated(path: Path, root: Path) -> bool:
    """Is this a tool's output that happens to be committed?

    Tracked and still not the project's prose. `graphify-out/` holds a
    knowledge graph built from this repository: a report, a manifest and
    saved queries, committed so the graph travels with the branch. Its
    text is written by that tool, so the documentation lints - frontmatter,
    stated counts, link shapes - would be checking the tool's output
    against rules the tool has never read, and a rebuild of the graph
    would turn the suite red without a line of prose having changed.
    """
    return path.relative_to(root).parts[0] in GENERATED_DIRS


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
    from smuniversal_lab_suite.drivers.base_instrument import (
        BaseInstrument,
    )
    from smuniversal_lab_suite.drivers.base_smu import BaseSMU
    from smuniversal_lab_suite.drivers.registry import KNOWN_DRIVERS

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
            "driver": str(Path(module.__file__).relative_to(PKG).as_posix()),
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
            # A driver that inherits the base stub cannot report a trip.
            # `False` is right for an electronic load, which has no
            # compliance to trip, and for the same reason it is right
            # for an SMU that never wired the query up: nothing
            # reported that anything was fine.
            "compliance_trip": (
                cls.compliance_tripped is not BaseInstrument.compliance_tripped
            ),
            # Which fleet, so a generated page can render the facts that
            # apply to it and the chooser can decline to rank a load
            # against instruments that do a different job.
            "fleet": "smu" if issubclass(cls, BaseSMU) else "load",
        }
    return facts


# --------------------------------------------------------------------------
# Facts from git
# --------------------------------------------------------------------------

def bench_status(meta: dict) -> tuple[str, str]:
    """Derive (status, reason) for one driver. Never hand-written.

    Five states:

    * `unavailable` - there is no access to the instrument, so no
      checkup can be run at all. Declared by hand in `bench_access`,
      because whether a lab can get at a piece of hardware is not
      something any file in this repository can work out.
    * `unverified` - this driver has never met its instrument, and
      nothing says it could not.
    * `failing` - it was checked, the code has not moved since, and the
      checkup **failed**. A date alone could not say this, so a checkup
      that failed used to render exactly like one that passed.
    * `stale` - it was checked, and the code has changed since. The
      checkup's answers were about code that no longer exists.
    * `commissioned` - checked, passed, unchanged since.

    `unavailable` was split out of `unverified` on 2026-09-04. The 2450
    sat in the checkup-owed table reading "never run against its
    instrument" beside seven drivers that genuinely are owed a session,
    which is a to-do list containing one item nobody can ever do. A
    reader cannot tell "nobody has got to this" from "nobody can", and
    the difference decides whether to wait for the row to clear.

    Staleness is a comparison of **content**, not of commit dates. See
    `core.provenance.code_fingerprint` for why: a commit date is rewritten
    by `git am`, by a rebase, and by a squash-merge, so the date rule
    reported a change when nothing had changed and turned `main` red on
    the first CI run after a merge.
    """
    if meta.get("bench_ever") is not True:
        # Checked before `unverified` and not after: an instrument
        # nobody can reach has also never been checked, and reporting
        # the reachable-sounding half of that is what this splits.
        no_access = meta.get("bench_access")
        if no_access:
            return "unavailable", str(no_access)
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
        provenance.code_paths_for(meta["driver"],
                                  fleet=meta.get("fleet", "smu")),
        root=str(PKG))
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
             if p.name != "index.md"}
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
    for scale, prefix in ((1e-12, "p"), (1e-9, "n"), (1e-6, "µ"),
                          (1e-3, "m"), (1.0, ""), (1e3, "k")):
        # A hair under the next prefix, so 1e-6 - which is 1000 nA in
        # floating point by a rounding error - prints as 1 uA.
        if abs(value) < scale * 1000 * (1 - 1e-9):
            return f"{value / scale:g} {prefix}{unit}"
    return f"{value:g} {unit}"


def guide_notes() -> dict[Path, tuple[dict, str]]:
    """The instruments the user guide shows: real hardware, less any held
    out of the guide with `in_user_guide: false` - an instrument nobody
    here can reach, whose page would be advice nobody can follow."""
    return {p: v for p, v in load_notes(physical_only=True).items()
            if v[0].get("in_user_guide") is not False}


def _driver_class(meta: dict):
    from smuniversal_lab_suite.drivers.registry import KNOWN_DRIVERS
    return {cls.__name__: cls for cls in KNOWN_DRIVERS}[meta["driver_class"]]


def measurement_windows() -> list[tuple[str, list]]:
    """(short name, hosted experiment classes) per measurement window."""
    from smuniversal_lab_suite.core.launcher import PLOTTER, WINDOWS
    return [(re.split(r" - | \(", label)[0],
             spec if isinstance(spec, list) else [spec])
            for label, spec in WINDOWS.values() if spec != PLOTTER]


def runs_window(driver, hosted) -> bool:
    """Would every experiment in a window accept this driver in every
    role? The same declarations the connection panel checks at Connect -
    each experiment's `ROLE_REQUIRES` and each driver's `supports_*()` -
    so a **no** in the guide is a refusal at the bench."""
    return all(getattr(driver, f"supports_{need}")()
               for experiment in hosted
               for needs in experiment.ROLE_REQUIRES.values()
               for need in needs)


#: How each checkup status reads in a table. `fails` is louder than
#: `re-check` on purpose: stale means nobody has confirmed it lately;
#: failing means somebody has, and it did not work.
STATUS_MARK = {"commissioned": "yes", "stale": "**re-check**",
               "failing": "**fails**", "unverified": "**never**",
               "unavailable": "**no access**", "unknown": "?"}


def _short_reading(text: str | None) -> str:
    """The figure from a `reading_time`, without the working after it:
    "14.4 ms at NPLC 0.01 (its declared minimum), ..." -> "14.4 ms at
    NPLC 0.01". The whole sentence stays in the developer note."""
    if not text:
        return "not measured"
    return re.split(r"\s*[,(]|\s+-\s", text, maxsplit=1)[0].strip()


def _smallest_current(driver) -> str:
    """The lowest current range - and, where the instrument measures on a
    range below any it can source or limit on, both."""
    lowest = min(driver.LIMITS.current_ranges)
    floor = getattr(driver, "MEASURE_LOW_RANGE_FLOOR_A", None)
    if floor and floor < lowest:
        return f"{_si(floor, 'A')} measuring, {_si(lowest, 'A')} sourcing"
    return _si(lowest, "A")


def instrument_facts(meta: dict) -> list[tuple[str, str]]:
    """The operator's facts about one instrument, as (label, value) rows.

    One list for both the matrix on the instruments page and the "at a
    glance" block on each instrument's own page, so the two cannot say
    different things. Everything is read from the driver class and the
    note's frontmatter; nothing here is typed per instrument.
    """
    driver = _driver_class(meta)
    limits = driver.LIMITS
    sources = getattr(driver, "CAN_SOURCE", True)
    corners = sorted(limits.power_envelope, key=lambda c: c[0])
    nplc = getattr(driver, "NPLC_RANGE", None)
    fixed = getattr(driver, "FIXED_SENSE", None)

    if meta["remote_sense_control"]:
        sensing = "2- or 4-wire, switchable"
    elif fixed:
        sensing = fixed.split(" (")[0] + (
            " (hardwired)" if "hardwired" in fixed else "")
    else:
        sensing = "fixed"
    if not sources:
        compliance = "n/a"
    else:
        compliance = "yes" if meta["compliance_trip"] else "no"

    facts = [
        ("Kind", "SMU" if sources else "Electronic load - sinks only"),
        ("Maximum voltage", _si(meta["max_voltage_v"], "V")),
        ("Maximum current", _si(meta["max_current_a"], "A")),
        # Most SMUs cannot give full voltage and full current at once;
        # the corners are what they can give together.
        ("Power limit", "up to " + " or ".join(
            f"{_si(i, 'A')} at {_si(v, 'V')}" for v, i in corners)
            if len(corners) > 1 else "none - full V and I together"),
        ("Smallest current range", _smallest_current(driver)),
        ("Smallest voltage range", _si(min(limits.voltage_ranges), "V")),
        ("Fastest reading", _short_reading(meta.get("reading_time"))),
        ("Integration (NPLC)", f"{nplc[0]:g} to {nplc[1]:g}"
         if nplc else "n/a"),
        ("Sweep runs on", "the instrument" if meta["sweep_kind"] == "hardware"
         else "the PC"),
        ("Sensing", sensing),
        ("Over-voltage protection", "yes" if meta["ovp"] else "no"),
        ("Can disconnect when off (high-Z)",
         "yes" if meta["high_z_off"] else "no"),
        ("Says when it hits compliance", compliance),
        ("Connection", meta.get("connection") or "not known"),
        ("Checked against the instrument",
         STATUS_MARK[bench_status(meta)[0]]),
    ]
    for name, hosted in measurement_windows():
        facts.append((f"Runs {name}",
                      "yes" if runs_window(driver, hosted) else "**no**"))
    facts.append(("Choose it for", meta.get("best_for") or "-"))
    return facts


def render_chooser() -> str:
    """The comparison matrix, plus a preserved block of human guidance.

    Features as rows and instruments as columns: nine narrow columns
    read better than twenty wide ones, and a row is the question an
    operator comes with - which of these reaches 3 A, which measures
    below a nanoamp.
    """
    notes = sorted(guide_notes().items(),
                   key=lambda item: (item[1][0].get("fleet", "smu") != "smu",
                                     item[1][0]["title"]))
    columns = [(f"[{meta['title']}]({path.stem}.md)", instrument_facts(meta))
               for path, (meta, _body) in notes]
    labels = [label for label, _value in columns[0][1]]

    head = "| | " + " | ".join(title for title, _facts in columns) + " |"
    sep = "|---|" + "---|" * len(columns)
    rows = []
    for index, label in enumerate(labels):
        cells = [dict(facts)[label] for _title, facts in columns]
        rows.append(f"| **{label}** | " + " | ".join(cells) + " |")

    return (
        f"{BANNER}\n"
        "# Instruments\n\n"
        "Every instrument the suite can drive, side by side. Each name "
        "opens its own page: what to choose it for, where to look "
        "elsewhere, and what to know at the bench.\n\n"
        "Everything in the table is read from the software's own "
        "declarations about each instrument, so it cannot disagree with "
        "what the windows will let you do.\n\n"
        # A class of its own, for a denser type size and labels kept to
        # one line - nine instruments side by side do not fit otherwise.
        '<div class="instrument-matrix" markdown>\n\n'
        f"{head}\n{sep}\n" + "\n".join(rows) + "\n\n</div>\n\n"
        "**Read *Checked against the instrument* first.** *re-check* "
        "means the software has changed since it was last tried on that "
        "instrument: it is probably fine, but nobody has confirmed it - "
        "see [Running a checkup](../good-data/running-a-checkup.md). "
        "*fails* means it was tried and did not pass; read the "
        "instrument's page before using it. *never* means it has not met "
        "the real thing.\n\n"
        "**Fastest reading is not a ranking.** Each figure is at that "
        "instrument's own shortest integration time, and those differ a "
        "thousandfold - so a smaller number buys less averaging, not the "
        "same quality faster. The miniSMU's integration is an equivalent "
        "figure from oversampling rather than a true mains-cycle count, "
        "and rejects mains hum less well than the same number on the "
        "others.\n\n"
        "**A no in a Runs row is refused at Connect**, before anything "
        "is switched on, and the window says why.\n\n"
        "## Connecting a GPIB instrument from a laptop\n\n"
        "The GPIB instruments reach the PC through a GPIB-USB adapter. "
        "On the lab PCs they appear under the **VISA** connection, "
        "because National Instruments' GPIB software is installed there. "
        "On a computer without it - typically a laptop, when an "
        "instrument is carried somewhere outside the labs - choose **NI "
        "GPIB-HS** as the connection instead, which drives the adapter "
        "directly. The adapter needs a one-time driver change on that "
        "computer first; see "
        "[the direct GPIB transport](../../architecture/direct-gpib-usb-hs.md)."
        "\n\n"
        "---\n\n"
        f"{KEEP_BEGIN}\n"
        "## Which instrument for which measurement\n\n"
        "*(Written by hand. Everything above is generated; this section is "
        "preserved across rebuilds.)*\n"
        f"{KEEP_END}\n"
    )


def render_checkup_owed() -> str:
    """Which drivers need a bench session, and why.

    `unavailable` is listed apart from the rest. This page is a to-do
    list, and a row for an instrument nobody can reach is not a task -
    it is a standing fact that will never clear. Left in the table it
    read like the oldest unattended item on the list.
    """
    lines = []
    blocked = []
    for path, (meta, _) in sorted(load_notes(physical_only=True).items()):
        status, reason = bench_status(meta)
        if status == "commissioned":
            continue
        row = (f"| {meta.get('title') or path.stem} | `{meta['driver']}` | "
               f"{status} | {reason} |")
        (blocked if status == "unavailable" else lines).append(row)

    body = "\n".join(lines) if lines else "| - | - | - | nothing owed |"
    no_access = ("\n## No checkup is possible\n\n"
                 "Not owed, and not waiting for anyone. There is no access "
                 "to these instruments, so no session can be run - the "
                 "drivers are kept working offline and the rows below will "
                 "not clear.\n\n"
                 "| Instrument | Driver | Status | Why |\n|---|---|---|---|\n"
                 + "\n".join(blocked) + "\n") if blocked else ""
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
        f"{no_access}"
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
# The user guide's instrument pages
#
# Written by hand - what to choose the instrument for, when to look
# elsewhere, what to know at the bench - around one generated block of
# facts, the same facts as the matrix. The developer note keeps the
# history: what was wrong with older files, and when it was put right.
# An operator choosing an instrument today needs neither.
# --------------------------------------------------------------------------

GLANCE_BEGIN = re.compile(r"<!-- generated:glance (\S+) -->\n")
GLANCE_END = "<!-- /generated:glance -->"


def guide_page_path(note: Path) -> Path:
    return GUIDE / "instruments" / note.name


def status_warning(meta: dict) -> str:
    """The warning an instrument page opens with while its driver is not
    confirmed against the instrument - empty once it is."""
    status, reason = bench_status(meta)
    if status == "failing":
        # First, and worded as a present-tense fact rather than a
        # caution. The other two say "nobody has checked"; this one says
        # "somebody has, and it did not pass", which is a different
        # instruction to the person standing at the fixture.
        return ("> **This instrument fails its own checkup.** "
                f"{reason.capitalize()}. Treat any measurement it "
                "produces as unconfirmed.\n\n")
    if status == "stale":
        return ("> **The software for this instrument has changed since "
                f"it was last checked against it.** {reason.capitalize()}. "
                "The measurement may be fine; nobody has confirmed it. "
                "Run a checkup first - see [Running a checkup]"
                "(../good-data/running-a-checkup.md).\n\n")
    if status == "unverified":
        return ("> **This instrument has never been checked against the "
                f"software.** {reason.capitalize()}. Nothing on this page "
                "has been confirmed at a bench.\n\n")
    if status == "unavailable":
        return ("> **There is no access to this instrument, so no checkup "
                f"can be run.** {reason.capitalize()}.\n\n")
    return ""


def render_glance(meta: dict) -> str:
    rows = "\n".join(f"| {label} | {value} |"
                     for label, value in instrument_facts(meta)
                     if label not in ("Kind",))
    return (f"{status_warning(meta)}"
            "| At a glance | |\n|---|---|\n"
            f"{rows}\n\n"
            "How it compares with the others: [Instruments](index.md).\n")


def instrument_pages() -> dict[Path, str]:
    """Each guide instrument page with its glance block rebuilt.

    Raises rather than skipping: an instrument the guide should show
    with no page, a page naming an instrument that is gone, and a page
    without its block are each a page an operator would find wrong or
    not find at all.
    """
    notes = {note.stem: (note, meta) for note, (meta, _body)
             in guide_notes().items()}
    problems = []
    out = {}
    for stem, (note, meta) in notes.items():
        page = guide_page_path(note)
        if not page.exists():
            problems.append(f"{page.relative_to(ROOT).as_posix()} is missing")
            continue
        text = page.read_text(encoding="utf-8")
        begin = f"<!-- generated:glance {stem} -->\n"
        start = text.find(begin)
        end = text.find(GLANCE_END, start)
        if start == -1 or end == -1:
            problems.append(f"{page.name} has no closed glance block for "
                            f"{stem}")
            continue
        out[page] = (text[:start] + begin + render_glance(meta)
                     + text[end:])
    for page in sorted((GUIDE / "instruments").glob("*.md")):
        for stem in GLANCE_BEGIN.findall(page.read_text(encoding="utf-8")):
            if stem not in notes:
                problems.append(f"{page.name} describes {stem}, which the "
                                "guide does not show")
    if problems:
        raise ValueError("instrument pages: " + "; ".join(problems))
    return out


# --------------------------------------------------------------------------
# README sections the user guide repeats
#
# How to install is in two places on purpose: the README, where anyone
# landing on the repository looks, and the guide's Getting started,
# where an operator looks. Two hand-kept copies would drift, so the
# guide's is copied from the README's, section by section.
# --------------------------------------------------------------------------

README = ROOT / "README.md"
README_BEGIN = re.compile(r"<!-- generated:readme (.+?) -->\n")
README_END = "<!-- /generated:readme -->"
REPO_BLOB = "https://github.com/jcgutierrezg/SMUniversal_Lab_Suite/blob/main/"
_LINK_TARGET = re.compile(r"(\]\()([^)\s#]+)(#[^)\s]*)?(\))")


def readme_section(heading: str) -> str:
    """The body of README's `### heading`, up to the next heading."""
    text = README.read_text(encoding="utf-8")
    start = text.find(f"\n### {heading}\n")
    if start == -1:
        raise ValueError(f"README.md has no '### {heading}' section")
    body = text[start + len(heading) + 6:]
    ends = [i for i in (body.find("\n## "), body.find("\n### ")) if i != -1]
    return body[:min(ends)] if ends else body


def _relink(text: str, page: Path) -> str:
    """README's links are from the repository root. On a guide page, one
    into docs/ becomes relative to the page, and one to anything else -
    a tool, a test - points at GitHub, since the site publishes only
    docs/."""
    def repl(match: re.Match) -> str:
        target = match.group(2)
        if re.match(r"[a-z][a-z0-9+.-]*:", target):
            return match.group(0)
        resolved = (ROOT / target).resolve()
        try:
            resolved.relative_to(DOCS.resolve())
        except ValueError:
            new = REPO_BLOB + target
        else:
            new = Path(os.path.relpath(resolved, page.parent)).as_posix()
        return f"{match.group(1)}{new}{match.group(3) or ''}{match.group(4)}"
    return _LINK_TARGET.sub(repl, text)


def readme_pages() -> dict[Path, str]:
    """Each guide page holding a readme block, with the blocks rebuilt.

    A plain walk of the guide folder, for the same reason as
    `instrument_pages`: rendering must not ask git anything.
    """
    out = {}
    for page in sorted(GUIDE.rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        headings = README_BEGIN.findall(text)
        if not headings:
            continue
        for heading in headings:
            begin = f"<!-- generated:readme {heading} -->\n"
            start = text.find(begin)
            end = text.find(README_END, start)
            if end == -1:
                raise ValueError(f"{page.name}: readme block {heading!r} "
                                 f"is not closed with {README_END}")
            body = _relink(readme_section(heading).strip("\n"), page)
            text = text[:start] + begin + body + "\n" + text[end:]
        out[page] = text
    return out


def experiment_notes() -> dict[Path, tuple[dict, str]]:
    return {p: read_frontmatter(p) for p in sorted(EXPERIMENTS.glob("*.md"))
            if p.name != "index.md"}


GENERATED = {
    GUIDE / "instruments" / "index.md": render_chooser,
    DOCS / "open" / "checkup-owed.md": render_checkup_owed,
    DOCS / "reference" / "deviation-index.md": render_deviation_index,
}


# --------------------------------------------------------------------------
# Site navigation
#
# The site's `nav` must name every page, and a list typed by hand is a
# claim about what exists - the kind this module was written to stop
# people making. So the tabs are chosen here, by hand, and what goes
# under each is read from the folder.
# --------------------------------------------------------------------------

SITE_CONFIG = ROOT / "mkdocs.yml"

#: The site's two tabs, one per audience, and the sections under each
#: in reading order. The user guide is for somebody running a
#: measurement who neither knows nor cares how the suite is built; the
#: developer tab is everything else. Each tab opens on its own index
#: page, and each section is a page or a folder under `docs/`.
NAV_TABS = (
    ("User guide", "index.md", (
        ("Getting started", "guide/getting-started"),
        ("Windows", "guide/windows"),
        ("Instruments", "guide/instruments"),
        ("Good data", "guide/good-data"),
        ("Troubleshooting", "guide/troubleshooting.md"),
    )),
    ("Developer", "developer/index.md", (
        ("Instruments", "instruments"),
        ("Experiments", "experiments"),
        ("House rules", "rules"),
        ("Faults", "faults"),
        ("Architecture", "architecture"),
        ("Workflow", "workflow"),
        ("Reference", "reference"),
        ("Open", "open"),
        ("Plan", "plan.md"),
    )),
)

#: The changelog stays at the repository root, where a log belongs, and
#: its links are written from there - so the site links out to it.
CHANGELOG_URL = ("https://github.com/jcgutierrezg/SMUniversal_Lab_Suite"
                 "/blob/main/CHANGELOG.md")

INDEX_LINK = re.compile(r"\]\(([^)#\s]+\.md)")


def _nav_order(folder: Path, children: list[Path]) -> list[Path]:
    """The folder's pages and subfolders, in the order its index links them.

    A folder's `index.md` already puts its pages in the order a reader
    should meet them, so the navigation follows it rather than
    inventing a second order. Whatever the index does not link comes
    after, alphabetically - which for `rules/` and `faults/` is their
    permanent number.
    """
    ordered: list[Path] = []
    index = folder / "index.md"
    if index.exists():
        for rel in INDEX_LINK.findall(index.read_text(encoding="utf-8")):
            target = (folder / rel).resolve()
            try:
                first = target.relative_to(folder).parts[0]
            except ValueError:
                continue
            child = folder / first
            if child in children and child not in ordered:
                ordered.append(child)
    return ordered + sorted(c for c in children if c not in ordered)


def _nav_section(folder: Path, pages: list[Path], depth: int) -> list[str]:
    pad = "  " * depth
    lines = []
    index = folder / "index.md"
    if index in pages:
        lines.append(f"{pad}- {index.relative_to(DOCS).as_posix()}")
    children = sorted({folder / p.relative_to(folder).parts[0]
                       for p in pages if p != index})
    for child in _nav_order(folder, children):
        if child.suffix == ".md":
            lines.append(f"{pad}- {child.relative_to(DOCS).as_posix()}")
            continue
        inner = [p for p in pages if child in p.parents]
        title = child.name.replace("-", " ").capitalize()
        if (child / "index.md").exists():
            title = read_frontmatter(child / "index.md")[0].get("title", title)
        lines.append(f"{pad}- {_dump_scalar(title)}:")
        lines += _nav_section(child, inner, depth + 1)
    return lines


def render_nav() -> str:
    """The `nav:` block for `mkdocs.yml`, from the pages that exist.

    Raises on a page outside every tab rather than leaving it out: a
    page missing from the navigation is published but unreachable, and
    nothing about the build says so.
    """
    pages = [p for p in owned_files("*.md", DOCS)]
    lines = ["nav:"]
    placed: set[Path] = set()
    for tab, home, sections in NAV_TABS:
        lines += [f"  - {tab}:", f"    - {home}"]
        placed.add(DOCS / home)
        for title, entry in sections:
            target = DOCS / entry
            if target.suffix == ".md":
                lines.append(f"    - {title}: {entry}")
                placed.add(target)
                continue
            inner = [p for p in pages if target in p.parents]
            if not inner:
                continue
            lines.append(f"    - {title}:")
            lines += _nav_section(target, inner, 3)
            placed.update(inner)
    lines.append(f"  - Changelog: {CHANGELOG_URL}")

    orphans = sorted(p.relative_to(DOCS).as_posix()
                     for p in pages if p not in placed)
    if orphans:
        raise ValueError(
            "these pages are under no tab in NAV_TABS, so the site would "
            "publish them with no way to reach them: " + ", ".join(orphans))
    return "\n".join(lines)


def render_site_config() -> str:
    """`mkdocs.yml` with its generated `nav` block rebuilt in place."""
    text = SITE_CONFIG.read_text(encoding="utf-8")
    start, end = text.find(GEN_BEGIN), text.find(GEN_END)
    if start == -1 or end == -1:
        raise ValueError(
            f"{SITE_CONFIG.name} is missing the generated-block markers "
            f"({GEN_BEGIN!r} / {GEN_END!r})")
    return (text[:start] + GEN_BEGIN + "\n" + render_nav() + "\n"
            + text[end:])


GENERATED[SITE_CONFIG] = render_site_config


def build(check: bool = False) -> list[str]:
    """Write (or verify) every generated file. Returns what was stale."""
    stale = sync_frontmatter(write=not check)

    for page, text in {**instrument_pages(), **readme_pages()}.items():
        if not is_current(page, text):
            stale.append(str(page.relative_to(ROOT).as_posix()))
            if not check:
                write_lf(page, text)

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
