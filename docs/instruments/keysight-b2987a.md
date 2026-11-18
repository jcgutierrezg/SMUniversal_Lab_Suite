---
type: instrument
title: "Keysight B2987A"
driver_class: KeysightB2987A
idn: "Keysight Technologies,B2987A,MY54320335,2.0.1608.8800"
idn_confirmed: true
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
reading_time: "about 34 ms per reading at 1 PLC on 50 Hz mains, autoranged or fixed (probe, 2026-11-18); 1.4 s with the automatic aperture *RST leaves on"
resolution: null
best_for: "femtoamp currents and very high resistance, sourcing up to 21 V, or 1000 V with the interlock fixture - IV sweeps and fixed-voltage traces only"
connection: "USB (USB-TMC)"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keysight_b2987a.py
model_ids: "['B2987A']"
max_voltage_v: 1000
max_current_a: 0.02
voltage_ranges_n: 2
current_ranges_n: 11
power_envelope_n: 0
sweep_kind: software
nplc_min: 0.0006
nplc_max: 100
high_z_off: false
ovp: false
ovp_trip: false
remote_sense_control: false
compliance_trip: true
fleet: smu
# --- end generated ---
---

# Keysight B2987A

An electrometer: a femtoammeter with a voltage source beside it, on
separate terminals. It measures current from a few femtoamps to 20 mA
and sources up to ±1000 V, and like the
[Keithley 487](keithley-487.md) it does nothing else that this suite
uses: it cannot source a current, and its voltmeter is a separate ±21 V
input, not the source terminals. It joins the SMU fleet as a
voltage-only source-measure unit, not as a fleet of its own - see
[An SMU that sources one quantity is still an SMU](../architecture/devices.md#an-smu-that-sources-one-quantity-is-still-an-smu).
It runs IV sweeps in voltage mode and Fixed sourcing; the four-contact
experiments refuse it at Connect.

## How it was written

From the *B2980 Series SCPI Command Reference* and one probe sitting,
`tools/bench_b2987a.py`, on 2026-11-18 at e6461a7 (report
`checkups/20261118/bench_B2987A_20261118_121508.md`). The commands it
sends, the ranges and the reset values are in
[B2987A command summary](../reference/manuals/b2987a-commands.md).

## Connection

USB, as `USB0::0x0957::0xD618::<serial>::INSTR`; the address list names
it from those ids. It answers `*IDN?`, so it is found without choosing a
driver. GPIB is off at the factory. No battery is fitted on this bench's
unit. Mains 50 Hz.

## What the probe found

- **A level the range in force cannot hold is refused, and the old one
  stays.** `-222`, level unchanged, range unchanged. That includes the
  one-sided 1000 V ranges: −5 V on +1000 V, and +5 V on −1000 V.
- **The range cannot change with the output on**, even at 0 V: `+213
  "Output relay must be off"`, and the output stays on, on the old range.
- **With the interlock open, a level above 21 V is refused when it is
  set**: `-222 "Data out of range; Interlock open"`. The interlock was
  open for the whole sitting.
- **The source holds its current limit; it does not trip.** Through
  323.4 Ω at 10 V it stayed on, held about 25.5 mA (8.24 V across the
  resistor), set status bit 8, and queued no error.
- **With the ammeter input off, a reading is a plausible number**:
  `+2.6E-11 A`, and the input stays off. `*RST` leaves it off.
- **`*RST` does not reset the element list** - eight elements, so a
  driver that relied on reset would parse voltage as current. It leaves
  automatic aperture on (1361 ms a reading against 34 ms at 1 PLC), and
  the low terminal common.
- **Floating, the low terminal returns no current** through the
  ammeter (about 3E-11 A where 5 µA flows with it common).
- Through 0.9978 MΩ, the current matched V/R within 0.1-0.5% at ±1, 5
  and 10 V, and a positive voltage reads as a positive current. It had
  settled by the first 1 PLC reading after a 0 → 10 V step.
- The integration time takes any value (0.5 PLC read back 0.5); a
  current range request snaps up to the next range.
- With no battery, `SYST:BATT?` queues `-241 "Cannot detect battery"`.

## What the driver does with it

**Ranges.** A run inside 21 V goes on the 20 V range. Beyond it, the
1000 V pair, and the interlock is asked first: open, the run is refused
before anything is energised. The ranging plan carries a magnitude, not
a sign, so the driver picks the side of the pair level by level. When a
sweep crosses from one side to the other with the output on - −100 V to
+100 V, say - it takes the source to 0 V, switches the output off (0 V,
then the relay opens), changes range, switches it on again at 0 V, and
then sets the next level. Decided 2026-11-18: two steps, switched at 0
V. The sample sees 0 V on both sides of the switch and floats for the
relay's operation. A level between −1 V and +1 V is reachable on either
side and switches nothing. On the 1000 V ranges each reading also asks
the interlock, so a lid opened mid-run stops the run.

**Compliance.** No command sets one. The compliance is a menu of the
two limits the source holds: 20 mA on the 20 V range and 1 mA on the
1000 V pair (decided 2026-11-18: wired as a compliance like every other
SMU's, though it is really the range's). 20 mA is first, so a fresh form
defaults to it. 20 mA with a level beyond 21 V is refused at Run, and 1
mA on the 20 V range when the run starts: either would record a
protection the sample did not have. Nothing is sent. A reading at the
limit is flagged from status bit 8. The compliance does not choose the
measurement range, which is autoranged.

**Reset.** `*RST`, then every setting stated: low terminal common,
output-off NORM, 20 V range at 0 V, current only, automatic aperture
off at 1 PLC, autorange, filters and null off, the instrument's settling
waits on (decided 2026-11-18), ASCII `CURR,STAT`, and the input on,
last. The input, output, low terminal, aperture and element list are
read back, and the error queue drained; any of them wrong refuses the
connect.

**Readings.** One `MEAS?`, the current and its status word. An overflow
is no reading. The run's source delay is a wait before each `MEAS?`.

**Off** is `SOUR:VOLT 0`, then `OUTP 0`: 0 V and the relay open.

## Not done yet

- **The first checkup.** `uv run tools/smu_checkup.py --address
  USB0::0x0957::0xD618::MY54320335::INSTR --trace`.
- **The 1000 V ranges with the interlock fixture**: the refusal with it
  closed, the switch at 0 V on a real sample, and how long `ZERO_HOLD_S`
  has to be.
- **The readbacks** are not trusted until a range set at the front panel
  has been read back.
- **The ammeter's own over-current emergency.** The source holds about
  25.5 mA and the ammeter's top range is 20 mA, so a shorted sample in
  the normal wiring may set it off, switching the source off and asking
  for `*TST?`. Not provoked on purpose.
