# Start here

**The documentation lives in `docs/` and `bench/`.** This file is a
router, not content.

| You want to | Read |
|---|---|
| take a measurement | `bench/README.md` |
| know which instrument to use | `bench/choosing-an-smu.md` |
| change the code | `docs/_index.md` |
| add an SMU | `docs/workflow/adding-an-smu.md` |
| know what is next | `docs/plan.md` |
| check every instrument at once | `docs/workflow/commissioning-round.md` |
| know why something changed | `CHANGELOG.md` |

`docs/` is an Obsidian vault and also plain Markdown, so it reads fine
on GitHub and in any editor.

## Work in flight

**`main` is not the whole picture right now.** Wave 8 is on branch
**`wave8`** and is not merged. It carries the transport work - a link
that stops answering now stops the run instead of returning replies that
belong to the previous command - and a documentation accuracy pass.

```powershell
git fetch origin
git checkout wave8
```

`docs/plan.md` is authoritative for what has landed and what is parked.
Read it before proposing anything; this table is a router and goes stale
faster than the plan does.

**Every instrument is owed a checkup.** Wave 8 changed every driver, so
`bench_code` no longer matches the running code anywhere and
`docs/open/checkup-owed.md` reports the whole fleet as stale. That is
the derivation working, not a fault - but it means no driver currently
carries a commissioning guarantee, and the next bench session is a full
round rather than a spot check.

## Two things worth knowing before you change anything

**Some pages are generated.** Anything under `bench/instruments/`,
`bench/experiments/`, `bench/choosing-an-smu.md`, and three files under
`docs/reference/` and `docs/open/` are built by
`tools/build_docs.py` from the notes and from the code. Editing one by
hand fails the test suite. Rebuild with:

```powershell
uv run python tools/build_docs.py
```

**The recurring hazard here is not code that crashes.** It is code that
produces a plausible number that is wrong — half of the faults this
project has found produced clean data and no error. `docs/faults/` is
the list, and it is worth reading before writing a driver rather than
after.

**A clean result is not the same as a correct one.** The most recent
fault — a single ranging command silently resetting an instrument's
compliance by five orders of magnitude — raised no error, produced a
clean checkup on most of the bench, and was found only because an
unrelated later command tripped over the damage. Where a check reports
"none", ask whether anything actually looked. Several here now
distinguish *verified* from *unverified* for exactly that reason.

## Running it

```powershell
uv sync
uv run python main.py
uv run python run_tests.py --all
```

Tests go through `run_tests.py`, never plain `pytest` — `tests/README.md`
explains why.
