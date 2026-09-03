---
type: rule
rule: 12
title: "Configure before energising"
---

# 12. Configure before energising

Every configuration command precedes the output-on transition. Once the
output is on, the sequence sets **levels** and reads; it does not set
functions, compliances, ranges, sensing, NPLC or protection.

**The electrical reason matters more than the rule.** A range change
part way through a run leaves a step in the data where the two segments
were sourced with different gain and offset errors. A straight line
fitted across that step absorbs it as slope — and slope is resistance.
No error, an excellent R², and a wrong answer. A fixed range gives every
point the same systematic error, which largely cancels out of a slope.

It also stops the instrument spending resolution where nobody wants it:
a run sourcing milliamps does not benefit from microamp resolution
merely because it passes through zero on the way.

**The sample is protected by whatever compliance was in force when the
output went on.** IV's periodic standby used to energise a biased sample
before setting any compliance at all, so the limit protecting it was
whatever the previous sweep left behind — or, on a fresh session, the
instrument's reset default. On a B2901A those defaults are 100 µA and
2 V. Neither will damage anything, which is exactly why it survived: the
bias is quietly clamped, the device is never held where the operator
asked, and the file records the requested bias rather than the achieved
one.

Wave 6b found Van der Pauw and Hall re-sending `set_source_delay()` and
a range call at the top of every polarity block — while the sample was
live. Not carelessness: the source level changes between polarities and
someone wanted the range able to reach it. But both `_configure` blocks
already sent the same calls with the same arguments, so the repeats
bought nothing. Both now fix the range once, before energising, sized to
the largest magnitude the run will source.

**Every driver rounds *up*** — checked across all of them before the
change, because the failure mode if any rounded down would be a clamped
source level, which is [Source levels rounded before sending](../faults/04-rounded-source-levels.md).

## How the ordering is held: state-transition traces

The rule above is about *order*, so a test that only asserts each
command was present cannot enforce it. The criterion is stronger: **a
change in command order that creates an unsafe or invalid transient
fails the suite.**

Fake transports record the command sequence and the simulated state, and
four files assert against it. Between them they cover the nine
transitions worth pinning: reset and initialisation, output-on from a
known off state, compliance configured before output-on, a
source-function change while the output is active, hardware sweep setup
and completion, software sweep cancellation, output-off and its
verification, error-queue inspection, and reconnect after a failure.

| File | Covers |
|---|---|
| `tests/test_transition_traces.py` | ordering invariants on every driver, from the shared `CASES` table, plus the exact output-command spellings |
| `tests/test_house_rule_12.py` | compliance before output-on, and the source-function change under a live output |
| `tests/test_sweep_traces.py` | hardware sweep setup and completion, software sweep cancellation, error-queue inspection |
| `tests/test_reconnect.py` | reconnect after a failed link |
| `tests/test_dialect_hygiene.py` | no driver speaking another driver's dialect |

Ordering and spelling are two claims, not one. An instrument sent a
command it does not recognise logs it in a queue nobody reads, ignores
it, and leaves the previous setting in force — so "the output-off went
out" is not the same claim as "the output-off went out *in this
instrument's dialect*". See [A command in the manual but not on the
instrument](../faults/10-command-not-on-the-instrument.md).
