---
type: fault
fault: 45
title: "A summary that contradicts the body it summarises"
---

# 45. A summary that contradicts the body it summarises

## Symptom

A report's headline row states one value; a detail row forty lines
below states a different one for the same quantity. Both are recorded
by the same tool in the same run, and neither is marked as superseding
the other. The report reads as internally consistent because nobody
reads both rows at once.

On the 2026-09-04 round the Keysight U2722A's tier 1 row said:

> `probe levels | pass | source 0.1 V / 1e-06 A, compliance 0.0001 A /
> 1 V - every nominal level is inside this model's declared envelope
> and is used unchanged`

while tier 3 said the nominal 1 µA was below what the instrument could
express on the range the plan landed on and it was probed at 73.2 µA
instead. The JSON header recorded `probe_levels.current =
7.32421875e-05`. The instrument sourced 73.2 µA. The summary said 1 µA
and said it was unchanged.

## Cause

The summary was **recorded before the value it summarises was final**.

Tier 1 emits the probe row from `probe_levels_for()`, which reconciles
the nominal request against the model's declared envelope. That is all
that is knowable at that point. Whether a level survives to be sourced
depends on the range the ranging plan lands on, which is not known
until tier 3 has run the plan and asked the instrument for its floor —
so tier 3 raises the level, writes it back into `self.probe`, and every
message *after* that point quotes the new number.

Every message after that point. The tier 1 row was already written.

The "used unchanged" sentence made it worse rather than merely
incomplete. It was appended by `probe_levels_for()` whenever no
envelope clamp had fired — a true statement about clamping, phrased as
a statement about the whole run. A row that had simply been early would
have been ambiguous; one that asserts nothing moved is wrong.

## Risk

The tier 1 summary is the part of a commissioning report people read.
It exists precisely so that reports for different instruments can be
compared without reading each one end to end, and the probe row exists
because instruments in the same round are legitimately probed at
different levels — see
[A test level the instrument cannot express](34-a-probe-the-instrument-cannot-express.md).

So the failure lands on the one reader the row was written for: someone
comparing two instruments' tier 3 readings, who checks the probe row to
find out whether the two are comparable, and is told they are when they
are not. A 73× difference in source current is not a detail.

It also hid the one visible demonstration that the envelope work does
its job. On this fleet the U2722A is the only instrument where a level
is substituted at all, and the summary reported it as the instrument
where nothing happened.

## Detection

For any summary line, ask **when it was written relative to the value
it names**. A summary emitted at the top of a run can only report a
plan; if anything downstream can change what it names, it is a
prediction rendered in the past tense.

The tell in a report is a quantity appearing twice with different
values and no ordering between them. Search a report for its own
headline numbers: if a later row disagrees, the header is stale rather
than the body wrong.

The tell in code is a field written back after the row quoting it was
recorded — here, `self.probe.current = raised` several hundred lines
below `self.record(1, "probe levels", ...)`.

## Prevention

**The row is kept and rewritten at the end of the run.**
`Checkup._probe_result` holds the recorded row, and
`_refresh_probe_summary()` rewrites its detail from the probe's final
state in `run()`, outside the `try`, so it is refreshed even on a run
that stopped on a desynchronised link.

Three supporting changes, each of which was a separate way to get this
wrong:

* `ProbeLevels.describe()` reports what was **used** and marks any
  level that is not the nominal — `7.32422e-05 A in place of the
  nominal 1e-06 A`. Showing only the substituted number would make two
  reports incomparable; showing only the nominal is this fault.
* The "nothing moved" sentence is **generated** by `ProbeLevels.notes`
  rather than stored at construction, so it cannot survive the event
  that falsifies it. A stored sentence is a claim frozen at the moment
  it was cheapest to make.
* Substitutions go through `ProbeLevels.substitute()`, which keeps the
  planned value alongside the used one. A bare attribute write loses
  the fact that anything happened.

Editing a recorded result is done in this one place and is documented
as such: a checkup result is an observation, and observations are not
revised. This is a completion rather than a revision — the row states
the four levels of a run, and one of them is not knowable until the
instrument has been asked.

## Status

Closed in the checkup. The class is open by nature: any tool that
records a summary before its subject settles can acquire it again.

## Evidence

`D:\SMU_Checkups\20260904\checkup_KeysightU2722A_20260904_104240.json`
and its `.md`, at commit `727022f`: the tier 1 `probe levels` row
against the tier 3 `current probe level is expressible on the active
range` row and the `probe_levels` header block.

Related: [A test level the instrument cannot express](34-a-probe-the-instrument-cannot-express.md)
is the fault whose fix introduced the substitution this one failed to
report. [A provenance stamp that never moves](31-a-stamp-that-never-moves.md)
is its opposite — a field that is present and no longer
discriminating, where this one discriminates perfectly and was captured
too early.
