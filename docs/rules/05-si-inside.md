---
type: rule
rule: 5
title: "Units: SI inside, convert only at the edges"
---

# 5. Units: SI inside, convert only at the edges

Three lines, and `tests/test_parameters.py` enforces the second.

1. **Internally, everything is SI base.** Amps, volts, seconds, metres,
   tesla, ohms, kelvin. Not millimetres, not gauss, not milliseconds.
2. **Every numeric field of a parameter or result object names its
   unit**: `settle_s`, `thickness_m`, `field_t`, `compliance_v`. A
   dimensionless count takes `_n` — `points_n`, `reversals_n` — which is
   an explicit statement that there is no unit rather than an omission
   that might mean anything. The suffix table is
   `core.units.UNIT_SUFFIXES`; add to it before inventing a suffix.
3. **Convert at the boundary and nowhere else.** The panel parses what
   the operator typed into SI on the way in. Where a downstream module
   wants something else — `fourpp_math` takes mm and µm, because the
   Ossila correction tables are published that way — the conversion goes
   in one named method on the parameter object, not inline at the call
   site. See `FourPointProbeParameters.as_math_geometry()`.

`test_every_numeric_field_declares_its_unit` walks every class in
`PARAMETER_CLASSES`. **Add new parameter classes to that list** or they
are not covered.

Why it earns a rule: the original Van der Pauw notebook mixed seconds
and milliseconds in one settle delay (deviation 1), and the 4PP original
labelled `Rs × t` in millimetres as `mΩ/m` (deviation 10). Neither
raised anything.
