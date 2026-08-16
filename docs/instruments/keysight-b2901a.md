---
type: instrument
title: "Keysight B2901A"
driver_class: KeysightB2901A
idn: "Keysight Technologies,B2901A,MY51141631,3.4.2011"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: 2026-08-13
bench_notes: "commissioning 2026-08-13 found the compliance-polarity fault (deviation 21). Three questions remain open and were prepared for 2026-08-14, when the instrument was not powered up"
bench_revalidated: null
reading_time: "one matched conversion"
resolution: "not characterised"
best_for: "the only instrument here above 1 A"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keysight_b2901a.py
model_ids: "['B2901A']"
max_voltage_v: 210
max_current_a: 3.03
voltage_ranges_n: 4
current_ranges_n: 10
power_envelope_n: 3
sweep_kind: software
nplc_min: 0.0004
nplc_max: 100
high_z_off: true
ovp: false
remote_sense_control: true
compliance_trip: true
# --- end generated ---
---

# Keysight B2901A

The highest-current instrument on the bench, and **the first driver here
written with no original lab script behind it.** Nothing below is a
departure from working code — each is a decision made from the command
reference, written down so the reasoning outlives whoever made it.

## Identity and envelope

210 V, 3.03 A DC, ten current ranges.

`MODEL_IDS` claims only the **B2901A**, not the series. The B2902A is
two-channel; the B2911A and B2912A add a 10 nA range this model does not
have. Claiming `B2900` would hand a B2911A a range table missing its
most useful range. An unclaimed instrument gets the manual driver
dropdown; a wrongly claimed one gets silently wrong limits.

## Reset defaults that had to be overridden

**B1 — automatic output-on disabled.** `:OUTP:ON:AUTO` resets to ON, and
the reference states that with it enabled the source output is turned on
automatically when `:INIT` or `:READ` is sent.

This is the sharpest reset default in the suite. The suite guarantees
that the output is energised only when a run asked for it, and "Stop
turns the output off and the worker turns it straight back on" is a
failure already seen on a bench here. On this instrument it would happen
**with no command in the log to trace it to.** Set to 0 after every
reset. Chosen, not inherited.

| Command | Why |
|---|---|
| `:OUTP:ON:AUTO 0` | see above — the self-energising trap |
| `:SYST:LFR 50` | NPLC cancels mains hum only if the instrument knows the period |
| `:FORM:ELEM:SENS VOLT,CURR` | the reply shape the driver parses |
| `:FORM:DATA ASC` | ASCII rather than whatever was left |

**B6 — line frequency is declared, not asked.** 50 Hz, because that is
where this bench is. A 60 Hz lab changes one constant.

Still unresolved: **do `:SENS:CURR:PROT` / `:SENS:VOLT:PROT` really
reset to 100 µA and 2 V?** The manual gives those as the `DEFault`
*parameter*, not the `*RST` value, and they are the compliance
protecting a biased sample when nothing sets one. On the open list
below.

## Decisions and deviations

**B2 — the measurement path is `:MEAS?`, not `:READ?`.** Two reasons,
either sufficient. `:READ` and `:INIT` are exactly the two commands that
trigger automatic output-on, so a measurement path that never touches
them means the output state does not depend on B1's setup line having
succeeded. And the reference is explicit that `:MEAS?` measures the
parameters `:SENS:FUNC` specifies using conditions set beforehand — it
is *not* the 2400 family's `MEAS?`, a hidden `:CONFigure` + `:READ?`
that resets ranging and compliance on every point. Fault 1 does not
apply here, and the driver comment says so.

**B3 — compliance uses the unlicensed spelling.** `:SENS:CURR:PROT`, not
`:SENS:CURR:PROT:BOTH`. The `BOTH` keyword and the
`:NEGative`/`:POSitive` split-polarity forms require licence "SWS" and
firmware 3.1 or later. A driver using them works on some B2901As and not
others, and the failure arrives as a run-time command error on whichever
unit nobody had tested.

**B4 — the hardware staircase sweep is not implemented.** The instrument
has one and it is fully documented. It is left out because the GSM's
hardware sweep cost three separate bench-found deviations — state left
behind by the sweep, a buffer setting that only applies before arming,
and an element list accepted and ignored — none of which an offline
suite could have found. The inherited software sweep is correct from day
one and reads back every level it sources. Upgrading is one file and
nothing in `experiments/` changes.

**B7 — the sense-function spelling is probed, not guessed.** The manual
contradicts itself: the parameter table quotes the argument, its own
`:MEASure?` example does not, and both spellings appear across its
worked examples. The driver sends one, then asks `:SENS:FUNC:ON:COUN?`
and requires exactly two. Sending both would leave nobody able to say
which the instrument acted on.

**The clear-first (`:SENS:FUNC:OFF:ALL`) is load-bearing, and the first
version omitted it.** Reset leaves all six functions enabled, so "at
least two" was already true before anything was sent. The probe returned
a fact, but not a fact about whether the command had worked. That is
fault 12, and it was caught by its own test.

**Fault 11 applies here, unlike on the TSP drivers.** This instrument
needs an explicit autorange-off before a manual measure range takes
effect. The 2635B needs the opposite, and both driver tests assert the
absence of the other's habit so nobody copies one across.

**Deviation 21 — `compliance_tripped()` was asking about the wrong
quantity.** It read `:SENS:CURR:PROT:TRIP?` unconditionally. Compliance
is always on the quantity you are *not* sourcing — source current and a
voltage limit clamps you — so that question is right only when sourcing
voltage. Sourcing current, the current protection is genuinely
untripped and the instrument answered `0` **honestly, to the wrong
question.** Van der Pauw and Hall both source current, so on those two
experiments the flag was `False` whatever the instrument was doing: not
a silence, a wrong reassurance.

Nothing could have caught it from the outside. The tests set a `tripped`
flag the fake returned regardless of mode, so a driver asking either
question passed, and the checkup only asked with the output off — where
`False` is the honest answer. It took a probe on a real instrument
riding a 1 V limit into an open circuit: `:MEAS?` reporting +1.000077 V
while the driver said `False`.

The fix reads `:SOUR:FUNC:MODE?` and asks about the matching protection,
rather than tracking the mode locally — a remembered copy is one reset
or one front-panel press from being wrong, and being wrong here produces
a confident `False`.

Two fake defects fell out of it, both worth more than the bug: the fake
answered the current trip in either mode, so it could not distinguish a
correct driver from this one; and its `_write` matched
`:SOUR:FUNC:MODE` **including the query form**, so *asking* what was
being sourced silently rewrote the answer to voltage. A fake that
mistakes a question for a command corrupts the state the test then
asserts against.

## Bench findings

Commissioned 2026-08-13. The three prepared questions below were for the
14 August session and the instrument was not powered up that day;
`tools/bench_probes.py` already carries the plan, so a future session
needs no new code.

## What this means for your data <!-- bench -->

**Any B2901A Van der Pauw or Hall result from before 13 August 2026
carries no compliance warning even if the instrument was limiting.** The
flag asked about the wrong quantity whenever current was being sourced,
which is both of those experiments. IV sweeps sourcing voltage were
unaffected.

**It energises its own output out of reset.** The B2900 series turns the
output on by itself on a measurement trigger. The driver disables that
on every reset. If you drive this instrument from your own script rather
than through the app, **send `:OUTP:ON:AUTO 0` first.**

**Compliance is sense-side here** — `:SENS:CURR:PROT`, where a 2450 uses
a source limit. Send the Keithley spelling and the B2901A logs it,
ignores it, and leaves the compliance at its reset value; a sweep that
then clamps still draws a convincing straight line.

**It resets to 2-wire.** The other switchable instruments do too, but
this one is worth naming because it is the newest driver and the least
exercised.

**It is the only instrument here above 1 A**, and the second-best choice
after the GSM for compliance-critical work.

## Open questions

Three, all needing the instrument on a bench, all in
`tools/bench_probes.py`:

| Question | Why it matters |
|---|---|
| Is compliance clamped by the present measurement range? | If there is coupling, any run that set the limit before the range may have been asking for a compliance it did not get. This is the U2722A's deviation 21 asked of a different instrument. |
| Do `:SENS:CURR:PROT` / `:SENS:VOLT:PROT` really reset to 100 µA / 2 V? | The manual gives those as the `DEFault` *parameter*, not the `*RST` value. It is the compliance protecting a biased sample when nothing sets one. |
| Does `:TRIG:ACQ:DEL` apply to `:MEAS?`, or only to `:INIT`/`:FETCh`? | It is what `set_source_delay()` writes. If it does not apply, the settle between sourcing a level and measuring it silently does not happen, and the readings look like ordinary noisy data rather than wrong ones. Check with a long delay and a stopwatch: 5 s per point is unmistakable, 0 s is the fault. |

The third was deliberately **not** worked around by sleeping host-side.
That would move *where the settle happens*, which is a measurement
parameter, and not a decision to make quietly inside a driver.

```
uv run python tools/bench_probes.py --address GPIB0::9::INSTR --load 10k
```
