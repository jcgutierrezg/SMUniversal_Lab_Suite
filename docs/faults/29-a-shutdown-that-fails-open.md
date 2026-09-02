---
type: fault
fault: 29
title: "A shutdown path that fails open"
---

# A shutdown path that fails open

## Symptom

The window closes. Nothing is reported. A heater on the sample stage is
still enabled, and the application that switched it on is gone.

Nothing about the close looked different from a clean one — no console
line, no dialog, no delay. The only way to find out is to walk back to
the bench and look at the stage.

## Cause

Three swallowed exceptions in `LabApp.on_close()` and
`shutdown_devices()`, each of the form:

```python
try:
    self.temp_ctrl.pid_off()
except Exception:
    pass
```

The port was then closed immediately afterwards, so there was no
opportunity to retry and no link left to ask over.

Underneath it, a second and quieter problem: `pid_off()` could not have
reported success even if the caller had wanted it to. The stage firmware
never acknowledges a command, so the method wrote `OFF` and returned
nothing. A write that returns without raising is evidence that the host
handed bytes to a serial port. It is not evidence that a heater stopped.

The same path never waited for measurement workers. `on_close()` asked
each experiment to cancel and then tore down transports immediately, so
a worker mid-cleanup could lose the shutdown and event-log state it was
in the middle of recording — and one experiment inherited a `on_close()`
hook that did nothing at all, so its worker was never asked to stop.

## Why it is dangerous

The three cheap arguments for a bare `except` on an exit path do not
survive contact with this one:

- *"There is nothing sensible to do about it."* There is: say so. The
  operator is standing next to the stage and can switch it off by hand,
  which is a thing they can only do if they are told.
- *"The process is exiting anyway."* The hardware is not.
- *"It has never failed."* A failure here produces no symptom in the
  software at all, so "never failed" and "never noticed" are the same
  observation.

An exit path is the *worst* place for a silent failure, not the most
excusable one, because it is the last moment anybody is looking.

## The rule

**A step that puts hardware into a safe state must return whether it
succeeded, and a caller that cannot confirm it must say so before it
disappears.**

That means:

- the de-energise reports a value (`StageShutdownReport`,
  `ShutdownReport`) rather than the absence of an exception;
- the confirmation asks a question whose answer was *not* already fixed
  before it was asked — the stage's confirmation waits for a status line
  broadcast **after** the OFF, because the most recent line before it
  says only what the board was doing a moment ago (see
  [A probe asked where the answer is already known](19-non-discriminating-probe.md));
- an unconfirmed shutdown produces a modal warning that outlives the
  window, not a console line the window destroys on its way out (see
  [A dialog nobody stubbed, on a machine that never showed it](28-a-dialog-nobody-stubbed.md));
- the close path waits, **bounded**, for every worker to reach idle
  before disconnecting anything, pumping the UI queue while it waits —
  a main thread that blocks without draining is waiting on work it is
  itself holding up (see [`app.ui()` is a queue, not a direct callback](../rules/08-ui-is-a-queue.md)).

Bounded matters as much as waiting does. A close that can hang is
answered by killing the process, and that skips every de-energise the
path exists to perform.

Where a suppression on a cleanup path is genuinely right, it carries a
one-line comment naming the invariant that makes it safe — a timer id
Tk has already forgotten cannot fire, so failing to cancel it leaves
nothing scheduled.

## Check

For any teardown step, ask the two questions separately:

1. *Did the command leave?* An exception answers this.
2. *Did the hardware do it?* Only the hardware can answer this, and on a
   device that does not acknowledge, only its next unsolicited report
   can.

If the code cannot distinguish them, it is reporting the first and
implying the second.

## Where it is guarded

`tests/test_shutdown_safety.py` injects each ending in turn: a PID write
that fails at the port, a board that keeps reporting `HEATING` after the
OFF, a link that goes quiet between the last status line and the write,
a stage object that raises out of its own shutdown call, and a worker
still parked when the cleanup budget expires. Each asserts what the
operator is told.

`tests/test_temperature.py` covers the controller's own decision against
a fake port, including the case that matters most: a board that was
already reporting `IDLE` and then goes silent must be UNCERTAIN, not
CONFIRMED.
