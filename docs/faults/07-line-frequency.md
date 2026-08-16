---
type: fault
fault: 7
title: "Line frequency never set"
found_by: "reading the originals"
---

# 7. Line frequency never set

*Found by reading the originals.*

NPLC only cancels mains hum if the instrument knows the mains period, so
an integration time set without `:SYSTem:LFRequency` is worth less than
it looks.

Deviation 16. Note the 2611A's variant, which is the opposite trap:
writing `linefreq` explicitly **disables automatic detection
permanently**, in nonvolatile memory, so that driver reads first and
writes only on disagreement.
