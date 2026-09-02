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
| 2 | audit A-04 | `build_id` header key. Additive — an older reader does not see it and `pd.read_csv(path, comment="#")` is unaffected either way |

Bump it whenever a header key or the column layout changes in a way a
reader could notice, and add a row here in the same patch.

### Line endings: LF, decided

Every file this suite writes uses **LF**, on every platform. It is not a
schema version, because nothing about the header or the columns changes
and both forms were already in the wild — a file saved on Linux was LF
and the same file saved on Windows was CRLF, from identical code.

That divergence is what made the decision necessary. `core/run_store.py`
sets `lineterminator="\n"` on both CSV writers and joins both `#` blocks
with `"\n"`; `LabApp.write_atomic()` opened in text mode and translated
every one of them, so the builder and the file on disk disagreed. RFC
4180 specifies CRLF for CSV, so CRLF would have been defensible too —
what was not defensible is that neither end had decided. Settled as LF
because a file whose bytes depend on which bench machine saved it cannot
be compared or checksummed against another, and because `csv`,
`pandas.read_csv` and Excel all read either.

**Nothing you already have needs converting.** A reader that opens these
files in Python text mode, or through `pandas.read_csv`, sees no
difference; one that splits on `\r\n` explicitly was already wrong for
every file written on Linux. See
[fault 36](../faults/36-two-ends-disagreeing-about-newlines.md).

### The header keys

| Key | Means |
|---|---|
| `schema` | which layout this file uses |
| `app_version` | the release that wrote it, from `core/version.py` |
| `build_id` | the release **and the commit** — `0.1.0+g5e7308eff34a` |
| `save_kind` | `snapshot` — the file holds everything in the store at that moment |
| `save_id` | shared by every file one press of Save produced |
| `record_id` | *(a column, not a header)* identifies one stored run; de-duplicate on this |

`record_id` is per stored run, and `run_id` is per lifecycle run. They
are not the same: a periodic IV run commits several records that share
one `run_id`, so de-duplicating on `run_id` would delete real cycles.

### `build_id`, because a release number that never moves says nothing

`app_version` is set by hand. It said `0.1.0` from Wave 7b-ii through
every wave that followed, and every one of those waves changed
behaviour — so a file from March and a file from September carried the
same answer to "which code produced this?". That is the question the
field exists for.

`build_id` is `app_version` with the commit welded on, in three forms:

| Form | Means |
|---|---|
| `0.1.0+g5e7308eff34a` | that release, built from that commit, clean tree |
| `0.1.0+g5e7308eff34a.dirty` | that commit **plus uncommitted changes** — the code that ran exists nowhere else |
| `0.1.0+unknown` | no way to determine a build. A zip download, or a frozen build shipped without a stamp |

Twelve hex characters, the same width `core.provenance` prints in a
checkup report header, so a stored file and a bench report compare by
eye. `.dirty` is not decoration: a sha alone would name a commit that
does not contain what ran.

`unknown` is written rather than the key being left out. An absent key
reads as "written by a version that did not record builds"; `unknown`
reads as "written by one that tried and could not tell". Those are
different facts about the file, and a provenance stamp that silently
disappears is the failure this field exists to remove.

A frozen `.exe` has no repository and may have no `git` at all, so it
receives the commit at build time and reads it from a baked-in
constant. The procedure is in
[Packaging and deployment](../workflow/packaging.md).

### Identifiers, and how wide the random part is

`smp-`, `rec-`, `sav-` and `res-` identifiers are a date and a random
tail. Run identifiers are the experiment, a per-session sequence
number, a timestamp and the session:

```
smp-20260808-a3f19c2b7d4e6f81
ossila_4pp-0007-20260808T143012-3f9a1c22b7e04d61
```

The tail is 64 bits. It was 32, on the strength of an arithmetic claim
in `core/identity.py` that a few hundred a day gave a collision
"roughly every ten thousand years"; the birthday expectation for 300
draws from 2³² is about 1.0 × 10⁻⁵ per day, which is **one collision
every 260 years or so**, and a `rec-` is minted per run rather than per
sample. At 64 bits the same figure is about 10¹² years.

The session on a run identifier is 64 random bits drawn once per
process. Without it, a restarted application — or a second bench
machine — produced the identical first run identifier, because the
sequence number restarts at 1 and the timestamp resolves to one second.
`run_id` is the join key between a stored row and the operational event
log, so that collision joined one run's readings to another run's
outcome.

**Old identifiers still read.** Stored files carry 8-character tails
and run identifiers with no session part. `core.identity.parse_object_id`
and `parse_run_id` accept both shapes; only the new one is written.
