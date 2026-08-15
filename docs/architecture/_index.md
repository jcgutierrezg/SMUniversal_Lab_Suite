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

> **Stub.** Content arrives in a later patch; see [[migration-status]].
