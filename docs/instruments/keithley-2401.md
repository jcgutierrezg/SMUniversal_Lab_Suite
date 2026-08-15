---
type: instrument
title: "Keithley 2401"
driver_class: Keithley2401
idn: "KEITHLEY INSTRUMENTS INC.,MODEL 2401,4084766,A01 Aug 25 2011"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: null
bench_notes: "checkup passed, all tiers; the exact date was not recorded"
bench_revalidated: null
reading_time: "~44 ms at NPLC 0.01"
resolution: "not characterised"
best_for: "general-purpose IV work up to 21 V"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keithley_2401.py
driver_class: Keithley2401
model_ids: "['MODEL 2401', '2401']"
max_voltage_v: 21
max_current_a: 1.05
voltage_ranges_n: 3
current_ranges_n: 7
power_envelope_n: 0
sweep_kind: software
nplc_min: 0.01
nplc_max: 10
high_z_off: true
ovp: false
remote_sense_control: true
compliance_trip: false
# --- end generated ---
---

# Keithley 2401

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
