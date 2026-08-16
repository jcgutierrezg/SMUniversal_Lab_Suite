---
type: reference
title: "Calculation and provenance"
---

# Calculation and provenance

`core/calculation.py`. Any physical quantity computed from measured runs
goes through this layer rather than reading widget strings and writing
label strings.

## Why a layer at all

A derived number is only as good as the story of where it came from, and
that story is exactly what a GUI throws away. The original notebooks
read a value off a screen, typed it into another box, and the
relationship between the two existed only in somebody's memory of that
afternoon.

## The four steps

1. **Build a `CalculationInput`** on the main thread — SI values **and
   the text the operator typed**, plus a `SourceRow` per contributing
   run.
2. **`validate(calc, distinct_runs=...)`.** Refuses mixed samples,
   missing or non-finite values, and one run backing two inputs. The
   message names the specific incompatibility, because a mixed-sample
   calculation is arithmetically perfect and the operator has nothing
   else to go on.
3. **`require_set()`** where the inputs must be a complete set — Van der
   Pauw's Pos1–4, Hall's four (position, field sign) combinations. **At
   copy time, not calculate time**: an operator may legitimately type
   one value in, and refusing that enforces traceability rather than
   correctness.
4. **`derive(calc, outputs)`** returns a frozen `DerivedResult` carrying
   a result id, the sample identity, the source run and reading ids, and
   the method and version. `to_metadata()` is what reaches the CSV
   header.

## Staleness, and the wiring fault it hides

**The signature must include every input the result depends on, not just
the numbers.** Hall's `sample_type` changes which carrier density is
reported by a factor of the thickness and moves none of the eight
voltages.

**The keys in the signature and in `CalculationInput.values` must match
exactly.** Wave 5a-i shipped a version where one said `thickness_m` and
the other `thickness_um`. Every result then read as **permanently
stale** and silently stopped reaching the CSV — no error, no dialog,
just a header with no sheet resistance in it.

`signature_difference()` now reports a *disjoint field set* as a wiring
fault rather than an edit, and every wired experiment has a
`test_..._is_never_stale` regression guard. **Add one.**

## Upstream is not sources

`sources` is a tuple of `SourceRow` — completed measurement *runs*. A
number arriving from another calculation is a `DerivedResult` with a
lineage already attached, and it goes in `CalculationInput.upstream` as
an `UpstreamResult`.

The analogy is a bill of materials: cite the sub-assembly's part number
and let its own BOM stay attached to it. Paste its screws into your
parts list and nobody can tell afterwards which screws belong to which
assembly.

Concretely, folding Van der Pauw's four runs into Hall's `sources` would
make `require_set()` see Pos1–4 among Hall's eight combinations and
**refuse a complete set as unexpected**, and would leave a saved header
claiming eight voltages came from twelve runs.

Three rules that come with it:

- **`validate()` applies the mixed-sample refusal to upstream results
  too.** A sheet resistance measured on one film and fed into a
  calculation set up for another is the same fault arriving through a
  box instead of a table row.
- **The upstream *result id* is in the staleness signature**, not just
  the number it supplied. Recalculating the source and getting an
  identical value would otherwise leave a result citing a calculation
  the operator never used.
- **Build the signature fields with `upstream_signature_items()`, from
  both sides.** The panel samples widgets; the calculation builds from
  the input object; they must produce the same field *names* or the
  result is permanently stale. One function, two callers, returning
  `{}` for no upstream — which is why the experiments that have none are
  untouched.

## Handing a value to another tab

The provider declares `PROVIDES = ("sheet_resistance",)` and implements
`provide(name)` returning a `ProvidedValue`; the consumer asks
`app.provider_of("sheet_resistance")`.

`provide()` raises `CalculationRefused` rather than returning `None`
when the value exists but is not usable — not calculated yet, or stale.
A stale result already cannot reach its own experiment's CSV; the
refusal is what stops it reaching **another experiment's arithmetic
through a side door.**

## Methods are versioned, and the goldens make that load-bearing

`core.calculation.METHODS` carries a version per method, and
`tests/golden/*.json` pins the arithmetic. Change a formula without
bumping its version and the golden stops reproducing. A new method with
neither golden cases nor a written reason in `NOT_YET_COVERED` fails the
suite.

See [[../faults/18-accidental-accuracy]] for why the goldens once went
red on a bench machine and what that turned out to mean.
