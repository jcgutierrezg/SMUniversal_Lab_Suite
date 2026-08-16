---
type: rule
rule: 10
title: "A derived value carries its provenance"
---

# 10. A derived value carries its provenance

If a new experiment computes a physical quantity from measured runs, it
goes through `core/calculation.py` rather than reading widget strings
and writing label strings.

Full treatment in [[../architecture/calculation-provenance]]. The four
steps: build a `CalculationInput` on the main thread, `validate()`,
`require_set()` where the inputs must be a complete set, and `derive()`
to a frozen `DerivedResult`.

Three rules learned the hard way:

- **Provenance is all-or-nothing per run.** Where one run fills several
  boxes, typing over any one of them drops that run as a source
  entirely. A chain that is half true reads exactly like one that is
  whole.
- **The staleness signature must include every input the result depends
  on, not just the numbers.** Hall's `sample_type` changes which carrier
  density is reported by a factor of the thickness and moves none of the
  eight voltages.
- **`calculated_fields()` returns `{}` when the result is stale.** The
  grey text on the panel is advice; this is the part that cannot be
  ignored. Raw data still saves.

Method versions live in `core.calculation.METHODS`, and
`tests/golden/*.json` is what makes them load-bearing: change a formula
without bumping its version and the golden file stops reproducing. A new
method with neither golden cases nor a written reason in
`NOT_YET_COVERED` fails the suite.
