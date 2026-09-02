---
type: fault
fault: 30
title: "A guard whose own failure reads as all-clear"
---

# A guard whose own failure reads as all-clear

## Symptom

The window closes without asking about unsaved measurements, and the
runs in the results table are gone. There were unsaved runs. The prompt
that exists to stop exactly this did not appear.

## Cause

The guard counted unsaved runs like this:

```python
for exp in self.experiments:
    try:
        if exp.has_unsaved_runs():
            total += len(exp.run_store)
    except Exception:
        pass
return total
```

and the caller wrapped the count *and* the prompt in a second
`try/except Exception: pass` before carrying on with the close.

So an error anywhere in the guard produced `0`, and `0` is the same
value the guard produces when everything is fine and there is genuinely
nothing to lose. The failure and the all-clear are indistinguishable to
the code that acts on them — and the action taken on the all-clear is
the destructive one.

## Why it is dangerous

This is the mirror image of a guard that is too noisy, and it is worse
in the way that matters. A guard that cries wolf gets investigated. A
guard that goes quiet when it breaks gets trusted, and it is trusted
most on the day it is broken.

The specific loss is not recoverable. Runs live only in memory until the
operator presses Save — that is the accepted cost of not auto-saving —
so the confirmation prompt is the only thing standing between a wrong
keystroke and a morning of measuring. A quarter of an hour of instrument
time at 200 points and a 2 s settle, per run.

Note also which direction the failures point. Both the count and the
dialog are *more* likely to fail when something else is already
wrong — and "something else is already wrong" is exactly when unsaved
data matters most.

## The rule

**A safety guard must be able to say "I do not know", and the caller
must treat "I do not know" as a refusal, never as a pass.**

Concretely:

- the count returns a three-valued result (`UnsavedState`: a number and
  a list of the experiments it could not read), not a bare integer;
- an unreadable results table leaves the window **open** and puts the
  diagnostic on screen;
- a confirmation dialog that raises leaves the window **open**. The
  question it was asking was "may I throw this away", and an unanswered
  question is not a yes;
- so does an answer of `None`. A neutralised dialog seam returns
  nothing, and nothing is not consent;
- the count reads from the store's own `has_unsaved` property rather
  than through an overridable method, so there is less between the
  question and the answer that can fail in the first place.

## Check

For any guard, write down what it returns when it fails, and then ask
what the caller does with that value. If the answer is the same thing it
does when the guard says "all clear", the guard is decorative.

The tell is a `try` whose `except` produces a value rather than a
refusal — `return 0`, `return None`, `return True`, or a `pass` that
leaves an accumulator at its initial value.

## Where it is guarded

`tests/test_shutdown_safety.py` gives one experiment a results table
whose unsaved state raises when read, and asserts the window is still
open, nothing was disconnected, and the operator was told. Separately it
makes the confirmation dialog itself raise, and makes it answer `None`,
and asserts the same. The control case — the operator saying yes, and
the window closing — is in the same file, because without it every one
of those would pass against an application that simply never closed.
