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
| `docs-instruments-v1` | instrument notes, deviations rehomed, generated bench pages | **done** |
| `docs-experiments-v1` | experiment notes and the script archaeology | |
| `docs-architecture-v1` | house rules, faults, `core/`, `tools/`, `devices/` | |
| `docs-retire-v1` | `bench/` pages, the review index, deletion of the four root documents, code comments updated | |

The instruments patch split experiments out into their own: the two
bodies of material are independent - instrument deviations come from
command references, experiment deviations come from the original scripts
- and putting both in one diff would mean a red test afterwards could
not say which half caused it.

## Why several patches and not one

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
| The 2450's source/measure range ambiguity needs "a wave of its own" | `HANDOFF.md` l.1067–1095 | **corrected**: Wave 6d-ii closed it. Both methods are deleted and the 2450 implements all four per-axis hooks. A lint now refuses any note that describes them as live |
| "Twenty-nine test files in `tests/`" | `HANDOFF.md` l.223 | now generated, never stated | <!-- lint-ok -->
| "drift between five hand-written drivers" | `HANDOFF.md` l.143, l.181 | as above | <!-- lint-ok -->
| "all commissioned against real hardware in August 2026" | `INSTRUMENTS.md` l.3 | contradicted at l.331 in the same file; now derived from git |
| A fabricated `*IDN?` for the 2635B | `INSTRUMENTS.md` l.317 | **corrected**: the observed reply, read off the unit 2026-08-13, is `Keithley Instruments Inc., Model 2635B, 4126721, 3.2.2`. The schema now refuses an unconfirmed one |
| "Not yet commissioned" for the 2635B and B2901A | `INSTRUMENTS.md` l.331, l.443 | **corrected**: both contradicted later in their own sections, and both were commissioned 2026-08-13. Recorded from the file's own evidence rather than from a bench record - worth a sanity check |
| The Python floor is 3.12 | `HANDOFF.md` l.1236 | `pyproject.toml` says `requires-python = ">=3.14"` and CI runs 3.14 only |

## Confirmed with the maintainer

- The 2635B and B2901A were both commissioned on 2026-08-13, as the
  corrected notes state.
- The Keithley 2450 is a 2450, not a 2460 or 2470, so its declared
  limits are correct. Its `*IDN?` is still unread.
- The miniSMU's LOW/HIGH voltage ranges were checked against Undalogic's
  published material and are **undocumented upstream**, not merely
  unfound here. Two unrelated findings came out of that check and are in
  [[undalogic-minismu]].

The Python-floor row is worth a second look during `docs-architecture-v1`: the
reasoning for a 3.12 floor was the Neumaier summation change, and that
reasoning is still correct and still worth recording even though the
floor has moved past it.
