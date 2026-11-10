---
type: fault
fault: 48
title: "A drain that was doing a second job"
---

# 48. A drain that was doing a second job

## Symptom

After 1.0.11 reached `main`, every IV sweep on the GW Instek GSM-20H10
ended with "Output shutdown not confirmed": `instrument reported 824:
Cannot exceed compliance range`, and the instrument blocked until it was
reconnected. Its checkups passed, twice, the same day. The same sweeps
had ended cleanly on the `main` before the merge.

## Cause

The GSM-20H10 and the Keithley 2401 refuse a measurement range wider
than the compliance already in force. Their drivers send the range, then
the limit, then the range again, so the second send meets the
compliance the run chose (`_resend_measure_range`). The first send's
refusal is logged as `+824` and stays in the error queue.

`confirm_output_off()` reads the error queue after switching the output
off, and treats anything in it as a possible sign that output-off was
rejected. On this instrument nothing reads the queue mid-run: a query at
the wrong moment goes unanswered and latches the link.

What had been emptying the queue was the GSM-20H10's hardware
staircase, which drained it before arming each sweep - for its own
setup check, not for this. When 1.0.8 retired the staircase and stepped
the sweep from the PC, the drain went with it, and the `+824` from
every run's setup survived to the shutdown check.

## Risk

Every sweep on the instrument ended as an uncertain shutdown and
blocked further runs: the instrument was unusable for IV work. The
reverse risk is the one the shutdown check exists for - an output-off
the instrument did not act on - and it is unchanged: any other code in
the queue still makes the shutdown uncertain.

The 2401 has the same re-send and has always stepped its sweeps from
the PC, so it was exposed in the same way.

## Detection

Not by the checkup, which reads the queue after every step it takes,
so nothing it provokes is left for the end. Not by the tests: the shared
fake GSM transport does not refuse a wider range, and the one that does
was only ever used for the range itself, never run through to the
shutdown. Found on the bench, on the first IV sweep after the merge.

## Prevention

A driver can name error codes an output-off command cannot raise, with
the reason, in `ERRORS_NOT_FROM_OUTPUT_OFF`. `confirm_output_off()`
notes those entries in the log and the shutdown detail, and confirms
the shutdown if nothing else is in the queue. The GSM-20H10 and the
2401 name `824`, a range refusal; switching the output off sends no
range. Every other code still makes the shutdown uncertain, and so does
`824` from a driver that has not named it.

The general lesson: when removing a code path, list what it did besides
its stated purpose. The staircase's drain was there for its own setup
check, and the shutdown check had come to depend on it.

## Status

Closed in the change that adds `ERRORS_NOT_FROM_OUTPUT_OFF`. The GSM-20H10
and 2401 need a checkup on the new driver code.

## Evidence

`tests/test_gsm_range_before_limit.py` and
`tests/test_2401_range_before_limit.py`
(`test_the_refusal_left_in_the_queue_does_not_make_shutdown_uncertain`)
run each driver's refusing fake through to `confirm_output_off()`;
`tests/test_run_control.py` covers the exemption and its limits.
