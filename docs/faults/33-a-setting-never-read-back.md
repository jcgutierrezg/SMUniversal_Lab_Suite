---
type: fault
fault: 33
title: "A setting reported from the command that was sent"
---

# 33. A setting reported from the command that was sent

## Symptom

The software says the instrument is on a 100 µA measurement range with a
100 µA compliance. The instrument is on 10.5 µA with a 1 nA compliance.
Nothing raised, the error queue is clean, and the run proceeds - drawing
a tidy curve bounded by something nobody chose.

Two measured cases, on two different instruments:

- **GSM-20H10, 2026-08-20.** `SENS:CURR:DC:RANG 1.000000e-04` with a
  10 µA compliance in force answers `+824` and leaves
  `SENS:CURR:DC:RANG?` reading `1.050000E-05`. Every reading afterwards
  is taken on a range the operator did not choose, and overranges into a
  sentinel rather than reading.
- **U2722A, 2026-08-24.** A range change moved a 100 µA compliance to
  12 mA with a clean error queue - the protection around somebody's
  sample widened by a factor of 120, and the only place it appeared was
  a readback nobody was making.

## Cause

`apply_ranges()` returned a description built from the values it had
been handed, not from anything the instrument said. So did every
compliance setter before 2026-08-20. The description is *what was
requested*, rendered in the past tense.

That is not a bug in the rendering. It is the absence of a question. A
wrong or refused setting is not an exception on any instrument in this
suite: SCPI logs it and carries on with the previous value, TSP takes
whatever the attribute will hold. The write succeeding is evidence that
the link works and nothing else.

The trap underneath it is that *reading a setting back is not
automatically better*. `OUTP?` on the GSM-20H10 returns 0 with the
output demonstrably on and 10 V flowing. A readback that lies produces
confident reassurance about the exact thing it exists to verify, which
is worse than no readback at all - five rounds of reasoning on that
instrument were built on believing it.

## Risk

The question has more than two answers, and a contract that offers only
*agreed* / *disagreed* will be forced to file "nobody asked", "asked and
got nothing", and "asked, and the asking has never been checked" under
one of them. All three get filed under *agreed*, because that is the one
that does not stop the run.

## Detection

For every setting the software relies on, ask which of the five states
the code can currently produce. If the answer is "two", the other three
are being silently filed under one of them.

Then ask the fake the same question. A readback check is untestable
against a model that always answers what was written: it cannot produce
a value on the wrong side, so no test above it can fail. The fakes in
this suite now select the range that *contains* a written value and
report that range's full scale, which is what the instruments do - and
what makes a silently narrowed range distinguishable from a correct
answer.

## Prevention

**A setting that matters is read back, and the answer has five states,
of which exactly one is a pass.** `core/readback.py` names them:
`unsupported`, `unreadable`, `unverified`, `confirmed`, `mismatched`.
Only `confirmed` renders as a pass, and it requires both an answer that
agrees *and* a bench session behind the readback itself.

Two consequences worth stating separately, because both are easy to
write backwards:

**Disagreement is never downgraded by doubt.** An *unverified* readback
that disagrees is a `mismatched`, not an `unverified`. Trust governs
what agreement is worth and nothing else - if the readback is honest the
instrument is holding a value nobody chose, and if it is dishonest the
software is steering a sample using a query that lies. There is no third
reading under which everything is fine.

**A query nobody has confirmed is not sent.** An unrecognised *command*
is logged and ignored; an unrecognised *query* is never answered, times
out, and latches the transport. So a guessed spelling costs a run rather
than a line in a report, and `unsupported` - naming the query somebody
should try at the bench - is the honest answer until then.

## Status

The contract is closed; the per-driver spellings are not. Range readback
is implemented on the 2611A, 2635B and GSM-20H10 and `unsupported` on
the 2401, 2450, B2901A and miniSMU; no range readback anywhere is yet
`TRUSTED`. See [technical debt](../open/technical-debt.md).

## Evidence

Bench sessions 2026-08-20 (GSM-20H10) and 2026-08-24 (U2722A).

This is [A probe asked where the answer is already known](19-non-discriminating-probe.md)
applied to a setting rather than to a measurement, and
[A bound checked on one side only](25-a-bound-checked-on-one-side.md)
applied to a state rather than to a number.
