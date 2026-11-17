---
type: instrument
title: "Keithley 236"
driver_class: Keithley236
idn: "236A10"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: 2026-11-16
bench_notes: "2026-11-16 first session at afb6e40 (18:08), GPIB0::16 over VISA, nothing attached, U0X 236A10: 61 pass, 8 warn, 0 fail, 9 skip. The eight warnings are the unmeasured source floors and the four readback agreements not yet checked against the front panel. Every status word and reading matched the parsers. Compliance on open circuit: 0.9998 V against 1 V, flagged O on both items. Burst check 10 of 10 on bursts of up to 24 writes, slowest reply 110 ms, no pacing"
bench_code: "32f3d6ca42eb"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "about 45 ms a cycle on a fixed 100 uA range at the fastest integration (trigger plus talk, 2026-11-16); about 440 ms on autorange into an open circuit, where it ranges down to 1 nA and waits that range's 360 ms settle. A sweep point is two cycles, because a level takes effect only at a trigger: 164 ms a point on the 1 mA range at line-cycle integration into 10 kOhm (2026-11-17)"
resolution: "10 fA on the 1 nA range at 5 digits (manual); seen on the unit: 1 nA steps on the 100 uA range at the fastest integration, 0.01 pA on autorange into an open circuit"
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

Its identity question is `U0X`. This unit answers `236A10` (firmware
A10, 2026-11-16). `reset()` asks it first and refuses anything that does not
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
  reads that cycle. Every trigger is followed by its read, so no reading
  is left for a later read to take by mistake.
- **No trigger until the unit says it is ready for one** (since the
  2026-11-16 bench sitting, which lost one sent 0.4 ms after a reading).
  Before every `H0X` the driver serial-polls the status byte and waits
  for bit 4, "ready for trigger"; a poll triggers nothing. If the bit
  does not come within 3 s it refuses, with no trigger on the bus. Over
  a transport that cannot serial poll - the direct GPIB-USB-HS adapter -
  it waits `TRIGGER_GAP_S` (150 ms) from the last reading instead,
  a little over twice the longest wait measured (64.6 ms, 2026-11-17).
  VISA, which this bench uses, polls.
- **In operate, every level and compliance change is triggered into
  effect at once.** Both take effect only at a trigger (measured
  2026-11-17, below), so the setter triggers one cycle and reads it, and
  the level is on the sample before the settle begins. That costs one
  cycle per point (`LEVEL_NEEDS_TRIGGER = True`): 164 ms a point against
  90 ms without, on the bench sweep. In standby nothing is triggered;
  `output_on()` triggers once after operate.
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
- **Off is 0, triggered in, then standby.** Standby holds 0 V rather
  than disconnecting, so `OUTPUT_OFF_DISCONNECTS = False`. Zero first
  because operate otherwise brings the level in force back for 10 ms -
  and triggered, since a `B0` merely sent leaves the old level in force
  (until 2026-11-17 it was sent alone). On a link that has stopped
  answering the cycle is given up and standby still follows.
- **Compliance and measurement-range readbacks are trusted** (since
  2026-11-17): both reported compliances keyed in at the front panel.
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

## Bench answers (2026-11-16)

The first checkup, at GPIB address 16, nothing attached. Nothing the
driver sends changed as a result.

- **Every reply matched the manual's figures**, and so every parser:
  - `U0X`: `236A10`.
  - `U1X`: `ERS` and 26 zeros; `U9X`: `WRS` and 10 zeros. Clean after
    every command the checkup sent.
  - `U3X`: `MSTG05,1,0K0M000,0N0R1T4,1,0,0V0Y0` after reset, `N1` after
    operate.
  - `U4X`: `IMPL,00F0,0O0P0S3W1Z0`. **The comma after `L` is real** - the
    OCR'd figure was right, and the driver strips it. `VMPL,02F1,0...`
    while sourcing current.
  - `U5X`: `ICP0100.00E-06` - a zero-padded mantissa, engineering
    exponent.
- **A reading's mantissa width follows the range and resolution**:
  `NSDCV+0.1000E+00,NMDCI-000.006E-06` on the 100 µA range at the
  fastest integration, `NMDCI-01.8621E-09` on autorange. The parser
  takes any number of digits.
- **At compliance both items read `O`.** Sourcing 1 µA into the open
  output against a 1 V limit: `OSDCI+1.0000E-06,OMDCV+0.99977E+00`, and
  `compliance_tripped()` said True. That is the case the driver keeps as
  a real reading; an overflow (`N` source, `O` measure) has not been
  seen yet.
- **Autorange into an open circuit is slow, and that is the
  instrument.** On autorange the default delays apply even with `W0`
  (manual 2.10.5), and an open circuit ranges down to 1 nA, whose delay
  is 360 ms: 440 ms a reading. On a fixed range a cycle took about
  45 ms. A sample that draws current ranges higher and reads faster.
- **The output came back up 672 ms after a change of source.** The
  source change itself takes about 135 ms to execute (`F1,0X`).
- **Off and operate behave as written.** `N1X` then `U3X` read `N1`;
  every off was `B0`, then `N0X`, with nothing refused.

## Bench answers (2026-11-16, `tools/bench_236.py`)

The first sitting with the bench tool, at 6c5266a. It stopped in part 2,
on the driver's fault, below.

- **A trigger sent straight after a reading can be lost.** In the
  wiring check the measuring `H0X` went out 0.4 ms after the extra
  cycle's reading had been read: no reading came, the read timed out
  after 3 s and the link latched. A trigger the unit is not ready for is
  a TRIG OVERRUN and is ignored. Every sweep point sends exactly that
  pair, so this would have hit IV sweeps with no settle delay. **Fixed:**
  the driver now polls the serial-poll byte's "ready for trigger" bit
  before every `H0X` (see *Decisions*), which the next checkup has to
  confirm.
- **`*IDN?` stays in the command buffer.** No reply, as expected - and
  because it carries no `X`, it waits there and spoils the next command:
  `U1X` on a fresh link went unanswered too (an IDDC voids the whole
  string). A device clear empties the buffer, so `reset()`'s clear,
  which comes first, is what lets the app's Connect recover after its
  `*IDN?`.
- **A device clear empties the error word** (`U1X` read clean straight
  after it), as the manual says - unlike the 487.
- **Line frequency: 50 Hz**, as the driver assumes for `S3`.
- **A compliance entered at the front panel is only pending until a
  trigger.** Both settings made by hand read back as the limit still in
  force: 100 µA where 50 µA was keyed in, and 0 V on autorange where 5 V
  was. Manual 2.12: "The compliance limit of the instrument will not
  update to the new value until the next trigger occurs." The sitting's
  steps did not include one, so they said nothing about the readback;
  the tool now ends each with MANUAL. Over the bus, `U4` showed a new
  range straight after an untriggered `L` in the checkup, so the bus and
  the front panel differ here.

## Bench answers (2026-11-17, `tools/bench_236.py`)

The second sitting, at a4ebdb6 (the ready-bit fix), ran to the end:
part 1 with nothing attached, part 2 with 9959 Ω from OUTPUT HI to
OUTPUT LO and a handheld meter across it. No trigger was lost.

- **A level takes effect only at a trigger.** `B1`, `B2`, `B0`, each
  sent alone: the meter read the previous level every time (−0.0001 V,
  1.0 V, 2.0002 V) until the next `H0X` put the new one out (1.0 V,
  2.0003 V, −0.0001 V). So `LEVEL_NEEDS_TRIGGER` is needed, not a
  precaution - and `output_off()` now triggers its `B0` in.
- **So does a compliance.** A 20 µA `L` sent alone left 2.0002 V on the
  resistor; the trigger clamped it to 0.1986 V, and that reading came
  back `OSDCV+02.000E+00,OMDCI+0.01996E-03` - compliance flagged on both
  items, into a real load.
- **Ready for the next trigger 5 to 14 ms after a reading, once 65 ms**
  (20 readings, median 10.7 ms, fixed 100 µA range, line cycle, 0 V).
  `TRIGGER_GAP_S`, the wait where a transport cannot poll, went from a
  50 ms margin to 150 ms.
- **The readbacks report the front panel.** With MANUAL pressed after
  each entry: 50 µA keyed in read back `ICP0050.00E-06`, on `L,06`
  (100 µA) where the bus had left 1 mA; 5 V on the current source read
  `VCP005.000E+00`, on `L,00` - autorange, which that source was on, so
  entering a value keeps autorange where it is set. Both readbacks are
  now trusted.
- **The extra cycle costs 74 ms a point** on that sweep: 164 ms with it,
  90 ms without, the readings the same to 20 nA - a resistor settles at
  once. A capacitive sample is where the difference would show.

## Open questions

The driver changed after both sittings, so the next step is the checkup
on the code as it now stands.

- **The source floors**, as on every instrument here: a level below one
  count of a range, and whether its sign survives.
- **What a trigger does in standby.** The driver never sends one, so
  nothing depends on it; it would matter only if the old level ever had
  to be cleared with the output off.

**Not a question: what an overflow looks like.** With a fixed range the
compliance *is* the measurement range (manual 3.6.10, note 1), so a
passive sample is clamped at or below full scale and never reaches the
112.5% overflow; only an external source of power can overload it
(3.6.19). The driver still reads a measure `O` with a source `N` as no
reading, which is the safe answer if one ever comes.
