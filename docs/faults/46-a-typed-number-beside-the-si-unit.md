---
type: fault
fault: 46
title: "A typed number written beside the unit it was converted into"
---

# 46. A typed number written beside the unit it was converted into

## Symptom

The `# --- calculated ---` block of a saved 4PP file reads:

```
# input_width_m: 10 m
# input_length_m: 10 m
# input_thickness_m: 180 m
```

for a sample 10 mm square and 180 µm thick. Van der Pauw and Hall wrote
`input_thickness_m: 1 m` for 1 µm. The results beside those lines are
correct: the arithmetic used the right numbers. Only the record of what
went into it is wrong, by three or six orders of magnitude.

## Cause

`InputValue` carries two things on purpose: the SI `value` the
calculation uses, and the `text` the operator typed, so that a header
can say `180` rather than the `179.99999999999997` a µm-to-m round trip
leaves behind (see the note at the top of `core/calculation.py`).

Its string form was `f"{text} {unit}"`, and `unit` is the unit of
`value`. Wherever the entry box was not in SI - millimetres for the 4PP
sides, micrometres for every thickness - the typed number was printed
beside a unit it had never been in. The two fields were individually
correct and wrong in combination, and nothing compared them.

## Risk

A header is read months later, by someone recomputing a result or
checking one against a notebook, when the panel that showed `mm` is not
on screen. `10 m` is a well-formed quantity. Nobody reading it has a
reason to doubt it unless they already know the sample, and the whole
purpose of the provenance block is to be trusted by someone who does
not.

It fails silently in the direction that matters most: the result is
right, so every check on the result passes, and the one line that could
be used to verify it is the one that is wrong.

## Detection

Read a saved file back and ask, for every `input_*` line, **whether the
unit printed is the unit of the number printed**. Any value that
crosses a unit conversion between the widget and the maths is a
candidate - which is every geometry entry in this suite, because house
rule 5 converts at the edge.

It was found by the CSV plotter showing the header beside the run's own
`width_mm` column, where `10` and `10 m` sat one line apart.

## Prevention

`InputValue` has a `text_unit`: the unit the text was typed in. The
header form never puts typed text beside a unit it was not typed in:

* declared: `10 mm (0.01 m)` - what was typed, then the SI value it
  became;
* not declared, and the text does not equal the value: `0.01 m (typed
  10)` - a caller that forgets the field gets a line that says less,
  not one that is wrong;
* typed in the value's own unit, or not typed: unchanged.

The 4PP declares `mm` and `µm`, Van der Pauw and Hall declare `µm`.
Staleness is unaffected: `signature()` reads the typed text, not the
unit.

## Status

Closed for every `InputValue` the experiments build. Files saved before
the fix still carry the wrong lines; the run columns (`width_mm`,
`thickness_um`) beside them are correct.

## Evidence

`tests/test_calculation.py` (`test_a_typed_value_is_written_with_the_unit_it_was_typed_in`,
`test_an_undeclared_conversion_never_borrows_the_si_unit`,
`test_declaring_the_typed_unit_does_not_change_staleness`);
`tests/test_4pp.py` and `tests/test_vdp_calculation.py` check the header
an experiment really builds. Related:
[A writer that quietly rewrote what it was handed](36-two-ends-disagreeing-about-newlines.md),
[Units: SI inside, convert only at the edges](../rules/05-si-inside.md),
[A derived value carries its provenance](../rules/10-provenance.md).
