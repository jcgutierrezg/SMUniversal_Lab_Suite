---
type: index
title: "Instruments"
---

# Instruments

One note per driver in `KNOWN_DRIVERS`, and the bijection is a test:
a driver without a note fails the suite, and so does a note without a
driver. That is the same mechanism as the capability `LEDGER` in
`tests/test_driver_contract.py` - the cost of adding an instrument
includes deciding what to say about it, collected when the driver is
written rather than at a bench six months later.

Each note carries the same headings so they are comparable at a glance:

| Heading | Holds |
|---|---|
| Identity and envelope | the observed `*IDN?`, what it can source |
| Reset defaults that had to be overridden | the single most productive section - every driver written from a manual has had at least one |
| Decisions and deviations | why the driver does what it does |
| Bench findings | what commissioning actually caught |
| What this means for your data | extracted into `bench/` |
| Open questions | linked from `open/` |

The capability comparison is not here and not hand-written: it is
generated into `bench/choosing-an-smu.md` from the driver classes.

## The notes

- [[keithley-2401]] - general-purpose, 21 V
- [[keithley-2450]] - never met hardware; kept for the lab that owns one
- [[keithley-2611a]] - TSP, hardware sweep, matched V/I conversion
- [[keithley-2635b]] - TSP, measures to 100 pA
- [[keysight-b2901a]] - highest current; self-energising out of reset
- [[keysight-u2722a]] - permanently 4-wire, 14-bit, slow slew
- [[gwinstek-gsm20h10]] - hardware staircase, per-quantity compliance
- [[undalogic-minismu]] - driven through a library, not a wire protocol
- [[dummy-smu]] - simulated

## The pattern worth carrying forward

Three of these drivers were written from a manual with no original
script behind them, and **each one audited the drivers that came
before it.** The GSM's sentinel handling, then the B2901A promoting it
to `BaseSMU`, then the 2635B finding that no driver had ever set
`format.asciiprecision`.

A new driver written carefully is the most reliable audit of the
existing ones this project has. Budget for that when adding the next
one: the findings will not all be about the new instrument.
