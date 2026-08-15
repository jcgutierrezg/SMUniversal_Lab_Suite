---
type: reference
title: "Note frontmatter schema"
---

# Note frontmatter schema

Every instrument note opens with a YAML block. It is not decoration:
`bench/choosing-an-smu.md` and [[checkup-owed]] are built from it, and
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
| `bench_revalidated` | string or `null` | the escape hatch — see below |
| `reading_time` | string or `null` | measured, not from a datasheet |
| `resolution` | string or `null` | measured |
| `best_for` | string | one line of judgement |

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
