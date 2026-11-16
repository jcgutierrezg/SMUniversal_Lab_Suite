---
type: guide
title: "Keysight 34401A"
---

# Keysight 34401A

A 6½-digit bench multimeter. It reads a voltage and sets nothing, so it
is not a source-measure unit, and **no window uses it yet**. The
software can talk to it and check it, but every measurement window
refuses it at Connect and says why. What it will be used for has not
been decided.

<!-- generated:glance keysight-34401a -->
> **This instrument has never been checked against the software.** Never run against its instrument. Nothing on this page has been confirmed at a bench.

| At a glance | |
|---|---|
| Maximum voltage | 1 kV |
| Maximum current | n/a - reads voltage only |
| Power limit | n/a - sets nothing |
| Smallest current range | n/a - reads voltage only |
| Smallest voltage range | 100 mV |
| Fastest reading | not measured |
| Integration (NPLC) | 0.02 to 100 |
| Sweep runs on | n/a - sets nothing |
| Sensing | 2-wire |
| Over-voltage protection | n/a - no output |
| Can disconnect when off (high-Z) | n/a - sets nothing |
| Says when it hits compliance | n/a |
| Connection | GPIB (GPIB-USB-HS adapter, most likely direct) |
| Checked against the instrument | **never** |
| Runs Van der Pauw + Hall | **no** |
| Runs IV sweep | **no** |
| Runs Fixed sourcing vs time | **no** |
| Runs Ossila 4-point probe | **no** |
| Choose it for | nothing yet - a driver only, refused by every window until a role for a meter is decided |

How it compares with the others: [Instruments](index.md).
<!-- /generated:glance -->

## Choose it for

- **Nothing in the suite yet.** Use it from its own front panel as you
  always would. The software can run a checkup on it, and that is all.

## Look elsewhere when

- **You want to measure a sample in any window.** Every window needs an
  instrument that sources, and a meter does not. Connect an SMU.

## At the bench

- **If connecting hangs, check the language.** On the front panel,
  *I/O MENU → LANGUAGE* must say SCPI. In either of the other two
  languages it never answers the software's first question.
- **The front/rear switch is yours to set.** The software reads which
  terminals are selected but cannot change it.
- **Connection:** GPIB, through the GPIB-USB adapter. Its factory
  address is 22, shown on the display at power-on.
