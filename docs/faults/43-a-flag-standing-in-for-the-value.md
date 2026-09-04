---
type: fault
fault: 43
title: "A flag read instead of the value it flags"
---

# 43. A flag read instead of the value it flags

## Symptom

The instrument is asked whether it is in compliance, answers honestly,
and the answer is useless for the question actually being asked. Every
check passes. The compliance protecting the sample is not the one the
experiment set.

On 2026-09-04 the 2611A, 2635B and B2901A all passed both compliance
probes - `False` with the output off, `True` while riding the voltage
limit - on the same run where the report said each *does not report its
compliance*. Both statements were true, about two different queries.

## Cause

A trip flag is a predicate on one bit of state: *was a ceiling reached*.
It is not a readback of the ceiling. So it is blind to the failure that
matters most, which is the ceiling moving:

- **U2722A, 2026-08-24.** A range change took a 100 µA compliance to
  12 mA with a clean error queue. Nothing was clamping before or after,
  so the trip flag read `False` throughout - correctly - while the
  protection around the sample widened by a factor of 120.
- **GSM-20H10, 2026-08-20.** `SOUR:CURR:RANG:AUTO ON` while sourcing
  voltage silently resets the current compliance from 105 µA to 1 nA.
  Again nothing trips; the run simply proceeds against a limit nobody
  chose.

On the 2635B the flag is weaker still. `source.compliance` there covers
the voltage, current **and** power limits together, so a `True` means "a
ceiling was reached" and cannot say which - and `limitv` reports the
programmed value rather than the effective one when `limitp` is enabled,
so even reading one limit back does not settle it.

The reason a flag gets accepted as coverage is that it is the *loud*
half. A clamp is dramatic and produces a visibly flat curve; a widened
limit produces nothing at all until something is damaged.

## Risk

The two failures are not symmetric and the flag catches the recoverable
one. A clamped sweep is a wasted run: the fit describes the limit rather
than the sample, and it is at least visible in the data afterwards. A
compliance that widened behind the software's back is a sample at a
current nobody authorised, with no trace in the data, the error queue or
the log.

Having the flag makes it worse rather than better, because the subject
now appears in the report with a pass beside it.

## Detection

For every guard the software relies on, ask whether the code reads **the
guard's setting** or **an event derived from it**. An event answers "did
this happen"; only the setting answers "is the bound the one I set".

The discriminating probe is not a clamp. Move the limit behind the
driver's back - which is what a range change does on two instruments
here - and ask both questions. The flag will say `False` and the
readback will say `mismatched`.

## Prevention

Read the value, and treat a disagreement as a safety event whether or
not the readback itself has been verified. `verify_compliance()` returns
`mismatched` on any disagreement; trust gates only what *agreement* is
worth. See [core/readback.py](../architecture/module-map.md).

The flag stays. It answers a real question - a run in compliance is
worth flagging while it happens - and the two are recorded as separate
capabilities in the contract ledger (`compliance_trip` and
`compliance_readback`) so that having one can no longer look like having
both.

## Status

Closed on the 2401, 2611A, 2635B and B2901A, which now read the limit as
well as the flag. None of those readbacks is trusted yet; each is
`unverified` until a bench session compares it against a compliance the
instrument was known to be holding. Genuinely open on the miniSMU, whose
vendor library exposes neither.

## Evidence

`D:\SMU_Checkups\20260904\` for the three instruments passing the flag
probes while reported as unable to report a compliance; bench sessions
2026-08-24 (U2722A) and 2026-08-20 (GSM-20H10) for the two mechanisms
that move a limit without tripping anything.

This is [Asking about the wrong quantity](21-wrong-quantity.md) with the
quantity right and the *kind* of answer wrong.
