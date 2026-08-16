---
type: reference
title: "Delivering work"
---

# Delivering work

**One conversation per wave.** Start it with:

> Wave N, <name>. Repo: https://github.com/jcgutierrezg/SMUniversal_Lab_Suite,
> branch `main`. Fetch with
> `curl -sL https://codeload.github.com/jcgutierrezg/SMUniversal_Lab_Suite/tar.gz/refs/heads/main`.
> Read `WAVE_PLAN.md` for scope, and the sections of
> `LAB54_DEVELOPMENT_REVIEW_AND_WORKFLOW.md` it names. Deliver as a
> `.patch` against `main`.

**Delivery is a `.patch` file**, applied with `git apply`. A patch
expresses deletions, renames and moves; a zip cannot, which is how the
orphaned `temp_panel.py` survived Wave 0b's zip and got caught only by a
test. Confirm the base commit (`git log --oneline -1`) before generating
any patch — the one failed application in Wave 0 was an assumed base.

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

and `.venv` in `.gitignore` **without** the trailing slash.

The wider lesson is the project's own: `--check` passing proved nothing
about the case that mattered, because it was asked where the answer was
already known. See [[../faults/19-non-discriminating-probe]].
