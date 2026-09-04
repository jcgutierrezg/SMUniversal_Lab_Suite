---
type: fault
fault: 45
title: "One message standing in for two different gaps"
---

# 46. One message standing in for two different gaps

## Symptom

A report says the same thing about several instruments, and on some of
them it is false. The message is not wrong about the check it guards —
the check really was skipped — but the *reason* it gives applies to
only part of the set it is printed for.

The checkup's `compliance survives ranging` skipped on five drivers in <!-- lint-ok -->
the 2026-09-04 round with:

> `<model> does not report its compliance - a collapse here would be
> invisible`

On the Keithley 2611A, the Keithley 2635B and the Keysight B2901A that
second clause is untrue. All three report the compliance **flag**:
`compliance_tripped()` returns True while the output is riding its
limit, and each report's tier 3 row says so on the same page. Only the
Keithley 2401 and the Undalogic miniSMU are blind to both.

## Cause

Two distinct capabilities were being described by one sentence written
for the narrower of them.

`supports_compliance_readback()` asks whether a driver can read the
compliance **limit value** back. `compliance_tripped()` asks whether
the output is **at** its limit right now. A driver can have either
without the other, and three here have exactly one.

The skip message was assembled from the limit readback's own
`unsupported_detail` plus a clause about what that costs — and the
clause was written while thinking about the drivers that have neither.
Once written, it printed for every driver that reached the branch,
because the branch is keyed on the limit readback alone.

Underneath is the same shape as
[A probe asked where the answer is already known](19-non-discriminating-probe.md),
inverted: not a check that cannot distinguish two states, but a
*message* that cannot, printed by a check that never asked the second
question.

## Risk

The message is read by an operator deciding whether to trust an
instrument with a sample. "A collapse here would be invisible" is an
instruction to watch the data by hand, and printing it about an
instrument that will in fact raise its flag spends the operator's
attention on a risk that is already covered.

The more expensive direction is the reverse one. A message that
over-warns on three instruments teaches its readers to discount it, and <!-- lint-ok -->
the same sentence is true and load-bearing on the other two. A warning
that is wrong more often than it is right stops being read at all,
which is the mechanism that makes a diagnostic tool worse than none —
see [A diagnostic tool with the fault it diagnoses](20-a-tool-with-the-fault-it-diagnoses.md).

## Detection

When one message is emitted for a set of subjects, ask **whether every
subject in the set makes it true**. The count matters: a sentence
printed once is checked against one instrument, and a sentence printed
five times is usually checked against none.

The specific tell here is a message that names a *consequence* rather
than a *fact*. "Does not report its compliance" is a fact about one
query and is correct. "A collapse would be invisible" is a claim about
everything else the instrument can report, and nothing had asked those.

The cross-check that found it costs nothing: the same report already
carried `compliance_tripped() while clamping | pass | reported True
while riding the voltage limit` for three of the five instruments the <!-- lint-ok -->
message was printed for.

## Prevention

`Checkup._compliance_blindness()` asks the driver which of the two
gaps this is and words the skip accordingly. Two sentences, one per
state:

* limit value unreadable, flag reported — says the flag works and that
  what is unseen is narrower: a limit that moved to a value nobody
  chose, which clamps nothing and trips nothing.
* neither reported — the original sentence, now printed only where it
  is true.

**Asked of the driver, never read from a list of models.** A hard-coded
list would be correct on the day it was written and wrong on the day a
driver grows a readback, which is the same class of decay as any other
cached fact. As the limit readbacks land, a driver that gains one stops
reaching the branch at all and a driver that gains only the flag gets
the milder sentence, with nothing in the checkup edited.

The branch also stops quoting the readback's own `unsupported_detail`.
That string says "does not report its compliance", which is the phrase
this fault is about; repeating it and then contradicting it in the next
clause would have been a smaller version of the same problem.

## Status

Closed in the checkup. Open in `drivers/base_smu.py`, whose
`verify_compliance()` still builds `unsupported_detail` as
"`<model>` does not report its compliance" where it means the limit
value specifically. Nothing renders that string now, but the next
caller to use it inherits the ambiguity.

## Evidence

The 2026-09-04 round in `D:\SMU_Checkups\20260904\` at commit
`727022f`: the `compliance survives ranging` skip beside the
`compliance_tripped() while clamping` pass in
`checkup_Keithley2611A_...`, `checkup_Keithley2635B_...` and
`checkup_KeysightB2901A_...`, against the same pair of rows in
`checkup_Keithley2401_...` and `checkup_UndalogicMiniSMU_...` where the
tier 3 row is a skip.
