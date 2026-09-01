---
type: fault
fault: 26
title: "A fault injected below the layer under test"
---

# A fault injected below the layer under test

## Symptom

A test that injects a failure and asserts the code handles it, passing
on the first attempt, for a code path that does not exist yet. It looks
like confirmation that a feature works. It is a report that nothing was
tested.

Observed 2026-08-27, twice in one afternoon, while writing the
end-to-end test for a link that stops answering mid-run. The test armed
a transport to raise on every read, started a real IV sweep, and
watched the run **complete normally** — five readings, no error, the
run recorded as `COMPLETED`.

## Cause

The fault was injected into a component the code under test never
reached.

The app was built in demo mode, which pairs `DummySMU` with
`NullTransport`. `DummySMU` fabricates readings arithmetically and never
calls `transport.query()` at all. Arming the transport to fail was
arming something that was not in the circuit.

The second attempt fixed the driver but not the method: readings were
routed over the link through `measure()`, while the IV sweep polls
`sweep_points_ready()`. Same shape of mistake one level down.

The third attempt found that the run failed but the shutdown still
reported CONFIRMED, because `read_error()` — the query
`confirm_output_off()` uses to decide whether it may say "confirmed" —
was still being answered by the fake rather than by the link.

Each version was wrong in the same way: **the injected fault and the
behaviour under test were connected by an assumption rather than by a
call.**

## Why it is dangerous

An ordinary broken test fails and gets fixed. This one *passes*, and
the passing is the whole problem — it is indistinguishable from the
feature working, so it gets committed, and from then on it is a green
line in CI standing guard over nothing.

It is the same fault as an assertion that would hold whether or not the
command worked, which this project has hit repeatedly. The difference is
that a non-discriminating assertion is visible in the assertion, and
this one is invisible in both the assertion and the setup. Only the
wiring between them is wrong.

## Check

Before trusting a fault-injection test:

1. **Break it on purpose and watch it go red.** Not the code under
   test — the *injection*. If the test still passes with the fault
   armed and the handling removed, the fault is not reaching the
   handling.
2. **Name the call chain out loud**, from the injected component to the
   assertion. If any link in it is "and then the driver presumably
   queries", go and read that method.
3. **Ask which method the code under test actually calls.** Not which
   method sounds like the one it calls. `measure()` and
   `sweep_points_ready()` both look like "take a reading".
4. Prefer injecting at the **narrowest point the real code passes
   through**, and prove it passes through there by grep rather than by
   memory.

## Where it is guarded

`tests/test_link_lost_during_a_run.py` routes exactly the four calls the
run makes — `sweep_points_ready`, `read_sweep`, `read_error` and
`measure` — over a transport it can arm, and each is commented with why
it is on the list. The file's mutation round is what establishes that
the wiring works: reverting the transport latch, reverting the
`UNCERTAIN` shutdown, or refusing writes on a poisoned link each turn it
red.
