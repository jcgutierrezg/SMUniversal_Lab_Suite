---
type: fault
fault: 17
title: "A default that is never sent is a default nobody chose"
found_by: "writing a driver from a manual"
---

# 17. A default that is never sent is a default nobody chose

*Found by writing a driver from a manual.*

Distinct from [[06-inherited-state]], which is about state inherited
from a previous *run*. This is state inherited from the factory.

`format.asciiprecision` resets to 6 significant figures on every 2600B —
below what the Hall measurement needs — and **no driver in this suite
had ever set it.** It arrives as slightly-wrong data rather than as an
error.

Where a reset default is load-bearing, send it explicitly **even when it
already has the value you want**, because firmware revisions move
defaults. Several writes in the 2635B's reset are no-ops against current
firmware and are kept for exactly that reason.

Decision D14. See [[../instruments/keithley-2611a]],
[[../instruments/keithley-2635b]].
