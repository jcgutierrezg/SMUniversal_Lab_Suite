---
type: fault
fault: 1
title: "`MEAS?` used per point"
found_by: "reading the originals"
---

# 1. `MEAS?` used per point

*Found by reading the originals.*

On the 2400 family and its relatives, `MEAS?` is `:CONFigure` followed
by `:READ?` — it resets ranging and compliance to `*RST` values on
**every point**, undoing whatever was set beforehand. On the GSM it also
turns the output on.

Found in the 2401 original and again in the 20H10 one. Use `:READ?`
against the configuration already in place.

Not universal: the B2901A's `:MEAS?` is documented as measuring with the
conditions already set, and is used deliberately there — partly because
`:READ` and `:INIT` are the two commands that trigger its automatic
output-on.

Deviation 11. See [[../instruments/gwinstek-gsm20h10]],
[[../instruments/keithley-2401]], [[../instruments/keysight-b2901a]].
