---
type: fault
fault: 3
title: "NAN and overflow sentinels treated as data"
found_by: "reading the originals"
---

# 3. NAN and overflow sentinels treated as data

*Found by reading the originals.*

"No reading" comes back as a *number*: `+9.91e37` for NAN, `+9.9e37` for
over-range. Nothing raises.

One of these in a sweep dominates the least-squares sum entirely, so the
fit runs to that single point **while still reporting a healthy R².**

Handled in `BaseSMU.drop_sentinel()`, which replaces in place rather
than filtering — dropping a value by omission shifts every later column
left and promotes the current into the voltage's position.
`tests/test_sentinel_handling.py` discovers drivers from the registry,
so a new driver cannot quietly opt out.

Deviation 17. See [[../instruments/gwinstek-gsm20h10]],
[[../instruments/keithley-2635b]].
