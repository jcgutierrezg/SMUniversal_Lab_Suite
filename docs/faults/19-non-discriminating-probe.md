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
