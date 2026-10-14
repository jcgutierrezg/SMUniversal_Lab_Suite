---
type: instrument
title: "Keithley 487"
driver_class: Keithley487
idn: "487B07"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: 2026-10-14
bench_notes: "2026-10-14, first session, at 6e450b44c175, GPIB address 3, firmware B07, nothing attached: 39 pass, 5 warn, 2 fail, 16 skip. Every reply matched the manual's figures and the reset took; the two failures were the checkup's, not the instrument's - see the note"
bench_code: "30cefc6e99f6"
bench_result: fail
bench_result_note: "measure() at 0 V and at 0.1 V returned (None, 9e-09) and (None, -1e-09): correct readings, failed by a checkup that took the 487's missing voltage for a reply that would not parse. The checkup was fixed the same day; the re-run is owed"
bench_revalidated: null
reading_time: "about 52 ms per reading at fast integration, one at a time over GPIB, measured 2026-10-14 with nothing attached on the 200 uA range"
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

Its identity question is `U2X`, which answers the model and firmware:
**`487B07`** on this unit, read on 2026-10-14 - firmware B07. That is
what `idn` above holds; it is not an `*IDN?` reply, because there is
none. `reset()` asks it before it configures anything, and refuses an
instrument that does not answer `487` - a 486 answers `486`, and is the
same picoammeter with no source.

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

## First bench session, 2026-10-14 (firmware B07, GPIB address 3)

`tools/smu_checkup.py --driver "Keithley 487" --trace`, nothing attached,
code at `6e450b44c175`: **39 pass, 5 warn, 2 fail, 16 skip.**

**Every reply matched the manual's figures.** `U2X` gave `487B07`, `U1`
gave `487` and thirteen zeros, `U9` gave `48700`, and `U0` gave
`487A0B0C0F0G0H17J0K0M000N000O0P0R11S1T1V00Y0Z00c0` - the Figure 4-6
layout exactly. The reset took: zero check off, trigger `T1`, filters
off, 25 µA. Not one illegal-command flag in the whole session, and a
line terminator after `X` is accepted.

**The status word follows the commands, in the fields the manual
names.** After `V0,1,0X` the `V` field went from `00` to `10`; after
`R6X`, `R` went from `11` to `06`. And one consequence agrees from
outside the word: on `R06` the readings came back as `NDCI+000.009E-06`,
three integer digits of microamps with nanoamp resolution - the shape of
the 200 µA range. That is evidence for the measure-range readback, not
yet the front-panel check the trust flag asks for.

**The readings are in engineering form**, `+000.009E-06`, not the
`1.23456E-03` the manual's figure shows. The parser takes both.

**Both failures were the checkup's.** `measure()` returned
`(None, 9e-09)` and `(None, -1e-09)`: no voltage, because nothing on
the 487 measures one, and a few nanoamps of open-circuit noise on the
200 µA range, inside the 20 nA offset the specification allows there.
The checkup took every `None` for a reply that would not parse. The
driver now declares `MEASURE_FUNCTIONS = ("current",)` and the checkup
accepts a missing voltage only where that is declared. Its header also
said the measurements ran "4-wire" on this 2-wire instrument; that is
gone. And the report's firmware line said "not reported" - it is now
read out of the `U2` reply.

**Timing.** About 52 ms per reading at fast integration, steady, and the
first reading after the output comes up costs no more. Configuration is
slower than any SCPI instrument here, because bus hold-off keeps the
handshake until each command has executed: `C0X` takes 660 ms (the
zero-check relay), `O0X` about 290 ms, `S1X` 150 ms. A reset is about
1.6 s, and the burst check passed 10 of 10 after bursts of 15 writes.

## Open questions

All of these are bench work, listed in the order a first session
should take them:

- **Re-run the checkup** at the code that fixed its two false failures.
  The open-circuit current check has not yet run on the instrument.
- **What `*IDN?` does to it.** Expected: an IDDC flag and no answer. If
  it answers anything, the auto-detect question reopens.
- **Compliance and range readback**, set from the front panel and read
  over the bus, before either is marked trusted. The first session
  already shows the fields moving with the commands.
- **Whether a source range change glitches the output**, and how long a
  step from 0 V to 500 V takes to settle - which decides whether the
  50 ms discharge hold is enough.
- **A deliberate current-limit trip**, into a resistor, to see `U9`
  latch and clear.
- **Zero correction.** The accuracy figures assume the instrument has
  been zero-corrected on each range. Nothing does that yet; whether it
  should happen at Connect, per run, or by hand is a decision for after
  the first measurements.
