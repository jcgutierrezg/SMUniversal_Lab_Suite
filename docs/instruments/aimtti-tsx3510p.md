---
type: instrument
title: "Aim-TTi TSX3510P"
driver_class: AimTTiTSX3510P
idn: "THURLBY-THANDAR,TSX3510P,0,1.20"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: 2026-10-08
bench_notes: "2026-10-08 first session at 5785baca8f98, GPIB address 11, nothing attached: 52 pass, 4 warn, 0 fail, 2 skip. The four warnings are readbacks that agreed and had not been verified; the two setpoint ones have been since, by hand. A current of zero came back as error 103, and the burst check passed 10 of 10. tools/bench_supply.py followed and ran to the end, resistor and deliberate trip included. The checkup passed, but the unit is out of calibration: 10 V set read 10.39 V and a 0.91 A setting delivered 0.80 A - see the note"
bench_code: "9fe7bfdf67ac"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "48 to 54 ms for a pair of readings, measured 2026-10-08 with the output on and nothing attached"
resolution: "10 mV and 10 mA, for setting and for readback. Measured 2026-10-08: an off-grid voltage lands on the nearest step, an off-grid current on the step below"
best_for: "holding a rail or driving a heater, up to 35 V and 10 A - an auxiliary, not a measuring instrument"
connection: "GPIB (GPIB-USB adapter)"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/aimtti_tsx_p.py
model_ids: "['TSX3510P']"
max_voltage_v: 35.3
max_current_a: 10.2
voltage_ranges_n: 1
current_ranges_n: 1
power_envelope_n: 0
sweep_kind: software
nplc_min: null
nplc_max: null
high_z_off: false
ovp: false
ovp_trip: true
remote_sense_control: false
compliance_trip: true
fleet: supply
# --- end generated ---
---

# Aim-TTi TSX3510P

A 35 V, 10 A bench power supply, and with the
[TSX1820P](aimtti-tsx1820p.md) the first driver in this suite that is
neither a source-measure unit nor an electronic load. It sits on
[`BaseSupply`](../architecture/devices.md) and is registered in
`KNOWN_SUPPLIES`. The two models share one driver file,
`drivers/aimtti_tsx_p.py`; this note covers what they have in common and
the other records only what differs.

**Both units have been on a bench**, on 2026-10-08. The driver was
written from the *TSX-P Instruction Manual*, Issue 18, with no script
behind it, and the sessions found it right about the commands and found
the manual wrong in several places. This note has this unit's
measurements; the [TSX1820P's](aimtti-tsx1820p.md) has the fuller
account of what the two have in common, because it went first.

**This unit is out of calibration.** Its checkup passed - the driver
and the instrument agree on every command - but what it puts out is not
what it is set to. See *What this means for your data*.

## Why it is here

As an auxiliary: something to hold a rail, bias an illumination source
or drive a heater while an SMU does the measuring. It is not a
substitute for one, and the suite does not offer it as one — see
*By invitation* below.

## Identity and envelope

`THURLBY-THANDAR,TSX3510P,0,1.20`, read off the unit on 2026-10-08:
firmware 1.20, the same as the 1820, and a literal `0` where a serial
number would be. `MODEL_IDS` matches on `TSX3510P` alone.

| | |
|---|---|
| Output voltage | 0 V to 35.3 V |
| Output current | 0.01 A to 10.2 A — **the current setting does not reach zero** |
| Power | the whole rectangle, about 360 W; no derating to declare |
| Quadrant | one: positive voltage, current out. It cannot sink |
| Setting and readback step | 10 mV, 10 mA |
| Readback accuracy | ±(0.2% + 1 digit) on voltage, ±(0.5% + 1 digit) on current |
| Over-voltage trip | 1 V to 40 V, a continuous value |
| Sensing | 2-wire with the rear links fitted, 4-wire with them removed |

Both ends of the voltage and current ranges were confirmed at the
bench: `V 35.3` and `I 10.2` land, and one step above each is refused
with errors 100 and 101.

The command set, registers and reset table are transcribed in
[TSX-P command summary](../reference/manuals/tsx-p-commands.md), with
what the bench corrected.

## What this means for your data

**On this unit, what you set is not what you get.** Measured on
2026-10-08, by the instrument's own meters, beside the 1820 doing the
same thing an hour earlier:

| Set | This unit read | The 1820 read |
|---|---|---|
| 1 V | 1.02 V | 1.00 V |
| 5 V | 5.19 V | 4.99 V |
| 10 V | 10.39 V | 9.98 V |
| 1.5 V into 3.3 Ω | 1.55 V | 1.50 V |
| 0.91 A current setting into 3.3 Ω | 0.80 A, 2.60 V | 0.93 A, 3.06 V |

That is about 4% on voltage and 12% on current, against a specification
of 0.1% and 0.2%. The instrument agrees it is wrong: asked to set 5 V
and confirm it, its own settle check gave up after five seconds, where
the 1820 confirmed in one.

Which half is out - the setting or the meter - needs an outside
voltmeter. The evidence here leans toward the settings: in current
limit the voltage and current it read give 3.25 Ω for a resistor the
1820 measured as 3.29 Ω, so the two meters agree with each other. If
that holds, the readings in a saved file are right and the level typed
into the window is not. **Until it has been checked with a multimeter
or recalibrated, treat the level you asked for as approximate and the
recorded readings as the measurement** - and remember that a current
limit set on this unit is about a tenth lower than it says.

**The numbers are coarse.** A reading moves in steps of 10 mV and
10 mA, and the current accuracy carries a full digit on top of 0.5%. At
100 mA that is ±10 mA before the percentage — ten percent. This is the
right instrument for "is the heater drawing about 2 A" and the wrong
one for a resistance.

**The level in the file is what was read back, not what was asked
for.** The full-precision level is sent and the instrument rounds it to
its grid ([fault 4](../faults/04-rounded-source-levels.md)). Every
sample records the voltmeter and ammeter readings.

**The two readings in a row are not simultaneous.** There is no
combined query, so a sample is two. On the 1820 the pair took 53 to
106 ms - far quicker than the 500 ms the manual warns of - and the
`read_s` column records what each one took.

**The output is slower than the readings.** On the 1820 a 9 V step up
took about 1.3 s to settle with a 50 mA current setting, and a 9 V step
down with nothing attached about 2.6 s, because the supply cannot sink.
A trace sampled faster than that shows the output moving, which is
real, but it is the supply and not the sample.

**The compliance column means something different in each mode.**
Sourcing voltage, *clamped* is the supply in constant current. Sourcing
current, it is the supply back in constant voltage because the load
would not take the current asked for — the trace is then of the voltage
ceiling, not of the sample. On the 1820 the register behind it reports
the present mode on every read, so the column is not left blank on a
run that never crosses over. The first sample after a large turn-on
step can read *clamped*: charging the output capacitor goes through
current limit.

**Turning the output off does not disconnect anything.** The switch is
electronic and a capacitor stays across the terminals. A short on a
current-limited output still produces a pulse the current setting does
not govern. On the 1820, switched off from 5 V with nothing attached,
the terminals took about 2 s to fall and then read 0.20 V.

**A pause between samples used to end a run with an "uncertain
shutdown" warning.** Both units report the bus going quiet after a
query as an error. The driver recognises it now; the account is in the
[1820's second session](aimtti-tsx1820p.md#second-session-2026-10-08-code-at-5785baca8f98).

## Reset defaults that had to be overridden

One, and for an unusual reason. `*RST` sets the over-voltage trip to
its **maximum**, which is the least protective value the setting has.
`reset()` sends `OVP 40` after it anyway, so the trip appears in the
trace as something the driver chose rather than as an absence
([fault 17](../faults/17-unsent-defaults.md)). Meter damping is sent
the same way.

The larger fact is in the other column of the manual's table:
**settings survive power-off.** Voltage, current and trip are held in
non-volatile memory, so a unit comes up with whatever the last person
set. Only the output state is reliably off.
[Fault 6](../faults/06-inherited-state.md) is the default condition
here, and the reset at connect is what removes it.

## Decisions and deviations

**A third fleet.** A supply is not an SMU — no source function to
select, no ranging plan, no bottom count worth measuring — and not a
load, whose protections are trips. `BaseSupply` is a sibling of both on
`BaseInstrument`, and nothing in `base_instrument.py`, `base_smu.py` or
`base_load.py` changed to make room for it.

**The level and the compliance are one knob each.** `set_voltage_level`
and `set_voltage_limit` both send `V`; `set_current_level` and
`set_current_limit` both send `I`. Which is regulating is the load's
decision. `set_source_function()` sends nothing — there is no such
command — and only records which of the two the caller means by
"level", so that *clamped* can be read the right way round.

**By invitation.** On its declarations alone a supply would be accepted
by every experiment: it sources, and it has a compliance. Van der Pauw
would then ask it for 100 µA. So `BaseSupply` declares a named caveat,
`power_supply_grade`, and an experiment's role takes this instrument
only where its `ROLE_ACCEPTS` lists that name. **Fixed sourcing vs time
is the only window that does.** Every other window identifies the
supply correctly and refuses it at Connect, with the caveat's own text
as the reason.

**The error path.** There is no `SYST:ERR?`. `read_error()` is built
from `*ESR?`, `EER?` and `QER?`. An execution error comes back under
the instrument's own number; the three conditions it reports only as a
bit — command error, verify time-out, query error — are filed under the
negative of the bit (−32, −8, −4), so they cannot be mistaken for
something the instrument said. Because a decoder reading the wrong
register would report "no error" for ever, the checkup first sends
`I 0` past the driver's guard and requires error 103 back.

**Guards before the wire.** A negative level, a current below 10 mA
(zero included), a level above the range and a trip outside its window
are refused by the driver, at the gate and again in the setter. The
instrument would refuse them too — into a one-deep register, mid-run.

**The over-voltage trip is not offered by the windows.** They read a
menu, `OVP_CHOICES`, and this is a continuous value; an invented ladder
would put a default in a dropdown that trips the output the first time
a level went above it. `set_overvoltage_trip()` sets it from code, and
the generated instrument table says which of the two is true.

## Never sent

| Command | Why |
|---|---|
| `INCV`, `DECV`, `INCI`, `DECI`, `DELTAV`, `DELTAI` | a relative step that reaches the end of the range stops there with no error, so the level is no longer known |
| `*SAV`, `*RCL` | a recall restores the stored output state, so it can energise whatever is attached |
| `*LRN?`, `LRN`, `STO` | binary blocks, GPIB only, same hazard |
| `BUZZER`, `BUZZ` | — |
| `*SRE`, `*ESE`, `LSE`, `*PRE` | they arm a service request, and nothing here listens for one |
| the RS-232 daisy-chain control codes | a unit on a serial cable is driven as an ordinary port |

## Bench session, 2026-10-08 (firmware 1.20, GPIB address 11)

The checkup, then `tools/bench_supply.py` through to the end: the
output off, on with nothing attached, a 3.3 Ω 11 W resistor at a 0.91 A
setting, a value set by hand, and a deliberate trip. Code at
`5785baca8f98`.

**The checkup passed**: 52 pass, 4 warn, 0 fail, 2 skip.

**In every way that is about the commands, it is the 1820.** The same
identity form and firmware; errors 100, 101, 102, 103 and 107 for the
same refusals; `OVP 40.01` accepted and landing as 40.00; voltage
rounding to the nearest step and current rounding down; the limit
register reading `2, 2, 2` in constant voltage, `1, 1, 1, 1` in current
limit and `3` once after each change; a burst check of 10 out of 10. A
pair of readings took 48 to 54 ms. The detail of each is in the
[1820's note](aimtti-tsx1820p.md#bench-session-2026-10-08-firmware-120-gpib-address-12).

**The query error behaves identically**: all 16 register reads that
followed a second of silence after a reply showed it, and none of the
74 that did not. See the
[1820's second session](aimtti-tsx1820p.md#second-session-2026-10-08-code-at-5785baca8f98).

**So does the trip.** The displays went to 0.22 V and then to 4.50 V
and 0.05 A, the output climbing back and tripping again. With the
setting back under the trip it answered at once: `LSR?` 7 then 0,
`EER?` 118, 0.22 V at the terminals, and 1.03 V again after being
switched off and on.

**A setting made by hand reads back over the bus**: 7.77 V and 1.23 A
came back as `V 7.77` and `I 1.23`. That says the setpoint queries read
the instrument. It says nothing about whether the output is at the
setting, which on this unit it is not.

**Where it differs from the 1820, it is the calibration**, tabulated
under *What this means for your data*. Two smaller things go with it.
The verified set, `VV 5`, returned a time-out after 5.5 s. And the trip
does not sit on the output's 10 mV grid: `OVP 20.5` read back as 20.40.

**Output movement**, for comparison with the 1820's table: 1 V to 10 V
with nothing attached and a 50 mA setting settled in about 1 s; 10 V
to 1 V with nothing attached took about 3 s; switched off from 5 V it
took about 2 s and then read 0.22 V.

## Open questions

1. **Is it the settings or the meters that are out?** Put a multimeter
   across the output at 10 V with nothing attached. If it reads 10.39 V
   the setting is high and the meter is right, which is what the
   resistor test suggests. Either way the unit wants recalibrating; the
   manual's service guide has the procedure, and none of it is
   reachable from the bus commands this driver uses.
2. **Is the trip's grid really coarser than the output's?** `OVP 20.5`
   came back as 20.40. One reading, on a unit whose other settings are
   out, so it may be calibration rather than resolution.
3. **How much does meter damping smooth?** As on the 1820, `IO?`
   dropped a step for about a second after it was switched on.
4. **The trip's readback has never been checked by hand.** Set a trip
   at the front panel and read `OVP?`.

The driver file has changed since this session, to carry what it found,
so this unit reads as owed a re-check. The plain checkup is enough:

```powershell
uv run tools/smu_checkup.py --address GPIB0::11::INSTR --trace
```
