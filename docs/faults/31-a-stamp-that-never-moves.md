---
type: fault
fault: 31
title: "A provenance stamp that never moves"
---

# A provenance stamp that never moves

## Symptom

Every stored file answers "which code produced this?" and every one of
them gives the same answer, whatever code produced it.

```
$ head -3 wafer_A_vanderpauw.csv        # saved 2026-03
# app_version: 0.1.0
$ head -3 wafer_A_vanderpauw.csv        # saved 2026-09, many waves later
# app_version: 0.1.0
```

Nothing is broken. The field is present, correctly spelled, in every
CSV, in every sample summary and on every line of the operational event
log. It is simply not discriminating, and there is no way to tell that
from a file — a reader who finds `0.1.0` in a March file and `0.1.0` in
a September one has been told, in writing, that the same code wrote
both.

`0.1.0` was introduced in Wave 7b-ii and had not changed by the Wave 8
merge. There are no tags in the repository. Every wave in between
changed behaviour.

## Cause

The version is set by hand, and a hand-set number moves when somebody
decides to move it. Nothing in the delivery pipeline requires that
decision, so on a project delivering in waves rather than releases it
never happens — and the field silently degrades from an identifier to a
constant.

The mechanism was not missing. `core/provenance.py` had recorded the
commit and the dirty flag in every checkup report header since
2026-08-20, for exactly this reason: a GSM-20H10 checkup was clean on
the 6th and had six failures on the 18th, and working out what changed
meant bisecting git by hand because neither report named its commit.
That lesson was applied to bench reports and not to the scientific
output, which is the artefact that has to outlive everyone involved.

## Why the fix is not "remember to bump the version"

Because that is the thing that already failed, and asking for it again
would be the same request with more emphasis behind it.

`build_id()` derives the discriminating part from the tree rather than
from an intention: `0.1.0+g5e7308eff34a`, `.dirty` where the tree had
uncommitted changes, `0.1.0+unknown` where neither a baked-in stamp nor
git can answer. The release number stays exactly what it was and keeps
its mirror in `pyproject.toml`; the commit is a second field beside it.

Two constraints shaped it:

* **It must not need git at runtime.** A frozen `.exe` on a bench
  machine has no repository and may have no `git` on PATH. It receives
  the commit at build time and reads it from a baked-in constant, and
  the git lookup is only the checkout's fallback.
* **It must never silently omit.** A missing key reads as "written by
  code that did not record builds". `unknown` reads as "written by code
  that tried and could not tell". A provenance stamp that quietly
  vanishes is the failure this whole field exists to remove, so there
  is no bare `except` anywhere on the path.

## The rule

**A provenance field must be derived from the thing it describes, not
declared alongside it.** A hand-maintained identifier answers correctly
until the day nobody remembers to maintain it, and gives no sign of
which day that was.

The test for whether a stamp is doing work is not that it is present.
It is whether two artefacts you *know* came from different code carry
different values.

## How to check

Take any field meant to identify what produced a record and ask what
updates it. If the answer is a person, ask when it last changed and
compare that against how much has changed since. A field whose value is
older than the behaviour it is supposed to identify is already broken,
and it looks exactly like one that is working.

The same question applied to calculation-method versions gives the
opposite answer, and the contrast is the point:
`core.calculation.METHODS` versions are hand-set too, and they are
sound — because `tests/golden/*.json` fails when a formula changes and
its version does not. The maintenance is not left to memory. That is
the difference between a declared fact and a checked one.
