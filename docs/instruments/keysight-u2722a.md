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
last_bench: null
bench_notes: "checkup passed, all tiers; the exact date was not recorded. Timing survived a cross-session comparison because the 500 ms aperture dominates the ~35 ms overhead"
bench_revalidated: null
reading_time: "2 apertures + ~37 ms overhead"
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

  **Fixed** by `RangePlan.widest()`, not by this driver: an axis
  carrying nothing no longer wins the shared knob, so the current range
  follows the compliance. A driver override written for this was found
  unreachable by mutation and removed; the reason is recorded in the
  driver beside the hooks.

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
