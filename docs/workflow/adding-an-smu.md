---
type: reference
title: "Adding an SMU"
---

# Adding an SMU

The path most likely to be walked next, so here it is in full.

## 1. Get the script and the manual

Ask for the working script *and* the manual's **Command List** — the
summary tables, not the prose pages. Both earn their place: the script
shows what the lab actually does; the command list settles argument
values.

**Pasted text beats screenshots.** SCPI ambiguity between `:` and `;`,
or `l` and `1`, is exactly the kind of error that fails silently.

Also ask for the **`*IDN?` reply**, which is the one thing no document
provides and which turns `MODEL_IDS` from a guess into a fact. If nobody
has read it off the unit, the note records `null` — a plausible-looking
guess in that field is worse than a blank, and
[[../reference/schema]] refuses one.

## 2. Decide what it is before writing anything

A different instrument is **never** a new experiment — that is what the
driver layer is for.

| If | Then |
|---|---|
| same measurement, different box | **driver only**, nothing else changes |
| same result columns, different sweep shape (log, list, pulsed, hysteresis) | **a feature in the existing experiment**, not a subclass |
| a different *derived quantity* | **a new experiment folder** |

Precedent for the middle row: three IV scripts collapsed into one
experiment with optional panels. Precedent for the last: Van der Pauw,
Hall and 4PP each earn a folder because each produces a different
quantity.

## 3. Read the original for the recurring faults

Every script ported so far has carried at least one, and **none of them
announce themselves.** The checklist is [[../faults/_index]] — work
through it *before* writing the driver, not after, because several
change what past data means, which makes finding one a question for
whoever owns that data.

## 4. Write the driver, the registry line, and the ledger entry

The ledger entry in `tests/test_driver_contract.py` is not optional
bookkeeping: it is what **forces a decision about every other driver**
when this one gains a capability they lack.

Several tests discover drivers from the registry —
`test_sentinel_handling.py`, `test_checkup_all_drivers.py` — so a new
driver cannot quietly opt out of a contract. The documentation does the
same: [[../instruments/_index]] has a note per driver and the bijection
is a test.

## 5. Test the command spellings, not just the results

A wrong SCPI header is logged by the instrument and ignored — no
exception, no warning, **the previous setting simply stays in force.** A
test asserting only that a sweep came back will pass against a driver
that silently does nothing.

Assert the exact strings, and assert that the *other* dialects'
spellings are **absent**. `tests/test_gsm20h10.py` is the model.

## 6. Where a command is inferred rather than documented, verify at runtime

The GSM's staircase sweep sends a probe at connect and reads
`SYST:ERR?`, falling back to the software sweep if the instrument
objects. That turns a guess from a silent wrong answer into a logged,
self-healing case.

**Make sure the probe is discriminating.** The B2901A's first one
counted enabled measurement functions — but reset already left all six
enabled, so the count was true whether or not the command had worked. A
probe that returns a fact is only useful if the fact would differ on
failure.

**And ask it where the interesting answer is the correct one.** The
checkup called `compliance_tripped()` with the output off, where `False`
is honest — so a method stuck at `False` passed. Two of the fakes
answered with a hardcoded `"false"`, which would have made a better
probe pass against a fake incapable of saying otherwise.

Both are [[../faults/19-non-discriminating-probe]], which is the most
repeated fault in this project's history.

## 7. Ask for the reset table, not just the spellings

**Every driver written from a manual so far has had at least one setting
whose reset default had to be overridden**, and the worst ones had no
command in the log to trace them to: the B2901A energises its own output
on `:INIT`/`:READ`, and the 2635B's "output off" is a driven 0 V source
with 1 mA available rather than a disconnection.

Ask for the **per-attribute default tables** — Keithley and Keysight both
publish them — and read the *Affected by* column, because a setting
reset does not touch (`localnode.linefreq`) needs the opposite treatment
from one it does.

Transcribe both tables into `docs/reference/manuals/` as Markdown. The
PDFs are not committed, and a table that can be grepped, diffed and
linked from a driver note is worth the transcription. See
[[../faults/17-unsent-defaults]].

## 8. Mutate your own driver before believing the tests

Both drivers written from a manual passed their own tests first time,
and **both times a mutation pass found real holes.** Change one thing,
run the tests, confirm something goes red, revert.

The 2635B's pass found four survivors, including a `format.data`
assertion that checked instrument state the fake's own `reset()` had
already set — true whether or not the driver sent anything.

The mutations worth trying: swap a return pair, cross two setters,
delete a reset override, delete the reset itself, and hardcode a
parameter the caller passes in.

## 9. Write the note, and commission it

A driver with no note fails the suite. Copy the shape of an existing one
— [[../instruments/keithley-2635b]] is the fullest, because it was
written from a manual with no original script behind it.

Then run it against the instrument:

```powershell
uv run tools/smu_checkup.py --address <address> --trace
```

**Half the faults this project has found came from this step**, and none
were reachable from the offline suite. Record `last_bench` and
`bench_notes` in the note and rebuild; the chooser table and
[[../open/checkup-owed]] update themselves.

Expect the commissioning of a *new* driver to find faults in the *old*
ones. It has happened every time — the GSM's sentinel handling, the
B2901A promoting it to `BaseSMU`, the 2635B discovering that no driver
had ever set `format.asciiprecision`. **A new driver written carefully
is the most reliable audit of the existing ones this project has.**
Budget for it.
