---
type: fault
fault: 20
title: "A diagnostic tool with the fault it diagnoses"
---

# 20. A diagnostic tool with the fault it diagnoses

## Symptom

Every result after the first `print(...)` off by one, silently, each
looking plausible.

## Cause

`tools/scpi_console.py` decided which lines produce a reply by looking
for `?`. TSP has no query punctuation - a 2600B answers when the script
calls `print()` and stays silent otherwise - so every `print(...)` was
sent as a write. The instrument still generates the reply, so it sits in
the output buffer and **the next real query reads the previous line's
answer.**

## Risk

**Tools that produce evidence need the same scrutiny as the code they
produce evidence about.** A diagnostic that is wrong is worse than no
diagnostic: its output is treated as a measurement.

The console had never been usable against the TSP instruments, and the
fault was found only because a TSP probe script was written for the
first time.

## Detection

Run the tool against an instrument whose answers are already known from
another path, and compare. Punctuation is not a protocol.

## Prevention

Decide read-versus-write from the dialect, not from the text of the
command. See
[Sweeps and transports](../architecture/sweeps-and-transports.md) on the
request/response assumption.

## Status

Closed.

## Evidence

Found while writing the tools. The same lesson arrived independently as
[Output state assumed across a source-function change](14-output-across-function-change.md),
where the checkup rather than the experiments carried the fault, and
again as
[A test level the instrument cannot express](34-a-probe-the-instrument-cannot-express.md).
