---
type: fault
fault: 35
title: "A derived file built from whatever was lying in the directory"
---

# 35. A derived file built from whatever was lying in the directory

## Symptom

A generated page that changes, and a suite that goes red, because of
something nobody committed. It reproduces on one machine and not
another, and the diff explains nothing.

## Cause

`tools/build_docs.py` computed two of its generated pages by walking
`ROOT.rglob("*.py")` and skipping three directory prefixes: `.venv`,
`build`, `dist`. Everything else in the checkout counted as the
project's source.

It is not. A checkout accumulates things nobody committed.

**First occurrence.** A `.uv-cache` directory left inside the repository
put a Pygments source file within reach of the review-citation grep. It
contributed a citation, a generated page changed, and
`test_generated_pages_match_a_fresh_build` failed. Moving the cache
outside the repository made the suite pass again - which is the shape of
the fault in one sentence: *the answer depended on housekeeping.*

**Second occurrence, and the one that shows it is a class.** Parallel
agent worktrees were created under `.claude/worktrees/`, each holding a
complete copy of the source tree. Every `.py` file existed several times
over. So did every `.md` file, and
`test_no_document_hardcodes_a_count_the_repo_can_derive` - which walked
the same unbounded tree - reported fifteen offences, every one a copy of
one of this repository's own Markdown files.

## Risk

The generator and the test had the same defect, so fixing the generator
alone would have left the class open. And an exclusion list would not
have prevented it: nobody writing the list in Wave 6 could have known
that `.claude/` would exist.

A guard that fires only when somebody's working directory is untidy is
not a guard; it is a source of failures that cannot be reproduced by the
person asked to fix them.

## Detection

The tests that now hold this **construct the condition**: they create an
untracked directory inside the repository containing a `.py` file with a
deviation marker, and a `.md` file with a hard-coded count, and they
check both that the old scan would have picked them up and that the new
one does not. Asking on a tidy tree would have been
[fault 19](19-non-discriminating-probe.md).

## Prevention

**Derive from what the repository contains, not from what the directory
contains.** `git ls-files` answers the first question; `rglob` answers
the second, and they are not the same question even when they happen to
give the same answer.

`owned_files()` in `tools/build_docs.py` is the single implementation,
used by the generator and by every test that scans the tree, so the two
cannot disagree about what "the project's files" means. It lists tracked
files. A defensive exclusion list backs it up where git cannot answer -
a zip download, or no git on PATH - because a fallback that walked
everything would be this fault wearing a fallback's clothes.

The consequence is worth stating rather than discovering: **a new file
is invisible to the generator until it is `git add`-ed.** That is the
right way round. The generated pages are committed artifacts compared
byte-for-byte, so building them from the index means the page in a
commit describes the code in that commit, and cannot describe scratch
work that never left one machine.

## Status

Closed.

## Evidence

Found by the Wave A audit (finding A-06), and then a second time, in a
different disguise, by the tooling that was auditing it.

**And the same shape, in `.gitignore`.** `.claude/` was untracked *and*
unignored, so one `git add -A` would have committed a copy of the whole
repository into itself. The entry is written `.claude`, with no trailing
slash, for the reason recorded in
[delivering work](../workflow/delivering-work.md): `.venv/` matches a
directory and not a symlink of the same name, and that difference once
put an absolute path from the author's machine into a delivered patch.
