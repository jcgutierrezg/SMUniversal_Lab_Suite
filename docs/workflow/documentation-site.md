---
type: workflow
title: "The documentation site"
---

# The documentation site

`docs/` is the source of the
[published site](https://jcgutierrezg.github.io/SMUniversal_Lab_Suite/).
Every merge to `main` that touches it rebuilds and republishes the site;
nobody deploys by hand.

## Previewing a change

```powershell
uv run --group docs zensical serve
```

That serves the site at http://127.0.0.1:8000/SMUniversal_Lab_Suite/ and
rebuilds it as you save. To check a change the way CI will:

```powershell
uv run python tools/build_docs.py
uv run --group docs zensical build --strict
```

`--strict` fails on a link to a page that does not exist, which is the
mistake a relative link makes when a note moves.

## What to know before adding a page

**The navigation is generated.** `tools/build_docs.py` writes the `nav`
block of `mkdocs.yml` from the pages under `docs/`, so a new page appears
once it is `git add`-ed and the tool has been run. The order within a
section follows the order that section's `index.md` links its pages;
anything the index does not link comes after, alphabetically. The tabs
themselves are `NAV_TABS` in that tool, and a page under no tab fails the
build rather than being published where nobody can reach it.

**A link must stay inside `docs/`.** The site publishes `docs/` and
nothing else, so a relative link to `README.md`, a test or a source file
is a dead link on the site. Link to the file on GitHub instead.
`tests/test_docs.py` fails on one that escapes.

**Every section folder's index page is `index.md`.** That is what the
site treats as the section's own page, and what GitHub shows for the
folder.

**Two tabs, two readers.** The **User guide** (`docs/index.md` and
`docs/guide/`) is for somebody running a measurement who neither knows
nor cares how the suite is built. Everything else is the **Developer**
tab. A page belongs in the guide only if that reader needs it.

## The user guide

Each window has a page under `docs/guide/windows/`, written by hand -
what the window measures, how to wire the sample, a run step by step,
how to read the result. Three things on it are not written by hand:

| Block | Written by | From |
|---|---|---|
| `<!-- generated:controls <window> -->` | `tools/build_guide.py` | the window's panels and their tooltips |
| `<!-- generated:data-notes <note> -->` | `tools/build_docs.py` | the note's `<!-- bench -->` sections |
| the screenshots | `tools/capture_screens.py` | the real window, in demo mode, in both looks |

**The control tables are the tooltips.** `build_guide.py` builds each
window hidden, walks it panel by panel, and writes one row per control
that has a tooltip. So a table is changed by changing the tooltip, and
`tests/test_guide.py` fails when a table and its window disagree. A
control with no words on it - a lamp, a plot, a box with no label -
needs `name=` where its tooltip is attached, or the test fails on its
placeholder name.

Controls that read the same in the panels every window has (the header,
Instruments, Run controls, Results, Plot) are described once, on
`guide/windows/every-window.md` (key `shared`), and left off each window's
own page.

**Screenshots are taken, not built.** On a Windows PC:

```powershell
uv run python tools/capture_screens.py iv_sweep
```

It opens the window on screen, connects the demo instrument, runs once,
and saves the whole window and each panel, light and dark, under
`docs/assets/screens/`. The site shows the one matching the reader's
look. Keep the mouse still and the middle of the screen clear while it
runs. Screenshots depend on the machine's fonts and scaling, so CI never
compares them; `tests/test_docs.py` only checks that every picture a page
shows exists. Retake them when a window's layout changes.

A new window page: write it with the two blocks empty, run both
generators and the capture, and add it to the table on
`guide/windows/index.md`.

## Why Zensical

The site follows the layout of Material for MkDocs, the common choice for
Python projects, but is built by Zensical, the same team's successor.
Material for MkDocs is in maintenance mode, with fixes ending in
November 2026. Zensical reads the same `mkdocs.yml`, so the config above is
ordinary Material configuration.

Zensical and its dependencies are in the `docs` dependency group, not the
project's dependencies. A bench machine installs what it measures with;
it never builds the site.

## The look

`docs/assets/app-theme.css` gives the site the windows' two modes: the
lab notebook in light, the instrument front panel in dark, switched from
the header. Its colours are copies of `core/gui/theme.py`'s, so a change
to the windows' palette is made there first and here second.

## Publishing

`.github/workflows/docs.yml` builds with `--strict` on every pull request
and deploys to GitHub Pages on a push to `main`. The repository's
*Settings → Pages → Source* must be set to **GitHub Actions**, once, for
the deploy step to have somewhere to publish.
