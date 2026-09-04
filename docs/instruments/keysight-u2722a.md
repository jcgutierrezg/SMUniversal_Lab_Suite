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
last_bench: 2026-09-04
bench_notes: "2026-09-04 checkup at 7f09e21: 66 pass, 0 warn, 0 fail, 10 skip. clean: no warnings and no failures. The 2026-08-25 failure is closed against hardware - the checkup now derives its probe from this model's own envelope and probes the current axis at 73.2 uA, ten counts of R120mA, instead of a seventh of one count. Both floors are declared and both refusals were demonstrated, each naming the range that would carry the level. SYST:LFREQ is no longer sent, so the error queue is clean from the first read rather than needing a drain. A 0.1 V command on R20V still measures back 0.1056 V"
bench_code: "d793c41378eb"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "81.6 ms at NPLC 1 (its declared minimum - there is no faster setting; 2 apertures), no first-read cost"
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

**Superseded by deviation 52.** Re-sending is necessary and was not
sufficient: it was done blind, and a re-sent value the new range cannot
hold is refused rather than applied. See below. <!-- lint-ok -->

**Deviation 52 — the compliance chooses the range, and every limit is
read back.** The bench round of 2026-08-24 established that a limit is
settable only between a tenth of the active range's full scale and full
scale. On decade-spaced ranges that makes the compliance very nearly
*determine* the range — 5 µA is settable on R10uA and nowhere else — so
the driver stops treating range and compliance as two independent knobs.

Four consequences, in the order they bite:

1. **The range is chosen from the limit**, not widened to fit it. The
   widest range that merely *fits* a value is usually one whose floor is
   above it: R120mA fits 100 µA in the sense that 100 µA is less than
   120 mA, and refuses it in the sense that matters.
2. **A range change that would strand a cached compliance is declined**,
   and the console says which range was kept and why. Resolution loses
   to protection: a narrower range than the plan asked for is a worse
   measurement, and a compliance nobody chose is a wrong one.
3. **Every limit written is read back** and the run stops if it did not
   take. Without this, a refusal is a `-222` sitting in a queue that
   only `start_linear_sweep()` reads, and a bias-hold run never looks.
4. **A compliance that no range can express is refused before the
   output goes on**, naming each range's window. Three ways that
   happens, and the middle one surprised us: below 100 nA or 200 mV;
   **between 10 mA and 12 mA**, because the current ranges are decades
   until the last one so R10mA's ceiling does not meet R120mA's floor;
   or above the instrument.

**This one changes what a run refuses to do.** A compliance the previous
driver accepted and the instrument quietly replaced now stops the run
before anything is energised. That is the intent — but a setup that
"worked" before may now refuse, and the message names the range that
would allow it.

**Deviation 53 — the sourced quantity's own limit follows its level.**
`SOUR:CURR:LIM` is the compliance while sourcing voltage. While sourcing
*current* it applies to the quantity the operator is commanding, and a
value carried over from a previous voltage-sourcing run is at best
meaningless — at worst a cap on the sweep, delivering a fraction of the
requested current and drawing a smooth, entirely wrong curve. So
`set_source_function()` drops it and gives that axis a limit of its own.

**Not full scale**, which was the first draft. Full scale never caps
anything, but it is the *weakest* value in the window: on R120mA it
means 120 mA where the range floor means 12 mA, so opening it would
trade a tight fallback for none at all. Instead the limit resolves to
the narrowest value the active range can hold that still clears every
level commanded — the range floor until a level exceeds it, then twice
the largest level, capped at full scale.

Twice, rather than just above, because this sits in the inner loop of a
software sweep and a limit write plus its readback is two round trips.
Granting headroom in doubling steps is the trick a growing array uses:
the write lands on a logarithmic number of points instead of all of
them, and the fallback is still twice the level rather than the whole
range. The doubling also covers what a bare "just above" would get
wrong — a limit set to exactly the level is a limit the level sits on,
and an instrument rounding it down by one count clips the endpoint of a
sweep with no error anywhere.

**The headroom goes up before the level goes out**, not after. If
`SOUR:CURR:LIM` does cap the sourced current — the open question this
instrument has not answered — then a level written under a limit below
it comes out capped, and `SOUR:CURR?` would still report the value that
was asked for. Ordering it this way is correct whichever way that
question resolves.

Protection during the run comes from the limit on the quantity *not*
being sourced, which is the one the experiment sets.

**Physical consequence, and it is not a small one.** A current-sourcing
run now delivers the current asked for, where a stale limit from an
earlier voltage-sourcing run may previously have been capping it. That
is correct and matches every other driver in the suite, but it is an
*increase* in delivered current in that configuration. Worth knowing
before the first bench session on this patch.

**Deviation 54 — a source level below ten counts of the active range is
refused.** Below one count of the converter there is no signal, only
offset, and the bench proved on 2026-08-25 that its **sign is not
commanded**: on R120mA, `-1 µA` and `+1 µA` produced the same output,
because 1 µA is a seventh of a count. Which way the residue points is
not under anyone's control — positive through eleven probes that day,
negative during the commissioning run, where it drove the output to the
−2 V range rail against a compliance that was working perfectly.

An operator asking for a 1 µA bias getting an output at the opposite
polarity from the one their sample is wired for is not something a log
line covers, so this refuses before the output is energised, naming the
range that would carry the level.

**Ten counts is a decision, not a measurement.** One count is the floor
where a request means anything at all, and there the quantisation error
is 100%; ten caps it at 10%. It is one constant, `MIN_LEVEL_COUNTS`.
What it costs:

| Range | One count | Minimum settable |
|---|---|---|
| R1uA | 61 pA | 610 pA |
| R100uA | 6.1 nA | 61 nA |
| R120mA | 7.3 µA | 73 µA |
| R2V | 122 µV | 1.22 mV |
| R20V | 1.2 mV | 12.2 mV |

**Read the last two rows before using this instrument at low bias.**
R2V's floor is the instrument's absolute voltage floor, so **nothing
below 1.22 mV can be sourced on any range** — a 1 mV level is refused
outright rather than being carried by a narrower range, because there
isn't one. That is a real restriction on low-bias work and it is the
price of the threshold, not of the hardware.

The threshold bounds quantisation error and **nothing more**. It is not
a guarantee that the sign comes out right; establishing that would need
sourcing into a known load, which has not been done.

**This one changes what a run refuses to do.** A level the previous
driver accepted and the instrument turned into residue now stops the run
before anything is energised.

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

### 2026-09-04 — fleet round: what this instrument measured

Descriptive measurements from the round of 2026-09-04, run at commit
`727022f`. **Not a commissioning record**, and deliberately not copied
into `last_bench` / `bench_code` / `bench_result`: the readback fix that
followed changed `drivers/base_smu.py`, which every driver's
fingerprint covers, so this round no longer describes the code that is
running. A fresh round is owed once the driver work lands.

| Measured | Value |
|---|---|
| Steady-state reading at NPLC 1 | 81.6 ms |
| First reading after the output comes up | none — 104 ms, 1× the steady state |
| Output gap across a source-function change | 228 ms de-energised |
| Open-circuit current at 0.1 V | 3.1 nA, at 0.1062 V |

**The reading time is not comparable with another instrument's, and
this instrument is the reason the caveat is needed.** NPLC 1 is its
*declared minimum* — there is no faster setting — so its 81.6 ms is
being measured against a B2901A figure taken at NPLC 0.0004, three and
a half decades of integration window apart. The U2722A is not fourteen
times slower than the B2901A at the same quality; it is integrating
enormously longer per reading. Compare cells only where the NPLC beside
them matches.

Two figures where this instrument is the extreme in the round:

* **The longest output gap: 228 ms de-energised** across a
  source-function change, an order of magnitude longer than the
  Keithleys. Anything that changes mode mid-run leaves the sample
  unbiased for a fifth of a second here.
* **No first-reading penalty at all.** Every other mains instrument in
  the round pays between 2× and 46× on the first read after the output
  comes up; this one pays 1×.

#### Range planning matters more here than on any other instrument

A `0.1 V` command measured back **0.1062 V** — 6% high — on the range
the all-AUTO plan lands on. The mechanism is arithmetic, not error:
this instrument has no autorange, so AUTO takes the widest voltage
range, R20V, where one count is 1.2207 mV. 0.1 V is 81.9 counts, and
87 counts is what came out: `0.106201172` V, exactly 87 × 1.2207 mV.

The same nominal endpoint reached **0.1003 V** in the sweep, which is
ranged from its own endpoints and therefore lands on R2V, where one
count is 0.1221 mV. Same command, same instrument, same run, 6% apart —
and the difference is entirely which range the plan chose.

A commanded level here is only as good as the range it is expressed
on, and on this instrument that is visible at the first decimal place
rather than in the last digit.

#### `SYST:LFREQ` is not a command this instrument has

Every connect sends `SYST:LFREQ F50HZ, (@1)` and gets
`-113,"Undefined header"` back, immediately after `*RST`. It is the
first entry in every trace and is harmless — the error is drained by
the next `SYST:ERR?` — but it is a command that has never worked on
this model, and setting the line frequency is
[fault 7](../faults/07-line-frequency.md). The line frequency here is
not settable; whatever the instrument does about mains rejection at
NPLC 1 it does without being told.

#### Sensing is hardwired 4-wire

`set_remote_sense(False)` skips: this model has no sense-mode control,
so the measurement checks run 4-wire into an open circuit. The report
says so in its header rather than working around it. It is also why
this instrument's readings settle cleanly at a compliance the checkup
cannot force it away from.

#### It reports neither the limit value nor a compliance flag

`compliance_tripped()` is not implemented for this model, so the tier 3
check skips. The limit half is different: `SOUR:VOLT:LIM?` and
`SOUR:CURR:LIM?` both answer here, which is why `compliance survives
ranging` **passes** on this instrument and skips on five others.

### 2026-09-01 — noise/rate envelope and sub-count floor

100 uA into 9958 ohm, 2 V compliance, current range pinned to the bias.

| NPLC | per reading | rate | RSD |
|---|---|---|---|
| 1 | 71.3 ms | 14.0 Hz | quantised |
| 3 | 153 ms | 6.5 Hz | quantised |
| 9 | 398 ms | 2.5 Hz | quantised |
| 28 | 1.17 s | 0.9 Hz | quantised |
| 84 | 3.46 s | 0.3 Hz | quantised |
| 255 | **10.4 s** | 0.1 Hz | quantised |

**Every rung is quantised**, because a 2 V compliance selects R2V and
readings are then multiples of 122 uV. The whole envelope says nothing
about noise on this instrument at this compliance - a tighter compliance
would buy a finer range, and that is the only way to see the noise floor
here.

**Its 1 PLC minimum caps it at 14 Hz**, an order of magnitude below
everything else on the bench, and a single reading at NPLC 255 takes
**ten and a half seconds**. This is not a trade-off that can be tuned
away; it is the floor of the ladder.

**Sub-count: the driver refuses, which is the answer.** It followed the
sign down to 98 nA and then deviation 54 refused 49 nA before energising
anything, naming R1uA as the range that would carry it. It is the only
instrument on this bench whose floor is *declared by the driver* rather
than inferred from readings that stopped making sense.

- **2026-08-25, after deviation 54:** the checkup at `ea2fca4` returned
  **46 pass, 6 skip, 1 fail**, and the one failure is the driver
  answering correctly:

  ```
  [FAIL] configure for current sourcing: set_current_level(1e-06)
         RangeError: ... R1uA would carry it ...
  [SKIP] output gap across a source-function change
  [SKIP] current-sourcing checks
  ```

  The checkup probes at 1 uA; the shared-knob reconciliation puts the
  current axis on R120mA, where one count is 7.32 uA; the driver
  declines. **The trace ends `OUTP OFF, OUTP OFF` — nothing was
  energised**, which is the guarantee deviation 54 exists for.

  This also confirms the `Checkup.setup()` change against hardware
  rather than against a fake. The same refusal used to raise out of
  `run()` and take the rest of tier 3 with it; the tool now grades it,
  says which step refused, carries the driver's own message, and records
  the two checks that depended on it as skips with reasons. Tiers 1 and
  2 completed normally around it.

  Deviation 52 is intact in the same run: the last commands set a 1 V
  compliance on R2V and read it back correctly.

  **This failure is expected and will stand.** Making it green means the
  checkup choosing a probe level from each instrument's envelope instead
  of a module constant, which is recorded in
  [technical debt](../open/technical-debt.md) and is a separate concern.

  The tree carried one untracked scratch file at the time of the run.
  It is outside the fingerprint, which covers the driver and
  `base_smu.py` only, so the provenance stands.

- **2026-08-25:** the checkup at `e44f3a5` returned 54 pass, 4 skip,
  **1 fail** — the four `-222` failures are gone and every limit now
  writes and reads back cleanly, so deviation 52 is confirmed against
  hardware. The one remaining failure took eleven probes to explain and
  the explanation is not the one it looks like.

  **The failure read as:** `compliance reached on open circuit — -2 V
  against a 1.0 V limit`. The limit had been verified by readback two
  commands before the output came on.

  **The compliance was working the whole time.** Probes A through J
  established that `SOUR:VOLT:LIM` is genuine bipolar compliance, and
  they are recorded here because three separate wrong conclusions were
  drawn along the way and each was drawn from a probe too short to
  settle:

  | Probe | Range | Limit | Commanded | Settles at |
  |---|---|---|---|---|
  | A | R1uA | 0.2 V | +100 nA | +0.1985 V |
  | B | R1uA | 0.2 V | −100 nA | −0.1993 V |
  | C | R1uA | 2.0 V | +100 nA | control — no clamp, still rising at 0.777 V |
  | D | R1uA | 1.0 V | +1 µA | +0.9996 V |
  | E | R120mA | 1.0 V | +1 µA | +0.9994 V |
  | F | R120mA, leads on | 1.0 V | +1 µA | +0.9995 V |
  | G | R120mA + `CURR:LIM` | 1.0 V | +1 µA | +0.9995 V |
  | J | R120mA | 1.0 V | **−1 mA** | **−1.0005 V** |
  | J | R120mA | 1.0 V | **+1 mA** | **+0.9997 V** |

  Two ranges, both polarities, two limit values, leads attached and
  terminals bare. It clamps everywhere, consistently about 0.05% below
  the value set — comfortably inside the 1% readback tolerance the
  driver uses, which until now was a number copied from
  `verify_compliance` with nothing behind it.

  **What actually failed is that the level was never sourced.** On
  R120mA one count is 7.32 µA, so the checkup's 1 µA request is a
  seventh of a count. Probe J settles it beyond argument: commanding
  `-1 µA` and `+1 µA` on that range produced **the same output**. The
  sign was ignored. Below a count there is no signal, only offset
  residue — and its polarity is not under anyone's control. It sat
  positive through every probe on 2026-08-25 and clamped harmlessly at
  +1 V; it sat negative during the commissioning run and walked the
  output to the −2 V range rail.

  So an operator asking for a 1 µA bias can get an output at the
  opposite polarity from the one their sample is wired for, with nothing
  in the error queue. Addressed by deviation 54.

  **Three further facts worth having, none of which anyone went looking
  for:**

  - **The negative clamp regulates far more loosely than the positive
    one on R1uA.** Twenty readings at +1 V spanned about 1 mV; at −1 V
    they spanned 134 mV — a hundredfold difference at the same range and
    limit. On R120mA both directions were tight (±0.4 mV), so this
    belongs to the small range, not to the negative direction generally.
    A measurement sitting at negative compliance on R1uA is sitting on
    something that wanders by 13%.
  - **The output capacitance is roughly 36 pF with the terminals bare.**
    Measured from probe C's slew: 0.0449 V per reading at 16 ms is
    2.8 V/s at 100 nA. At 100 nA that is 1 V per second of ramp, so
    anything measured into an open circuit needs twenty readings before
    it means anything. Three of the eleven probes drew a wrong
    conclusion from a value that had not arrived yet.
  - **Charge persists across `*RST`, output-off and the gap between
    runs.** Probes A, B and C each began where the previous one left
    off, decayed a little: +0.199, then +0.066, then −0.073. A
    compliance probe that reads too early is reading the *previous*
    measurement's residue.

  **Not measured:** whether ten counts is enough to guarantee the
  commanded sign. Probe G saw current readings excursing to twelve
  counts on R120mA, but that figure includes measurement noise and
  separating it from source residue needs a known load, which was not
  attempted. Deviation 54's threshold bounds quantisation error and
  claims nothing more.

  **Also cleared along the way**, each having been proposed and then
  refuted: that the limit is one-sided; that the limit does nothing and
  only the range rail bounds the output; that the leads left attached to
  the channel were responsible; that the hardwired 4-wire sense loop was
  responsible; and that deviation 53's `CURR:LIM` write caused it. None
  survived contact with a settled reading.

- **2026-08-24:** the remaining half, characterised properly. Seven
  numbered snippets (A–G), each written to make one hypothesis fail, and
  the outcome was not the tidy rule the earlier entries assumed.

  **What is settled.** A compliance is settable only between a tenth of
  the active range's full scale and full scale. Measured directly at
  four points — R100uA refused 9.9 uA and accepted 10.0 uA; R20V refused
  0.5 V and accepted 2.0 V; and `*RST` leaves 100 nA on R1uA and 200 mV
  on R2V, both evidently legal. The four intermediate current ranges are
  interpolation across a uniform decade family, not four more
  measurements.

  A value outside that window is **refused** with `-222, "Data out of
  range"` and the previous value stays in force. It is not clamped, and
  the instrument does not stop. Snippet E confirmed this with a readback
  either side of each of three refused writes.

  The readback itself tells the truth, including the truth that a write
  did not take, which is what moved `COMPLIANCE_READBACK_TRUSTED` from
  `None` to `True`.

  **What a range change does to a limit — twelve observations, no single
  rule.** Recorded as observations rather than as a model, because every
  rule that fits eleven of them fails on the twelfth:

  | # | Snippet | Range change | Old value vs new window | Limit afterwards |
  |---|---------|--------------|-------------------------|------------------|
  | 1 | A | R100uA → R120mA | below floor | moved up to floor, 12 mA |
  | 2 | B | R120mA → R1uA | above ceiling | moved down to ceiling, 1 uA |
  | 3 | B | R1uA → R10uA | at floor | unchanged, 1 uA |
  | 4 | B | R10uA → R100uA | below floor | moved up to floor, 10 uA |
  | 5 | B | R100uA → R1mA | below floor | moved up to floor, 100 uA |
  | 6 | B | R1mA → R10mA | below floor | moved up to floor, 1 mA |
  | 7 | B | R10mA → R120mA | below floor | moved up to floor, 12 mA |
  | 8 | G | R10mA → R1mA | **above ceiling** | **unchanged, 5 mA** |
  | 9 | D | R2V → R20V | below floor | **unchanged, 200 mV** |
  | 10 | D | R20V → R2V | inside | unchanged, 200 mV |
  | 11 | E | R2V → R20V | below floor | **unchanged, 200 mV** |
  | 12 | F | R2V → R20V | below floor | **unchanged, 200 mV** |

  The current axis moves the value in seven of eight; the voltage axis
  never moves it in four of five. Each axis has exactly one observation
  contradicting its own pattern, and the two contradictions point in
  opposite directions. Row 8 in particular means the instrument will
  hold a limit above the active range's own full scale quite happily —
  5 mA of "compliance" on the 1 mA range is 5 mA of nothing.

  Two further observations resist explanation and are recorded because
  the alternative is to leave them out and quietly forget them:

  - Snippet C read 2 V from `SOUR:VOLT:LIM?` on R20V. Snippets D, E and
    F read 200 mV under conditions that differ from C only in that C had
    written a *current* limit of 20 mA beforehand. Three attempts to
    reproduce it failed. The reading also took 23 ms against a typical 6.
  - Row 8 is the only current-axis observation where a value above the
    new ceiling survived. Rows 1–7 came from one continuous run; row 8
    from another.

  **What was done about it.** Nothing in the driver depends on resolving
  either anomaly, because the fix does not model the behaviour — it
  refuses to be exposed to it. The range is chosen from the compliance,
  a range change that would strand a compliance is declined, and every
  limit written is read back. See the decisions below.

  **Not measured:** whether `SOUR:CURR:LIM` caps the *sourced* current
  while sourcing current, as opposed to acting as compliance while
  sourcing voltage. Snippet C1 showed it does not gate *programming* a
  level with the output off — a 50 mA level was accepted and reported
  back under a 20 mA limit — but the output-on case needs a load and was
  not attempted. The driver is written so the answer does not matter;
  see decision U5.

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

  This is `D7` in `docs/plan.md`, deliberately outside what was signed <!-- lint-ok -->
  off for the `NOT_SOURCED` wave. The voltage-sourcing half is genuinely
  fixed and visible in the same trace as `SOUR:CURR:RANG R100uA` with no
  error.

  **Superseded 2026-08-25.** Deviation 52 takes the range from the
  compliance limit and forces it, and deviation 54 re-checks it before
  every level write, so the range `apply_ranges()` picks is overwritten
  before anything is sourced. The trace above cannot recur. `D7` is
  closed - see [Known technical debt](../open/technical-debt.md).

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

**Your compliance also picks your resolution.** This is the one thing to
take away. On every other SMU here the compliance protects the sample
and the measurement range sets the resolution, and they are separate.
On this instrument a limit is only settable between a tenth of the
active range and its full scale, so the compliance you type *is* the
range — and the range is what a 14-bit converter divides into 16384
counts.

| Compliance you type | Range you get | Smallest step in the data |
|---|---|---|
| 9 µA | R10uA | 0.61 nA |
| 90 µA | R100uA | 6.1 nA |
| 900 µA | R1mA | 61 nA |
| 90 mA | R120mA | 7.3 µA |

Setting a generous compliance "to be safe" costs a decade of resolution
per step. Setting a tight one buys it back. The log says which you got
each time a compliance is applied, so it is worth reading the line
rather than guessing.

**Two things this instrument cannot source at all.** Nothing below
**1.22 mV**, on any range, and nothing below **610 pA**. Below ten
counts of the converter the output is offset rather than signal, and its
sign is not the one you asked for — the bench watched `-1 µA` and
`+1 µA` produce the same output. A level under those floors is refused
before the output comes on rather than turned quietly into noise. If you
need millivolt-scale bias, this is the wrong instrument.

**Twenty readings, not two.** With the terminals bare the output looks
like about 36 pF, so at 100 nA it ramps a volt per second and charge
survives between runs — a reading taken early is the previous
measurement's residue, not this one's answer.

**Two compliance values this instrument cannot give you.** Anything
**below 100 nA**, and anything **between 10 mA and 12 mA** — the current
ranges are decades until the last one, so the 10 mA range's ceiling does
not meet the 120 mA range's floor and there is a real gap in between.
Either is refused before the output comes on, with a message naming the
ranges that would work. For a sample needing less than 100 nA of
protection, this is the wrong instrument; see [choosing an SMU](../../bench/choosing-an-smu.md).

**Switching sourcing mode mid-session is now safe.** The instrument is
reset when you connect, not between runs, so a compliance used to
survive from one run into the next. Sourcing voltage with a 100 µA
compliance and then switching the same window to current mode left that
100 µA sitting on the axis you were now commanding. Each run now clears
it. If a current sweep on this instrument ever looked lower or flatter
than it should, after a voltage-mode run, that was this.

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

**Which range you land on changes the level you get, at the first
decimal place.** Measured 2026-09-04: the same `0.1 V` command came back
as **0.1062 V** on R20V and **0.1003 V** on the finer range — 6% apart,
one run, one instrument. R20V's count is 1.2207 mV, so 0.1 V rounds to
87 counts and 87 counts is 0.10620 V. There is no autorange here, so an
axis left on AUTO takes the widest range and pays that quantisation.
Range planning matters more on this instrument than on any other in the
fleet; if a level has to be accurate, pin the range rather than leaving
it to AUTO.

**The output is down for about a fifth of a second across a
source-function change** — 228 ms measured, an order of magnitude
longer than the Keithleys. Anything that switches mode mid-run leaves
the sample unbiased for that long.

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

## What the checkup now sources here

Until the probe became instrument-aware, `tools/smu_checkup.py` asked
this instrument for a module-wide 1 µA. The shared-knob reconciliation
puts the current axis on R120mA, where one count is 7.32 µA, so that
request was a seventh of a count and deviation 54 refuses it. The tool
could not pass on this instrument however well it was working, and the
2026-08-25 report records that failure as accepted-and-explained.

The checkup now asks this driver what its floor is *on the range the
ranging plan landed on* and raises the level to it — ten counts of
R120mA, 73.2 µA. The tier 1 *probe levels* row in the report says which
levels ran and why, so this instrument's tier 3 numbers can still be
compared against another's by somebody who reads that row first.

That row was wrong until 2026-09-04. It was recorded in tier 1, before
the substitution tier 3 makes, so it reported the nominal 1 µA and
added "used unchanged" beside it while the instrument was being handed
73.2 µA — on the one instrument in the fleet where the substitution
happens at all. It is now rewritten at the end of the run and names
both numbers. See
[fault 44](../faults/44-a-summary-that-contradicts-its-own-body.md).

**Whether it passes is a bench question.** Nothing in the repository can
assert it; the frontmatter above still records the last physical run.

## Open questions

- **Is ten counts enough to guarantee the commanded sign?** Deviation
  54's threshold bounds quantisation error at 10% and claims nothing
  about polarity. Probe G saw current readings excursing to twelve
  counts on R120mA, but that includes measurement noise; separating
  source residue from it needs sourcing into a known load, which has not
  been done. Until it is, the threshold is a decision rather than a
  measurement.
- **Why does the negative clamp regulate so much more loosely on
  R1uA?** 134 mV of spread against 1 mV positive, same range and limit,
  while R120mA is tight in both directions. Not chased.
- **Two observations from 2026-08-24 that no rule explains.** Snippet C
  read 2 V from `SOUR:VOLT:LIM?` on R20V where D, E and F all read
  200 mV under conditions differing only in that C had written a current
  limit beforehand; and row 8 of the matrix is the only current-axis
  observation where a value above the new range's ceiling survived a
  range change. Neither blocks anything — the driver refuses to be
  exposed to the behaviour rather than modelling it — but both should be
  re-probed before anyone writes a rule into this note.
- **Does `SOUR:CURR:LIM` cap the sourced current while sourcing
  current?** Unverified against hardware. Snippet C1 showed it does not
  gate *programming* a level with the output off; the output-on case
  needs a load and was not attempted. Deviation 53 is written so the
  answer does not change the code, but it would change what the note can
  claim.
- **Is `SOUR:CURR:RANG?` supported?** If it is, reading the range back
  in `_confirm_limit()` would make its window check real rather than
  unreachable — see the docstring there, and it would also let this
  driver answer the range half of the readback contract, which it
  currently reports as `unsupported`. Deliberately not guessed: an
  unrecognised *command* on this instrument is logged and ignored, but
  an unrecognised *query* is never answered, times out and latches the
  transport. Ask it once at the bench with a trace running and the
  question is settled either way.
- **Does anyone want the other two channels?** The driver takes a
  `channel` argument defaulting to 1, which is what the original
  hardcoded. Two channels driving two roles at once is the dual-SMU
  experiment in disguise, and that is still unported.
- The exact commissioning date was not recorded, so this driver reads as
  stale regardless of what has changed. Worth closing on the next bench
  session — see [checkup-owed](../open/checkup-owed.md).
