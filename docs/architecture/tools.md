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
