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
| know why something changed | `CHANGELOG.md` |

`docs/` is an Obsidian vault and also plain Markdown, so it reads fine
on GitHub and in any editor.

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

## Running it

```powershell
uv sync
uv run python main.py
uv run python run_tests.py --all
```

Tests go through `run_tests.py`, never plain `pytest` — `tests/README.md`
explains why.
