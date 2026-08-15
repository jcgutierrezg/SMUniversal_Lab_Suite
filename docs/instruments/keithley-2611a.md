---
type: instrument
title: "Keithley 2611A"
driver_class: Keithley2611A
idn: "Keithley Instruments Inc., Model 2611A, 1314733, 2.2.2"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: "2026-08-14"
bench_notes: "checkup 2026-08-13, bench probes 2026-08-14"
bench_revalidated: null
reading_time: "1 aperture + ~13 ms overhead"
resolution: "not range-limited"
best_for: "matched V and I in one conversion; fast hardware sweeps"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keithley_2611a.py
driver_class: Keithley2611A
model_ids: "['MODEL 2611A', '2611A']"
max_voltage_v: 200
max_current_a: 1.5
voltage_ranges_n: 4
current_ranges_n: 9
power_envelope_n: 2
sweep_kind: hardware
nplc_min: 0.001
nplc_max: 25
high_z_off: true
ovp: false
remote_sense_control: true
compliance_trip: true
# --- end generated ---
---

# Keithley 2611A

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
