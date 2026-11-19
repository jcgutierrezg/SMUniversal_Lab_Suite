---
type: guide
title: "Keithley 6485"
---

# Keithley 6485

A picoammeter. It reads a current, down to femtoamps, and sets nothing,
so it is not a source-measure unit, and **no window uses it yet**. The
software can talk to it and check it, but every measurement window
refuses it at Connect and says why. What it will be used for has not
been decided.

<!-- generated:glance keithley-6485 -->
> **This instrument has never been checked against the software.** Never run against its instrument. Nothing on this page has been confirmed at a bench.

| At a glance | |
|---|---|
| Maximum voltage | 220 V |
| Maximum current | 21 mA |
| Power limit | n/a - sets nothing |
| Smallest current range | 2 nA |
| Smallest voltage range | n/a - reads current only |
| Fastest reading | not measured |
| Integration (NPLC) | 0.01 to 5 |
| Sweep runs on | n/a - sets nothing |
| Sensing | 2-wire |
| Over-voltage protection | n/a - no output |
| Can disconnect when off (high-Z) | n/a - sets nothing |
| Says when it hits compliance | n/a |
| Connection | GPIB (factory address 14) or RS-232 - not yet known for this lab's unit |
| Checked against the instrument | **never** |
| Runs Van der Pauw + Hall | **no** |
| Runs IV sweep | **no** |
| Runs Fixed sourcing vs time | **no** |
| Runs Ossila 4-point probe | **no** |
| Choose it for | nothing yet - a driver only, refused by every window until a role for a picoammeter is decided |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Nothing in the suite yet.** Use it from its own front panel as you
  always would. The software can run a checkup on it, and that is all.

## Look elsewhere when

- **You want to measure a sample in any window.** Every window needs an
  instrument that sources, and a picoammeter does not. Connect an SMU.
  For femtoamp currents with a source built in, the
  [Keysight B2987A](keysight-b2987a.md) and the
  [Keithley 487](keithley-487.md) both run IV sweeps.

## At the bench

- **Leave zero check on while you plug and unplug.** The ZCHK key, or
  the software: it turns zero check on when you disconnect and at the
  end of a checkup, and off when it connects. With zero check on, the
  display reads almost nothing whatever is connected - that is the
  meter's own offset, not your sample.
- **If connecting hangs, check the language.** Press *CONFIG* then
  *COMM*: on GPIB the language must be SCPI (488.1 also works). In DDC
  it never answers the software's first question.
- **Never give the input more than 21 mA or 220 V.** Either damages it.
  A source in series with it needs a compliance under 20 mA.
- **Connection:** GPIB, factory address 14, or RS-232 - one or the
  other, chosen in the COMM menu.
