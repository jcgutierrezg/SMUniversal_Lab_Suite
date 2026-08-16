---
type: reference
title: "The run lifecycle"
---

# The run lifecycle

`core/run_control.py`. Every experiment goes through it via
`begin_run()` — see [[../rules/07-run-is-a-transaction]] for the shape to
copy.

## The problem it solves

A measurement run is not a function call. It runs on a worker thread,
touches hardware that stays energised between steps, can be cancelled at
any moment, and produces data that must either all arrive or none of it.

Before this existed, each experiment carried its own `self.measuring`
flag and its own idea of what Stop meant. The failure that motivated it:
**Stop turned the output off and the worker turned it straight back on**,
because the worker had already decided to source the next level and
nothing told it otherwise.

## The shape

**States**, so "is it running" is one question with one answer, rather
than a boolean per experiment.

**A cancellation token**, not a flag. `run.checkpoint()` raises if the
run has been cancelled, and it is called before every step that
energises or alters the output: output-on, source-function change, each
new level, each polarity flip, after every long wait, and immediately
before commit. Cancellation therefore takes effect at a point where the
worker is between operations and can de-energise cleanly.

**Provisional readings.** Data accumulates in the run, not in the
experiment. A cancelled run's readings are discarded, and the discard is
free because nothing outside has seen them.

**A single atomic commit gate.** Either the whole run lands in the
results table or none of it does. The sink must not block — the
controller's lock is held while it runs — so an experiment posts to the
UI thread and returns.

## Three endings, and they are different

| Ending | Data | Output |
|---|---|---|
| completed | committed | de-energised in cleanup |
| cancelled | **discarded** | de-energised in cleanup |
| failed | discarded | de-energised, and `confirm_shutdown` reports if it could not be confirmed |

`confirm_shutdown()` is the part worth understanding. Turning the output
off is a command that can fail like any other, so the run asks the
instrument afterwards and returns a report. **`uncertain` is a real
outcome**, distinct from "off" and from "on" — and it is escalated to
the operator through `report_uncertain_shutdown` rather than logged,
because an instrument that may still be sourcing into a fixture someone
is about to reach into is not a logging matter.

## Ownership unwinds in the right order

`run.on_cleanup(...)` is registered **before** the instrument claim.
An `ExitStack` unwinds in reverse, so the UI is told "idle" *after* the
instrument has been handed back. Registered the other way round, a
sibling tab could see the instrument free while the UI still showed a
run in progress.

## One Stop, and it discards

Do not add an OFF button to a new experiment. Nothing outside the
worker may talk to the instrument during a run — the worker owns the
session and de-energises on the thread that owns it.

On a periodic IV run, Stop discards **everything**, for consistency with
the other three. A partial periodic run is not a shorter periodic run;
the repetitions are the measurement.
