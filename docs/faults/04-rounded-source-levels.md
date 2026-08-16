---
type: fault
fault: 4
title: "Source levels rounded before sending"
found_by: "reading the originals"
---

# 4. Source levels rounded before sending

*Found by reading the originals.*

`round(V, 4)` quantises to 100 µV, invisible at ±1 V and catastrophic at
±100 µV: **21 requested points collapse to 3 distinct levels while the
saved x-axis still claims 21 evenly spaced values.**

The damage is invisible afterwards, because the file records what was
asked for rather than what was sourced — which is why this fault and
[[09-reconstructed-x-axes]] compound each other.

Deviation 12 and the 2401 note. See [[../instruments/keithley-2401]].
