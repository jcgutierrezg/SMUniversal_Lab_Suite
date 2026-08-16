---
type: fault
fault: 18
title: "An accuracy that is an implementation detail, not a guarantee"
found_by: "writing the maths"
---

# 18. An accuracy that is an implementation detail, not a guarantee

*Found by writing the maths.*

The maths modules averaged with the built-in `sum()`. On CPython 3.12
and later that is Neumaier compensated summation and is very accurate;
on 3.11 it is not, and the difference moved a fitted intercept enough to
turn an exact-comparison golden red on a bench machine that had picked
the older interpreter.

**The accuracy was real but accidental** — a property of one interpreter
version, not of the language. `math.fsum` is *documented* to return the
correctly rounded sum.

Where a number ends up in saved data, prefer the guarantee over the
accident. Keep the built-in only for integer counts, where it is exact
and `fsum` would wrongly return a float. Guarded by
`tests/test_no_bare_sum.py`.
