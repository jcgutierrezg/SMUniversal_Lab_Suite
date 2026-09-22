---
type: "query"
date: "2026-09-19T23:45:07.424145+00:00"
question: "Why does TransportDesynchronised bridge the checkup machinery to all seven driver communities?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["TransportDesynchronised", "CheckupBase", "BaseInstrument"]
---

# Q: Why does TransportDesynchronised bridge the checkup machinery to all seven driver communities?

## Answer

Traversed by exact node lookup on graph.json (not the substring matcher): 80 edges across 23 communities. It is the desync latch exception in core/transports/base.py - raised when a query fails after its command was committed, and on every query after that until reconnect. It bridges because it is the one failure every layer must refuse to absorb: the checkup tiers (base/load/tier1/tier2/tier3) catch it at 20+ sites, 9 of the 15 driver files catch it, run_control.confirm_output_off catches it, and the bench tools import it. Verified in code: the GSM-20H10 ran 1386 further queries in the desynchronised state on 2026-08-25, which is the incident the class docstring records.

## Outcome

- Signal: useful

## Source Nodes

- TransportDesynchronised
- CheckupBase
- BaseInstrument