---
type: fault
fault: 38
title: "A contract method that was not abstract, and returned None"
---

# 38. A contract method that was not abstract, and returned None

## Symptom

None, which is the point. A driver instantiates, connects, identifies,
configures, sources, and produces a full-length trace of `(None, None)`
readings. The run has the right number of points, the right timestamps
and the right metadata. Every value in it is absent.

## Cause

`BaseSMU.measure()` had an empty body and no `@abstractmethod`:

```python
    def measure(self):
        """Take one reading. Returns (volts, amps); either may be None
        if this instrument/configuration doesn't report it."""
```

Ten of the eleven contract methods around it are decorated and raise
`NotImplementedError`. This one was not, so the single method every
experiment calls was the single method a driver could omit - and
omitting it inherited a concrete implementation that falls off the end
and returns `None`.

The declared signature also disagreed with every implementation:
`measure(self)` here, `measure(self, timeout_s=3.0)` in all nine
drivers. The contract file described a contract nobody had.

## Risk

`None` is a legal reading here. The drivers turn an instrument's
over-range sentinel (`+9.91e37`) into `None` deliberately, so that a
missing value stays *in place* rather than shifting every later column
left - see [fault 3](03-sentinels-as-data.md). A blanked point is
ordinary and the experiments handle it.

That is exactly what makes this shape bad. A driver that never measured
anything is indistinguishable, at the point where the data is written,
from an instrument that was over range for the whole run. The trace
commits, saves, and carries provenance saying which instrument produced
it.

Two things kept it harmless. Every driver in the fleet does implement
`measure()`; and `tests/test_driver_contract.py` requires every
*registered* driver to define it rather than inherit it. So the fault
was latent, not live.

## Detection

In an abstract base class, a method with an empty body is a promise or a
default, and the two are not interchangeable. If a subclass that forgets
it would be *wrong*, decorate it and raise. If inheriting it is a
legitimate choice, the body has to do the legitimate thing rather than
implicitly return `None`.

A suite-level check that every driver defines a method is not a
substitute. It runs when the suite runs; `@abstractmethod` runs at
construction, which is where a driver written in a later wave finds out.

## Prevention

`drivers/base_smu.py` declares `measure()` abstract with the real
signature, so an SMU class missing it cannot be instantiated at all.
`tests/test_driver_contract.py` keeps its own check, which still catches
the different mistake of a driver that satisfies the class and then
inherits a base hook it should have overridden.

## Status

Closed.

## Evidence

Found by ruff's `B027`, which is what a lint gate is for: nobody reading
this file was going to notice one missing decorator in a column of
eleven. It had been in the tree since the first import.
