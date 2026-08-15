---
type: index
title: "SMUniversal Lab Suite — documentation"
---

# Documentation

This folder is an Obsidian vault. It is also plain Markdown, so it reads
fine on GitHub and in any editor.

> **This is a skeleton.** The folders exist, the schema is enforced and
> the generators run, but almost nothing has been written into them yet.
> `HANDOFF.md`, `PORTING_NOTES.md`, `INSTRUMENTS.md` and `WAVE_PLAN.md`
> at the repository root are still the live documents until the
> remaining patches move their content here. See
> [[reference/migration-status]].

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

## Where things are

- **[[instruments/_index|Instruments]]** — one note per driver: identity,
  envelope, the reset defaults that had to be overridden, the decisions
  behind it, and what it means for your data.
- **[[experiments/_index|Experiments]]** — one note per measurement:
  where it came from, what it computes, what the saved file holds.
- **[[rules/_index|House rules]]** — the requirements every experiment
  meets. Numbered, and the numbers are permanent.
- **[[faults/_index|Faults]]** — the checklist of mistakes that have
  turned up in every ported script. Read before writing a driver.
- **[[architecture/_index|Architecture]]** — what each module in `core/`,
  `drivers/`, `devices/` and `tools/` is for, and what breaks without it.
- **[[workflow/_index|Workflow]]** — patches, tests, CI, and the whole
  procedure for adding an SMU.
- **[[open/_index|Open]]** — what is unverified, what is owed, what is
  still undecided.

## The parts nobody writes

Four pages are computed rather than typed, because each of them was
previously a hand-maintained claim that went stale without anyone
noticing:

| Page | Derived from |
|---|---|
| `bench/choosing-an-smu.md` | driver `LIMITS` and capability declarations |
| [[open/checkup-owed]] | `last_bench` in each note vs `git log` on the driver |
| [[reference/deviation-index]] | `# DEVIATION n` markers in the source |
| the generated block in each instrument note | the driver class |

Rebuild them with:

```powershell
uv run python tools/build_docs.py
```

`tests/test_docs.py` fails if a committed copy disagrees with a fresh
build, so a hand-edit cannot survive a pull request.
