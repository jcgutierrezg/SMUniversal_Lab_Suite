---
type: fault
fault: 9
title: "Reconstructed x-axes"
found_by: "reading the originals"
---

# 9. Reconstructed x-axes

*Found by reading the originals.*

`np.arange(start, stop, step)` assumes the instrument hit every
requested level exactly. Read back what it actually sourced.

This is the fault with the widest reach, because a reconstructed x-axis
means the saved file describes the sweep that was *requested* — so every
instrument-side reason the real levels differ (rounding, range clipping,
a compliance clamp) becomes invisible in the one place you would look.

Deviation 4. See [IV sweep](../experiments/iv-sweep.md).
