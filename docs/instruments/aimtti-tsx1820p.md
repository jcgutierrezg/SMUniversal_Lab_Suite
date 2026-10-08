---
type: instrument
title: "Aim-TTi TSX1820P"
driver_class: AimTTiTSX1820P
idn: null
idn_confirmed: false
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: false
last_bench: null
bench_notes: "not yet run. The driver was written from the manual on 2026-10-08, before the unit had been asked anything"
bench_code: null
bench_result: null
bench_result_note: null
bench_revalidated: null
reading_time: null
resolution: "10 mV and 10 mA, for setting and for readback. From the specification, not measured"
best_for: "holding a rail or driving a heater, up to 18 V and 20 A - an auxiliary, not a measuring instrument"
connection: "GPIB (GPIB-USB adapter)"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/aimtti_tsx_p.py
model_ids: "['TSX1820P']"
max_voltage_v: 18.15
max_current_a: 20.2
voltage_ranges_n: 1
current_ranges_n: 1
power_envelope_n: 0
sweep_kind: software
nplc_min: null
nplc_max: null
high_z_off: false
ovp: false
ovp_trip: true
remote_sense_control: false
compliance_trip: true
fleet: supply
# --- end generated ---
---

# Aim-TTi TSX1820P

An 18 V, 20 A bench power supply. It is the same instrument as the
[TSX3510P](aimtti-tsx3510p.md) with the output traded the other way —
half the voltage, twice the current — and it shares that model's driver
file, command set, manual and open questions. **That note is the one to
read.** This one records only what differs.

**Nothing here has been confirmed at a bench.**

## Identity and envelope

`*IDN?` has not been read off the unit, so `idn` is `null`.
`MODEL_IDS` matches on `TSX1820P` alone, and
`tests/test_tsx_p.py` checks that each model's identity resolves to its
own class: a 1820 driven by the 3510's class would be allowed 35 V on an
18 V output and refused everything above 10 A.

| | TSX1820P | TSX3510P |
|---|---|---|
| Output voltage | 0 V to 18.15 V | 0 V to 35.3 V |
| Output current | 0.01 A to 20.2 A | 0.01 A to 10.2 A |
| Over-voltage trip | 1 V to 25 V | 1 V to 40 V |

Everything else in the specification is common to both: 10 mV and
10 mA steps, the same accuracies, one quadrant, the 10 mA floor under
the current setting.

## What this means for your data

As for the [TSX3510P](aimtti-tsx3510p.md#what-this-means-for-your-data),
with one thing made worse by the higher current: **lead resistance.**
The manual's own example is that 10 mΩ of lead drops 0.2 V at 20 A,
which on an 18 V output is more than one percent and twenty steps of
the readback. Above a few amps, take the rear links off and wire the
sense terminals to the load — and note that software cannot see which
way they are, so the run records the rule rather than the wiring.

## Reset defaults that had to be overridden

The same one: the over-voltage trip, which `*RST` leaves at its
maximum. Here `reset()` sends `OVP 25`.

## Decisions and deviations

None of its own. The class differs from the 3510's in `MODEL_IDS`,
`LIMITS` and `OVP_RANGE_V` and in nothing else.

## Bench findings

None yet.

## Open questions

The [TSX3510P's list](aimtti-tsx3510p.md#open-questions), run on this
unit as well. A second unit of the same family is not the same measurement:
the firmware versions may differ, and question 7 has different numbers
here — `V 18.15` and `I 20.2` should land, and one step above each
should be refused.
