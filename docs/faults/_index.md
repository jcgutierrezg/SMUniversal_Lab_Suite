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

## The shape every note has

Seven sections, in this order, so two notes can be compared without
reading both end to end:

| Section | Answers |
|---|---|
| **Symptom** | What you see. What it looks like from outside, before anyone knows the cause |
| **Cause** | The mechanism. What the instrument or the code actually does |
| **Risk** | Why it is dangerous, and which way it fails |
| **Detection** | The question to ask, the probe to send, the measurement to take |
| **Prevention** | The design change or rule that stops it, and where the guard lives |
| **Status** | Open or closed, and on what. One line |
| **Evidence** | Bench dates and transcripts, deviation numbers, test files, related notes |

`Detection` and `Prevention` are separate on purpose. Most of these
faults were survivable once somebody knew to look, and the looking is
the transferable part - a new instrument gets the detection step long
before it gets the fix.

`Status` exists because a fault note is not a changelog entry. "Closed
on the GSM-20H10, open on six others" is the common case here, and a
note that does not say so reads as closed.

## Found by reading the original scripts

| # | Fault |
|---|---|
| 1 | [`MEAS?` used per point](01-meas-per-point.md) |
| 2 | [Concurrent measurement never enabled](02-concurrent-measurement.md) |
| 3 | [NAN and overflow sentinels treated as data](03-sentinels-as-data.md) |
| 4 | [Source levels rounded before sending](04-rounded-source-levels.md) |
| 5 | [Sweep completion slept rather than polled](05-slept-not-polled.md) |
| 6 | [Instrument state inherited rather than set](06-inherited-state.md) |
| 7 | [Line frequency never set](07-line-frequency.md) |
| 8 | [`rm.open_resource(instruments[0])`](08-first-visa-resource.md) |
| 9 | [Reconstructed x-axes](09-reconstructed-x-axes.md) |
| 10 | [A command in the manual but not on the instrument](10-command-not-on-the-instrument.md) |

## Found by running the finished drivers against real instruments

These are the ones the offline test suite cannot reach: each is an
instrument disagreeing with a reasonable assumption, rather than code
disagreeing with itself. `tools/smu_checkup.py` exists to find them.

| # | Fault |
|---|---|
| 11 | [A command the instrument accepts and then ignores](11-accepted-then-ignored.md) |
| 12 | [A setting that only applies before something is armed](12-applies-only-before-arming.md) |
| 13 | [State left behind by a sweep](13-state-left-by-a-sweep.md) |
| 14 | [Output state assumed across a source-function change](14-output-across-function-change.md) |
| 15 | [A limit sent before the range that has to hold it](15-limit-before-range.md) |
| 21 | [Asking about the wrong quantity](21-wrong-quantity.md) |
| 22 | [Direct GPIB-HS address picker was empty](22-direct-gpib-hs-empty-address-picker.md) |
| 23 | [A ranging command that silently resets the compliance](23-autorange-resets-compliance.md) |
| 27 | [A direct GPIB-USB-HS link that never asserts IFC](27-direct-gpib-hs-missing-ifc.md) |
| 33 | [A setting reported from the command that was sent](33-a-setting-never-read-back.md) |
| 34 | [A test level the instrument cannot express](34-a-probe-the-instrument-cannot-express.md) |

## Found while writing a driver from a manual, or writing the tests

| # | Fault |
|---|---|
| 16 | [One range list standing in for two](16-one-range-list-for-two.md) |
| 17 | [A default that is never sent is a default nobody chose](17-unsent-defaults.md) |
| 18 | [An accuracy that is an implementation detail, not a guarantee](18-accidental-accuracy.md) |
| 19 | [A probe asked where the answer is already known](19-non-discriminating-probe.md) |
| 20 | [A diagnostic tool with the fault it diagnoses](20-a-tool-with-the-fault-it-diagnoses.md) |
| 24 | [A derived claim resting on something a merge rewrites](24-derived-from-a-rewritable-date.md) |
| 25 | [A bound checked on one side only](25-a-bound-checked-on-one-side.md) |
| 26 | [A fault injected below the layer under test](26-a-fault-injected-below-the-layer.md) |
| 28 | [A dialog nobody stubbed, on a machine that never showed it](28-a-dialog-nobody-stubbed.md) |
| 29 | [A shutdown path that fails open](29-a-shutdown-that-fails-open.md) |
| 30 | [A guard whose own failure reads as all-clear](30-a-guard-that-fails-to-all-clear.md) |
| 31 | [A provenance stamp that never moves](31-a-stamp-that-never-moves.md) |
| 32 | [A safety margin asserted in a docstring and never computed](32-arithmetic-in-a-docstring.md) |
| 35 | [A derived file built from whatever was lying in the directory](35-derived-from-whatever-is-lying-around.md) |
| 36 | [A writer that quietly rewrote what it was handed](36-two-ends-disagreeing-about-newlines.md) |
| 37 | [A test that measured the machine instead of the code](37-a-test-that-measured-the-machine.md) |

## Found by switching a linter on

Review A-09 configured the first automated quality gate this project has
had. Two of its findings were defects rather than untidiness, and both
had been in the tree since the first import - which is the argument for
the gate: nobody reading these files was going to see one missing
decorator in a column of eleven, or work out what a dead local was the
residue of.

| # | Fault |
|---|---|
| 38 | [A contract method that was not abstract, and returned None](38-a-contract-method-that-was-not-abstract.md) |
| 39 | [An override that quietly dropped the guard it inherited](39-an-override-that-dropped-its-guard.md) |

## Found by auditing the documents themselves

| # | Fault |
|---|---|
| 40 | [A document holding state that git already owns](40-a-document-holding-state-git-owns.md) |

## Found by reading a commissioning report against its own body

Both came out of the 2026-09-04 round, and neither is a defect in an
instrument or in a driver. They are defects in what the report *said*
about instruments that were working — which is the failure mode a
commissioning tool has instead of a wrong reading.

| # | Fault |
|---|---|
| 44 | [A summary that contradicts the body it summarises](44-a-summary-that-contradicts-its-own-body.md) |
| 45 | [One message standing in for two different gaps](45-one-message-for-two-different-gaps.md) |

## The one to internalise

[A probe asked where the answer is already known](19-non-discriminating-probe.md). It has recurred more than any other,
in more disguises, and it is the only one that can hide *all the
others* - a test that passes whether or not the code works leaves every
fault above it undetected.
