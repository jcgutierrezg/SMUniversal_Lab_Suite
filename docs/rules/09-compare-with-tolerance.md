---
type: rule
rule: 9
title: "Converted values are compared with a tolerance, never `==`"
---

# 9. Converted values are compared with a tolerance, never `==`

Measured, not assumed. A round trip through a power of ten is exact for
most doubles but not all. On realistic typed values — integers and one
or two decimals — `x/1e6` then `*1e6` fails to return `x` for about
**2.9%** of entries, and `x*1e-6` then `*1e6` for **28.7%**.
`core/units.py` uses the better one; the residue is inherent and no
arrangement of the arithmetic removes it.

180 µm typed in comes back as 179.99999999999997. Scientifically
irrelevant, legible enough to matter when someone opens the CSV. If a
test asserts on a geometry value that has been through the snapshot, use
`math.isclose`.
