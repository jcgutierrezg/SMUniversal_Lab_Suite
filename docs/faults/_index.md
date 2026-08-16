---
type: index
title: "Faults to check for"
---

# Faults to check for

The mistakes that have turned up in every script ported so far. None of
them announce themselves: each produces data that looks entirely
reasonable, and several change what past data means.

**Work through these before writing a driver, not after.**

One note per fault, so a driver note can link to the specific one it
checked - "fault 15 does not apply, because `smuX.source.limitY`
autoranges for the limit setting" is a finding worth recording as a
link, and "checked and found absent" appears twice in the old documents
with different lists.

Numbers are permanent, as with the house rules.

## Found by reading the original scripts

| # | Fault |
|---|---|
| 1 | [[01-meas-per-point]] |
| 2 | [[02-concurrent-measurement]] |
| 3 | [[03-sentinels-as-data]] |
| 4 | [[04-rounded-source-levels]] |
| 5 | [[05-slept-not-polled]] |
| 6 | [[06-inherited-state]] |
| 7 | [[07-line-frequency]] |
| 8 | [[08-first-visa-resource]] |
| 9 | [[09-reconstructed-x-axes]] |
| 10 | [[10-command-not-on-the-instrument]] |

## Found by running the finished drivers against real instruments

These are the ones the offline test suite cannot reach: each is an
instrument disagreeing with a reasonable assumption, rather than code
disagreeing with itself. `tools/smu_checkup.py` exists to find them.

| # | Fault |
|---|---|
| 11 | [[11-accepted-then-ignored]] |
| 12 | [[12-applies-only-before-arming]] |
| 13 | [[13-state-left-by-a-sweep]] |
| 14 | [[14-output-across-function-change]] |
| 15 | [[15-limit-before-range]] |
| 21 | [[21-wrong-quantity]] |

## Found while writing a driver from a manual, or writing the tests

| # | Fault |
|---|---|
| 16 | [[16-one-range-list-for-two]] |
| 17 | [[17-unsent-defaults]] |
| 18 | [[18-accidental-accuracy]] |
| 19 | [[19-non-discriminating-probe]] |
| 20 | [[20-a-tool-with-the-fault-it-diagnoses]] |

## The one to internalise

[[19-non-discriminating-probe]]. It has recurred more than any other,
in more disguises, and it is the only one that can hide *all the
others* — a test that passes whether or not the code works leaves every
fault above it undetected.
