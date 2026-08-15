---
type: reference
title: "Migration status"
---

# Migration status

The documentation is being rebuilt across four patches. This note says
which is done, so nobody reads a stub and concludes the information was
lost.

**Until `docs-retire-v1` lands, the root documents are still the live
ones.** `HANDOFF.md`, `PORTING_NOTES.md`, `INSTRUMENTS.md` and
`WAVE_PLAN.md` are untouched and remain authoritative for anything not
yet moved.

| Patch | Contents | State |
|---|---|---|
| `docs-skeleton-v1` | folder tree, frontmatter schema, generators, `tests/test_docs.py`, `manuals/` | **done** |
| `docs-instruments-v1` | instrument and experiment notes; deviations rehomed; generated bench pages | |
| `docs-architecture-v1` | house rules, faults, `core/`, `tools/`, `devices/` | |
| `docs-retire-v1` | `bench/` pages, the review index, deletion of the four root documents, code comments updated | |

## Why four and not one

One concern per patch, applied to the documentation itself. The
skeleton adds capability that nothing reads, so it cannot regress
anything; the content patches then adopt it one layer at a time. That is
the same shape as Waves 6d-i and 6d-ii, where the first changed no wire
traffic at all — which is what made every existing test staying green
mean something.

## Known-stale claims, corrected on the way through

These were found by reading the root documents against the code. They
are listed here so the corrections are visible as corrections rather
than arriving silently inside a large move.

| Claim | Where | Reality |
|---|---|---|
| IV sweep still runs on its own `measuring` flag | `HANDOFF.md` l.838, l.848, l.1206 | Wave 6a migrated it; `begin_run()` at `experiments/iv_sweep/experiment.py` l.529 and l.594, and `self.measuring` does not exist |
| The 2450's source/measure range ambiguity needs "a wave of its own" | `HANDOFF.md` l.1067–1095 | Wave 6d-ii closed it; both methods are deleted and the 2450 implements all four per-axis hooks |
| "Twenty-nine test files in `tests/`" | `HANDOFF.md` l.223 | now generated, never stated | <!-- count-ok -->
| "drift between five hand-written drivers" | `HANDOFF.md` l.143, l.181 | as above | <!-- count-ok -->
| "all commissioned against real hardware in August 2026" | `INSTRUMENTS.md` l.3 | contradicted at l.331 in the same file; now derived from git |
| A fabricated `*IDN?` for the 2635B | `INSTRUMENTS.md` l.317 | the observed reply is recorded in the note, and the schema refuses an unconfirmed one |
| "Not yet commissioned" for the 2635B and B2901A | `INSTRUMENTS.md` l.331, l.443 | both contradicted later in their own sections; both were commissioned 2026-08-13 |
| The Python floor is 3.12 | `HANDOFF.md` l.1236 | `pyproject.toml` says `requires-python = ">=3.14"` and CI runs 3.14 only |

The last one is worth a second look during `docs-architecture-v1`: the
reasoning for a 3.12 floor was the Neumaier summation change, and that
reasoning is still correct and still worth recording even though the
floor has moved past it.
