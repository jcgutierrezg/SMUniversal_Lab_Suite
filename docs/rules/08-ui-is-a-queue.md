---
type: rule
rule: 8
title: "`app.ui()` is a queue, not a direct callback"
---

# 8. `app.ui()` is a queue, not a direct callback

Measurement threads hand work back with `app.ui(fn, ...)` and
`app.log(...)`. Both put onto a queue that the main thread drains every
`UI_PUMP_MS`. **Workers never call into Tcl.**

This replaced a direct `root.after(0, ...)` from the worker, which is
not thread-safe: `after()` registers a Tcl command, and Tcl is
single-threaded. The application only survived it because the main
thread sits inside `mainloop()`.

**What this means for tests.** Anything driving the loop with
`root.update()` rather than `mainloop()` must drain explicitly:

```python
exp.app.drain_ui_now()
```

Sixty back-to-back `update()` calls take well under one pump interval,
so without the drain a committed row is still sitting in the queue when
the assertions run. This is also why tests must not sleep and hope —
wait on the fact, drain the queue.

`core/thread_guard.py` is the diagnostic that answers "is anything still
reading Tk from a worker?". It is opt-in and off by default, which is
why nothing appears to call it.
