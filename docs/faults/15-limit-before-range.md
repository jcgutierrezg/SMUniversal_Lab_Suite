---
type: fault
fault: 15
title: "A limit sent before the range that has to hold it"
found_by: "running the drivers"
---

# 15. A limit sent before the range that has to hold it

*Found by running the drivers.*

On the U2722A a compliance value is **clamped to the range active when
it arrives**, and `*RST` leaves the smallest range selected. The limit
was accepted, silently clamped, and the sweep ran with a compliance a
hundred times lower than asked for.

Widen the range first. This is now a formal requirement of the ranging
contract rather than a habit — see [[../architecture/ranging]].

Checked and found absent on the 2635B, whose `source.limitY` page states
the SMU always autoranges for the limit setting.

Deviation 21. See [[../instruments/keysight-u2722a]].
