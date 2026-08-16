---
type: fault
fault: 11
title: "A command the instrument accepts and then ignores"
found_by: "running the drivers"
---

# 11. A command the instrument accepts and then ignores

*Found by running the drivers.*

Worse than [A command in the manual but not on the instrument](10-command-not-on-the-instrument.md), because the error queue
stays clean.

The GSM accepts `FORM:ELEM VOLT,CURR`, queues no error, and keeps
sending three columns — **and answers `FORM:ELEM?` with the list it was
given rather than the one it sends.** Neither the command nor the
read-back described reality.

What cannot lie is arithmetic: `read_sweep()` asks how many readings the
buffer holds, counts the numbers that came back, and takes the ratio as
the stride. **Where the shape of a reply matters, count what arrived.**

Deviation 50. See [GW Instek GSM-20H10](../instruments/gwinstek-gsm20h10.md).
