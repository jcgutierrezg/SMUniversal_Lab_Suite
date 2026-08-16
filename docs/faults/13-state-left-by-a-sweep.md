---
type: fault
fault: 13
title: "State left behind by a sweep"
found_by: "running the drivers"
---

# 13. State left behind by a sweep

*Found by running the drivers.*

The GSM's staircase sets `TRIG:COUN` to the sweep length and puts the
source in `MODE SWE`. Neither was restored, so the next single reading
took N times as long and **the next level-set was read as a sweep
endpoint** — the software fallback meant to rescue a failed sweep
returned five points, no error, every one at 0 V.

Anything a sweep changes, a sweep must put back.

Deviation 44. See [[../instruments/gwinstek-gsm20h10]].
