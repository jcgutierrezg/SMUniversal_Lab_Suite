---
type: fault
fault: 10
title: "A command in the manual but not on the instrument"
found_by: "reading the originals"
---

# 10. A command in the manual but not on the instrument

*Found by reading the originals.*

SCPI instruments log unrecognised commands and carry on. Nothing raises,
and **the previous setting stays in force.**

Where a spelling is inferred rather than documented, send it and then
read `SYST:ERR?` — see the GSM's `_probe_sweep_support()`. Confirmed on
the bench: `:ABOR` exists on the 2400 family and is rejected by the GSM
with `-113 Undefined header`.
