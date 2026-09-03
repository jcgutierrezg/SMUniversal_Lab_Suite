---
type: fault
fault: 18
title: "An accuracy that is an implementation detail, not a guarantee"
---

# 18. An accuracy that is an implementation detail, not a guarantee

## Symptom

An exact-comparison golden that is green on every developer machine and
red on one bench machine, with no code difference between them.

## Cause

The maths modules averaged with the built-in `sum()`. On CPython 3.12
and later that is Neumaier compensated summation and is very accurate;
on 3.11 it is not, and the difference moved a fitted intercept far
enough to fail the comparison.

**The accuracy was real but accidental** - a property of one interpreter
version, not of the language.

The bench machine was on 3.11 because `pyproject.toml` said
`requires-python = ">=3.10"`, and it took that declaration at its word.
Nothing had ever run 3.10 or 3.11, so the floor was a guess written in a
config file rather than a claim anybody had checked.

## Risk

A number that reaches saved data is only as reproducible as the weakest
interpreter it might be computed on. A result that cannot be reproduced
is not evidence, and the divergence is far too small to notice by eye.

The second half generalises past this instance: **a constraint nothing
tests is not a constraint.** A supported-version floor, a declared
minimum, a documented platform - each is a claim, and a claim with no
run behind it fails in whichever direction nobody was watching.

## Detection

For any numerical result that reaches a file, ask which of its
guarantees are documented and which are observed. `math.fsum` is
*documented* to return the correctly rounded sum; `sum()` is not.

For any declared constraint, ask what would go red if it were wrong. If
the answer is nothing, the constraint is decoration.

## Prevention

Prefer the guarantee over the accident. Keep the built-in only for
integer counts, where it is exact and `fsum` would wrongly return a
float. Guarded by `tests/test_no_bare_sum.py`.

The floor now says what is true and tested: `requires-python`,
`.python-version` and the CI matrix must agree, and
`tests/test_python_floor.py` fails if they drift apart. Moving to a
newer interpreter means adding it to the matrix first, letting it go
green, then changing all three together - see
[delivering work](../workflow/delivering-work.md).

## Status

Closed. The floor is 3.14 and every machine runs it.

## Evidence

Found while writing the maths modules, and confirmed by the bench
machine that installed 3.11.
