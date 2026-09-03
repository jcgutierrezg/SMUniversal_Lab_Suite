---
type: index
title: "SMUniversal Lab Suite — documentation"
---

# Documentation

The index for whoever is changing the code. The repository's entry point is
[README.md](../README.md), which routes and holds nothing else; this page is
where it sends you.

**Written for GitHub.** Plain Markdown with relative links, so every
link works in the browser, in any editor, and through pandoc for an
eventual PDF.

It also opens as an Obsidian vault, which is an optional convenience
rather than the intended reader. Two settings matter if you use it, both
under *Settings -> Files and links*: turn **"Use Wikilinks" off**, and
set **New link format** to *Relative path to file*. Otherwise Obsidian
rewrites links on index to its own format, which breaks them on GitHub
and shows up as files modifying themselves behind your back.

`.obsidian/` is gitignored - vault config is per-person.

## Two audiences, two folders

| Folder | Audience | Answers |
|---|---|---|
| `docs/` | whoever is changing the code | *why is it built this way?* |
| `bench/` | whoever is taking a measurement | *what does this mean for my data?* |

`bench/` is generated from `docs/`, so the two cannot disagree. Never
edit a file under `bench/` — it says so at the top of each one.

## Three kinds of note, and they are never mixed

This is the organising rule the old documents lacked, and the reason a
1,846-line `HANDOFF.md` happened. A log grows forever by design; put one
inside a reference document and the reference grows forever too, and a
reader can no longer tell which sentences are current and which are
history.

| Kind | Edited how | Answers | Lives in |
|---|---|---|---|
| **Reference** | rewritten in place when reality moves; carries no dates | *what is true now?* | `instruments/`, `experiments/`, `rules/`, `faults/`, `architecture/` |
| **Log** | append-only, never edited, always dated | *why did it change, and when?* | `CHANGELOG.md` |
| **State** | short, high churn | *what next?* | `open/`, `plan.md` |

The analogy: a lab notebook and a datasheet. The notebook is dated and
never corrected. The datasheet is corrected in place and carries no
history, but it cites the notebook. One document that is both has to be
read chronologically to be trusted, which is what went wrong.

**There is a fourth kind, and it is not written down here at all: live
branch state.** A checked-in file naming the branch the work is on is stale
the moment that branch merges, and a reader cannot tell a stale sentence from
a current one. It has already misled two readers in opposite directions —
one of them from remote-tracking refs a checkout had never pruned. Ask the
remote (`git fetch --prune`), not a Markdown file.

## Two things worth knowing before you change anything

**The recurring hazard here is not code that crashes.** It is code that
produces a plausible number that is wrong — half of the faults this project
has found produced clean data and no error. [Faults](faults/_index.md) is the
list, and it is worth reading before writing a driver rather than after.

**A clean result is not the same as a correct one.** One of those faults was
a single ranging command silently resetting an instrument's compliance by
five orders of magnitude: no error, a clean checkup across most of the bench,
and found only because an unrelated later command tripped over the damage.
Where a check reports "none", ask whether anything actually looked. Several
things here now distinguish *verified* from *unverified* for exactly that
reason — [checkup owed](open/checkup-owed.md) is the one to read before
trusting a driver, and it separates a driver whose code has moved since its
last checkup from one that has never met its instrument.

## Where things are

- **[Instruments](instruments/_index.md)** — one note per driver: identity,
  envelope, the reset defaults that had to be overridden, the decisions
  behind it, and what it means for your data.
- **[Experiments](experiments/_index.md)** — one note per measurement:
  where it came from, what it computes, what the saved file holds.
- **[House rules](rules/_index.md)** — the requirements every experiment
  meets. Numbered, and the numbers are permanent.
- **[Faults](faults/_index.md)** — the checklist of mistakes that have
  turned up in every ported script. Read before writing a driver.
- **[Architecture](architecture/_index.md)** — what each module in `core/`,
  `drivers/`, `devices/` and `tools/` is for, and what breaks without it.
- **[Workflow](workflow/_index.md)** — patches, tests, CI, and the whole
  procedure for adding an SMU.
- **[Plan](plan.md)** — status, the next wave, what is undecided.
- **[Open](open/_index.md)** — what is unverified, what is owed, what is
  still undecided.

## The parts nobody writes

Four pages are computed rather than typed, because each of them was
previously a hand-maintained claim that went stale without anyone
noticing:

| Page | Derived from |
|---|---|
| `bench/choosing-an-smu.md` | driver `LIMITS` and capability declarations |
| [checkup-owed](open/checkup-owed.md) | `last_bench` in each note vs `git log` on the driver |
| [deviation-index](reference/deviation-index.md) | `# DEVIATION n` markers in the source |
| [review-index](reference/review-index.md) | the code review's headings, and where each cited section's reasoning now lives |
| the generated block in each instrument note | the driver class |

Rebuild them with:

```powershell
uv run python tools/build_docs.py
```

`tests/test_docs.py` fails if a committed copy disagrees with a fresh
build, so a hand-edit cannot survive a pull request.
