---
type: instrument
title: "Keithley 2450"
driver_class: Keithley2450
idn: null
idn_confirmed: false
physical: true
maintenance: on-request

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: false
last_bench: null
bench_notes: "not in this lab - the hardware belongs to the group that wrote the original Van der Pauw and Hall scripts"
bench_revalidated: null
reading_time: null
resolution: null
best_for: "kept so the lab that owns one can adopt the suite"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keithley_2450.py
model_ids: "['MODEL 2450', '2450']"
max_voltage_v: 210
max_current_a: 1.05
voltage_ranges_n: 5
current_ranges_n: 9
power_envelope_n: 2
sweep_kind: software
nplc_min: 0.01
nplc_max: 10
high_z_off: true
ovp: false
remote_sense_control: true
compliance_trip: false
# --- end generated ---
---

# Keithley 2450

**Nothing in this driver has ever met hardware.** It is kept, and kept
working, because the Van der Pauw and Hall scripts this repository was
built from used one — and that group may adopt the suite. It is not
developed alongside the others, which is what `maintenance: on-request`
records.

There is no `*IDN?` string here because nobody has read one off a unit.
A plausible-looking guess in this field would be worse than a blank: see
[[schema]].

## Identity and envelope

210 V, 1.05 A, nine current ranges, with a two-corner power envelope —
210 V at 105 mA *or* 21 V at 1.05 A. Most SMUs cannot reach maximum
voltage and maximum current at once, and a flat max_v/max_i pair would
happily allow an impossible request.

**The model is confirmed as a 2450**, so the declared limits are right.
It had been an inference — `:SOUR:CURR:VLIM` is 2450/2460/2470-specific
syntax and the driver was written from that — and it is now settled.
What remains unconfirmed is the `*IDN?` reply, which is a different
question: the model tells us the limits are correct, the identity string
is what auto-detection matches on.

## Reset defaults that had to be overridden

None recorded, because the driver has never been exercised against an
instrument. That is a gap rather than a finding: **every driver written
from a manual so far has had at least one reset default that had to be
overridden**, so the honest expectation is that this one has an
unfound one too.

## Decisions and deviations

**The source/measure range ambiguity is closed.** This is worth stating
plainly, because the previous documentation described it as an open
defect needing "a wave of its own, and not one to start without a 2450
on a bench."

That wave happened. `BaseSMU.set_current_range()` and <!-- lint-ok -->
`set_voltage_range()` were documented as setting a **measurement** range <!-- lint-ok -->
while this driver's `set_current_range()` sent `:SOUR:CURR:RANG`, a <!-- lint-ok -->
*source* range — and 4PP and Van der Pauw called it as though it meant
source while IV sweep called it the documented way. Nothing produced a
wrong number, because the mismatches cancelled on the instruments
actually in use.

Wave 6d-i replaced both methods with a four-axis `RangePlan`, and 6d-ii
deleted them. This driver now implements all four per-axis hooks with
the source and measure spellings correctly separated:

| Axis | Command |
|---|---|
| source current | `:SOUR:CURR:RANG` |
| source voltage | `:SOUR:VOLT:RANG` |
| measure current | `:SENS:CURR:RANG` |
| measure voltage | `:SENS:VOLT:RANG` |

`RangePlan.for_sourcing()` additionally makes the one combination no SMU
accepts — a measurement range for the quantity being sourced —
impossible to express, which is what error 823 on the 2401 and the GSM
was telling us.

`tests/test_docs.py` asserts that no note describes those two deleted <!-- lint-ok -->
methods, so this correction cannot silently come back.

## Bench findings

None. That is the point of this note.

## What this means for your data <!-- bench -->

**Do not trust a measurement from this instrument without running the
checkup first.** Every other driver here was commissioned against real
hardware and the process found nine faults across them — four of which
produced plausible-looking wrong data rather than an error. There is no
reason to think this driver is the exception; it simply has not been
asked.

```
uv run tools/smu_checkup.py --address <address> --trace
```

Nothing connected to the outputs. Three minutes, and it writes a report.

**Auto-detection may not recognise it on first connect.** The `*IDN?`
reply has never been read off a unit, so `MODEL_IDS` is written from the
family convention. If detection fails, the app offers a manual driver
dropdown — an inconvenience rather than a dead end. Please send the
string back so it can be recorded.

## Open questions

- **What is its `*IDN?`?** Until that is read off the unit,
  auto-detection is an educated guess and manual driver selection is the
  fallback. `tools/visa_doctor.py --idn` prints it.
- **Which reset default is this driver missing?** Every other
  manual-written driver had at least one.
