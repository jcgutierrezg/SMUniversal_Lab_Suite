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
last_bench: 2026-08-21
bench_notes: "2026-08-21 checkup at 7dc6264: 45 pass, 4 fail, 5 skip. NOT_SOURCED fixed the voltage-sourcing half - the compliance range now follows the limit (R100uA, no error). The current-sourcing half is D7 and still live"
bench_code: "cc0cb76c2d81"
bench_result: fail
bench_result_note: "four checks fail with -222 while sourcing current: the measure axis arrives as AUTO, takes the shared knob to R120mA, and a 100 uA compliance is below this instrument's 10%-of-range floor"
bench_revalidated: null
reading_time: "71 ms at NPLC 1 (2 apertures), no first-read cost"
resolution: "14-bit: range / 16384, whatever the NPLC"
best_for: "when the others are busy; permanently 4-wire by wiring"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keysight_u2722a.py
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

The most constrained instrument here — lowest voltage, lowest current,
coarsest resolution, slowest per reading — and the most quirk-laden.
It is also the one that forced two shared-layer changes, so it has
earned its place in the ledger twice over.

Ported from `IV_Meas_2722A.py` (plus `_OG.py` and `_OG_2.py`, the same
program with GUI additions).

## Identity and envelope

20 V, 120 mA, six current ranges, three channels of which only channel 1
is used. Every command carries the channel list, in comma form for
writes and space form for queries; a driver that drops it addresses
whichever channel the instrument was last left on.

## Reset defaults that had to be overridden

Only the line frequency is written at reset — but the interesting
default is one that cannot be overridden, only worked around.

**`*RST` leaves the instrument on the R1uA range with a 100 nA limit.**
That is the whole of deviation 21 below, and it is the reason
range-before-limit is now a formal contract in `core/ranges.py` rather
than a habit.

## Decisions and deviations

**Deviation 20 — the current-range dropdown becomes the compliance
field.** The original had a "current range" dropdown driving
`SOUR:CURR:RANG` and a separately hardcoded `SOUR:CURR:LIM 100mA`. Those
are inconsistent below the 120 mA range — a 100 mA limit cannot be
honoured on the 1 µA range — and the instrument silently clamps the
limit to the range. The port uses the experiment's single compliance
field for both, so the two can no longer disagree.

**Deviation 21 — compliance is re-sent after every range change.** This
is the one that changed a rule for the whole suite. `CURRent:LIMit`'s
accepted maximum depends on the active range, and `*RST` leaves the
instrument on R1uA with a 100 nA limit. The experiment sets the limit
before the range, which is right for the other instruments and wrong for
this one. The driver caches the requested value and re-sends it, so the
order the experiment happens to use stops mattering.

**This one changes what past data means**: a run set up limit-first on
this instrument had a compliance far below what was asked for.

**Deviation 22 — the source range is chosen to cover the whole sweep.**
There is no auto range on this model, and the experiment does not set
the swept quantity's range because every other SMU here auto-ranges its
source. Left alone, a sweep to 5 V would sit on the `*RST` default R2V
and clip at 2 V, returning a straight line with an excellent R².
`start_linear_sweep()` picks one range covering both endpoints before
the first point, rather than letting the range change partway through a
dataset. Where a level would exceed what the instrument can reach, that
is **refused up front with the range needed**, not clipped silently.

**Deviation 23 — sensing is recorded as wiring, not as a checkbox.** The
U2722A has no remote-sense command anywhere in its Programmer's
Reference; local versus remote is decided by how the SENSE terminals are
strapped, and this unit is wired 4-wire permanently. The
`REMOTE_SENSE_CONTROL` capability greys the control out and pins it, and
the CSV column reads `4-wire (hardwired)`. Accepting the checkbox and
ignoring it would have written a sensing mode into the file that the
measurement did not use.

**Deviation 24 — per-point averaging is dropped.** The original's
"Average mode" used `MEAS:ARR:CURR?` with `SENS:SWE:POIN` /
`SENS:SWE:TINT` to take N samples per point and average them in Python.
Removed at the user's request; it was implemented but never used.
Consequence worth knowing: the original CSV never recorded whether the
mode was on, so a historical file taken with it enabled is
indistinguishable from one without.

**Deviation 25 — NPLC is rounded to a whole number.**
`SENSe:CURRent[:DC]:NPLCycles` takes an integer from 0 to 255.
`NPLC_RANGE` is declared as (1, 255) rather than (0, 255) on purpose:
with a floor of 0 the shared preset menu would offer 0.01 and 0.1, both
of which round to 0 — no integration at all — from a control the
operator just used to ask for quieter readings.

**Deviation 26 — no source delay command exists.** The only
`SOURce:DELay` entries are memory-list ones, which are U2723A features.
`set_source_delay()` is a documented no-op; the panel's delay field
still works because the software sweep settles host-side. What cannot be
removed is the instrument's own auto delay of 0.5–20 ms per point
depending on range, reported at connect rather than left to be
discovered.

**Deviation 35 — VISA backends are merged rather than chosen.** This is
the instrument that forced it: plugged in, powered, and absent from the
address dropdown, because a vendor VISA library and pyvisa-py do not
enumerate the same instruments. `VisaTransport` now scans every backend,
merges for listing, and falls through at connect.

**Deviation 36 — `pyusb` and `libusb-package` became hard
dependencies.** pyvisa-py finds no USB instruments at all without a USB
layer beneath it, and **reports no error while doing so** — the quietest
failure mode in the suite, and exactly how a working U2722A goes missing.

## Bench findings

- **2026-08-18:** the checkup failed four checks with `-222 Data out of
  range`, including `start_linear_sweep()` — *"nothing was sourced"*.
  The cause was `RangePlan`'s unsourced source axis arriving as `AUTO`:
  this model has no autorange, so the driver substituted the widest
  fixed range, and a 100 uA compliance is 0.08% of 120 mA, which the
  instrument refuses outright. Not a resolution cost — an unsettable
  compliance and a sweep that sourced nothing.

  **Half fixed** by `RangePlan.widest()`, not by this driver: an axis
  carrying nothing no longer wins the shared knob, so when *voltage* is
  being sourced the current range follows the compliance. A driver
  override written for this was found unreachable by mutation and
  removed; the reason is recorded in the driver beside the hooks.

  The other half survives — see 2026-08-21 below. Until 2026-08-21 this
  entry read "**Fixed**", which was true of the fault as diagnosed and
  false of the checkup, and the two were easy to confuse because the
  failure count did not move. <!-- lint-ok -->

- **2026-08-21:** the same four checks still fail with `-222`, and the
  cause is now the opposite axis. When *current* is the sourced
  quantity, `RangePlan.for_sourcing()` sets its **measure** half to
  `AUTO` — read back from the source — and on a shared knob that `AUTO`
  takes the range to R120mA in front of the fixed 1 µA source range:

  ```
  SOUR:CURR:RANG R120mA        <- 1 µA was asked for
  SOUR:CURR:LIM 1.000000e-04   -> -222
  ```

  This is `D7` in `docs/plan.md`, deliberately outside what was signed
  off for the `NOT_SOURCED` wave. The voltage-sourcing half is genuinely
  fixed and visible in the same trace as `SOUR:CURR:RANG R100uA` with no
  error.

- **The compliance floor is 10% of the active range**, which is what
  refuses these limits. Three independent readings agree:
  `SOUR:CURR:LIM?` returned `+1.20000000E-02` — 12 mA, exactly a tenth
  of 120 mA — where 100 µA had been asked for; `*RST` leaves R2V with a
  0.2 V limit; and `SOUR:VOLT:LIM 1.0` is refused on R20V. The driver's
  own comment says the accepted *maximum* depends on the active range.
  The minimum does too, and it is the half doing the damage.

- **The compliance readback reads the instrument, not a cache.**
  `SOUR:CURR:LIM?` reported the clamped 12 mA while the driver's stored
  value was 100 µA. That is the discriminating evidence the ledger entry
  was waiting for: a readback echoing the request would have said
  100 µA.

- **A sweep refuses; a fixed level does not.** In the same failing
  configuration `start_linear_sweep()` aborted with *"nothing was
  sourced"*, while the fixed-level path went ahead and returned
  readings — quantised to multiples of 7.32 µA, the LSB of the range it
  had been forced onto, with 1 µA requested.

- **Every reading costs two integrations.** There is no combined
  voltage+current read, so NPLC is worth twice what it looks like.
- **It is a 14-bit instrument.** Every reading is an exact multiple of
  range ÷ 16384 — 6.1 nA on the 100 µA range, 122 µV on the 2 V range.
- **It slews slowly at low currents.** Output capacitance around 1 µF,
  so sourcing 1 µA into a high-impedance sample moves the voltage at
  about 1 V/s.
- **Its compliance reading is not sign-inverted.** Checked, and settled:
  a railed output saturates whichever way its loop happens to go, and a
  10 kΩ resistor confirmed conventional polarity. Do not re-derive this.

## What this means for your data <!-- bench -->

**Do not source current on this instrument until D7 lands.** As of the
2026-08-21 checkup, a current-sourced setup puts the shared range knob
on its widest setting, which has two consequences at the fixture. The
compliance you asked for is refused, so the output is bounded by the
range limit instead of by your limit — 2 V where 1 V was requested. And
the sourced current is quantised to that range's LSB, 7.32 µA, so a
1 µA request produces multiples of 7.32 µA. A sweep refuses to start;
a fixed-level run does not, and returns readings that look ordinary.

Voltage-sourced measurements are unaffected and were confirmed on
2026-08-21.

**Was any U2722A data taken near compliance?** The original set the
current limit before the range, and on this model the limit is clamped
to whatever range is active at the time — R1uA with a 100 nA limit after
`*RST`. Runs that never approached compliance are unaffected; runs that
did were limited far below where they were supposed to be.

**Every reading costs two integrations**, because there is no combined
voltage+current read. NPLC 25 is about 1.06 s per point, not 0.5 s, and
a 200-point sweep takes roughly 3.5 minutes.

**It is a 14-bit instrument**, and that is the resolution floor
*whatever NPLC is set to* — averaging longer does not add bits. If you
need finer resolution, use a smaller range or a different instrument.

**Allow a generous settle.** At 1 µA into a high-impedance sample the
output moves at about 1 V/s, so reaching 1 V takes over a second. This
is the instrument most likely to need the delay setting increased, and
the symptom of not doing so is each point resembling the one before.

**It is permanently 4-wire**, by wiring, and cannot be switched. The
sensing control is greyed out and the CSV records `4-wire (hardwired)`
rather than whatever the checkbox says.

**If it goes missing from the address dropdown**, pick "VISA
(pyvisa-py)" in the transport dropdown — this instrument has a history
of being opened by a vendor backend and then misbehaving.

## Open questions

- **Does anyone want the other two channels?** The driver takes a
  `channel` argument defaulting to 1, which is what the original
  hardcoded. Two channels driving two roles at once is the dual-SMU
  experiment in disguise, and that is still unported.
- The exact commissioning date was not recorded, so this driver reads as
  stale regardless of what has changed. Worth closing on the next bench
  session — see [checkup-owed](../open/checkup-owed.md).
