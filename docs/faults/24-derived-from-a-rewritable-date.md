---
type: fault
fault: 24
title: "A derived claim resting on something a merge rewrites"
---

# 24. A derived claim resting on something a merge rewrites

## Symptom

A generated, committed file disagrees with a fresh build of itself, on a
tree where **nothing has changed**. The test that compares them goes
red, usually on `main`, usually straight after a merge, and re-running
it does not help. Nothing in the diff explains it, because the input
that moved is not in the diff.

Observed 2026-08-21. `docs/open/checkup-owed.md`,
`bench/choosing-an-smu.md` and one bench page were built saying the
GSM-20H10 was commissioned, and a rebuild minutes later said it needed
re-checking. The driver file was byte-identical in both.

## Cause

The bench status was derived by comparing two dates:

```python
moved = last_changed([driver, *SHARED_DEPENDENCIES])   # git log -1 --format=%cs
if moved > date.fromisoformat(last_bench):
    return "stale", ...
```

A commit date is not a property of the tree. It is a property of *when
the commit object was made*, and the whole delivery pipeline makes new
commit objects out of unchanged content:

| Operation | What it does to the date |
|---|---|
| `git am` | committer date becomes the moment the patch was applied |
| `git rebase` | committer date becomes the moment of the rebase |
| GitHub squash-merge | **both** author and committer date become the merge instant |

So the same bytes answer the question differently depending on when
somebody merged them. Three commits authored on 2026-08-20 were applied
by `git am` on 2026-08-21, which moved the driver's date past the note's
`last_bench` and flipped the status.

Two smaller faults were hiding underneath it. The comparison had day
resolution, so a code change made *later the same day* as the bench
session was invisible - failing in the dangerous direction, claiming
commissioned. And because `SHARED_DEPENDENCIES` names a file every
driver depends on, a single merge would flip the status of the entire
fleet at once.

## Risk

A commissioning claim is a safety claim. Failing towards "commissioned"
means an instrument nobody has checked reads as checked, and the reader
has no way to tell the two apart.

## Detection

Ask whether the generated file would render identically if the same tree
were merged tomorrow instead of today. If any input to it comes from
`git log`, `git rev-parse`, `datetime.now()` or a path outside the
repository, the answer is no.

The test for it is **not** "render twice and compare" - that passes if
both renders read the same rewritten value. It is to make the rewritable
source *unavailable* and require the render to succeed anyway:

```python
monkeypatch.setattr(build_docs.provenance.subprocess, "run", explode)
```

The clean-checkout verification could not catch it either. `git apply`
leaves the files uncommitted, so `git log` still reports the *pre-patch*
date - the local run asked a question whose answer had already been
fixed. Committing before running is now the documented procedure, and it
is what caught the second instance. See
[A probe asked where the answer is already known](19-non-discriminating-probe.md).

## Prevention

**A derived claim must rest on something the delivery pipeline cannot
rewrite.** Commit dates, commit shas surviving a squash-merge, working
directory paths, and the wall clock are all rewritable. File contents
are not.

`core.provenance.code_fingerprint` hashes the content of the driver plus
its shared dependencies; the note records the digest the checkup
printed; the build compares digests. Rebase, `git am` and squash-merge
change none of them. It needs no git at all, which removed a
shallow-clone guard and, with it, a check that was silently skipped
anywhere `fetch-depth: 0` had not been set.

## Status

Closed.

## Evidence

Found during the Wave A audit, 2026-08-21. Note that
`code_fingerprint()` still hashes the path string; see
[technical debt](../open/technical-debt.md).
