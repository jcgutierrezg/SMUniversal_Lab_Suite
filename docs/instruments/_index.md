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

> **Stub.** Content arrives in a later patch; see [[migration-status]].
