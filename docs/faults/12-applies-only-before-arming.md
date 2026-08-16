---
type: fault
fault: 12
title: "A setting that only applies before something is armed"
found_by: "running the drivers"
---

# 12. A setting that only applies before something is armed

*Found by running the drivers.*

`TRAC:FEED` cannot be changed while buffer storage is active, and
`FORM:ELEM` behaves the same way in practice. Sent afterwards they are
accepted and do nothing.

**Order matters even when nothing complains.**

Deviations 46 and 50.
