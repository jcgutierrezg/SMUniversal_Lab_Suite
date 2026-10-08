---
type: instrument
title: "Aim-TTi TSX3510P"
driver_class: AimTTiTSX3510P
idn: null
idn_confirmed: false
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: false
last_bench: null
bench_notes: "not yet run. The driver was written from the manual on 2026-10-08, before the unit had been asked anything"
bench_code: null
bench_result: null
bench_result_note: null
bench_revalidated: null
reading_time: null
resolution: "10 mV and 10 mA, for setting and for readback. From the specification, not measured"
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

**Nothing here has been confirmed at a bench.** The driver was written
from the *TSX-P Instruction Manual*, Issue 18, with no script behind it.
Every statement below is the manual's, and the last section is the list
of things the first session has to settle.

## Why it is here

As an auxiliary: something to hold a rail, bias an illumination source
or drive a heater while an SMU does the measuring. It is not a
substitute for one, and the suite does not offer it as one — see
*By invitation* below.

## Identity and envelope

`*IDN?` has **not been read off the unit**, so `idn` is `null`. The
manual gives the form `<name>,<model>P,0,<version>`, with a literal `0`
where a serial number would be, and does not print the name field.
`MODEL_IDS` matches on `TSX3510P` alone.

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

The command set, registers and reset table are transcribed in
[TSX-P command summary](../reference/manuals/tsx-p-commands.md).

## What this means for your data

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
combined query, the meters update at 4 Hz, and the manual gives 500 ms
as what reading the output back can cost. A sample is two queries. Ask
for a sampling interval of a second or more and read the `read_s`
column to see what each one actually took.

**The compliance column means something different in each mode.**
Sourcing voltage, *clamped* is the supply in constant current. Sourcing
current, it is the supply back in constant voltage because the load
would not take the current asked for — the trace is then of the voltage
ceiling, not of the sample. And it is built from *events*: see the
first open question.

**Turning the output off does not disconnect anything.** The switch is
electronic and a capacitor stays across the terminals. A short on a
current-limited output still produces a pulse the current setting does
not govern.

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

## Bench findings

None yet.

## Open questions

What the first bench session has to answer, in the order that changes
the most. One command per unit runs the checkup and then asks every
question below, prompting for a power resistor when it needs one:

```powershell
uv run tools/bench_supply.py --address GPIB0::11::INSTR
```

The address is the factory default; read the real one off the front
panel with the BAUD/ADDR key. It writes four files into `checkups/` -
the checkup's report and its own, each as Markdown and JSON. See
[the tools note](../architecture/tools.md) for what it does and in what
order.

1. **What is `*IDN?`?** Copy the reply into `idn` on both notes. Until
   then `MODEL_IDS` is a reading of the manual.
2. **Does `LSR?` report a limit once, or for as long as it holds?** The
   compliance column depends on it. Put a power resistor across the
   output so the supply sits in constant current, and read `LSR?` three
   times a few seconds apart. `1, 1, 1` means the bit is reasserted;
   `1, 0, 0` means it is an edge. The driver is right both ways, but
   only the first makes the answer independent of polling.
3. **Is there a limit event when the output comes on?** Read `LSR?`
   straight after `OP 1` with nothing attached. If it is `0`, a run
   that never leaves constant voltage records a blank compliance
   column, and the driver should start from constant voltage rather
   than from "cannot say".
4. **Does `I 0` come back as error 103?** The checkup asks. If the
   number differs it reports a warning; if nothing comes back, no clean
   error register on this instrument means anything yet.
5. **How long does a reading take?** The checkup times five. That
   figure goes in `reading_time` and sets the shortest sampling
   interval worth asking for.
6. **Does `DAMPING` change what `IO?` returns?** The manual describes
   it as damping the meter. Compare `IO?` with it on and off on a load
   that draws in pulses.
7. **Where does the instrument actually stop?** `V 35.3` should land
   and `V 35.31` should give error 100; likewise `I 10.2`. The envelope
   in `LIMITS` is the specification's.
8. **Does an out-of-grid level round or round up?** Send `V 1.004` and
   `V 1.006` and read `V?`. This manual says a number is "rounded up";
   the newer generation's says "rounded".
9. **How does a step down behave with little attached?** The supply
   cannot sink, so this is whatever the load allows. Step 10 V to 1 V
   open-circuit and watch `VO?`.

When the checkup has passed, copy `last_bench`, `bench_code` and
`bench_result` from its report header into both notes and rebuild. The
setpoint readbacks stay `unverified` until one has been checked against
a value set at the front panel.
