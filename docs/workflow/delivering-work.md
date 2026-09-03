---
type: reference
title: "Delivering work"
---

# Delivering work

**One conversation per wave.** Start it with:

> Wave N, <name>. Repo: https://github.com/jcgutierrezg/SMUniversal_Lab_Suite.
> Clone it — `git clone https://github.com/jcgutierrezg/SMUniversal_Lab_Suite.git` —
> rather than downloading a tarball, because confirming the base commit
> needs history. Check `HANDOFF.md` for the branch; it is `main` unless
> work is in flight. Read `docs/plan.md` for scope and `docs/faults/`
> before writing a driver. Deliver as a `.patch` against the confirmed
> base.

**Delivery is a `.patch` file**, applied with `git am` — not
`git apply`. A patch expresses deletions, renames and moves; a zip
cannot, which is how the orphaned `temp_panel.py` survived Wave 0b's zip
and got caught only by a test.

`git am` commits; `git apply` leaves the tree dirty. That difference is
load-bearing, because anything derived from `git log` — commissioning
staleness, provenance stamps, the report header — still reports
pre-patch values on an uncommitted tree, so a verification run that way
cannot fail. That gap shipped a CI failure once.

Confirm the base with `git fetch origin && git log --oneline -1
origin/<branch>`, never a plain `git log` — a branch tip that looked
right once cost a three-way merge conflict, and the one failed
application in Wave 0 was an assumed base.

`.patch` files are gitignored. Do not commit them.

**Tests run with `run_tests.py`, not plain `pytest`.** See
`tests/README.md` for why.

**Windows CI is load-bearing.** It found a `ZeroDivisionError` and
15.6 ms clock quantisation that a Linux container structurally cannot
reproduce. A red Windows job is information, not noise.

**Do not delete `_retry_tk_construction` in `tests/conftest.py`** on the
grounds that it never fires. It is instrumentation for an unresolved
intermittent fault; `tests/README.md` records what has been ruled out.

**Gather evidence before proposing fixes.** Wave 0 lost several days to
theorising about an intermittent Tcl failure and shipping fixes that
made it worse. Progress came only from diagnostics that could return
facts. If a fix is being proposed for a fault that cannot be reproduced
on demand, that is the signal to build a diagnostic instead.

---

## What CI is shaped like, and why each part of it is there

`.github/workflows/tests.yml`. Two jobs.

**`gates`** runs `ruff check` and `mypy` on one cell, not across the
matrix: neither reads the operating system, and a finding repeated four
times is still one finding.

**`test`** runs the suite on `windows-latest` and `ubuntu-latest`, on
one Python version.

| Choice | The constraint behind it |
|---|---|
| Windows in the matrix | It is the deployment platform, and Wave 0a found two defects Linux structurally cannot reproduce: `time.monotonic()` resolving to 15.6 ms, and a Tcl runtime that fails once too many Tk interpreters have been built in one process. |
| Ubuntu in the matrix | Fast, and it catches path-separator and case-sensitivity mistakes. |
| One Python version | Carrying a second that nothing is deployed on produces red cells nobody can act on. A newer interpreter is added here **first** and has to go green before `requires-python` and `.python-version` move — see [An accuracy that is an implementation detail](../faults/18-accidental-accuracy.md). |
| `actions/setup-python`, not uv's managed distribution | Every Windows `TclError` this project has seen came from a uv-managed interpreter under `AppData\Roaming`, reporting that Tcl files it can see are unreadable — with **errno 0**, which is what a filesystem filter driver returns, not what a missing file returns. `[tool.uv] python-preference = "system"` is the same workaround for developer and bench machines. |
| `fetch-depth: 0` | `tests/test_docs.py` compares each driver's note against `git log -1 -- <driver>`. On a shallow clone that query reports HEAD for every tracked file, so the whole fleet would read as stale. The test skips itself rather than lying when history is truncated; this is what stops it skipping in the one place it must run. |
| `PYTHONUNBUFFERED: "1"` | `print()` to a pipe is block-buffered and a whole run's output fits inside one buffer, so a step that never exits produces a completely empty log. |
| `timeout-minutes: 25` | A liveness bound, not a performance target. Without it a hung job runs to the platform default of six hours and reports a cancellation, which names nothing. |
| `uv sync --locked --extra bench` | `--locked` fails if `uv.lock` disagrees with `pyproject.toml`, so a dependency change that was never locked cannot merge. `--extra bench` is the environment a bench machine has; the absent-package case is tested in-process by `tests/test_optional_extras.py` rather than by a second matrix cell. |

The dependency audit is scheduled rather than run here. See
`.github/workflows/dependency-audit.yml`: an advisory published today
makes yesterday's green run wrong without anything in this repository
changing, and blocking a merge on that fails whoever opens the next PR
for something they did not do.

---

## Patch hygiene, learned by getting it wrong

A delivered patch once carried a `.venv` **symlink** pointing at a path
on the author's machine. `.gitignore` said `.venv/` with a trailing
slash, which matches a directory and not a link of the same name, so
`git add -A` swept it in.

On Windows, creating a symlink usually fails without developer mode, so
`git apply` aborted partway and left a tree with sixteen files deleted
and nothing said about why — `git apply --check` had passed, because it
was run on a clean tree before the damage.

Two checks before generating any patch, and
`tests/test_packaging.py` now enforces both:

```powershell
git ls-files -s | Select-String "^120000"     # tracked symlinks
```

and `.venv` in `.gitignore` **without** the trailing slash. The same
applies to every name that can appear in a checkout without belonging to
it — `.claude`, which holds agent worktrees, is the second entry written
that way. `tests/test_packaging.py` holds the list, so adding the next
one is a line rather than a new test.

The wider lesson is the project's own: `--check` passing proved nothing
about the case that mattered, because it was asked where the answer was
already known. See [A probe asked where the answer is already known](../faults/19-non-discriminating-probe.md).
