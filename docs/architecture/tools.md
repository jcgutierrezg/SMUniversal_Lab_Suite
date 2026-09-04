---
type: reference
title: "The tools"
---

# The tools

Six standalone programs under `tools/`, plus the documentation
generator. Each answers one question, and the useful way to hold them is
by which question.

| Tool | The question it answers |
|---|---|
| `visa_doctor.py` | *Why can't I see it?* — the instrument is plugged in, powered, and absent from the dropdown |
| `scpi_console.py` | *What does it say to this one command?* |
| `smu_checkup.py` | *Is this driver right about this instrument?* — tiered commissioning |
| `bench_probes.py` | *The specific questions no manual answered* — a prepared list per instrument |
| `timing_scan.py` | *Is the timing model even true?* |
| `bench_envelope.py` | *How fast can I poll and stay quiet, and where does the commanded sign stop being commanded?* |
| `bench_readback.py` | *Does this query report the instrument, or repeat the question?* |
| `make_goldens.py` | Regenerate `tests/golden/*.json` after a deliberate method change |
| `build_docs.py` | Rebuild the generated documentation pages |

## `smu_checkup.py` — the one that matters most

Ten of the twenty-one faults were found by running finished drivers
against real instruments, and none of them are reachable from the
offline suite: they are all cases of **an instrument disagreeing with a
reasonable assumption**, rather than code disagreeing with itself.

That is what this tool exists to find, and why a driver's status is
derived from when it was last run — see [checkup-owed](../open/checkup-owed.md).

Nothing needs connecting to the outputs. It takes about three minutes.

```powershell
uv run tools/smu_checkup.py --address <address> --trace
```

## `timing_scan.py` — and why it refuses two points

It requires **at least three points and prints the residuals**, because
a two-point fit has zero degrees of freedom: it passes through both
points by construction, cannot fail, and cannot be checked.

Two earlier "confirmations" of the miniSMU's timing model were two-point
fits, and both were wrong. See
[Undalogic miniSMU MS01](../instruments/undalogic-minismu.md#bench-findings).

## Tools need the same scrutiny as the code they check

Two faults in this list were **in the tools**, not in the drivers:
`scpi_console.py` had been unusable against the TSP instruments from the
start ([A diagnostic tool with the fault it diagnoses](../faults/20-a-tool-with-the-fault-it-diagnoses.md)), and the
checkup — not the experiments — carried the source-function ordering
fault ([Output state assumed across a source-function change](../faults/14-output-across-function-change.md)).

A tool that produces evidence is part of the evidence.


## `bench_readback.py` — the one that needs a person

Run after `smu_checkup.py`, on the same connection.

`core/readback.py` has five states, and two of them look identical in
the reply. `unverified` and `confirmed` both mean the instrument agreed
with what it was asked for; what separates them is whether anyone has
established that the query reads hardware rather than replaying the last
value written to it.

Over the bus those two are indistinguishable, and asking more often does
not separate them — the driver would be putting a question where it
already knows the answer. So the first leg is a range **dialled in by
hand**: a value that never crossed the bus, which a query can only
report by reading the instrument.

Two more legs follow, both bus range changes, and they are not padding.
A query that returns a constant passes leg 1 whenever the constant
happens to match. A query that latches the first value it ever saw
passes leg 1 *and* leg 2. Each leg exists because it is the only one
that catches its own case.

The tool sets no flags. It prints what one session with one unit
established; whether that supports a standing `*_READBACK_TRUSTED` claim
about a model is a person's call.

## `bench_envelope.py` — the two questions one fixture answers

Run after `smu_checkup.py`, on the same connection and the same load.
The procedure is [One pass per instrument](../../bench/one-pass-per-instrument.md).

**The envelope** is a curve, not a number. The per-reading figure in
`bench/choosing-an-smu.md` says how long a reading takes; this says how
fast you can poll while keeping the noise you can live with, one row per
rung of the NPLC ladder.

It reports **relative standard deviation**, where `timing_scan.py`
reports peak-to-peak. Both are right for their own question. Peak-to-peak
answers *"is this instrument integrating at all?"*, where a thirtyfold
change is unmissable however it is measured. It is a poor way to compare
instruments, because it is set by the single worst sample and grows with
the burst length, so an instrument scanned harder looks noisier.

**The sub-count pass** halves the commanded level down and asks whether
`+X` and `-X` still read differently. Two conditions have to hold before
it says the sign is commanded: the groups must be separated by more than
their own scatter, *and* by more than the level asked for. The second is
the load-bearing one — with a quiet instrument the scatter approaches
zero and any difference at all clears the first, which an offline fake
demonstrated by manufacturing exactly that.

**The reading noise is the detection limit and is not the source
floor.** A crossing found below the noise is a statement about the
measurement. Compare it against the envelope's RSD at the same NPLC
before recording it as a converter count.
