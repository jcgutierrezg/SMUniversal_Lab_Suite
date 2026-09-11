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
report by reading the instrument. The tool reads the range *first* and
refuses a hand-set range equal to it, because a query that never moves
would name that one too.

Two more legs follow, both bus range changes, and they are not padding.
A query that returns a constant fails leg 1 now that the hand-set range
must differ from the one before, but a query that latches the first
value it is *told* passes leg 1 *and* leg 2. Each leg exists because it
is the only one that catches its own case.

Ranges are compared by the range the reply **names**, using the
checkup's own rule, not by its digits: the Keithley and GW Instek
families report full scale 5% above the nominal decade, so the 1 A range
answers `1.05`. The first version compared digits and stopped two
instruments at leg 1 on correct answers.

Each range is put to its legs while sourcing the quantity under which it
is a setting of its own — a measurement range while sourcing the *other*
quantity, because on the 2400 family the sourced quantity's reading comes
back from the source and its range is refused (error 823). The bus legs
pick the narrowest ranges, which sit under any compliance in force, and
read the error queue after each write: a query that keeps reporting the
range that survived a refused write is inconclusive, not lying.

Compliance and power limits need no panel. Two bus writes must be
followed, then the tool writes ten times the model's maximum. A query
that reports the value that *survived*, with an error queued, is
reporting the instrument's state rather than the last write; one that
reports the refused value is repeating the question. An instrument that
simply takes the value leaves nothing to tell apart, and the verdict
says so. The setting is put back however the check ends — for the
2635B's power ceiling that matters, because a nonzero one left behind
overrides the compliance of every run after it.

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
`+X` and `-X` still read differently. The legs must land on opposite
sides of zero, be separated by more than their own scatter, and by
between half and three times the separation asked for. Every range it
depends on is set through `RangePlan.for_sourcing`, including the
quantity it is not reading, so nothing is inherited from the axis
before; it runs at a stated NPLC rather than the envelope's last rung.

Three checks guard the verdict itself, each from a 2026-09-11 run:

- **Settling.** Readings are discarded after every step, and at the
  control the count is doubled until the output stops moving. At 1 PLC
  the U2722A read 71% of every command, and the window passed it.
- **Control accuracy.** At the control level the reading must be
  within 5% of the command; no count or offset explains more.
- **A halving that changed nothing.** If neither leg moved by half of
  what the halving asked, that level fails whatever its signs say. The
  2401 reported such a level as its floor on two separate days.

Each row records the midpoint of its two legs — the output's zero
offset on that range — because that turned out to be what the crossing
measures: the legs straddle zero exactly while the level is larger than
the offset. It is a lower bound, too. The instrument is measuring its own
output, and an offset shared by its source and measure paths does not
show in its own readings at all.

**The reading noise is the detection limit and is not the source
floor.** A crossing found below the noise is a statement about the
measurement. Compare it against the envelope's RSD at the same NPLC,
and against the offset, before recording it as anything.
