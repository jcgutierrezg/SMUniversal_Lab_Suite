---
type: instrument
title: "Keithley 236"
driver_class: Keithley236
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
best_for: "femtoamp-resolution IV sweeps and fixed traces up to 110 V or 100 mA - not the four-contact windows yet"
connection: "GPIB (GPIB-USB adapter)"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keithley_236.py
model_ids: "[]"
max_voltage_v: 110
max_current_a: 0.1
voltage_ranges_n: 3
current_ranges_n: 9
power_envelope_n: 0
sweep_kind: software
nplc_min: 0.0208
nplc_max: 1
high_z_off: false
ovp: false
ovp_trip: false
remote_sense_control: true
compliance_trip: true
fleet: smu
# --- end generated ---
---

# Keithley 236

A source-measure unit from the late 1980s: it sources a voltage on
1.1, 11 or 110 V ranges and measures current from 1 nA to 100 mA full
scale (10 fA resolution on 1 nA), or sources a current on those ranges
and measures voltage. Triax outputs with guard and remote sense, and an
interlock. It joins the SMU fleet as a `BaseSMU`.

Written from the Model 236/237/238 Operator's Manual, 236-900-01 Rev. E,
with no script behind it. What it was written from is in
[236 command summary](../reference/manuals/236-commands.md).

## Identity and envelope

**It answers no `*IDN?`.** It speaks the same device-dependent command
style as the [487](keithley-487.md) - a letter, options, then `X` - and
`*IDN?` is an illegal command to it. So it is never auto-detected:
**choose "Keithley 236" from the manual driver list at Connect.**
`MODEL_IDS` is empty on purpose, and `NO_IDN` in
`tests/test_driver_contract.py` records why.

Its identity question is `U0X`, which the manual says answers `236A01`
and two blanks. `idn` above is `null` because nobody has read it off this
unit yet. `reset()` asks it first and refuses anything that does not
answer `236`: a 237 reaches 1100 V and a 238 sources 1 A, and both
answer every command this driver sends.

| | |
|---|---|
| Source V | ±1.1000 V, ±11.000 V, ±110.00 V |
| Source / measure I | ±1.0000 nA to ±100.00 mA, nine decades |
| Envelope | a rectangle: 110 V at up to 100 mA, either way round |
| Compliance | one bipolar value; with a fixed range it is also the measurement range |
| Integration | 416 µs, 4 ms, or one 50 Hz line cycle (20 ms) |
| Default delay | a settle added to each reading: 360 ms on 1 nA down to 0 from 100 µA up |
| Sensing | local or remote (`O0` / `O1`) |

## Decisions and deviations

- **Decided 2026-11-16: IV sweep and Fixed Source only.** The 236 sources
  current, so the four-contact windows would accept it on capability
  alone. They refuse it at Connect by its caveat,
  `sourced_quantity_not_measured`, which IV sweep and Fixed Source
  accept. See the next point for why; wiring it into Van der Pauw and
  Hall is a separate change.
- **`measure()` returns None for the quantity being sourced.** The 236
  measures only the other one. Its output string has a "source value"
  item, but the manual says it is the programmed value, and this suite
  records a programmed value as the level it commanded, never as a
  reading. The IV sweep already records the commanded level where no
  measurement of it exists. `MEASURES_SOURCED_QUANTITY = False` tells the
  checkup which None is the answer.
- **One reading per trigger, and a talk never triggers.** The
  instrument idles in trigger origin 4 - immediate only - with a trigger
  starting the source phase (`T4,1,0,0`). `measure()` sends `H0X` and
  reads that cycle. Every trigger is followed by its read, so none lands
  on a running cycle and no reading is left for a later read to take by
  mistake. This is the 487's lost-reading race made impossible rather
  than worked around.
- **In operate, every level and compliance change is triggered into
  effect at once.** The manual says a compliance change needs a trigger
  in dc operation, and implies the same for the level outside continuous
  triggering. So the setter triggers one cycle and reads it, and the
  level is on the sample before the settle begins. That costs one extra
  cycle per point (`LEVEL_NEEDS_TRIGGER = True`). In standby nothing is
  triggered; `output_on()` triggers once after operate.
- **A level beyond the fixed range is refused by the driver.** The
  instrument would put the range's *full scale* on the sample - 1.1 V
  for a 5 V request on the 1.1 V range - with only a `U9` warning.
- **A compliance beyond the range, or below 100 counts of it, is
  refused.** The instrument would hold full scale, or raise it to 100
  counts (1% of the range) in silence: less protection than asked for.
  Every compliance the driver sets is followed by a `U9` check for VALUE
  OUT OF RANGE.
- **A range change moves the compliance under the new range** and the
  level to 0, so a ranging step cannot provoke a clamp.
- **Both sources are configured at reset, and a source change sends the
  settings again.** Each source remembers its own integration time,
  filter, sense, compliance, ranges and level.
- **Reset is a device clear and every setting stated, never `J0X`.**
  `J0X` runs the whole power-up initialisation (1-3 s). The clear brings
  back power-up defaults, and the driver sends the rest, then reads `U1`,
  `U9`, `U3` and `U4` back and refuses the instrument if anything did not
  take. Flags latched before the reset are read and set aside first.
- **Default delay stays on (`W1`).** It is the manufacturer's settle for
  each current range, and it is on from the factory.
- **Integration is snapped to three settings**, as NPLC at 50 Hz: 0.0208,
  0.2 and 1. `S2` (the 60 Hz line cycle) is not used.
- **Off is 0, then standby.** Standby holds 0 V rather than
  disconnecting, so `OUTPUT_OFF_DISCONNECTS = False`. Zero first because
  operate otherwise brings the old level back for 10 ms.
- **Compliance is read off each reading.** The source item's `O` means
  the source was in compliance; `compliance_tripped()` reports whether
  any reading since it was last asked carried one. A measure `O` with a
  source `N` is an overflow, and reads as no reading.
- **The interlock gates the whole output.** `output_on()` reads the `U3`
  machine status and refuses if operate did not take.
- **`read_error()` reads `U1` only.** Warnings (`U9`) include an overflow,
  which during a run would read as a failed shutdown. The driver checks
  the warnings that matter where they arise, and `read_warnings()` gives
  the rest to the checkup and the bench.

## What this means for your data

Nothing yet: no data has been taken on it.

## Open questions

All of these are bench work, in the order a first session should take
them. The first session is the checkup:
`uv run tools/smu_checkup.py --address GPIB0::<n>::INSTR --driver "Keithley 236" --trace`.

- **Read the real replies.** `U0X`, `U1X`, `U3X`, `U4X`, `U5X`, `U9X`
  and a reading, against the manual's figures. Every parser here was
  written from those figures; `idn` above is filled in from `U0X`.
- **What `*IDN?` does to it.** Expected: an IDDC flag and no answer.
- **Whether a level goes out on `X` or on the next trigger.** If on `X`,
  the extra cycle per point can go (`LEVEL_NEEDS_TRIGGER = False`),
  halving the time per point. Needs a resistor and a level step.
- **Compliance versus overflow on a reading.** Into a resistor at a low
  compliance, and on a fixed range too narrow for the current: do the
  source and measure prefixes read `O`/`O` and `N`/`O` as assumed, and
  what number does an overflow carry?
- **Compliance and measurement-range readback** (`U5`, `U4`), set from
  the front panel and read over the bus, before either is trusted.
- **The line frequency.** The driver assumes 50 Hz for `S3`. Check the
  menu says 50 Hz.
- **The bus address.** Factory 16; whatever the unit shows in its menu
  goes into the user guide.
