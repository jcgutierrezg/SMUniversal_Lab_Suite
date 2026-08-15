---
type: instrument
title: "Keithley 2635B"
driver_class: Keithley2635B
idn: "Keithley Instruments Inc., Model 2635B, 4126721, 3.2.2"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: "2026-08-14"
bench_notes: "checkup 2026-08-13, bench probes 2026-08-14 (ranging, sentinel, asciiprecision)"
bench_revalidated: null
reading_time: "~87 ms (autorange floor at 100 pA)"
resolution: "measures to 100 pA; sources to 1 nA"
best_for: "high-resistance samples and sub-nanoamp currents"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keithley_2635b.py
driver_class: Keithley2635B
model_ids: "['MODEL 2635B', '2635B']"
max_voltage_v: 200
max_current_a: 1.5
voltage_ranges_n: 4
current_ranges_n: 11
power_envelope_n: 2
sweep_kind: software
nplc_min: 0.001
nplc_max: 25
high_z_off: true
ovp: false
remote_sense_control: true
compliance_trip: true
# --- end generated ---
---

# Keithley 2635B

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
