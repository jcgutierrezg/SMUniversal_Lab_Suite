---
type: reference
title: "The core modules"
---

# The core modules

> **Stub.** The table arrives with `docs-architecture-v1`. It exists as
> a file now so the link from [[_index]] resolves.

One row per file under `core/`, `devices/` and `drivers/`, answering
three questions:

| Module | Holds | Called by | What breaks without it |
|---|---|---|---|

The third column is the one that is missing today and the reason this
note was asked for. `core/` has grown to the point where several files
look like dead code from the outside — `thread_guard.py` is opt-in and
off by default, so nothing calls it in a normal run, and
`driver_registry.py` is a deprecation shim kept alive for external
importers. Neither is obvious from reading them, and both look
deletable.

`core/base_app.py` gets its own note rather than a row: `LabApp` carries
enough methods that a single line cannot say what it is for, and they
group into distinct jobs — tabs and experiment hosting, the UI queue,
connections and ownership, file paths and saving, the per-sample
summary, and shutdown.
