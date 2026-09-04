---
type: fault
fault: 41
title: "A measurement recorded without the configuration it was taken in"
---

# 41. A measurement recorded without the configuration it was taken in

## Symptom

One number, measured carefully, correct where it was taken and wrong
everywhere else. Nothing in the record says which - so the next person
to use it has no way to know they are outside its validity, and the code
built on it fails quietly in whichever direction the configuration moved.

The measured case, on one instrument, a week apart:

| Date | Source current range pinned to | Floor found |
|---|---|---|
| 2026-08-27 | 1 A | 6.250e-06 A |
| 2026-09-01 | 100 µA | 7.629e-10 A |

Four orders of magnitude, same B2901A, same procedure, same operator.
Either figure written into the driver as "the B2901A's sub-count floor"
would have been wrong by four orders on the other range.

## Cause

The 2026-09-01 round measured, on six instruments, the level below which
a commanded source current stops having its sign followed. The report is
a table of instruments and currents, and it reads as a property of each
instrument. It is not. `tools/bench_envelope.py` pins the source range
before it sweeps:

    driver._apply_source_current_range(BIAS_A)

so every figure in that table is a floor **on the range that pin
selected**, and the two B2901A rows differ because the pin differed.

The underlying quantity is a ratio: one count of whatever range is
active. Recorded as a current, the denominator is dropped and cannot be
recovered - the number looks complete.

## Risk

Both directions are silent.

A floor recorded from a wide range and applied on a narrow one refuses
levels the instrument can express perfectly well, and the run stops for
no reason anybody can see. A floor recorded from a narrow range and
applied on a wide one lets through levels that come out as offset
residue with a polarity nobody commanded - which is the whole hazard the
floor exists to prevent, restored in full while a report says it is
guarded.

The second is worse, and it is the one an "average of the fleet" or a
"most conservative value" would produce on half the ranges.

## Detection

Ask, of every measured constant: **what was held fixed while this was
measured, and does the code that uses it hold the same thing fixed?**

Then look for a second measurement at a different setting. One
measurement cannot distinguish an absolute from a ratio; two, taken at
settings that differ, separate them immediately. Here the ratio between
the two B2901A floors (8192) matches the ratio between the two ranges
(10000) to inside the factor of two a halving sweep can resolve, and
that is the entire proof.

Where a second measurement does not exist, the question is still
answerable from the procedure: read what the measuring tool set before
it measured.

## Prevention

**Store the ratio, derive the number.** `SOURCE_COUNTS_PER_RANGE` holds
counts per source range per axis; `BaseSMU.source_level_floor()`
multiplies by whichever range `apply_ranges()` last applied. The measured
current is not stored anywhere - it appears only in the constant's
comment, as the observation the count reproduces:

    Keithley 2401    1e-4 / 32768  = 3.0518e-09 A   measured 3.052e-09
    GSM-20H10        1e-4 / 32768  = 3.0518e-09 A   measured 3.052e-09
    Keithley 2635B   1e-4 / 32768  = 3.0518e-09 A   measured 3.052e-09
    Keithley 2611A   1e-4 / 8192   = 1.2207e-08 A   measured 1.221e-08
    Keysight B2901A  1e-4 / 131072 = 7.6294e-10 A   measured 7.629e-10

Under autoranging the active range is not known, and the floor falls
back to counts of the model's *narrowest* source range - a bound that
holds whichever range the instrument picked, rather than a guess at
which one it picked.

The other half of the prevention is scope. The bench procedure sources
current and only current, so the voltage converter on those five models
is still `unmeasured` and no voltage count is declared. Carrying the
current-axis figure across would be this same fault in its other
dimension: a measurement generalised past the configuration it was taken
in.

## Status

Closed on the current axis of five instruments. Open on their voltage
axes, which no round has measured. See
[technical debt](../open/technical-debt.md).

## Evidence

`checkups/20260901/bench_envelope.txt` and `checkups/20260827/envelope.txt`.

The 08-27 round is corroboration of the scaling only, not a second
calibration point: its B2901A control leg read +6.93e-05 A against a
commanded 1e-4 A, and four of the seven instruments failed their control
leg outright that day.

This is [An accuracy that is an implementation detail, not a
guarantee](18-accidental-accuracy.md) turned around - there the number
was better than it was entitled to be, here it is narrower - and it is
the measurement-side twin of [One range list standing in for
two](16-one-range-list-for-two.md).
