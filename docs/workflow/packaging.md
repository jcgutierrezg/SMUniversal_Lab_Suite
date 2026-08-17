---
type: workflow
title: "Packaging and deployment"
---

# Packaging and deployment

Carries the reasoning from review §42. Landed in Wave 7e.

## What was wrong

The project could not be built or installed at all. There was no
`[build-system]`, so `import core` worked only when the current
directory happened to be the checkout — Python puts the running
script's own directory on `sys.path`, and nothing else put it there.

§42's acceptance criterion is *launch from an arbitrary working
directory*. That failed at **import**, several steps before it ever
reached a resource file:

```
cd /somewhere/else
python -c "import core"   →  ModuleNotFoundError: No module named 'core'
```

The resource half of §42 was already satisfied — the 4PP geometry
diagram is loaded relative to `__file__`, not to the working directory —
and a test now pins that so a refactor cannot quietly reintroduce
`open("experiments/...")`, which works on every developer machine and
nowhere else.

## The layout decision: flat, not `src/`

The packages stay at the top level.

A `src/` layout's advantage is that the source tree cannot shadow the
installed copy. That matters for a library other code imports, and much
less for an application with one entry point. It is also not the
protection it first appears: an **editable** install of a `src/` layout
still points at the source, so a data file missing from the build would
still be found on disk and the tests would still pass.

What actually catches a broken build is checking the built artifact, and
[test_build_artifact.py](../../tests/test_build_artifact.py) does that on
this layout. Moving to `src/` later is the same mechanical change if
shadowing ever turns out to bite.

## Why assets need checking and `.py` files do not

A build follows imports. Every `.py` file is reachable that way, so
every `.py` file gets in.

**Nothing imports a `.png`.** No edge in the dependency graph points at
it, so a build that only follows imports never sees it. It is included —
or not — by a rule somebody wrote, and rules like that fail silently:
the window simply does not open on a machine that has the artifact but
not the checkout.

Cloning the repository is not protection, and the distinction is worth
stating precisely:

> Git guarantees the file is in the **checkout**. Packaging decides
> whether it is in the **artifact**. Those are the same thing right up
> until something is shipped that is not a checkout.

## What hatchling actually does

Every **tracked file inside a declared package**, whatever its
extension. So a future `.svg` or `.ico` under `assets/` is included
without anyone editing `pyproject.toml`.

This is worth stating because the first version of the build
configuration got it wrong. It carried
`artifacts = ["**/assets/**"]` with a comment explaining that non-Python
files must be named explicitly — true of build backends in general,
false of this one, whose `artifacts` key is for pulling in files that
*version control excludes*. The line did nothing. Mutation testing
caught it: emptying the key changed no wheel.

The line is gone. The lesson is the one this vault exists for — a rule
believed to be doing the work, and not doing it, protects nothing while
looking like it does — and it is why the test inspects a real built
wheel rather than reading the configuration.

The realistic ways to break asset inclusion are an `exclude` or
`only-include` rule, or dropping a package from the declared list. Both
fail the suite.

## Running it

```
uv build --wheel
uv pip install dist/smuniversal_lab_suite-<version>-py3-none-any.whl
```

The declared package list is checked against the tree, so adding a
fifth top-level package fails the suite here rather than at the bench.

## Deployment: still open

Two models, and they are genuinely different:

| | Bench clones the repo | Bench gets a frozen `.exe` |
|---|---|---|
| Needs on the bench machine | git, uv | nothing |
| Updating | `git pull` | rebuild and copy |
| Docs and `bench/` pages | present, in step with the code | absent |
| `checkup-owed.md` | meaningful — it derives from `git log` | meaningless, no history |
| Link from a running copy to its commit | the checkout itself | **only `app_version`** |

That last row is why `core/version.py` holds the version in code rather
than reading packaging metadata: `importlib.metadata` needs an installed
distribution, and a frozen executable is not one.

Nothing here forces the choice. This wave makes the project installable,
which is a prerequisite for freezing and useful without it. **If freezing
goes ahead, a bench session is required before it counts as
commissioned** — the freeze itself has never been run.
