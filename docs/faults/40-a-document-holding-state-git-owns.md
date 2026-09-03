---
type: fault
fault: 40
title: "A document holding state that git already owns"
---

# 40. A document holding state that git already owns

## Symptom

A document states a fact about the repository. Three people read the
same repository and get three different answers about whether the
document is right, and none of them is being careless.

`HANDOFF.md` named a `wave8` branch as the one to start from. Asked
whether that branch existed, the original audit said no, one reviewer
said yes, and a third reader's first check also said yes. The branch had
in fact been merged and deleted on the remote. All three were reading
`git branch -a` in checkouts whose remote-tracking refs had not been
pruned, so each was reporting a local cache of a fact that had moved.

## Cause

The document was holding a piece of state that git already owns, and
that lives on a server rather than in the checkout.

That makes the claim unmaintainable by care. A stale *value* is fixed by
updating it; a stale *kind of value* is not, because the next person to
read the document is in the same position as the last one - reading a
copy, with no way to tell from the copy how old it is. The reader who
notices nothing is the one who agrees with the cache.

`git fetch --prune` makes the two agree again, which is precisely the
problem: the document's correctness depends on a housekeeping step
nobody is told to run.

## Risk

An onboarding document is read by somebody who does not yet know the
repository, which is the one audience with no independent way to check
it. A wrong branch name sends work onto a base that is not the base, and
the cost lands at merge time rather than at the moment of the mistake.

It also fails quietly in the direction of looking maintained. "The
branch is `wave8`" reads exactly like a fact somebody checked this
morning.

## Detection

For any sentence in a document, ask **where the fact lives**. If the
authoritative copy is outside the repository - a remote's branch list, a
CI dashboard, an issue tracker, somebody's machine - then the sentence
is a cache, and a cache with no invalidation is a claim that decays
silently.

The tell in review is a disagreement that survives everyone checking
again. Three readers who each checked and each got a different answer
are not careless; they are reading three copies.

## Prevention

**Remove the dependency, do not update the value.** The branch name came
out of `HANDOFF.md` entirely, replaced by the instruction to ask git for
the branch rather than to read it here.

The general rule this project already applies elsewhere: a derived claim
must rest on something that cannot be rewritten underneath it - see
[A derived claim resting on something a merge rewrites](24-derived-from-a-rewritable-date.md).
This is the same rule for a *hand-written* document rather than a
generated one. Where a document genuinely must name repository state,
the value is generated into it by `tools/build_docs.py` from the tree,
so a stale copy fails the suite instead of misleading a reader.

## Status

Closed for the branch name. The class stays open by nature: every
document can acquire a new sentence of this kind.

## Evidence

Found during the Wave C audit, by three readers disagreeing about one
branch. Distinct from
[A provenance stamp that never moves](31-a-stamp-that-never-moves.md),
which is a field that is present and no longer discriminating; here the
field discriminates perfectly and is answering about a different
machine.
