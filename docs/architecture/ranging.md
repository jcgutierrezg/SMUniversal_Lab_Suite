---
type: reference
title: "The ranging contract"
---

# The ranging contract

`core/ranges.py`. `RangePlan` states ranging intent **once and in full**,
for all four axes, before anything energises.

## The four axes

An SMU has two quantities and two directions, so it has four ranges:

|  | current | voltage |
|---|---|---|
| **source** | `:SOUR:CURR:RANG` | `:SOUR:VOLT:RANG` |
| **measure** | `:SENS:CURR:RANG` | `:SENS:VOLT:RANG` |

Before Wave 6d there were two methods, `set_current_range()` and <!-- lint-ok -->
`set_voltage_range()`, documented as setting a *measurement* range — <!-- lint-ok -->
and the 2450 driver's `set_current_range()` sent a *source* range. <!-- lint-ok -->
4PP and Van der Pauw called it as though it meant source; IV sweep
called it the documented way.

**Nothing produced a wrong number**, because the mismatches cancelled on
the instruments actually in use. That is the least reassuring reason for
a defect to be invisible: it was correct by coincidence, and the
coincidence was one new instrument away from ending.

Both methods are now deleted. A lint in `tests/test_docs.py` refuses any
note that describes them as live, so the old account cannot come back.

## Range before limit

**A compliance may only be set after the range that has to hold it.**

On the U2722A a limit is clamped to whatever range is active when it
arrives, and `*RST` leaves the smallest range selected — so a limit set
first was accepted, silently clamped, and the sweep ran a hundred times
below what was asked for. See [A limit sent before the range that has to hold it](../faults/15-limit-before-range.md).

This started as a workaround inside one driver and is now a requirement
of the contract, because a rule that lives in one driver protects one
instrument.

## `for_sourcing()` makes one mistake unrepresentable

**The measurement range of the quantity being sourced must never be
set.** The 2401 and the GSM-20H10 both reject it with error 823,
*"Invalid with source read-back on"* — the instrument already knows what
it is sourcing, and asking it to measure that quantity on a chosen range
is a contradiction.

`RangePlan.for_sourcing()` constructs a plan in which that axis cannot
be populated. The forbidden combination is not avoided by discipline; it
cannot be expressed.

## AUTO on instruments without autoranging

The U2722A has no autorange. `AUTO` there selects **the widest available
range** rather than refusing, because the alternative — an experiment
that works on every other instrument and raises on this one — pushes
instrument-specific handling back up into the experiments, which is the
thing the driver layer exists to prevent.

`None` is not a range, and is refused as one. It used to mean "auto" by
convention at some call sites and "leave it alone" at others.

## Every driver rounds up

Checked across all of them before house rule 12 began sizing ranges to
the largest magnitude a run will source. The failure mode if any driver
rounded *down* would be a clamped source level — which is
[Source levels rounded before sending](../faults/04-rounded-source-levels.md), arriving from the instrument
instead of from the script.
