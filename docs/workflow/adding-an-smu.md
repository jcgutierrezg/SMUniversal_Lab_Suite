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
[Note frontmatter schema](../reference/schema.md) refuses one.

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
announce themselves.** The checklist is [Faults to check for](../faults/_index.md) — work
through it *before* writing the driver, not after, because several
change what past data means, which makes finding one a question for
whoever owns that data.

## 4. Write the driver, the registry line, and the ledger entry

Mechanically it is one file in `drivers/`, one line in
`drivers/registry.py`, and one entry in a test ledger. **Nothing in
`experiments/` changes** — if it seems to need to, the difference belongs in
the driver layer and section 2 above is the test for that.

1. **`drivers/<model>.py`**, subclassing `BaseSMU`. Implement the mandatory
   methods — the ones `BaseSMU` leaves raising `NotImplementedError` — set
   `MODEL_IDS` so `*IDN?` resolves to it, and fill in `LIMITS` including the
   power envelope, which is what the range dropdowns and the safety gate
   read.
2. **Declare the optional capabilities**: `NPLC_RANGE`, `OVP_CHOICES`,
   `HIGH_Z_OFF`, `SWEEP_KIND`. The obligation runs **both ways** — declaring
   one obliges you to implement its method, and implementing a method obliges
   you to declare it. The panel reads the *declaration* to decide whether to
   offer a control, so a working feature nobody declared stays greyed out
   forever and nothing reports it.
3. **Register it** in `KNOWN_DRIVERS`.
4. **Add it to `LEDGER`** in `tests/test_driver_contract.py`, recording each
   capability as `True` or `False` with a comment saying why for the Falses.
   The test fails until you do, on purpose.
5. **Run `tests/test_driver_contract.py`.** It checks the mandatory methods;
   that declarations and implementations agree; that your `MODEL_IDS` resolve
   to *your* driver rather than poaching another's; that `LIMITS` is
   internally consistent; and that your method signatures match the rest of
   the suite.

**A hardware sweep is an override, not a branch.** If the model has one,
override `start_linear_sweep`, `sweep_points_ready` and `read_sweep`, and set
`SWEEP_KIND = "hardware"`. If it does not, do nothing at all: the software
fallback in `BaseSMU` is inherited and the experiment cannot tell the
difference. What it *can* tell is which one ran, because every run records
`sweep_kind` — the two give equally accurate levels and not equally
trustworthy timing.

The ledger entry in `tests/test_driver_contract.py` is not optional
bookkeeping: it is what **forces a decision about every other driver**
when this one gains a capability they lack.

Several tests discover drivers from the registry —
`test_sentinel_handling.py`, `test_checkup_all_drivers.py` — so a new
driver cannot quietly opt out of a contract. The documentation does the
same: [Instruments](../instruments/_index.md) has a note per driver and the bijection
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

Both are [A probe asked where the answer is already known](../faults/19-non-discriminating-probe.md), which is the most
repeated fault in this project's history.

## 6b. Decide what the driver can be asked to confirm

Three settings are read back rather than assumed — the compliance, the
four ranges, and any power limit — and the ledger forces a decision on
each. See [fault 33](../faults/33-a-setting-never-read-back.md) for the
five states and why there are five.

For a new driver, both answers are usually the same at first:

- **implement the readback only where the query spelling came off a
  manual or a bench.** Guessing is not conservative here. An
  unrecognised *command* is logged and ignored; an unrecognised *query*
  is never answered, times out and latches the transport, so a guess
  costs a run rather than a line in a report. Leave it `unsupported`,
  say in the ledger which query somebody should try, and it becomes a
  bench task rather than a silent gap.
- **leave `*_READBACK_TRUSTED` False until it has been checked against a
  value the instrument was known to hold.** Not against a value the
  software just wrote — that is a query answering the question it was
  handed. `OUTP?` on the GSM-20H10 returns 0 with the output on and 10 V
  flowing, so a readback that has not been checked is a readback that
  may be lying about the one thing it exists to confirm.

Also declare `SUB_COUNT_LEVELS` per axis. `unmeasured` is the default
and is almost always the honest answer for a new driver; `refused`
requires a `source_level_floor()` and a bench measurement behind it, and
the contract test enforces that pairing in both directions.

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
[A default that is never sent is a default nobody chose](../faults/17-unsent-defaults.md).

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
— [Keithley 2635B](../instruments/keithley-2635b.md) is the fullest, because it was
written from a manual with no original script behind it.

Then run it against the instrument:

```powershell
uv run tools/smu_checkup.py --address <address> --trace
```

**Half the faults this project has found came from this step**, and none
were reachable from the offline suite. Record `last_bench` and
`bench_notes` in the note and rebuild; the chooser table and
[checkup-owed](../open/checkup-owed.md) update themselves.

Expect the commissioning of a *new* driver to find faults in the *old*
ones. It has happened every time — the GSM's sentinel handling, the
B2901A promoting it to `BaseSMU`, the 2635B discovering that no driver
had ever set `format.asciiprecision`. **A new driver written carefully
is the most reliable audit of the existing ones this project has.**
Budget for it.
