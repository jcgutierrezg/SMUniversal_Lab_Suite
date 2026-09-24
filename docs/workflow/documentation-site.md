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
