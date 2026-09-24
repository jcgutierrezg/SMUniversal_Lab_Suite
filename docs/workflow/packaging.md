---
type: workflow
title: "Packaging and deployment"
---

# Packaging and deployment

Why the project is a package, and what the build has to keep true.

## What was wrong

The project could not be built or installed at all. There was no
`[build-system]`, so `import core` worked only when the current
directory happened to be the checkout — Python puts the running
script's own directory on `sys.path`, and nothing else put it there.

The requirement is *launch from an arbitrary working directory*. That
failed at **import**, several steps before it ever reached a resource
file:

```
cd /somewhere/else
python -c "import core"   →  ModuleNotFoundError: No module named 'core'
```

The resource half was already satisfied — the 4PP geometry
diagram is loaded relative to `__file__`, not to the working directory —
and a test now pins that so a refactor cannot quietly reintroduce
`open("experiments/...")`, which works on every developer machine and
nowhere else.

## One namespace

Everything the wheel installs is under `smuniversal_lab_suite`, and the
only other name it puts on the path is the `smu-lab-suite` console
script. Until Wave E the packages were installed as top-level `core`,
`devices`, `drivers` and `experiments` — names at least as generic as the
`main` this project had already refused to install, and free to collide
with any other package in a shared environment. `main.py` stays at the
root as the way to run from a checkout, and is not in the wheel.

## The layout decision: flat, not `src/`

The namespace sits at the top level of the checkout.

A `src/` layout's advantage is that the source tree cannot shadow the
installed copy. That matters for a library other code imports, and much
less for an application with one entry point. It is also not the
protection it first appears: an **editable** install of a `src/` layout
still points at the source, so a data file missing from the build would
still be found on disk and the tests would still pass.

What actually catches a broken build is checking the built artifact, and
[test_build_artifact.py](https://github.com/jcgutierrezg/SMUniversal_Lab_Suite/blob/main/tests/test_build_artifact.py) does that on
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

The declared package list is checked against the tree, and the built
wheel is checked for a single top-level package, so a second one fails
the suite here rather than surprising someone's environment.

## What gets installed

Everything, on every machine. A plain `uv sync` installs every instrument's
library:

| | Why |
|---|---|
| pyvisa, pyvisa-py, pyserial | the transports every instrument uses |
| NumPy, Matplotlib, SciPy, Pillow | every window's plot, the 4PP corrections, its geometry drawing |
| `minismu-py` | the Undalogic miniSMU |
| PyUSB + libusb-package | pyvisa-py's view of USB instruments |
| `ni-gpib-usb-hs` (pinned `==0.1.0`) | the direct GPIB-USB-HS transport |

For a while (review A-11) the instrument libraries were optional extras, so a
machine that owned none of those instruments did not install them. That
narrowed the install and made it harder to get right: a bench that forgot a
flag lost an instrument, and without the USB layer that loss is silent. Having
them all interferes with nothing - each is imported only when its own
transport is chosen - so they are back in the one install, and
`tests/test_missing_packages.py` fails if an extra reappears.

The direct GPIB driver being installed does not make that transport any less
explicit. It is used only when it is picked by hand, and nothing probes it on
the way - see [the direct GPIB-USB-HS transport](../architecture/direct-gpib-usb-hs.md).

### The numerical packages are not split

SciPy, Matplotlib and Pillow stay mandatory, and that was decided rather
than overlooked. Every experiment window builds a Matplotlib canvas, the
4PP corrections are SciPy, and the geometry panel is Pillow. Splitting
them would shave a download and buy no deployment anybody has asked for,
while turning the common case into a two-step install.

### A package missing from a broken install

Every machine should have every package, but an install can still come out
incomplete - interrupted, or copied by hand. An opaque `ImportError` at the
moment an operator selects an instrument leaves them debugging Python at a
bench, so each library's absence has to fail legibly, and
`tests/test_missing_packages.py` provokes each failure rather than trusting it.

`MiniSMUTransport.connect()` and `NIUSBGPIBTransport.connect()` import lazily
and raise a `RuntimeError` naming the fix.

The USB layer is the hard one. pyvisa-py without PyUSB raises nothing at all:
it enumerates GPIB and sockets, reports success, and never mentions a USB
device. That silence is precisely how the Keysight U2722A once went missing
from the address dropdown while plugged in and working. An empty scan and an
unplugged cable look identical.

`VisaTransport.scan_summary()` therefore says so, on the `@py` line itself:

```
@py: nothing - USB support is not installed, so no USB instrument can
     be seen here. Run: uv sync
```

The note rides on its backend's own line rather than adding one, so the line
count keeps meaning "how many backends were asked", and it is computed at scan
time rather than at import, so repairing the install and pressing Refresh is
enough.

## Deployment

**The bench clones the repository and launches through uv**, from a desktop
shortcut that `tools/make_shortcut.ps1` makes once per machine:

```
uvw.exe run --directory <checkout> smu-lab-suite-gui
```

Each part of that line is there for a reason.

- **`smu-lab-suite-gui`** is a `[project.gui-scripts]` entry point, which
  Windows builds as a windowless executable. No console matters for safety:
  a console is one more thing to close, and closing it kills Python outright,
  so `LabApp.on_close()` never runs and the output is never switched off.
  Nothing in the suite can catch that. With no console, the window's close
  button is the only way out, and it is the one that puts the instruments
  away.
- **`uvw.exe`** is uv's own windowless twin, so uv does not open a console
  either.
- **`--directory`** points at the checkout wherever it lives, so the shortcut
  works from the desktop and a `git pull` is the whole of an update.
- **`uv run`** installs anything an update added on the next click, so a `git
  pull` is the whole of an update.

Having no console moves two jobs elsewhere. What would have been printed -
including a traceback from a Tk callback, which Tk reports on stderr - goes to
`launcher.log` beside the single-instance lock. A failure to start is a
dialog naming the error and that log, rather than an icon that does nothing
when clicked. The script also installs the packages before making the
shortcut, so a missing uv or a failed install is read in a console rather
than discovered by clicking.

The icon is drawn by `tools/make_icon.py` and committed; `core/gui/app_icon.py`
puts it on every window and declares an application id, without which Windows
groups the windows on the taskbar under `pythonw.exe` and shows Python's icon.

The frozen-executable model below remains the alternative, and what follows
still holds for it.

### The two models

Two models, and they are genuinely different:

| | Bench clones the repo | Bench gets a frozen `.exe` |
|---|---|---|
| Needs on the bench machine | git, uv | nothing |
| Updating | `git pull` | rebuild and copy |
| Docs and `docs/bench/` pages | present, in step with the code | absent |
| `checkup-owed.md` | meaningful — it derives from `git log` | meaningless, no history |
| Link from a running copy to its commit | the checkout itself | `BUILD_COMMIT`, baked in at freeze time |

That last row is why `smuniversal_lab_suite/core/version.py` holds the version in code rather
than reading packaging metadata: `importlib.metadata` needs an installed
distribution, and a frozen executable is not one. It used to read **only
`app_version`**, which is the gap the next section closes.

Nothing here forces the choice. This wave makes the project installable,
which is a prerequisite for freezing and useful without it. **If freezing
goes ahead, a bench session is required before it counts as
commissioned** — the freeze itself has never been run.

## Stamping the build

Every stored CSV, every sample summary and every operational event
records `build_id` — the release with the commit welded on. See
[the schema reference](../reference/schema.md) for the three forms it
takes.

**From a checkout** it needs no ceremony. `smuniversal_lab_suite/core/version.py` asks
`core.provenance.head_commit()` — the same function every checkup
report already uses — once per process, and caches the answer.

**A frozen build has no repository**, and possibly no `git` on PATH, so
it must receive the commit at build time:

```python
# run from the copy about to be frozen
import pathlib, subprocess

sha = subprocess.run(["git", "rev-parse", "HEAD"],
                     capture_output=True, text=True, check=True).stdout.strip()
dirty = bool(subprocess.run(["git", "status", "--porcelain"],
                            capture_output=True, text=True).stdout.strip())

path = pathlib.Path("smuniversal_lab_suite/core/version.py")
text = path.read_text(encoding="utf-8")
text = text.replace('BUILD_COMMIT = ""', f'BUILD_COMMIT = "{sha}"')
text = text.replace("BUILD_DIRTY = False", f"BUILD_DIRTY = {dirty}")
path.write_text(text, encoding="utf-8", newline="\n")   # LF, per .gitattributes
```

Run that against the copy being frozen, never against the working tree
you go on to commit from. `tests/test_version.py` fails if a stamped
`BUILD_COMMIT` reaches the repository, and the reason is worth stating:
a committed value would name one commit while sitting in every commit
after it — a wrong answer that looks authoritative, which is strictly
worse than `unknown`.

**Freeze from a clean tree.** `BUILD_DIRTY` exists for honesty, not for
routine use; a release build that ships `.dirty` in the header of every
file it writes describes code that exists nowhere else.

**A stamp that cannot be determined is still recorded**, as
`0.1.0+unknown`. The alternatives — omitting the field, or crashing —
are both worse: the first is indistinguishable from an older writer,
and the second turns a provenance detail into a lost measurement.

## Should bench deployments come from tagged releases?

**Yes, once freezing goes ahead; no, for the clone model.** The reasons
differ per row above, and the question is worth settling here rather
than at the moment somebody needs the answer.

For the **clone** model the tag buys nothing the checkout does not
already have. The bench machine's own `git` answers "which commit is
this?" exactly, `docs/open/checkup-owed.md` derives staleness from the
history that is present, and `build_id` reads the same tree. A tag is
one more thing to forget, and forgetting it would degrade nothing.

For the **frozen** model it is the only mechanism that works, and for a
specific reason: a `.exe` carries a sha and nothing else. A sha is not
stable under the delivery pipeline —
[fault 24](../faults/24-derived-from-a-rewritable-date.md) is the whole
argument — so a squash-merged branch leaves an executable naming a
commit that no longer exists on `main`, and the bench has an artefact
nobody can map back to code. A tag is a name the pipeline does not
rewrite.

So the rule, for when freezing lands:

- one `.exe` per tag, and the tag is what `smuniversal_lab_suite/core/version.py`'s
  `__version__` says — bumping the version is what makes a build
  releasable, which `tests/test_version.py` already ties to
  `pyproject.toml`;
- stamp `BUILD_COMMIT` from the tagged commit, so the executable names
  both the tag and the exact tree;
- the tag is pushed before the artefact leaves the build machine,
  because a sha nobody else can resolve is the failure this is meant to
  prevent.

**Not adopted yet, and deliberately not.** There are no tags in this
repository today, and adding a release process to a project whose
freeze has never been run would be writing down a procedure nobody has
followed. `build_id` does not depend on it: it is exact from a
checkout, and honest (`unknown`) from anything else.
