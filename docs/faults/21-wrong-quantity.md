---
type: fault
fault: 21
title: "Asking about the wrong quantity"
found_by: "running the drivers"
---

# 21. Asking about the wrong quantity

*Found by running the drivers.*

The B2901A's `compliance_tripped()` read `:SENS:CURR:PROT:TRIP?`
unconditionally. Compliance is always on the quantity you are *not*
sourcing — source current and a voltage limit clamps you — so that
question is right only when sourcing voltage.

Sourcing current, the current protection is genuinely untripped and the
instrument answered `0` **honestly, to the wrong question.** Van der
Pauw and Hall both source current, so on those two experiments the flag <!-- lint-ok -->
was `False` whatever the instrument was doing: not a silence, **a wrong
reassurance.**

Nothing could have caught it from the outside. The tests set a `tripped`
flag the fake returned regardless of mode, and the checkup only asked
with the output off. It took a probe on a real instrument riding a 1 V
limit into an open circuit.

The fix reads `:SOUR:FUNC:MODE?` and asks about the matching protection,
rather than tracking the mode locally — a remembered copy is one reset
or one front-panel press from being wrong, and being wrong here produces
a confident `False`.

Deviation 21. See [[../instruments/keysight-b2901a]].
