# Start here

**The router is [README.md](README.md).** If you are changing the code, go
straight to [docs/_index.md](docs/_index.md).

This file exists because notes, commit messages and past conversations point
at it by name. It is kept deliberately empty of content: it used to be a
1,846-line reference document, and later a second copy of the README's router
that disagreed with it.

## It carries no branch or wave state, on purpose

It used to. It named the branch the current work was on and told the reader
to check it out, and by the time anyone read it that branch had been merged
and deleted. Worse, two readers looking at two checkouts of this repository
days apart reached **opposite conclusions about which branches existed**, one
of them from remote-tracking refs that no `git fetch --prune` had ever
cleaned up.

So the fix is not a fresher branch name here; that is the same defect with a
newer value in it. Branch state is not written down in this repository at
all. Ask the remote, which is the only thing that knows:

```powershell
git fetch --prune
git branch -r
```

What has landed and what is parked is in [docs/plan.md](docs/plan.md); what
changed and when is in [CHANGELOG.md](CHANGELOG.md). Neither names a branch
that has to still exist for the sentence to be true.
