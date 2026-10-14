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
bench_notes: "2026-10-14, eleven checkups and two probe runs, GPIB address 3, firmware B07, nothing attached. Found and fixed in the day: a trigger-overrun race, the checkup taking a missing voltage for a failure, and lost readings from the instrument's own trigger delay. The last two checkups, 18:19 and 18:20 at eefe595375b9, passed whole: 42 pass, 5 warn, 0 fail, 16 skip each, every reading answered and no flag raised. See the note"
bench_code: "fe18cacfa943"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "about 75 ms per reading at fast integration, measured 2026-10-14 with nothing attached on the 200 uA range; 20 ms of it is switching the trigger mode around each reading"
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
- **The instrument idles in `T3`, one-shot on GET**, and `measure()`
  switches to `T1`, one-shot on talk, for its one talk. In `T1` every
  talk is a trigger, status queries included, and the second session
  showed what that costs - see below.
- **The instrument's trigger delay (`W`) is never used.** It loses
  readings - see the fourth session. A settle asked for through
  `set_source_delay()` is a wait in the driver before each reading.
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

## Second session, 2026-10-14 (code at `ed5900ddc47e`)

Two runs, a minute apart. The first stopped on a timeout; the second
failed one check and passed every measurement, the open-circuit current
included (−11 nA on the 200 µA range, at 0.1 V).

**The timeout was a race in the driver, not chance.** In `T1`, one-shot
on talk, *every* talk is a trigger - the one that fetches a status word
as much as the one that fetches a reading. A conversion takes about
50 ms, and a talk that arrives before it has finished is refused as a
**trigger overrun** (flag 5 of `U1`). In the first run, a `U1X` right
after `S0X` came about 20 ms sooner than the same step had in the
session before, and caught a conversion in progress. The checkup then
drains the error word until it reads clean, polling every 22 ms, so
each poll re-triggered and overran again - the flag read set 21 times
over, three times. The reading asked for next came 22 ms after the last
poll; its trigger was an overrun, so no reading was ever made, and the
talk waited out the 16.8 s timeout. The link latched, as it should.

**The second run's failure was the first run's flag.** The lost
reading left trigger overrun latched, and a device clear does not empty
the error word, so the next reset's first `U1X` reported it as its own.
The poll after it read clean.

So it was decided by tens of milliseconds of bus timing - which is why
the first session never saw it - but the mechanism is fixed, not
random. The driver now idles in `T3`, one-shot on GET, which nothing in
this suite sends, so a status query triggers nothing; `measure()` sets
`T1`, takes its one talk, and sets `T3` again even if the talk fails.
And `reset()` reads both flag words straight after the clear and sets
them aside, so it grades only what its own commands did. The fake
instrument in the tests now reproduces the race, and the previous
driver fails ten of its tests.

The cost is two short commands per reading, about 10 ms each on this
bus.

## Third session, 2026-10-14 (code at `94628971e22b`)

Three runs, with the instrument idling in `T3`. **Not one trigger
overrun** anywhere in the error word, across all three - the race above
is closed. One run passed whole: 42 pass, 5 warn, 0 fail, the sweep
included. Readings now take about 75 ms, 20 ms more than before, which
is the two trigger-mode commands around each one.

The other two each lost **one reading, at the same step**: the sweep's
first point, `V0,0,0X` then `T1X` then the talk, which never answered.
The first run went through the identical sequence and got its reading.
This is a different failure from the overrun - that one left its flag
latched through the next device clear, and this left nothing: the next
run's first look at the error word was clean. Across the three runs
there were 31 reading talks; the 15 with no level command before them
all came back, and the 2 losses are among the 16 that followed one.

Those two runs were headed "PASS WITH WARNINGS". They had stopped at the
lost reading, and the checkup recorded nothing for it, because the
timeout happened inside the sweep's own thread. That is fixed for every
instrument: an unfinished run is now headed INCOMPLETE and names where
it stopped.

## Fourth session, 2026-10-14 (code at `61f00639b5a0`)

`tools/bench_487_trigger.py` again, now varying the instrument's own
trigger delay, and three checkups.

**The three checkups passed whole**, 42 pass and 0 fail each.

**The probe found the lost readings, and they need the trigger delay.**
Of 864 readings, 4 never came - all 4 with `W` at 10 ms: 4 of 432 there,
none of the 432 with it at 0, and none of the 720 in the first probe
run, which never set it. Had the losses nothing to do with `W`, all four
landing on its side would be about a 1-in-180 chance. Nothing else the
probe varied separates them: the wait after the level, a changed or
re-sent level, the thread and the integration period all have losses on
both sides or none on either. Each loss left `U1` and `U9` clean and
`U0` showing the instrument idle in `T3` with the output on - the talk
simply went unanswered. All four did follow a level command, but only
48 talks with `W` at 10 ms did not, which is too few to say whether
that matters.

Every reading the checkups had lost was taken with the 10 ms its own
tier 2 leaves in force (`set_source_delay(0.01)`), which is why the
first probe, with none, could not find them.

So the driver no longer uses `W` at all. `reset()` sets it to 0, and
`set_source_delay()` keeps the settle itself, sleeping before each
reading's `T1X` - the same meaning, done where it cannot lose a reading.
The probe still sends `W` raw, so it can reproduce the fault.

**Confirmed the same evening**, at `eefe595375b9`: two checkups, both
42 pass and 0 fail, every one of the 13 readings in each answered, no
flag in any error word, and no trigger delay but `W0` ever sent.

## Open questions

`tools/bench_487.py` asks every one of these that can be asked at
50 V or less, in one sitting.

All of these are bench work, listed in the order a first session
should take them:

- **Which readings are lost, and after what.** At `9462897` one run
  of three passed whole; the other two each lost one reading at the
  same step - the sweep's first point, right after re-sending
  `V0,0,0X` - with no flag left behind. Not the overrun race: that
  leaves trigger overrun latched, and these left nothing. Two in
  thirty-one cannot separate the delay since the level, re-sending an
  unchanged level, the sweep's thread and the integration period, so
  `tools/bench_487_trigger.py` asks a few hundred times, varying each.
  Its first run, at `783f8c3219ab`, **lost nothing in 720** - the exact
  failing sequence included - so none of those four explains it, and
  chance does not either. What the checkup had and that run did not is
  a 10 ms trigger delay (`W0.010X`, left by the checkup's tier 2), so
  the probe now varies that too; and every trace entry now records when
  it began, so the next lost reading shows the gaps before it.
- **Whether switching from `T3` to `T1` triggers anything by itself.**
  The manual does not say. If it did, every reading would be one
  conversion late, and a slow sweep across a resistor would show it.
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
