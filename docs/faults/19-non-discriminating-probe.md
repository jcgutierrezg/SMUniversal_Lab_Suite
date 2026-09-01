---
type: fault
fault: 19
title: "A probe asked where the answer is already known"
found_by: "writing the tests"
---

# 19. A probe asked where the answer is already known

*Found by writing the tests.*

The commissioning checkup called `compliance_tripped()` at tier 2, with
the output **off** — where `False` is the honest answer, and where a
method that always returns `False`, or always returns `None`, passes
exactly as well as a correct one. Thirty lines later the same instrument
was riding its voltage limit into an open circuit and nothing asked it
again.

**Ask at the moment the answer is known and known to be the interesting
one.** An assertion made where the boring answer is correct proves
nothing.

Fixed by `_check_compliance_reported()` in `core/checkup.py`, and by
making the fakes compute compliance from state — two of them returned a
hardcoded `"false"`, so the new probe passed against fakes that could
not have said otherwise.

This is the most-repeated fault in the project's history. It has also
appeared as a test asserting state the fake's own reset had set, a
count that reset already satisfied, a mixed-sample guard whose
pre-existing check refused first, and an escape-marker test that
reimplemented the code it was testing. **Mutate and confirm the test can
fail.**

## It applies to hypotheses, not only to probes

A probe asked where the answer is already known proves nothing. So does
a mechanism reasoned out from a plausible story and never asked at all —
and that one is worse, because it leaves no failed assertion behind to
notice.

The GSM-20H10's 2026-08-20 session proposed and disproved three
mechanisms before finding the real one: a rear-panel interlock, a source
auto-clear, and an ambiguous channel suffix on `:OUTPut`. Each was
plausible. None was probed before being believed, and **one reached the
instrument note as a statement of fact and had to be retracted.**

The U2722A's sub-count round repeated it in a different shape: three
wrong conclusions, all from reading a value before it had settled.

Two rules follow, and they are the reason instrument notes in this
repository read the way they do:

- **A note records what was measured, not what was inferred.** If it was
  not probed, it goes under *Open questions* with the question written
  out, not into the body as a finding.
- **A retracted hypothesis is deleted, not archived.** Left in place it
  reads back later as a finding, and the next person to read the page —
  including the person who wrote it — cannot tell which is which.
