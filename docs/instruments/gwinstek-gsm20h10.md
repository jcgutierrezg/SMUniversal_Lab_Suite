---
type: instrument
title: "GW Instek GSM-20H10"
driver_class: GWInstekGSM20H10
idn: "GWInstek,GSM-20H10,GEW852313,V1.16"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: "2026-08-14"
bench_notes: "checkup 2026-08-05 found four faults; :ABOR probe 2026-08-14"
bench_revalidated: null
reading_time: "~50 ms at NPLC 0.01"
resolution: "not characterised"
best_for: "long unattended sweeps; per-quantity compliance reporting"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/gwinstek_gsm20h10.py
driver_class: GWInstekGSM20H10
model_ids: "['GSM-20H10', 'GSM20H10', '20H10']"
max_voltage_v: 210
max_current_a: 1.05
voltage_ranges_n: 4
current_ranges_n: 7
power_envelope_n: 2
sweep_kind: hardware
nplc_min: 0.01
nplc_max: 10
high_z_off: true
ovp: true
remote_sense_control: true
compliance_trip: true
# --- end generated ---
---

# GW Instek GSM-20H10

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
