---
type: instrument
title: "Multicomp Pro 72-13200"
driver_class: MulticompPro7213200
idn: "Multicomp Pro 72-13200 V3.30 SN:00028215"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: false
last_bench: null
bench_notes: ""
bench_code: null
bench_result: null
bench_result_note: null
bench_revalidated: null
reading_time: "3.5-6 ms per query, measured 2026-09-15 open-circuit. Two queries per point, so ~10 ms a point plus settling - and see the note: the suite's own serial transport was costing 1010 ms of that until the same session"
resolution: "0.1 mA on the 3 A ceiling, 1 mA on the 30 A ceiling (current); 0.1 mV on 18 V, 10 mV on 120 V. From the specification table, not measured"
best_for: "illuminated solar cells above 3 A, where every SMU here clamps. Nothing else - it cannot source"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/multicomp_72_13200.py
model_ids: "['72-13200']"
max_voltage_v: 120
max_current_a: 30
voltage_ranges_n: 2
current_ranges_n: 2
power_envelope_n: 0
sweep_kind: software
nplc_min: null
nplc_max: null
high_z_off: false
ovp: false
remote_sense_control: false
compliance_trip: false
fleet: load
# --- end generated ---
---

# Multicomp Pro 72-13200

A 150 W DC electronic load, and the first driver in this suite that is
not a source-measure unit. It sits on
[`BaseLoad`](../architecture/devices.md) rather than `BaseSMU`, and is
registered in `KNOWN_LOADS`.

## Why it is here

The illuminated IV curve of a large silicon solar cell, whose
short-circuit current is around 10 A. The B2901A is the widest-range SMU
in this lab and stops at 3 A, so the current clamped at the first point.
A load is the right instrument for that measurement because the cell is
the source; nothing here needs to push.

## What this means for your data <!-- bench -->

**Two of the three numbers you want from a solar IV curve come out of
the fit, not the instrument.** The load measures the middle of the
curve well and both ends badly, so plan for that before the run rather
than reading it off the data afterwards:

- **Isc is not measured.** It is at V = 0, which is below the headroom
  floor. It has to be extrapolated from the low-voltage end of whatever
  the load could actually reach.
- **Voc is measured, but with the input off**, where the 150 kΩ input
  impedance leaves the cell essentially open-circuit. It is not a point
  on the swept curve.
- **The maximum power point is the part this instrument is good at** —
  the floor at 0.431 V sits below the knee, so the whole of the useful
  region is measurable. `:MEAS:POW?` is there, but it agreed with V x I
  to every digit at four separate currents, so treat it as computed
  rather than as an independent third reading.

**Check the front-panel ceiling before the run, because it sets your
noise floor and nothing in software can see it.** The current accuracy
carries a full-scale term of 0.045%, so the floor is 1.35 mA on the 3 A
ceiling and 13.5 mA on the 30 A one. On a 10 A cell that is 0.14% or
1.4% of Isc depending on a setting made with a keypad.

**A run will refuse anything below 0 V.** That is deliberate and it is
not the driver being unhelpful: reverse bias needs a source. Sweep the
reverse-bias part on an SMU and the high-current part here, and expect
two files rather than one.

## What it can and cannot measure

**It covers 0 V to Voc, and nothing either side.** That is the whole of
the power-generating quadrant and none of the rest:

| Region | Why |
|---|---|
| V < 0 (reverse bias) | the cell must be **driven**; a load cannot source |
| 0 ≤ V < 43.1 mΩ × I (includes Isc) | below the headroom floor — the pass element has nothing to regulate with. 0.431 V at 10 A, 0.216 V at 5 A |
| above the floor, below Voc | **this is the usable window**, and it contains the knee and the MPP |
| V > Voc | the cell must be driven again |

On a silicon cell with Voc near 0.65 V that window is about 0.22 V
wide. A sweep of −0.2 V to 0.8 V — the one this lab runs on an SMU —
is therefore mostly outside what this instrument can do, and the driver
refuses the parts it cannot reach rather than returning readings from a
region it never entered. `LIMITS` declares the quadrant, both sweep
endpoints are checked before a run, and `guard_operating_point()`
refuses below the headroom floor.

**Voc is recoverable, Isc is not.** With the input off, the specified
150 kΩ input impedance leaves an illuminated cell essentially at
open circuit, so `:MEAS:VOLT?` with the input off reads Voc directly.
There is no equivalent trick for Isc; it has to be extrapolated.

**The ceiling decides the floor.** The current accuracy is
±(0.05% of set + 0.045% of full scale), so the full-scale term puts the
floor at 1.35 mA on the 3 A ceiling and 13.5 mA on the 30 A one. A cell
whose Isc is a few milliamps cannot be measured here at all — use an
SMU.

The ceilings **are settable over the bus** — the manual says otherwise —
so `apply_ranges()` picks one from the run's own expectations rather
than leaving it to whoever last touched the keypad. It snaps to the two
documented ranges, because the specification states accuracy per range
and an intermediate ceiling's effect on the full-scale term is
unmeasured.

## What the manuals do not say

**No error queue.** There is no `:SYST:ERR?` or equivalent anywhere in
the command set; `:STATus?` returns the buzzer state and the baud rate
and says the rest is "to be determined". This removes the mechanism
every other driver here is verified with — on this instrument a wrong
header is ignored in silence. Readback stands in for it, and unusually
this instrument has a query for nearly every setting.

**No `*RST`.** Nothing resets anything, so
[fault 6](../faults/06-inherited-state.md) is structural rather than
avoidable. `reset()` disables the input and records the mode and
ceilings it found, so a session begins with the inherited state written
down instead of assumed.

**No minimum operating voltage — so it was measured.** Neither document
states one. **0.431 V at 10 A**, 2026-09-15, and the answer it gives is
the one that mattered: the maximum power point is reachable and the
short-circuit current is not.

**The command PDF is for a product family, not this model.** Its
examples answer `>150V` and `>300W` where this unit is 120 V and 150 W.
No figure in `LIMITS` comes from it.

## Never sent

`:FUNC SHORT` is in the command table and is unreachable from the
driver — the user manual describes it as making the tested equipment
output its maximum current, which is a deliberate short across the
sample. `:LIST` is declined for a different reason: it is a genuine
hardware stepper, but it steps current in whole-second dwells with no
measurement buffer, so the host would still poll for readings and would
no longer know which step each belonged to. `SWEEP_KIND` stays
`software`.

## Second bench session, 2026-09-15 (supply attached, 5 V / 10 A limit)

A bench supply in CV at 5 V with its limit at 10 A, on 1 m of 10 AWG
each way. Two phases: a low-current check of the measurement path, then
the headroom walk.

**The measurement path works, and the sign convention is right.** The
first discriminating measurement this driver has had — everything
before it was zero into an open circuit, which is true whether the
driver works or not. At 0.1, 0.2, 0.5 and 1.0 A the ammeter tracked the
commanded current to better than 1 mA, every reading came back
**negative** as the suite's convention requires, and the terminal
voltage drooped linearly with current.

**The loop resistance is 10.2 mOhm**, against 6.6 mOhm predicted for
the cable alone — so about 3.6 mOhm of terminal and contact resistance.
At 10 A that is 102 mV between the supply's display and the load's own
reading, and it sits *outside* the headroom measurement, which is taken
at the load's terminals.

**Headroom is a saturation resistance of 43.1 mOhm**, measured at two
currents a factor of two apart:

| current | floor | implied R |
|---|---|---|
| 9.998 A | 0.4310 V | 43.11 mΩ |
| 5.023 A | 0.2164 V | 43.08 mΩ |

Both sharp — 0.0 mV of spread across every setpoint below the floor,
four points at 10 A and five at 5 A. Predicting the 5 A floor from the
10 A one gave 0.2165 V against 0.2164 V measured, so there is **no
measurable fixed term**: once the pass element saturates it is simply a
resistance.

That is why the driver holds it as a resistance rather than a number,
which is the B2901A's sub-count lesson arriving from the other side of
the fleet: an absolute figure is right at one current and wrong at
every other, and this instrument is used across a 6:1 range of them.

**There are two floors and they cross at 2.32 A.** The 0.1 V CV
commanding limit is absolute; the headroom floor scales with current.
Below 2.32 A the commanding limit decides, above it the headroom does.
They are kept separate because the remedies differ — one limits what
can be asked for, the other what can be held.

For a silicon cell with Voc near 0.65 V:

| | |
|---|---|
| Isc, at V = 0 | **unreachable** |
| the floor, 0.431 V | the bottom of what can be measured |
| the knee and MPP, ~0.52 V | **reachable** |
| Voc, ~0.65 V | reachable, and also readable with the input off |

So the load measures the part of the curve that carries the maximum
power point, and Isc has to be extrapolated. That was the make-or-break
question and the answer is yes.

**The ranging change and the output-on guard, confirmed.** A 0.8 V span
lands on the 18 V ceiling and a 40 V span on 120 V; the current ceiling
follows the expected current the same way (30 A for a 10 A run, 3 A for
a 2 A one). So a solar sweep now measures on 18 V full scale — a 4.5 mV
accuracy floor rather than 30 mV, which on a 0.65 V Voc is 0.7% instead
of 4.6%.

The guard was tested without putting anything dangerous across the
terminals, by forcing an arbitrary 3 V ceiling — which this instrument
accepts, itself a finding from the first session — with the 5 V supply
attached. `output_on()` refused and the input stayed off; raising the
ceiling to 18 V let it through.

**Settling is 430 ms for a step down at 10 A**, and it is the floor
under any sweep's per-point delay — a 100-point CV sweep cannot run
much under a minute without recording the control loop rather than the
cell. The queries themselves take 4–6 ms, so this is the instrument,
not the bus.

**The first headroom walk was wrong, and the data said so.** A 350 ms
dwell produced three phantom floors — 0.80 V reading 0.8496, 0.60
reading 0.6169, but 0.50 reading 0.5005. A floor that comes and goes as
the setpoint descends is not a floor; those were readings taken
mid-slew. Re-running at 2 s per point gave the clean result above.

## First bench session, 2026-09-15 (open circuit, firmware V3.30)

Not a checkup — `smu_checkup.py` is SMU-shaped and there is no load
equivalent yet — but a probe session through `tools/scpi_console.py`
and direct `pyserial`. Five of the six open questions answered, and it
found a driver bug that would have invalidated every run.

**Connection.** COM6, USB-CDC (VID:PID `0416:5011`). It answers at every
baud and every line ending, so the front-panel baud setting is
irrelevant over USB. `*IDN?` is **not comma-delimited** — it returns a
sentence where every other instrument here returns four fields.

**The manual's `:FUNCtion` arguments are wrong, and the driver was
wrong with them.** The command table gives `VOLT|CURR|RES|POW|SHORT`
and its worked example is `:FUNCtion VOLT`. Neither works. The
arguments are **`CV` and `CC`** — the same vocabulary the query
answers with. `:FUNCtion VOLT` sent to an instrument in CC leaves it in
CC and reports nothing, because there is nothing to report with.

This is the fault this project's rule about asserting spellings exists
for. As first written the driver would have run every *voltage* sweep
as a constant-**current** sink: a complete, plausible set of readings
of an experiment nobody asked for, with no error anywhere. It was found
by a probe that alternated modes; the first attempt asked for CV while
the instrument was already in CV and read the unchanged value as
success, which is fault 19 committed live.

`set_source_function()` now reads the mode back and refuses on
disagreement. One query, ~5 ms, once per run — and on an instrument
with no error queue it is the only protection available.

**The CV setpoint floor is 0.1 V, and it clamps silently.** Asking for
0.05 V, 0.01 V or 0 V all leave `:VOLTage?` reading `0.1000V`. No
error. `:VOLTage:LOWer?` reports the same 0.1 V and is honest.

This is a **commanding** floor and is not the headroom floor — they are
separate mechanisms and the headroom one is still unmeasured. Whichever
is higher decides where a sweep can start. The driver refuses below it
rather than letting a sweep record several distinct requested levels at
one physical point.

**Zero is included.** A CV setpoint of 0 V is a short across the
terminals and this model will not hold one. To stop it sinking, disable
the input — on a load that is the real settle-to-zero path.

**The CC axis has no such floor.** 0.001 A and 0 A both land exactly,
and `:CURRent:LOWer?` reports 0. The floor is a CV-only property.

**`*RST` does nothing**, confirmed discriminatingly: a distinctive
setpoint went in first and was still there afterwards. The driver
correctly never sends it.

**The silence demonstrated.** `:SOURce:CURRent 9.999A` — the
2400-family spelling — was accepted and ignored, setpoint unchanged,
nothing said. That is the behaviour of every wrong header on this
instrument, shown rather than inferred from the manual's omission.

**`:INPut?` works and answered truthfully in both states**, which is
better than the GSM-20H10's `OUTP?`. Still only tested open-circuit,
where "ON" is cheap.

**Unit suffixes are mandatory on input.** `:CURRent 2.345` was ignored;
`:CURRent 2.345A` landed. Abbreviated headers (`:CURR`, `:VOLT`) work.

**Both ceilings are settable over the bus**, which the manual denies —
its command table marks `:CURRent:UPPer` and `:VOLTage:UPPer`
"Setup: no". They are writable, the unit suffix is mandatory here too
(`:CURRent:UPPer 3` is ignored), and the abbreviated `:CURR:UPP 3A`
works.

Confirmed from two directions rather than one: `:CURRent:UPPer?`
reports the new value, **and** an over-large setpoint then clamps to it
— asking for 10 A with a 3 A ceiling comes back 3 A. A query that
agrees with an independent consequence of the same setting is a query
that has been checked.

Intermediate ceilings are accepted (5 A and 15 A both land exactly),
but `apply_ranges()` snaps to the two documented ranges: the
specification states accuracy *per range*, and what an in-between
ceiling does to the full-scale term is unmeasured.

The CV floor does **not** track the voltage ceiling — 0.1 V on both
18 V and 120 V. It is absolute.

**A third non-discriminating probe, in the same session.** The first
attempt at the ceiling setters tried `:CURR:UPP 3A` while the ceiling
was already 3 A and read "unchanged" as "ignored". Forcing the opposite
value first showed it works. Three times in one session the same
mistake: fault 19 is not a thing that happens to other people.

**A finding about this suite, not the instrument.** Every query took
1010 ms through `SerialTransport` and 4–6 ms read directly. The cause
was `ser.read(4096)` waiting out its timeout for a twelve-byte reply.
Fixed; it affects every serial instrument here, including the
temperature stage.

## Open questions

In priority order. The first still changes the driver.

In priority order. The first two change the driver.

1. **A CV sweep lands on the 120 V ceiling, and that costs 30 mV.**
   Not a bug — a consequence of the plan shape. `RangePlan.for_sourcing`
   sets `measure_voltage=AUTO` because on an SMU the sourced voltage is
   read back through the source and must not be given a range; `widest()`
   then lets AUTO win the shared knob. On this instrument that knob is
   the CV ceiling, so a 0.1–0.8 V sweep runs at 120 V full scale: a
   30 mV accuracy floor where the 18 V ceiling would give 4.5 mV.
   On a 0.65 V Voc that is **4.6% against 0.7%**.

   Left as it is deliberately. The widest-range landing is a decided
   design, and the safety argument runs the same way here: an 18 V
   ceiling with something other than a cell attached would overrange the
   measurement. Changing it is a decision about what this rig is allowed
   to assume, not a fix.

1. **Is `measure_power()` independent, or computed?** It agreed with
   V x I to every digit displayed at all four Phase A currents, which
   is consistent with the instrument computing it. An earlier note here
   claimed it "reads power directly rather than by multiplication" —
   that was inference, and the bench does not support it. **Low
   priority**: nothing depends on it, and power is recoverable from the
   V and I columns in the CSV.

Note the trap in running these: `tools/scpi_console.py` checks the error
queue after every write, and this instrument has none — so every command
will look accepted. Nothing in the console's output is evidence a
command landed; read the setting back instead.
