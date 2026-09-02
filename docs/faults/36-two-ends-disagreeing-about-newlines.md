---
type: fault
fault: 36
title: "A writer that quietly rewrote what it was handed"
found_by: "the Wave A audit follow-up"
---

# 36. A writer that quietly rewrote what it was handed

*Found while auditing finding A-06.*

Two places in this project decided their own line endings, and the layer
between them overruled both without saying so.

**The generated documents.** `tools/build_docs.py` wrote every page with
`Path.write_text(text, encoding="utf-8")`. Text mode translates `\n` to
`\r\n` on Windows. `.gitattributes` pins these files to LF, so a rebuild
on a bench machine left every generated page showing as modified with no
content change — once, enough to block a `git switch`. Measured on the
current tree: a regenerated `docs/reference/review-index.md` had **44
CRLF pairs and zero LF bytes**.

**The measurement CSVs.** `core/run_store.py` sets
`lineterminator="\n"` on both CSV writers and joins both `#` headers
with `"\n"` — deliberately, with a test asserting it. `write_atomic()`
then opened the file in text mode with no `newline`, and translated
every one of them. **The code that produced a measurement file and the
file on disk disagreed about its bytes**, on every save taken on
Windows.

## Why nothing noticed

Both guards asked on the side that was already right.

`test_generated_pages_match_a_fresh_build` compares with `read_text`,
which decodes using universal newlines — a CRLF page compares **equal**
to the LF text meant to replace it. So the comparison said "up to date",
the rebuild that would have fixed it never ran, and `--check` passed
against files it would not itself have written.

`test_the_files_are_written_with_lf_endings` inspected the string the
builder returned. That string was never wrong. The translation happened
one layer down, at the file.

[Fault 19](19-non-discriminating-probe.md) again, in its quietest form:
both tests were asking a real question in a place where the answer was
already known.

## The decisions

**Generated pages: LF, and staleness judged on bytes.** `write_lf()` and
`is_current()` in `tools/build_docs.py`. A CRLF page *is* stale — it is
not what the tool produces — and once staleness is a byte comparison, a
rebuild converges instead of declaring victory.

**Measurement CSVs: LF, by preserving what the builder produced.**
`write_atomic` opens with `newline=""`.

This one was a real decision rather than an obvious bug, and it is worth
recording that it was taken rather than defaulted into. RFC 4180
specifies CRLF for CSV, so CRLF on disk was defensible. Three things
settled it:

- Files written on Linux were always LF, so no reader can ever have
  depended on CRLF. `csv`, `pandas.read_csv` and Excel take either.
- A file whose bytes depend on which bench machine saved it cannot be
  compared, checksummed or diffed against another — the same argument
  `build_id` in the header exists to make.
- A writer that silently rewrites its input is the wrong shape whichever
  ending wins. `write_atomic` is asked to put *this text* on disk.

No `schema` bump: the header keys and the column layout are unchanged,
and both forms already existed in the wild depending on the platform.
See [the stored-file schema](../reference/schema.md).

## The rule

**Assert on the artifact, not on the value that was about to become
one.** A test that reads a string, and a test that reads the file that
string was written to, are answering different questions, and only the
second one is about what a reader will get.
