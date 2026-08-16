---
type: fault
fault: 16
title: "One range list standing in for two"
found_by: "writing a driver from a manual"
---

# 16. One range list standing in for two

*Found by writing a driver from a manual.*

A driver declares `current_ranges` and everything assumes source ranges
and measure ranges are the same set. **On the 2635B they are not:** it
measures to 100 pA and sources only to 1 nA.

Offering a measure-only range as a sourced level gets it clamped to the
nearest sourceable one, and the derived resistance is then computed from
a current that was never sourced — no error, plausible number.

Check both directions in the manual before declaring `LIMITS`. The
2635B was the first instrument here where they differ, which is why the
conflation went unnoticed across every earlier driver.

Decision D15. See [[../instruments/keithley-2635b]], and
[[../instruments/undalogic-minismu]] for the same field holding
something that is not a range list at all.
