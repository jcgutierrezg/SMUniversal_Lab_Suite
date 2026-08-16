---
type: fault
fault: 5
title: "Sweep completion slept rather than polled"
found_by: "reading the originals"
---

# 5. Sweep completion slept rather than polled

*Found by reading the originals.*

`sleep(round(points * delay * 1.3))` reads a partly-filled buffer on
short sweeps and **silently returns fewer points than requested.**

`round()` also puts the wait on a whole-second grid, so a 10-point 0.1 s
sweep waited 1 s rather than 1.3 s. And the original's `waitcomplete()`
was sent with `write()` and never read back, so it never blocked the
host at all — that sleep was the *only* thing between firing the sweep
and reading the buffer.

Poll the instrument's own count. Deviation 3. See [[../experiments/iv-sweep]].
