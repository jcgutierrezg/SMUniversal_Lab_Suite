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
last_bench: 2026-09-16
bench_notes: "2026-09-16 fleet round, re-run at 5d32980234ae after the driver changed: 73 pass, 2 warn, 0 fail, 5 skip. The first run that day at 3c2164e failed the new wider-range step on both axes: a measure range wider than the compliance in force is refused with 824 and the narrower range stays - 1 mA against 100 uA read back 105 uA, 20 V against 1 V read back 2.1 V. The driver now re-sends the range once the limit arrives, and the re-run read back 1.05 mA and 21 V. The refusal still beeps and shows 824 on the front panel. Burst check 10 of 10 on bursts of up to 16 writes. Both warnings are the unmeasured source-voltage floor"
bench_code: "1b4595a9e2a5"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "35.4 ms at NPLC 0.01 (its declared minimum), +90 ms first read - 3x"
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
compliance_trip: true
fleet: smu
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

### 2026-09-16 - a range wider than the compliance is refused

The record `last_bench` points at: re-run at `5d32980234ae`,
fingerprint `1b4595a9e2a5`, **73 pass, 2 warn, 0 fail, 5 skip**.

The first run that day, at `3c2164e`, failed the checkup's new tier 2
step on both axes. A measurement range wider than the compliance already
in force is refused with `824 Cannot exceed compliance range`, and the
narrower range stays:

| Axis | Compliance in force | Range asked | Read back (3c2164e) | Read back (5d32980) |
|---|---|---|---|---|
| current | 100 µA | 1 mA | 105 µA | 1.05 mA |
| voltage | 1 V | 20 V | 2.1 V | 21 V |

Every experiment ranges before it limits (fault 15), so any run whose
compliance was higher than the one already set measured on the old
compliance's range. The same refusal as the GSM-20H10's - the 2611A,
2635B and B2901A all accepted the wider range outright the same day -
and fixed the same way: the driver remembers the range and sends it
again once the limit arrives (`_resend_measure_range()`), kept in this
driver rather than the shared base so the instruments that do not refuse
keep their records.

**The refusal still happens and beeps.** A run whose compliance is
higher than the one already set shows `824` on the front panel at the
start; the range in force afterwards is the one asked for. The error
queue held one `824` per axis where two refusals were provoked - it may
merge repeats; the readback, not the count, is what the check grades.

Burst check: 10 of 10 unpaced bursts of up to 16 writes answered, so no
write pacing is declared.

### 2026-09-14 - commissioning round: clean

The record this instrument's `last_bench` now points at. Run at commit
`702023916de6`, fingerprint `0e82874b3a47`: **70 pass, 2 warn, 0 fail,
5 skip**, first attempt.

| Measured | Value |
|---|---|
| Steady-state reading at NPLC 0.01 | 42.5 ms |
| First reading after the output comes up | 82.6 ms, 2x the steady state |
| Output gap across a source-function change | 88 ms de-energised |
| Open-circuit current at 0.1 V | -8.8 nA, at 0.1000 V |
| Software sweep | 5 points in 0.35 s |

**The readback trust is confirmed.** `SOUR:VOLT:RANG?` answered `0.21`
for the 0.2 V range and `SENS:CURR:RANG?` answered `1.050000E-04`, both
against ranges the driver had just set, and the compliance survived the
all-AUTO ranging at 100 uA. Those three rows were warnings on
2026-09-04 and are passes here.

**A reply that took 822 ms.** The error query following
`SENS:VOLT:NPLC 10.0000` answered in 822 ms against roughly 20 ms
everywhere else in the run. Nothing failed - the budget is 3 s - but it
is the same shape as the GSM-20H10's aborts, on GPIB and on a different
vendor. See that note's open question.

### 2026-09-11 — voltage floor, offsets, readback

`tools/bench_envelope.py` and `tools/bench_readback.py`, 100 µA / 1 V
into 9958 Ω, 1 PLC.

| Axis | Last level whose output changed | Zero offset |
|---|---|---|
| current, 100 µA range | 6.1 nA | +3 nA |
| voltage, 2 V range | 61 µV | +0.1 mV |

**The current floor below is one halving too low.** The walk reported
3.05 nA on 2026-09-01 and again today, but on both days the output at
3.05 nA was identical to the output at 6.1 nA — the command halved and
nothing changed. The walk now fails a level like that. The declared
floor, ten counts or 30.5 nA, is five times the corrected figure and
stands.

**Readback: every subject verified.** Each of the four ranges was read
first, set to a different range from the front panel and named by the
query (reported as full scale, 1.05 for the 1 A range), then followed
through two bus changes. Both compliance limits refused a write ten
times the maximum (`-222`) and kept reporting the value that survived.
`RANGE_READBACK_TRUSTED` and `COMPLIANCE_READBACK_TRUSTED` are set on
that evidence.

### 2026-09-04 — fleet round: what this instrument measured

Descriptive measurements from the round of 2026-09-04, run at commit
`727022f`. **Not a commissioning record**, and deliberately not copied
into `last_bench` / `bench_code` / `bench_result`: the readback fix that
followed changed `smuniversal_lab_suite/drivers/base_smu.py`, which every driver's
fingerprint covers, so this round no longer describes the code that is
running. A fresh round is owed once the driver work lands.

| Measured | Value |
|---|---|
| Steady-state reading at NPLC 0.01 | 33.0 ms |
| First reading after the output comes up | 74 ms, 2× the steady state |
| Output gap across a source-function change | 46 ms de-energised |
| Open-circuit current at 0.1 V | 5.4 nA, at 0.1001 V |

**The reading time is not comparable with another instrument's.** Every
instrument in the round ran at its own declared minimum NPLC, and those
minima span 0.0004 to 1 — three orders of magnitude of integration
window. This instrument's 33.0 ms was taken at NPLC 0.01, which is the
slowest floor of any of the SCPI instruments here; a smaller number
elsewhere buys less averaging, not more speed at the same quality.

The first-read penalty is the mildest in the round — 2×, where the
2635B pays 46×. The 46 ms output gap is the longest of the Keithleys,
and it is the measured size of the hazard
[fault 14](../faults/14-output-across-function-change.md) describes:
this driver disables auto output-off, so the output must be turned on
*after* the mode change or the next read blocks with the instrument
looking dead.

**This instrument is blind to compliance in both senses**, which is why
two checks skip rather than one. It reports neither the compliance
limit value nor a compliance flag, so `compliance survives ranging` and
`compliance_tripped() while clamping` both have nothing to ask. That is
the narrow case the checkup's skip message now states explicitly — see
[fault 45](../faults/45-one-message-for-two-different-gaps.md) — and it
is distinct from the 2611A, 2635B and B2901A, which do report the flag.
The manual says both queries exist here; see Open questions.

### 2026-09-01 — noise/rate envelope and sub-count floor

100 uA into 9958 ohm, 2 V compliance, current range pinned to the bias.

| NPLC | per reading | rate | RSD |
|---|---|---|---|
| 0.01 | 58.7 ms | 17 Hz | 0.006% |
| 0.040 | 42.8 ms | 23 Hz | 0.001% |
| 0.159 | 62.0 ms | 16 Hz | 0.000% |
| 0.63 | 93.4 ms | 11 Hz | 0.000% |
| 2.5 | 244 ms | 4.1 Hz | 0.000% |
| 10 | 855 ms | 1.2 Hz | 0.000% |

The slowest of the SCPI instruments, and not monotonic - 0.01 PLC is
slower than 0.04 PLC, so at the fast end this is bound by something
other than integration.

**Sub-count floor: 3.1 nA on the 100 uA range**, and the last row before
it already reads about twice the commanded level. Treat anything below
about 10 nA on this instrument as indicative rather than measured.

- **2026-08-21:** the checkup at `7dc6264` returned 56 pass, 3 skip, no
  failures. Rails to 0.9999 V in 87 ms at 1 µA into an open circuit,
  which is fifteen times faster than the GSM-20H10 and is why the
  settle-loop fault (C1) does not show here.

  Two of the three skips are one missing capability: this driver reports
  neither its compliance level nor its trip state, so
  `compliance survives ranging` and `compliance_tripped() while
  clamping` cannot run. `NOT_SOURCED` therefore has no hardware evidence
  on this instrument. The manual has both queries — see Open questions.

Commissioned, all tiers, no failures. Nothing surprising: the two
findings from that session were the checkup tool's own fault (deviation
48) and the timeout desynchronisation (deviation 40), not defects in
this driver.

## What this means for your data <!-- bench -->

**A 2401 run whose compliance was higher than the one already set on the
instrument measured on the old compliance's range.** That is the first
run after a connect at any compliance above 105 µA (or a voltage
compliance above 21 V), and any later run that raised the compliance.
Readings beyond the narrow range overranged into a sentinel and were
dropped, so such a run came back short rather than wrong; one whose
readings all fitted the narrow range is complete but was measured on a
range other than the one in its `ranges` column. Fixed in the driver
2026-09-16.

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
The checkup used to send a device clear and carry on; since Wave 8a it
stops at the break instead, so the symptom cannot multiply. Results
taken before it are kept and the report says it did not finish.

## Open questions

- **What moved the current compliance to 1.0001 A?** Wired up on
  2026-09-04 and verified on 2026-09-11, the compliance readback read
  1.0001 A when the readback session reached it, where reset leaves
  1.05e-4 A. Only range changes came before it, including a 1 A range set
  from the front panel; the GSM-20H10 did the same. `:PROTection:
  RSYNchronize`, which couples the measurement range to the compliance,
  resets to `OFF` and this driver depends on that rather than setting it
  — a candidate, not an answer. Experiments set their compliance after
  their ranges, so a run is unaffected.

  **It did not reproduce on 2026-09-14.** `:SENS:CURR:PROT?` answered
  `1.000000E-04` both times the commissioning round asked, including
  after the all-AUTO ranging sequence. That round set every range from
  the bus and touched no front panel, which is the difference worth
  noting: the readback session that saw 1.0001 A had a 1 A range set by
  hand.

  Still unanswered by the manual: whether `TRIPped?` is meaningful with
  the output off; what `:PROT:LEV?` returns after a set below the
  documented floor of 0.1% of the measurement range; and whether
  querying the inactive axis is legal or merely meaningless.

- **What was the 2401 measuring while the 2611A applied its long bias?**
  A second device on the same stage, another terminal of the same
  device, or a cross-check. The code cannot say, and the answer decides
  whether the dual-SMU script is one experiment with two roles or simply <!-- lint-ok -->
  two experiments. <!-- lint-ok -->
