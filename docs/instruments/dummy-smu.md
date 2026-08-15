---
type: instrument
title: "Dummy SMU (demo mode)"
driver_class: DummySMU
idn: "Anthropic Lab Suite,DUMMY SMU,0,1.0"
idn_confirmed: true
physical: false
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: false
last_bench: null
bench_notes: "simulated - there is no instrument to commission"
bench_revalidated: null
reading_time: "instant"
resolution: "exact"
best_for: "development and demo without hardware"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/dummy_smu.py
driver_class: DummySMU
model_ids: "['DUMMY SMU']"
max_voltage_v: 200
max_current_a: 1
voltage_ranges_n: 5
current_ranges_n: 9
power_envelope_n: 2
sweep_kind: hardware
nplc_min: 0.01
nplc_max: 10
high_z_off: true
ovp: true
remote_sense_control: true
compliance_trip: false
# --- end generated ---
---

# Dummy SMU (demo mode)

> **Stub.** Frontmatter is complete and drives the generated pages; the
> prose body arrives with `docs-instruments-v1`, which rehomes this
> instrument's sections from `INSTRUMENTS.md` and its deviations from
> `PORTING_NOTES.md`.

## Identity and envelope

## Reset defaults that had to be overridden

## Decisions and deviations

## Bench findings

## What this means for your data

## Open questions
