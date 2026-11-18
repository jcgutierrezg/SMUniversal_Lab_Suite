---
type: instrument
title: "Keithley 2400"
driver_class: Keithley2400
idn: null
idn_confirmed: false
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: false
last_bench: null
bench_notes: null
bench_code: null
bench_result: null
bench_result_note: null
bench_revalidated: null
reading_time: null
resolution: null
best_for: "general-purpose IV and four-contact work up to 210 V, or 1 A up to 21 V"
connection: null

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keithley_2400.py
model_ids: "['MODEL 2400']"
max_voltage_v: 210
max_current_a: 1.05
voltage_ranges_n: 4
current_ranges_n: 7
power_envelope_n: 2
sweep_kind: software
nplc_min: 0.01
nplc_max: 10
high_z_off: true
ovp: false
ovp_trip: false
remote_sense_control: true
compliance_trip: true
fleet: smu
# --- end generated ---
---

# Keithley 2400

The 200 V member of the 2400 series: the [Keithley 2401](keithley-2401.md)
with one more voltage range. It speaks the 2401's dialect, through the
same code, and runs every experiment the 2401 does - IV sweeps, Fixed
sourcing, Van der Pauw, Hall and the 4-point probe.

## How it was written

From the *Model 2400 Series SourceMeter User's Manual* (2400S-900-01,
the same PDF as the 2401's, in `manuals/2401 SMU/`) and the 2401's
commissioned driver. No probe: the command reference is one for the
whole family, and every command this driver sends has already been
checked at the bench on the 2401.

**Where the code lives.** On 2026-11-18 the 2401's driver was split in
two. Everything that speaks the dialect went into
`drivers/keithley_2400_series.py`, unchanged, and both models build on
it. Each model file holds only what is its own: identity, envelope, and
the numbers measured on that unit. An edit to the series file stales
both checkups - see
[Checkup owed](../open/checkup-owed.md).

## Identity and envelope

| | 2400 | 2401 |
|---|---|---|
| Voltage ranges | 200 mV, 2 V, 20 V, **200 V** | 200 mV, 2 V, 20 V |
| Maximum voltage | ±210 V | ±21 V |
| Current ranges | 1 µA to 1 A | the same |
| Envelope | 21 V at 1.05 A, **or** 210 V at 105 mA | 21 V at 1.05 A |

The envelope is declared as two corners, as on the
[Keithley 2450](keithley-2450.md), so a run asking for more than
105 mA of compliance above 21 V is refused before anything is sent.
Above 50 V the run asks first, as on every SMU here that can get there.

It is matched on `MODEL 2400` only. A bare `2400` would match a serial
number that contains it; the 2401's longer `MODEL 2401` still wins for a
2401 whose serial does.

## No borrowed bench claims

The 2401's readbacks are trusted and its current axis has a measured
sub-count floor - both from sessions with that unit (serial 4084766).
None of that carries over:

- **Compliance and range readbacks are `unverified`.** The queries are
  the same, so they answer and a disagreement still fails loudly, but
  whether they report the state rather than the last write is a
  `tools/bench_readback.py` question not yet asked of a 2400.
- **Both source axes are `unmeasured`.** No floor is applied to small
  levels until `tools/bench_envelope.py` has been run on a 2400.

## Reset defaults that had to be overridden

The 2401's, by the same code: `:OUTP:ENAB 0` (the output-enable line
off), `:SYST:RSEN 1` (4-wire, as the rigs are wired) and
`:SOUR:CLE:AUTO 0` (the level held between points). See
[the 2401's note](keithley-2401.md#reset-defaults-that-had-to-be-overridden).

## Connection

Not yet known. GPIB or RS-232. **GPIB address 24 is the factory default
of both models, and the 2401 here is already on 24**, so a 2400 on the
same bus needs another address set from its front panel. The address
list names it once its first checkup report records where it is.

## Not done yet

- **The first checkup**: `uv run tools/smu_checkup.py --address <addr> --trace`.
- **`tools/bench_readback.py`**, to earn the readback trust the 2401 has.
- **`tools/bench_envelope.py`**, for a sub-count floor of its own.
- **Over-voltage protection.** `:SOUR:VOLT:PROT` would be a hardware
  backstop on the 200 V range; `*RST` leaves it at NONE. Left for a
  change of its own, since the 2401 has nothing like it.
