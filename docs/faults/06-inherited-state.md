---
type: fault
fault: 6
title: "Instrument state inherited rather than set"
found_by: "reading the originals"
---

# 6. Instrument state inherited rather than set

*Found by reading the originals.*

Sensing, NPLC, compliance and output-off mode all persist between runs.
If the original sets one inside only *some* code paths, **the same
sample reads differently depending on what ran before it.**

The IV original set `SENSE_REMOTE` inside the periodic path and nowhere
else, so a single sweep was 4-wire after a periodic run and 2-wire after
a reset, with nothing on screen to say so.

Set everything that matters on every run. Distinct from
[[17-unsent-defaults]], which is about state inherited from the factory
rather than from a previous run.

Deviations 6 and 18.
