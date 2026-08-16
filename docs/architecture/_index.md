---
type: index
title: "Architecture"
---

# Architecture

What each module is for, and what breaks without it.

Start with [The core modules](core-modules.md), which is one row per file. The deeper notes
exist only where a table cannot carry the reasoning - the run lifecycle,
ownership, calculation provenance, the ranging contract.

The one rule that keeps the rest maintainable:

```
experiments/  ->  drivers/  ->  core/transports/
```

Nothing in `core/` imports from `experiments/`, and no driver imports an
experiment. If breaking that ever feels necessary, something is in the
wrong layer.

## Read in this order

1. [The core modules](core-modules.md) - one row per module, and what breaks without it
2. [The application shell](app-shell.md) - `LabApp`'s methods, grouped by job
3. [The run lifecycle](run-lifecycle.md) - states, tokens, the commit gate, three endings
4. [Instrument ownership](ownership.md) - the hotel key, and why it is keyed on the connection
5. [Calculation and provenance](calculation-provenance.md) - how a derived number keeps its lineage
6. [The ranging contract](ranging.md) - the four axes, and the mistake made unrepresentable
7. [Sweeps and transports](sweeps-and-transports.md) - two seams, one reason
8. [The tools](tools.md) - six programs, six questions
9. [Devices — why the stage is not a driver](devices.md) - why the temperature stage is not a driver
