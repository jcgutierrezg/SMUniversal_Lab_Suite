---
type: rule
rule: 7
title: "A run is a transaction — use `begin_run()`"
---

# 7. A run is a transaction — use `begin_run()`

4PP is the worked example; copy its shape.

```python
def _do_run(self, params):
    with self.begin_run(parameters=params) as run:
        run.on_cleanup(lambda: self.app.ui(self._end_run))
        run.enter(self.app.claim_instrument("source", run.run_id))
        smu = self.instrument("source")
        run.expect(params.points_n)
        try:
            ...                       # checkpoint before anything energising
            run.start()
            ...
        finally:
            report = run.confirm_shutdown(smu, log=self.log)
            if report.uncertain:
                self.app.report_uncertain_shutdown("source", report)
        run.commit(record, lambda r: self.app.ui(self._record_run, r, ...))
```

Four rules that are not obvious from the code:

- **`run.checkpoint()` goes before every step that energises or alters
  the output** — output-on, source-function change, each new level, each
  polarity flip, after every long wait, and immediately before commit.
- **Register `on_cleanup` before the claim.** An `ExitStack` unwinds in
  reverse, so the UI must be told "idle" *after* the instrument has been
  handed back, not before.
- **The commit sink must not block.** The controller's lock is held
  while it runs, so post to the UI thread and return.
- **There is one Stop and it discards.** Do not add an OFF button to a
  new experiment. Cancellation is a token; the worker de-energises in
  its own cleanup, on the thread that owns the session. Nothing else may
  talk to the instrument during a run.

See [The run lifecycle](../architecture/run-lifecycle.md) for why it is shaped this way.
