---
type: instrument
title: "Keithley 2400"
driver_class: Keithley2400
idn: "KEITHLEY INSTRUMENTS INC.,MODEL 2400,0797936,C22   May 21 2001"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: 2026-11-19
bench_notes: "2026-11-19 12:01 first checkup at 2d72012, GPIB, firmware C22, nothing attached: 64 pass, 9 warn, 1 fail, 6 skip. Every live check passed - readings at 0 and 0.1 V, open-circuit current 20 nA, current sourcing into the 1 V limit with compliance_tripped() True, a 5-point software sweep. Burst check 10 of 10 on bursts of up to 16 writes, slowest reply 82 ms. Warnings: the five untrusted readbacks (all agreeing) and the three unmeasured floor checks"
bench_code: "17bb33547a67"
bench_result: fail
bench_result_note: "reset() sent :OUTP:ENAB 0, which firmware C22 does not know (-113 Undefined header); dropped from the shared reset the same day"
bench_revalidated: null
reading_time: "35.7 ms at NPLC 0.01 (its declared minimum), +82 ms first read - 2x"
resolution: null
best_for: "general-purpose IV and four-contact work up to 210 V, or 1 A up to 21 V"
connection: "GPIB"

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

The 2401's, by the same code: `:SYST:RSEN 1` (4-wire, as the rigs are
wired) and `:SOUR:CLE:AUTO 0` (the level held between points). See
[the 2401's note](keithley-2401.md#reset-defaults-that-had-to-be-overridden).

## First checkup, 2026-11-19

This unit runs firmware **C22** (May 2001). It failed one check: the
error queue after `reset()` held `-113, "Undefined header"`. Of the
commands sent after `*CLS`, `:SYST:RSEN` and `:SOUR:CLE:AUTO` were sent
again later in the run without an error, which leaves
`:OUTP:ENAB 0` - the output-enable line, which C22 does not know
although the manual says every 2400 has it.

The command was not doing anything: `*RST` already leaves the
output-enable line off. It was dropped from the shared reset, so both
models' checkups went stale and both are owed again. The firmware is
staying at C22.

Everything live passed: readings at 0 V and 0.1 V, current sourcing
into the 1 V limit with the trip reported, and the software sweep.

## Connection

GPIB, address **23** on the bench's GPIB0. The first checkup ran on a
second adapter (GPIB1) for that sitting only; the address list records
it on GPIB0, where it lives. Both models leave the factory on 24, and
the 2401 here has that.

## Not done yet

- **A passing checkup** on the reset without `:OUTP:ENAB 0`:
  `uv run tools/smu_checkup.py --address GPIB0::23::INSTR --trace`.
- **`tools/bench_readback.py`**, to earn the readback trust the 2401 has.
- **`tools/bench_envelope.py`**, for a sub-count floor of its own.
- **Over-voltage protection.** `:SOUR:VOLT:PROT` would be a hardware
  backstop on the 200 V range; `*RST` leaves it at NONE. Left for a
  change of its own, since the 2401 has nothing like it.
