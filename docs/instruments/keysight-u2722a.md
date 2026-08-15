---
type: instrument
title: "Keysight U2722A"
driver_class: KeysightU2722A
idn: "AGILENT TECHNOLOGIES,U2722A,MY62030002,R1.10-1.12-1.06"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: null
bench_notes: "checkup passed, all tiers; the exact date was not recorded"
bench_revalidated: null
reading_time: "2 apertures + ~37 ms overhead"
resolution: "14-bit: range / 16384, whatever the NPLC"
best_for: "when the others are busy; permanently 4-wire"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keysight_u2722a.py
driver_class: KeysightU2722A
model_ids: "['U2722A']"
max_voltage_v: 20
max_current_a: 0.12
voltage_ranges_n: 2
current_ranges_n: 6
power_envelope_n: 0
sweep_kind: software
nplc_min: 1
nplc_max: 255
high_z_off: false
ovp: false
remote_sense_control: false
compliance_trip: false
# --- end generated ---
---

# Keysight U2722A

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
