---
type: instrument
title: "Aim-TTi TSX1820P"
driver_class: AimTTiTSX1820P
idn: "THURLBY-THANDAR,TSX1820P,0,1.20"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: 2026-10-08
bench_notes: "2026-10-08, second run of the day, at 5785baca8f98, GPIB address 12, nothing attached: 54 pass, 2 warn, 0 fail, 2 skip. The two warnings are the trip readback, which nobody has checked against a trip set by hand; the two skips need a load. The setpoint readbacks now pass. tools/bench_supply.py followed and ran to the end, resistor and deliberate trip included. The first run that morning, at a1eb7b66680c, is written up in the note as well"
bench_code: "9fe7bfdf67ac"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "about 50 to 110 ms for a pair of readings, measured twice on 2026-10-08 with the output on and nothing attached. One query takes 22 to 60 ms"
resolution: "10 mV and 10 mA, for setting and for readback. Measured 2026-10-08: an off-grid voltage lands on the nearest step, an off-grid current on the step below"
best_for: "holding a rail or driving a heater, up to 18 V and 20 A - an auxiliary, not a measuring instrument"
connection: "GPIB (GPIB-USB adapter)"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/aimtti_tsx_p.py
model_ids: "['TSX1820P']"
max_voltage_v: 18.15
max_current_a: 20.2
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

# Aim-TTi TSX1820P

An 18 V, 20 A bench power supply. It is the same instrument as the
[TSX3510P](aimtti-tsx3510p.md) with the output traded the other way —
half the voltage, twice the current — and it shares that model's driver
file, command set and manual. That note explains the design. **This is
the unit that has been on a bench**, so the measurements are here.

## Identity and envelope

`THURLBY-THANDAR,TSX1820P,0,1.20`, read off the unit on 2026-10-08:
firmware 1.20, and a literal `0` where a serial number would be, as the
manual says. `MODEL_IDS` matches on `TSX1820P` alone, and
`tests/test_tsx_p.py` checks that each model's identity resolves to its
own class: a 1820 driven by the 3510's class would be allowed 35 V on an
18 V output and refused everything above 10 A.

| | TSX1820P | TSX3510P |
|---|---|---|
| Output voltage | 0 V to 18.15 V | 0 V to 35.3 V |
| Output current | 0.01 A to 20.2 A | 0.01 A to 10.2 A |
| Over-voltage trip | 1 V to 25 V | 1 V to 40 V |

Both ends of this model's voltage and current ranges were confirmed at
the bench: `V 18.15` and `I 20.2` land, and one step above each is
refused with errors 100 and 101.

## What this means for your data

As for the [TSX3510P](aimtti-tsx3510p.md#what-this-means-for-your-data),
with one thing made worse by the higher current: **lead resistance.**
The manual's own example is that 10 mΩ of lead drops 0.2 V at 20 A,
which on an 18 V output is more than one percent and twenty steps of
the readback. Above a few amps, take the rear links off and wire the
sense terminals to the load — and note that software cannot see which
way they are, so the run records the rule rather than the wiring.

## Reset defaults that had to be overridden

The same one as the 3510: the over-voltage trip, which `*RST` leaves at
its maximum. Here `reset()` sends `OVP 25`. Confirmed: after a reset the
unit reports `V 0.00`, `I 0.01` and `OVP 25.00`.

## Decisions and deviations

None of its own. The class differs from the 3510's in `MODEL_IDS`,
`LIMITS` and `OVP_RANGE_V` and in nothing else.

## Bench session, 2026-10-08 (firmware 1.20, GPIB address 12)

The checkup, then `tools/bench_supply.py`: the output off, the output on
with nothing attached, and a 3.3 Ω 11 W resistor at 0.91 A. Code at
`a1eb7b66680c`.

**The checkup passed**: 52 pass, 4 warn, 0 fail, 2 skip. The warnings are
readbacks that agreed and had never been verified. The skips need a
load.

**The error path works, and is numbered as the manual says.** Each of
these left the setting where it was:

| Sent | `*ESR?` | `EER?` | |
|---|---|---|---|
| `I 0` | 16 | 103 | below the floor |
| `I 0.009` | 16 | 103 | one step under the floor — it is not rounded up to 0.01 |
| `V -1` | 16 | 102 | |
| `V 18.16` | 16 | 100 | one step above the top |
| `I 20.21` | 16 | 101 | |
| `OVP 0.99` | 16 | 107 | |
| `XYZZY` | 32 | 0 | a command error, once |
| `OVP 25.01` | 0 | 0 | **accepted, and lands as 25.00** — the one end that is not refused |

**Voltage rounds to the nearest step; current rounds down.** `V 1.004`
lands as 1.00 and `V 1.005` and `V 1.006` as 1.01. `I 0.104` and
`I 0.106` both land as 0.10. The manual says "rounded up" for both. On
this model `I?` answers to two decimals, `I 0.05`, where the manual's
example shows three.

**The limit register reports the mode it is in, for as long as it is in
it.** This was the question the compliance column depended on. In
current limit, four reads two seconds apart gave `1, 1, 1, 1`; in
constant voltage, `2, 2, 2`. So a bit that has been read comes straight
back while the condition holds. The first read after a change of mode
gives `3` — the mode it left and the mode it entered — and the reads
after that the new mode alone:

| | `LSR?`, successive reads | the driver said |
|---|---|---|
| output on, nothing attached | 2, 2, 2 | CV, CV, CV |
| in current limit | 1, 1, 1, 1 | clamped, every time |
| voltage lowered, limit released | 3, 2, 2, 2 | clamped once, then not |
| limit forced again | 3, 1, 1, 1 | clamped, every time |
| the same, read as a current source | 1, 1 then 3, 2 | not clamped, then clamped |

There **is** an event when the output comes on, so a run that never
leaves constant voltage records "not clamped" rather than a blank. And
the flush before `OP 1` works: the stale `3` it read was not seen again.

One consequence for a trace: a step up charges the output capacitor
through the current setting, and the register says so. 1 V to 10 V with
a 50 mA setting read `3`. A run whose first sample follows a large
turn-on step can therefore record that sample as clamped, truthfully.

**The meters agree with what was set.** 1 V read 1.00 V; 10 V read
9.98 V; 5 V read 4.99 V; 3 V read 2.99 V. In current limit at a 0.91 A
setting into 3.3 Ω it read 3.05 V and 0.93 A, positive, and `POWER?`
gave 2.8 W, which is their product.

**A reading is much faster than the manual suggests.** 22 to 60 ms a
query and 53 to 106 ms for the pair, against the manual's 500 ms. What
is slow is the *output*, and the readback follows it:

| Step | Time for the reading to settle |
|---|---|
| 1 V to 10 V, nothing attached, 50 mA setting | about 1.3 s, in current limit on the way |
| 10 V to 1 V, nothing attached | about 2.6 s |
| 6 V to 1.5 V into 3.3 Ω | about 1 s |
| `VV 5` from 1 V, the instrument's own settle check | returned settled after 1.0 s |
| output off from 5 V, nothing attached | about 2 s, and it then reads **0.20 V**, not zero |

**A setting made by hand reads back over the bus.** 7.77 V and 1.23 A
set at the front panel came back as `V 7.77` and `I 1.23`. So `V?` and
`I?` read the instrument rather than repeating the last thing they were
sent, which is what the checkup's "unverified" warnings were waiting
for. `SETPOINT_READBACK_TRUSTED` is now `True` on this model, and its
two setpoint rows will read as a pass. The trip's readback was only ever
compared with what the software had just sent, and stays unverified.

**What a session puts into the driver makes that session stale.** The
flag above, the measured settling time and the corrected comments went
into `drivers/aimtti_tsx_p.py`, and a checkup describes the bytes it
ran against. The unit was run again that afternoon and passed; what
*that* run found went into the driver too. So `bench_code` above is the
fingerprint of the code that was last on the bench, and this instrument
reads as owed a re-check whenever the file has moved on since. That is
the right way round: the alternative is knowing these things and not
writing them down.

**Meter damping**: `IO?` read 0.93 A five times with it off, and 0.92,
0.92, 0.93, 0.93, 0.93 with it on. Too small to call on a steady load.

**The burst check passed** 10 of 10 after bursts of 6 writes, with no
pause declared. The reply after a burst took 310 to 325 ms.

## Second session, 2026-10-08 (code at `5785baca8f98`)

Run to answer the two things the first one left open. The checkup
passed again - 54 pass, 2 warn, 0 fail, 2 skip, the setpoint readbacks
now among the passes - and everything measured the first time came out
the same: the range ends, the rounding, the limit register's
`1, 1, 1, 1` and `3, 2, 2, 2`, 0.93 A into the 3.3 Ω resistor.

**The query error is the bus going quiet after a query.** The first
session saw `*ESR?` 4 and `QER?` 3, "unterminated", twice, with every
query answered. This one read the registers after every exchange, and
the pattern is exact:

| | Register reads | With the query error |
|---|---|---|
| a second or more of silence after a reply | 16 | 16 |
| at most 0.31 s of silence after a reply | 74 | 0 |

Thirty queries sent one after another raised none. A query followed by
a one-second pause raised one every time. A *command* followed by a
pause - 27 s, at one point - raised none. With the first session's
twenty reads and the 3510's ninety, that is 34 of 34 on one side and
none of 166 on the other.

So it is not a fault and not intermittent: it is what this instrument
does when it has answered and then hears nothing. That describes every
sample of a slow trace, and a run ends by asking for errors, so every
such run would have closed with an "uncertain shutdown". The driver now
recognises query error 3, counts it and does not report it; the other
two query errors are reported as before. The checkup has a row that
pauses after a reading on purpose and requires a clean answer.

**The trip silences it only while the cause lasts.** With the trip at
5 V and 6 V asked for, the displays read 4.50 V and 0.05 A - the output
climbing back through its current setting and tripping again, with
`TRIP` shown in between, as the first session saw. Nothing was asked
while it did that. With the setting put back to 3 V it answered at
once:

| | |
|---|---|
| `LSR?` | 7 - the trip bit, and both limit bits from the cycling |
| `LSR?` again | 0 - the trip is reported once, and the output is off |
| `*ESR?`, `EER?` | 16, 118 - "output stage has tripped" |
| `VO?` | 0.20 V - off, and it stayed off |
| after `OP 0`, `*CLS`, `OP 1` at 1 V | 1.00 V - it comes back when switched on again |

The driver read the register second in that sequence and so was told
nothing, which is the point of latching it: whoever reads first gets
the trip, and nobody after.

## Open questions

Small ones. Neither changes what the driver sends.

1. **How much does meter damping smooth?** It does do something to the
   bus reading: `IO?` dropped one step for about a second after it was
   switched on, in both sessions. A load that draws in pulses would
   show how much.
2. **The top of the trip range is not refused.** `OVP 25.01` lands as
   25.00 with no error, where every other range end gives one. The
   driver refuses it before the wire regardless.
3. **The trip's readback has never been checked by hand**, so its two
   checkup rows stay warnings. Set a trip at the front panel and read
   `OVP?`.
