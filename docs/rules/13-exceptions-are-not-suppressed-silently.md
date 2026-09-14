---
type: rule
rule: 13
title: "A suppressed exception states the invariant that makes it safe"
---

# 13. A suppressed exception states the invariant that makes it safe

Production code holds 169 `except Exception` handlers, 62 of which
suppress the exception outright — `pass` or `continue` and nothing
else. Most are correct. Review A-09 measured them because two of this
project's worst faults were the same shape:

* [fault 29](../faults/29-a-shutdown-that-fails-open.md) — the stage's
  `pid_off()` and `close()` were swallowed on the way out of the
  application, so a heater could stay enabled after the window closed,
  with nothing on screen and no link left to retry over.
* [fault 30](../faults/30-a-guard-that-fails-to-all-clear.md) — the
  unsaved-measurement guard caught everything and returned a count, so
  a failure and a genuine all-clear were the same value, `0`, and the
  action taken on `0` was the destructive one.

Neither was a missing handler. Both were a handler that turned a
failure into something indistinguishable from success.

## The rule

**Safety, data-preservation and provenance paths do not suppress.** A
path that decides whether the sample is de-energised, whether readings
may be kept, whether a claim is released, or what a stored record says
about where it came from, reports the failure. It returns a value the
caller must branch on — `ShutdownReport`, `StageShutdownReport`, a
count plus the things that could not be read — or it raises. "Nothing
went wrong" and "I could not tell" are different answers and must not
share a spelling.

**A cleanup-only suppression carries a comment stating the invariant
that makes it safe.** Not that it is safe — *why*. The comment names
what is already recorded, what has already happened, or what would
happen instead. Three from the tree:

> the operational log is written separately and does not come through
> here

> an id Tk has already forgotten cannot fire, so failing to cancel it
> leaves nothing scheduled

> the sample was put away by `safe_output_off()` before the link was
> touched; this is the host releasing a port it has already stopped
> using

**`except:` with no class is never correct.** It also catches
`KeyboardInterrupt` and `SystemExit`, so it turns Ctrl-C during a run
into a silent no-op. Ruff's `E722` is enabled and there are none.

## What is enforced, and what is not

`tests/test_exception_policy.py` checks the second half of the rule on
a named surface: the modules that carry run control, the run store, the
event log, provenance, identity, ownership, the app shell, the
experiment base and the driver contract. On those files, a suppression
with no stated reason fails the suite.

It checks that a reason was **written**, not that it is **true**. No
test can do the second one. The point is that the reason becomes an
artefact a reviewer can disagree with, in the diff that introduces the
suppression, rather than a silence nobody can argue with three years
later.

The rest of the tree — drivers, transports, panels, the tools — is not
on that surface yet. 55 of the 62 suppressions had no stated reason
when this rule was written; the ones on the surface above were given
one, and the remainder are recorded in
[technical debt](../open/technical-debt.md) as a per-area pass rather
than a single sweep, because writing 55 invariants in one change would
produce 55 sentences nobody had time to mean.

Ruff's `S110` and `S112` — `try/except/pass` and `try/except/continue`
— are **deliberately not enabled**, for the reason this rule exists: a
linter sees the shape and not the path, so it would flag the correct
`after_cancel` cleanup and the wrong shutdown identically. A gate that
fires 74 times on the day it is switched on teaches everybody to ignore
it, which is how the next fault 29 gets through.
