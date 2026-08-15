---
type: instrument
title: "Undalogic miniSMU MS01"
driver_class: UndalogicMiniSMU
idn: "Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: null
bench_notes: "checkup passed; timing scan 6-point. Exact date not recorded"
bench_revalidated: null
reading_time: "~6 ms floor (link-limited)"
resolution: "~-1.5 mV voltage offset, confirmed three ways"
best_for: "small, portable, quick; not for single-point small voltages"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/undalogic_minismu.py
driver_class: UndalogicMiniSMU
model_ids: "['MINISMU MS01', 'MINISMU', 'MS01']"
max_voltage_v: 12
max_current_a: 0.18
voltage_ranges_n: 4
current_ranges_n: 5
power_envelope_n: 2
sweep_kind: hardware
nplc_min: 0.0005
nplc_max: 16.384
high_z_off: false
ovp: false
remote_sense_control: true
compliance_trip: false
# --- end generated ---
---

# Undalogic miniSMU MS01

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
