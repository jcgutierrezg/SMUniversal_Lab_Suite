---
type: instrument
title: "Keithley 2401"
driver_class: Keithley2401
idn: "KEITHLEY INSTRUMENTS INC.,MODEL 2401,4084766,A01 Aug 25 2011"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: null
bench_notes: "checkup passed, all tiers; the exact date was not recorded. The current-source hang found during it was the checkup tool's fault, not the driver's"
bench_revalidated: null
reading_time: "~44 ms at NPLC 0.01"
resolution: "not characterised"
best_for: "general-purpose IV work up to 21 V"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keithley_2401.py
model_ids: "['MODEL 2401', '2401']"
max_voltage_v: 21
max_current_a: 1.05
voltage_ranges_n: 3
current_ranges_n: 7
power_envelope_n: 0
sweep_kind: software
nplc_min: 0.01
nplc_max: 10
high_z_off: true
ovp: false
remote_sense_control: true
compliance_trip: false
# --- end generated ---
---

# Keithley 2401

Straightforward and reliable, and the only driver here extracted from a
script whose *experiment* was deliberately not ported.

Ported from `IV_Meas_2611A_2401_-_Long_bias_Dual_SMU.py` — 1911 lines,
with entire function families suffixed `_2611` / `_2401` differing only
in command dialect. That file is the reason the driver layer exists.

## Identity and envelope

21 V, 1.05 A, seven current ranges. No power envelope is declared: on
this model the flat maxima are the whole story.

## Reset defaults that had to be overridden

| Command | Why |
|---|---|
| `:OUTP:ENAB 0` | disables the output-enable interlock |
| `:SYST:RSEN 1` | 4-wire, as the rigs are wired |
| `:SOUR:CLE:AUTO 0` | so a sweep holds its level between points |

The first two were lost the same way the GSM's were: the 2401 spelled
its reset `configure()`, so there was no single name for the app to
call, and nothing called either. Deviation 19.

The third one has a consequence that reads as a dead instrument — see
below.

## Decisions and deviations

**Source levels are no longer rounded to 4 decimals.** The original sent
`round(Vo + i*step, 4)`, quantising the source to 100 µV. Harmless at
±1 V. At ±100 µV over 21 points it collapses to **three distinct levels
with eighteen duplicates**, while the saved x-axis still claims 21
evenly spaced values — so the damage is invisible afterwards. Regression
guard in `tests/test_2401_driver.py`. This is fault 4.

**`:READ?` instead of `MEAS?` per point.** `MEAS?` means "configure,
then read", so it reset the ranging and compliance that had just been
set, on every point of the sweep. Same fault as the GSM's deviation 11,
found the same way.

**Deviation 18 — output-off mode is a per-run choice.** This driver
pinned `OUTP:SMOD HIMP` from the start. It now leaves the mode at
NORMal and takes the setting from a checkbox, defaulting off, because
high-impedance off opens the output relay and IV sweep's periodic mode
can cycle it hundreds of times in an unattended run.

**Deviation 40 — `Transport.clear()` exists because of this
instrument.** A timed-out query is not a self-contained failure on GPIB:
the late reply sits in the output buffer and the next query collects it,
putting the session one command out of step. A 2401 on the bench turned
one slow reading into three consecutive failures and a warning, which
read as four findings.

**Deviation 41 — error 823 is a 2400-family behaviour, not a GW Instek
one.** Both this instrument and the GSM-20H10 rejected a *source*-range
change with `Invalid with source read-back on`. Nothing in the app was
affected — the experiments range the measured quantity — but it was the
checkup exercising a combination the application cannot produce. It is
now the rule underlying `RangePlan.for_sourcing()`, which makes the
forbidden combination unrepresentable rather than merely avoided.

**Deviation 48 — the output must be turned on *after*
`set_source_function()`.** The 2400 family drops the output when the
source function changes, and this driver disables auto output-off so a
sweep holds its level. The 2401 reference is explicit: *"if auto output
off is disabled, then the output must be turned on before you can
perform a `:READ?`"*. With the output off, `:READ?` — `:INITiate` then
`:FETCh?` — blocks forever, because `:FETCh?` only runs once the
source-measure operations complete and they never start.

It reports as a VISA timeout, indistinguishable from a dead instrument,
and a device clear does not help because the configuration is still
wrong. **The experiments always got this right; `tools/smu_checkup.py`
did not.** That was the whole of the "2401 current-source hang", which
cost two rounds of bench diagnosis and was solved by one sentence in the
command reference rather than by theorising from traces. Now documented
on `BaseSMU.set_source_function` for every driver.

**The dual-SMU experiment was deliberately not ported.** The driver was
written; the experiment was not. The script had been run a few times,
years ago, and its requirements are no longer remembered — reading the
code answered what it did but not what it was *for*, and porting it
would have produced a plausible-looking experiment nobody could confirm
was correct. What it actually did is recorded in the experiment notes so
nobody has to re-derive it.

## Bench findings

Commissioned, all tiers, no failures. Nothing surprising: the two
findings from that session were the checkup tool's own fault (deviation
48) and the timeout desynchronisation (deviation 40), not defects in
this driver.

## What this means for your data <!-- bench -->

**Any low-bias 2401 data from the old script is suspect.** Source levels
were rounded to four decimal places, which quantises to 100 µV. At ±1 V
that is invisible; at ±100 µV a 21-point sweep collapses to three
distinct levels while the saved file still lists 21. Nothing in the file
records that it happened.

**Runs before the output-off change used high-impedance off**; runs
after use normal off unless the box is ticked. No measured value
changes, but if a rig depended on the sample being isolated between
sweeps, that no longer happens by default. The `output_off_mode` column
records which you got.

**The output turns itself off when the source function changes**, and
this driver disables auto output-off so a sweep holds its level between
points. So the output must be turned on *after* changing mode. The
experiments all do this; if you write new code that does not, the next
reading blocks forever with no error and the instrument looks dead.

**One slow reading is not three faults.** A timed-out read leaves its
reply in the buffer and puts everything after it one step out of phase.
The checkup sends a device clear on any timeout and records whether it
worked, so the symptom stops multiplying.

## Open questions

- The exact commissioning date was not recorded, so this driver reads as
  stale regardless of what has changed. Worth closing on the next bench
  session — see [checkup-owed](../open/checkup-owed.md).
- **What was the 2401 measuring while the 2611A applied its long bias?**
  A second device on the same stage, another terminal of the same
  device, or a cross-check. The code cannot say, and the answer decides
  whether the dual-SMU script is one experiment with two roles or simply <!-- lint-ok -->
  two experiments. <!-- lint-ok -->
