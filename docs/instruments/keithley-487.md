---
type: instrument
title: "Keithley 487"
driver_class: Keithley487
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
best_for: "picoamp currents and high resistance, sourcing up to 505 V - IV sweeps and fixed-voltage traces only"
connection: "GPIB (GPIB-USB adapter)"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keithley_487.py
model_ids: "[]"
max_voltage_v: 505
max_current_a: 0.0025
voltage_ranges_n: 2
current_ranges_n: 7
power_envelope_n: 0
sweep_kind: software
nplc_min: 0.1
nplc_max: 1
high_z_off: false
ovp: false
ovp_trip: false
remote_sense_control: false
compliance_trip: true
fleet: smu
# --- end generated ---
---

# Keithley 487

A picoammeter with a ±505 V voltage source beside it, from the late
1980s. It measures current from 10 fA to 2 mA and sources voltage, and it
does nothing else: it cannot source a current and nothing in it measures
a voltage. It joins the SMU fleet as a voltage-only source-measure unit,
not as a fleet of its own - see
[An SMU that sources one quantity is still an SMU](../architecture/devices.md#an-smu-that-sources-one-quantity-is-still-an-smu).

Written from the Model 486/487 Instruction Manual, a scanned copy, with
no script behind it. The command summary and the reset table it was
written from are in [487 command summary](../reference/manuals/487-commands.md).

## Identity and envelope

**It answers no `*IDN?`.** It speaks Keithley's device-dependent
commands - a letter, an option, then `X` - and `*IDN?` is an illegal
command to it, flagged and never answered. An unanswered query latches
the transport, so the 487 is never auto-detected: **choose "Keithley 487"
from the manual driver list at Connect.** `MODEL_IDS` is empty on
purpose, and `NO_IDN` in `tests/test_driver_contract.py` records why.

Its identity question is `U2X`, which the manual says answers the model
and firmware, `487A03` with two trailing blanks. `idn` above is `null`
because nobody has read it off this unit yet. `reset()` asks it before it
configures anything, and refuses an instrument that does not answer
`487` - a 486 answers `486`, and is the same picoammeter with no source.

| | |
|---|---|
| Source | ±50.500 V in 1 mV steps, or ±505.00 V in 10 mV steps |
| Current limit | 25 µA or 2.5 mA (±20%), nothing between |
| Ammeter | 2 nA to 2 mA in seven decades, 10 fA resolution on 2 nA |
| Burden | under 200 µV below 100 µA |
| Integration | 1.6 ms (4½ digits) or one line cycle (5½ digits) |
| Readings over the bus | about 12 to 16 a second, one at a time |
| Sensing | none: the source and the ammeter are separate circuits |

## Reset defaults that had to be overridden

**A device clear does not restore the factory defaults.** It restores
the *saved* defaults, which are whatever the last person stored with
`L1` at the front panel. So `reset()` sends every setting this suite
depends on, one at a time, after the clear - and then reads the `U0`
machine status word back and refuses the instrument if zero check,
V/I ohms, rel, the trigger mode, the data format or the reading source
did not take.

From the factory table (Table 4-3), the ones that matter:

| Setting | Factory | Sent | Why |
|---|---|---|---|
| Zero check | on (`C1`) | `C0` | on, every reading is zero |
| Trigger | multiple on external (`T6`) | `T1` | one-shot on talk; any other mode can return the previous reading |
| Filters | both on (`P3`) | `P0` | the analog filter slows the 2 nA range from 12 ms to 70 ms |
| Range | autorange | `R0` | autorange, stated |
| Source | 0 V, 50 V range, 25 µA, standby | `V0,0,0`, `O0` | stated |
| V/I ohms, rel | off | `F0`, `Z0` | stated, because a saved set can have either on |

It **never sends `L0` or `L1`.** `L0` restores the factory defaults *and
saves them over the stored set*; `L1` saves the present state. Both
change a shared instrument for everyone who uses it next.

The manual disagrees with itself about one factory value: Figure 4-6
shows the status word with `V01` - a 2.5 mA limit - where Table 4-3 says
25 µA. The driver states the limit, so it does not depend on either.

## Decisions and deviations

- **One command per `X`.** Commands in one `X`-terminated string run
  *simultaneously*, and one illegal command voids the whole string.
  Separate strings make the order mine and the trace name the culprit.
- **A level beyond the selected source range is refused by the driver.**
  The instrument would drop the whole command with only a CONFLICT bit
  to show for it, leaving the previous level on the sample.
- **A range change puts the level at 0 V.** A level carried over from a
  wider range could be beyond the new one and void the command.
- **The compliance is a menu.** The panels offer 25 µA and 2.5 mA,
  read-only, safer first, and the driver refuses anything else rather
  than round it.
- **The compliance does not set the measurement range.** Every other SMU
  here derives one from the other. On the 487 that would put the
  ammeter on its 200 µA range for a 25 µA limit - 1 nA resolution on a
  picoammeter. The experiments leave the range to autorange instead and
  record it.
- **`measure()` returns no voltage.** Nothing measures one. The voltage
  in the data is the programmed level, which is what an IV sweep and a
  fixed-source trace record for every instrument when no reading of the
  sourced quantity comes back.
- **Off is 0 V, a 50 ms hold, then standby.** Standby opens a relay in
  series with the output, and the manual warns that an open output lets
  dielectric absorption recharge a capacitive sample. There is no
  normal-off to choose instead, so high-Z is not declared as a control.
- **Integration is snapped to its two settings.** Asked for 0.5 PLC the
  driver uses fast (recorded as 0.1, the nearest round figure for a fixed
  1.6 ms) and says so, rather than record 0.5.
- **The interlock gates the whole source.** Fitting the interlock cable
  enables it; while it is open the source cannot leave standby at any
  level. `output_on()` reads `U9` and refuses if it stayed in standby,
  and `compliance_tripped()` raises if the interlock opens mid-run.

## What this means for your data

Nothing yet: no data has been taken on it.

## Open questions

All of these are bench work, listed in the order a first session
should take them:

- **Read the real replies.** `U2X`, `U0X`, `U1X`, `U9X` and a reading,
  against the manual's figures. Every parser here was written from those
  figures and nothing else; `idn` above is filled in from the `U2X`
  reply.
- **What `*IDN?` does to it.** Expected: an IDDC flag and no answer. If
  it answers anything, the auto-detect question reopens.
- **Whether a line terminator after `X` is accepted.** The transports
  append one to every write. The manual's own BASIC examples do the same,
  so it should be.
- **Compliance and range readback**, set from the front panel and read
  over the bus, before either is marked trusted.
- **Whether a source range change glitches the output**, and how long a
  step from 0 V to 500 V takes to settle - which decides whether the
  50 ms discharge hold is enough.
- **A deliberate current-limit trip**, into a resistor, to see `U9`
  latch and clear.
- **Zero correction.** The accuracy figures assume the instrument has
  been zero-corrected on each range. Nothing does that yet; whether it
  should happen at Connect, per run, or by hand is a decision for after
  the first measurements.
