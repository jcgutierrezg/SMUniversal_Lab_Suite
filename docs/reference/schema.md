---
type: reference
title: "Note frontmatter schema"
---

# Note frontmatter schema

Every instrument note opens with a YAML block. It is not decoration:
`bench/choosing-an-smu.md` and [checkup-owed](../open/checkup-owed.md) are built from it, and
`tests/test_docs.py` refuses a note that is missing a field.

## Why the fields are required rather than defaulted

A default here is a claim nobody made. `bench_ever` defaulting to
`false` would quietly mark a commissioned driver unverified; defaulting
to `true` would do the far worse opposite, which is exactly the mistake
the old documents made in prose. So the schema has no defaults — a new
instrument note cannot be written without deciding each answer.

## Hand-written fields

| Field | Type | Meaning |
|---|---|---|
| `type` | `instrument` | fixed |
| `title` | string | as it appears in tables |
| `driver_class` | string | must match a class in `KNOWN_DRIVERS` |
| `idn` | string or `null` | the **observed** `*IDN?` reply, verbatim |
| `idn_confirmed` | bool | has anyone read this off the unit? |
| `physical` | bool | `false` only for the simulated driver |
| `maintenance` | `active` \| `on-request` | is this driver developed alongside the others? |
| `bench_ever` | bool | has it ever passed a checkup against its instrument? |
| `last_bench` | ISO date or `null` | when, if recorded |
| `bench_notes` | string | what was actually run. Required when `bench_ever` is true |
| `bench_code` | 12-char hex digest or `null` | the `bench_code` line from the report header — which code that checkup ran |
| `bench_result` | `pass` \| `fail` \| `null` | how the last checkup went. Required when `bench_ever` is true |
| `bench_result_note` | string or `null` | what failed. Required when `bench_result` is `fail` |
| `bench_revalidated` | string or `null` | the escape hatch — see below |
| `reading_time` | string or `null` | measured, not from a datasheet |
| `resolution` | string or `null` | measured |
| `best_for` | string | one line of judgement |

### `bench_code` is content, not a date

A driver is *commissioned* only while the code that was checked is the
code that is running. That comparison used to be a date: `git log -1
--format=%cs` on the driver, against `last_bench`.

A commit date is not a property of the tree. `git am` sets it to when
the patch was applied, a rebase sets it to the rebase, and a GitHub
squash-merge sets **both** author and committer date to the instant of
the merge. So the same bytes answered differently depending on when they
were merged — and because the generated pages are committed and
byte-checked, the answer changing under a merge turned `main` red with
nothing in the tree changed.

`bench_code` is a digest of the driver's contents plus its shared
dependencies, computed by `core.provenance.code_fingerprint` and printed
in every checkup report header. Copy it from the report. It survives
rebases, `git am` and squash-merges, because none of them change the
bytes, and it needs no git at all — the check works on a zip download
and on a bench machine with no history.

It still over-reports: a comment-only edit changes the digest and marks
the driver stale. That is the same behaviour the date rule had and the
same conservative direction. The escape hatch is `bench_revalidated`.

### `bench_result` because a date cannot say how it went

`last_bench` records that a session happened. Everything downstream used
to infer that a recorded date meant a clean run, and on 2026-08-21 that
inference broke: the U2722A was checked and failed four checks, and
under the previous schema it would have rendered `Verified: yes` in the
chooser.

So the result is recorded rather than assumed, and a failing driver gets
its own status — `failing`, distinct from `stale`. Stale means nobody
has checked recently. Failing means somebody has, and it did not pass.
`bench_result_note` says what failed, and is rendered into
`docs/open/checkup-owed.md` so the reason is visible without opening the
note.

Anything other than `pass` is treated as failing. A misspelled value
must not be the thing that promotes a failing driver to commissioned.

### `idn` must be observed, never plausible

If nobody has read the string off the unit, `idn` is `null` and
`idn_confirmed` is `false`. A guess is not allowed, and the test
enforces it.

This is not pedantry. `INSTRUMENTS.md` printed
`Keithley Instruments Inc.,MODEL 2635B,4001234,4.0.2` for the 2635B —
invented serial, wrong capitalisation, wrong firmware — inside a code
block formatted identically to the real ones, with a caveat two lines
below that a reader copying the string never sees. The real reply, read
off the unit on 13 August 2026, is
`Keithley Instruments Inc., Model 2635B, 4126721, 3.2.2`.

### `bench_revalidated` is the escape hatch, and it costs a sentence

The staleness check deliberately over-reports: a docstring edit to
`drivers/base_smu.py` marks the whole fleet stale, because the check
cannot tell a comment from a command. That is the right trade — a
checkup takes three minutes, and a driver wrongly believed current costs
a dataset — but it will occasionally be wrong in a way a person can see
and a script cannot.

When that happens, `bench_revalidated` takes a written reason naming the
commit and why it does not affect what the checkup proved. A bare `true`
is refused; the test requires prose. Waving a driver through should cost
a sentence of justification, not a keystroke, because the failure it
guards against — a commissioning claim outliving its truth — is exactly
what happened before.

## Generated fields

Everything between the two markers is written by
`tools/build_docs.py` from the driver class. Editing it by hand is
pointless: the next build overwrites it, and the test fails before then.

```yaml
# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keithley_2635b.py
max_voltage_v: 200
sweep_kind: software
compliance_trip: true
# --- end generated ---
```

`compliance_trip` is asked by comparing the driver's method against
`BaseSMU`'s stub rather than by looking for the name, because a driver
could define the method and still not implement it — and "not reported"
is the answer that matters at the bench either way.

## The supported YAML subset

`tools/build_docs.py` parses this itself rather than depending on
PyYAML. Adding a dependency to read four kinds of scalar would put a
third-party parser between the documentation and the test that guards
it, and CI installs with `uv sync --locked`.

Supported: `key: scalar`, `key:` followed by indented `- items`, inline
`[a, b]`, and `#` comment lines. Scalars may be a quoted string, a bare
string, an integer, a float, `true`, `false`, or `null`.

**Strings are always quoted when written.** Plain YAML scalars have edge
cases that bite silently — a value beginning `~` reads as null in some
parsers, one containing `: ` reads as a mapping. Two characters removes
the class.

Anything outside the subset **raises** rather than being skipped. A
hand-rolled parser that quietly mis-reads a construct would put wrong
numbers into the generated pages with nothing to say so, which is the
whole failure this documentation exists to close.

## The lint escape

Two checks in `tests/test_docs.py` read prose rather than frontmatter: one
refuses a hardcoded count of drivers, instruments, experiments or test
files, and one refuses a mention of a driver method Wave 6d-ii deleted.

Both honour `<!-- lint-ok -->`, **per line**. Use it when the sentence is
recording history rather than making a live claim — "four of the six
drivers returned the sentinel as data" is a finding, and rewording it to
avoid the number would lose the finding.

It is deliberately not a file-level opt-out. One would be added once and
then silently inherited by everything written into that file afterwards,
which is exactly how a temporary allowance becomes permanent.

---

## Stored-file schema

Separate from the frontmatter above, and versioned separately: this is
the `schema` integer in the `#` header of every CSV the suite writes.
The constant is `core.run_store.FILE_SCHEMA`.

One integer for every file kind rather than one each. Two schemes need
somebody to remember which is which, and the version exists precisely
for a reader who was not here.

| Version | Landed | What changed |
|---|---|---|
| *(absent)* | before Wave 7b | no `schema` key. Absence reads as "older than 1", which is true |
| 1 | Wave 7b | `record_id` column; `schema`, `app_version`, `save_kind` and `save_id` header keys |

Bump it whenever a header key or the column layout changes in a way a
reader could notice, and add a row here in the same patch.

### The header keys

| Key | Means |
|---|---|
| `schema` | which layout this file uses |
| `app_version` | the code that wrote it, from `core/version.py` |
| `save_kind` | `snapshot` — the file holds everything in the store at that moment |
| `save_id` | shared by every file one press of Save produced |
| `record_id` | *(a column, not a header)* identifies one stored run; de-duplicate on this |

`record_id` is per stored run, and `run_id` is per lifecycle run. They
are not the same: a periodic IV run commits several records that share
one `run_id`, so de-duplicating on `run_id` would delete real cycles.
