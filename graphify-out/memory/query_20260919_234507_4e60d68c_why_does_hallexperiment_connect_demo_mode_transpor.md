---
type: "query"
date: "2026-09-19T23:45:07.959488+00:00"
question: "Why does HallExperiment connect demo-mode transport to shutdown safety, provenance and ownership?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["HallExperiment", "FourContactExperiment", "NullTransport"]
---

# Q: Why does HallExperiment connect demo-mode transport to shutdown safety, provenance and ownership?

## Answer

87 edges across 24 communities, but split by file kind it is 47 test-file edges against 40 production edges. The community placement in 'Null Transport And Demo Mode' is an artifact: NullTransport is the driver every GUI test connects, and Hall is the experiment most test files exercise (shutdown safety, lifecycle, combined window, ownership, clamp/progress, on-every-driver, on-a-load). Its real production coupling is narrow and local: inherits FourContactExperiment, uses HallParameters, RangePlan, Run, ValidationError, and the calculation layer (CalculationInput, InputValue, SourceRow, CalculationRefused) for the Van der Pauw sheet-resistance handoff. The bridge is test coverage, not architectural entanglement.

## Outcome

- Signal: useful

## Source Nodes

- HallExperiment
- FourContactExperiment
- NullTransport