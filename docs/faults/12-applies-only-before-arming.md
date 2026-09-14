---
type: fault
fault: 12
title: "A setting that only applies before something is armed"
---

# 12. A setting that only applies before something is armed

## Symptom

A command that works when the driver is written and does nothing in the
finished sequence, with no error either way.

## Cause

`TRAC:FEED` cannot be changed while buffer storage is active, and
`FORM:ELEM` behaves the same way in practice. Sent afterwards they are
accepted and do nothing.

## Risk

**Order matters even when nothing complains.** The same command, the
same arguments, a different position in the sequence, and a different
outcome - which makes it invisible in a diff that only moved a line.

## Detection

For every setting, ask what state the instrument has to be in for it to
take. Then send it in the wrong order deliberately and read it back.

## Prevention

Configure before arming, and before energising -
[house rule 12](../rules/12-configure-before-energising.md). The
ordering is held by the state-transition traces described there.

## Status

Closed on the GSM.

## Evidence

Found by running the finished drivers against real instruments.
Deviations 46 and 50.
