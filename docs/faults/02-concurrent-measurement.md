---
type: fault
fault: 2
title: "Concurrent measurement never enabled"
found_by: "reading the originals"
---

# 2. Concurrent measurement never enabled

*Found by reading the originals.*

With `[:SENSe]:FUNCtion:CONCurrent` off, only one function is measured
and the other field of the reply is filled from the **source setting**.

Source 1 V and the voltage column reads back exactly 1.000000 V — the
number you asked for, not the number across the sample. Lead and contact
drops vanish, and **a 4-wire rig silently returns a 2-wire
measurement.**

Deviation 14. See [[../instruments/gwinstek-gsm20h10]].
