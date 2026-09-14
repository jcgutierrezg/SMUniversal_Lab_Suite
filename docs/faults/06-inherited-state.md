---
type: fault
fault: 6
title: "Instrument state inherited rather than set"
---

# 6. Instrument state inherited rather than set

## Symptom

**The same sample reads differently depending on what ran before it**,
with nothing on screen to say so.

## Cause

Sensing, NPLC, compliance and output-off mode all persist between runs.
Where a script sets one inside only *some* code paths, the run inherits
whatever the last path left.

The IV original set `SENSE_REMOTE` inside the periodic path and nowhere
else, so a single sweep was 4-wire after a periodic run and 2-wire after
a reset.

## Risk

Two runs on one sample, taken minutes apart, are not comparable and
nothing in either file records the difference. A 2-wire result read as a
4-wire one is a contact-resistance error attributed to the sample.

## Detection

Run the same measurement twice with a different run in between, and
diff the results. Anything that moves is inherited state.

## Prevention

Set everything that matters on every run, in the configuration block,
before the output goes on - [house rule 12](../rules/12-configure-before-energising.md).

Distinct from
[A default that is never sent is a default nobody chose](17-unsent-defaults.md),
which is state inherited from the factory rather than from a previous
run.

## Status

Closed.

## Evidence

Found by reading the original scripts. Deviations 6 and 18.
