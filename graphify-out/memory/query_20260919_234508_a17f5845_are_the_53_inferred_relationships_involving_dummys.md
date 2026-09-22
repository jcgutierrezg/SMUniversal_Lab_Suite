---
type: "query"
date: "2026-09-19T23:45:08.498122+00:00"
question: "Are the 53 inferred relationships involving DummySMU actually correct?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["DummySMU", "SMULimits"]
---

# Q: Are the 53 inferred relationships involving DummySMU actually correct?

## Answer

Yes, and they are all one relation: every one of the 53 INFERRED edges is 'uses', and 52 of the 53 point at test files. Spot-checked four against the source: tests/test_checkup.py subclasses DummySMU for fault injection (Talkative at L596), tests/test_4pp_lifecycle.py passes smu_cls=DummySMU (L234, L446), tests/test_bench_readback.py subclasses it in driver_with() (L62). The single production edge is DummySMU.LIMITS = SMULimits(...) at dummy_smu.py L49, which is an EXTRACTED-strength fact marked INFERRED. Low risk: the inference is 'the test constructs this driver', which is true, so the confidence tag is conservative rather than wrong.

## Outcome

- Signal: useful

## Source Nodes

- DummySMU
- SMULimits