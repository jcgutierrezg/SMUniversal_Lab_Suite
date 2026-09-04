---
type: fault
fault: 42
title: "A driver's silence reported as the instrument's"
---

# 42. A driver's silence reported as the instrument's

## Symptom

A commissioning report says the instrument cannot do something. The
instrument can. What cannot do it is the driver, and the sentence does
not distinguish them - so the gap is filed as a hardware limitation,
which is a thing nobody schedules work against.

Five of seven instruments in the 2026-09-04 round:

> **compliance survives ranging** — skip — *Keithley 2611A does not
> report its compliance - a collapse here would be invisible*

> **range readback: source voltage** — skip — *Keysight B2901A has no
> confirmed query for this range, so what it is actually on is unknown*

Both sentences name the instrument as the subject. In four of the five
cases the query is the query form of a header the driver already
*writes*, three lines further up its own file.

## Cause

`supports_compliance_readback()` and `supports_range_readback()` ask
whether the *driver* overrides the reader. That is the right question
and the reason `unsupported` exists as a separate state from
`unreadable` - a `None` from a driver that never implemented the reader
means something completely different from a `None` from one that did.

The rendering then attaches the driver's answer to the instrument's
name. `unsupported` renders as a skip, and a skip is what this project
uses for a genuine model difference, so a gap in the software arrives in
the report wearing a model difference's clothes.

The reason it survived is that both readings of the sentence produce the
same non-action. A model difference needs no work. A driver gap needs
work, and looks identical.

## Risk

The states are ordered by how much is known, and this fault moves a gap
into the *most settled* of them. `unsupported` is the only one of the
five that is not a to-do: `unreadable` says something is wrong with the
asking, `unverified` says a bench session is owed, `mismatched` needs a
human now. `unsupported` says nothing is owed by anybody.

So the gap stops being counted. On the 2611A and the 2635B the effect
was sharper still, because their compliance *flag* works and passes both
of its probes - a reader comparing the two lines could reasonably
conclude the instrument reports what it can and the rest is hardware.

## Detection

For every `unsupported` in a report, ask **whether the driver already
sends a command with that header.** On SCPI a settable numeric command
has a query form by construction; on TSP a written attribute is a read
attribute. If the driver writes it, "the instrument does not report it"
is a claim about nobody having tried.

Where the driver does not write it, the question is whether a manual
names the query. `unsupported` earns its place only when the answer to
both is no.

## Prevention

Say which. A skip whose detail names the *driver* as the subject
("nothing in this driver asks for it, and the header would be X") reads
as work; the same skip naming the instrument reads as physics. That
wording lives in `core/checkup.py`.

And on the drivers, the standing rule that produced the silence is
narrower than it was being applied. It is *a query nobody has confirmed
is not sent*, because an unrecognised query is never answered, times out
and latches the transport - so a guess costs a run rather than a line in
a report. That rule does not reach a header the driver already writes.
It does still reach the U2722A, whose ranges are named tokens with no
numeric form and no confirmed query spelling, and the miniSMU, whose
vendor library exposes setters and no getters at all.

## Status

Closed on the 2401, 2611A, 2635B and B2901A, which gained compliance and
range readbacks in the states they had earned - `unverified`, never
`confirmed`. Open, and correctly `unsupported`, on the U2722A's ranges
and on both subjects for the miniSMU.

## Evidence

`D:\SMU_Checkups\20260904\`, all seven reports.

The miniSMU finding is a library audit rather than a bench session:
`minismu_py.SMU` has `set_current_protection` and
`set_voltage_protection` and no getter for either, and its only
range-shaped getter is `get_current_range_limit(index)`, a static table
lookup that asks the instrument nothing.

This is [A setting reported from the command that was
sent](33-a-setting-never-read-back.md) one level up - there the software
answered from what it had sent, here the *report* answers from what the
software can send.
