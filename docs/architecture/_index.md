---
type: index
title: "Architecture"
---

# Architecture

What each module is for, and what breaks without it.

Start with [[core-modules]], which is one row per file. The deeper notes
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

1. [[core-modules]] - one row per module, and what breaks without it
2. [[app-shell]] - `LabApp`'s methods, grouped by job
3. [[run-lifecycle]] - states, tokens, the commit gate, three endings
4. [[ownership]] - the hotel key, and why it is keyed on the connection
5. [[calculation-provenance]] - how a derived number keeps its lineage
6. [[ranging]] - the four axes, and the mistake made unrepresentable
7. [[sweeps-and-transports]] - two seams, one reason
8. [[tools]] - six programs, six questions
9. [[devices]] - why the temperature stage is not a driver
