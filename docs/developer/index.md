---
type: index
title: "SMUniversal Lab Suite — documentation"
---

# Documentation

The index for whoever is changing the code. The repository's entry point is
[README.md](https://github.com/jcgutierrezg/SMUniversal_Lab_Suite#readme),
which routes and holds nothing else; this page is where it sends you.

**Written for the documentation site.** `docs/` is the source of the
[published site](https://jcgutierrezg.github.io/SMUniversal_Lab_Suite/):
plain Markdown with relative links, built by Zensical on every merge to
`main`. The same links also work when a page is read on GitHub. How to
build and preview it: [the documentation site](../workflow/documentation-site.md).

## Two audiences, two tabs

| Tab | Where | Audience | Answers |
|---|---|---|---|
| **User guide** | `docs/index.md`, `docs/guide/` | whoever is taking a measurement, and neither knows nor cares how the suite is built | *how do I run this, and what does this mean for my data?* |
| **Developer** | this page, and every other folder under `docs/` | whoever is changing the code | *why is it built this way?* |

Much of the user guide is generated, so it cannot disagree with the code
or with these notes:

- **Control tables** on the window pages are the windows' own tooltips,
  read out by `tools/build_guide.py`. To change one, change the tooltip.
- **"What this means for your data"** sections are the `<!-- bench -->`
  sections of the instrument and experiment notes, copied by
  `tools/build_docs.py`.
- **The instrument pages and tables** are built from the drivers.
- **Screenshots** are taken from the real windows by
  `tools/capture_screens.py`.

The rest of each window page is written by hand. A generated file says
so in its first line; a generated block inside a hand-written page sits
between `generated:` markers. See
[the documentation site](../workflow/documentation-site.md#the-user-guide).

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
has found produced clean data and no error. [Faults](../faults/index.md) is the
list, and it is worth reading before writing a driver rather than after.

**A clean result is not the same as a correct one.** One of those faults was
a single ranging command silently resetting an instrument's compliance by
five orders of magnitude: no error, a clean checkup across most of the bench,
and found only because an unrelated later command tripped over the damage.
Where a check reports "none", ask whether anything actually looked. Several
things here now distinguish *verified* from *unverified* for exactly that
reason — [checkup owed](../open/checkup-owed.md) is the one to read before
trusting a driver, and it separates a driver whose code has moved since its
last checkup from one that has never met its instrument.

## Where things are

- **[Instruments](../instruments/index.md)** — one note per driver: identity,
  envelope, the reset defaults that had to be overridden, the decisions
  behind it, and what it means for your data.
- **[Experiments](../experiments/index.md)** — one note per measurement:
  where it came from, what it computes, what the saved file holds.
- **[House rules](../rules/index.md)** — the requirements every experiment
  meets. Numbered, and the numbers are permanent.
- **[Faults](../faults/index.md)** — the checklist of mistakes that have
  turned up in every ported script. Read before writing a driver.
- **[Architecture](../architecture/index.md)** — what each module in `core/`,
  `drivers/`, `devices/` and `tools/` is for, and what breaks without it.
- **[Workflow](../workflow/index.md)** — patches, tests, CI, and the whole
  procedure for adding an SMU.
- **[Plan](../plan.md)** — status, the next wave, what is undecided.
- **[Open](../open/index.md)** — what is unverified, what is owed, what is
  still undecided.

## The parts nobody writes

Four pages are computed rather than typed, because each of them was
previously a hand-maintained claim that went stale without anyone
noticing:

| Page | Derived from |
|---|---|
| `docs/guide/instruments/index.md` | driver `LIMITS` and capability declarations, and each experiment's `ROLE_REQUIRES` |
| [checkup-owed](../open/checkup-owed.md) | `bench_code` in each note vs a digest of the driver's contents |
| [deviation-index](../reference/deviation-index.md) | `# DEVIATION n` markers in the source |
| the generated block in each instrument note | the driver class |

Rebuild them with:

```powershell
uv run python tools/build_docs.py
```

`tests/test_docs.py` fails if a committed copy disagrees with a fresh
build, so a hand-edit cannot survive a pull request.
