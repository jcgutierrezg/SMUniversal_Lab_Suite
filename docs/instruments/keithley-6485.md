---
type: instrument
title: "Keithley 6485"
driver_class: Keithley6485
idn: null
idn_confirmed: false
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: false
last_bench: null
bench_notes: null
bench_code: null
bench_result: null
bench_result_note: null
bench_revalidated: null
reading_time: null
resolution: "5.5 digits; 10 fA on the 2 nA range (manual)"
best_for: "nothing yet - a driver only, refused by every window until a role for a picoammeter is decided"
connection: "GPIB (factory address 14) or RS-232 - not yet known for this lab's unit"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keithley_6485.py
model_ids: "['MODEL 6485']"
max_voltage_v: 220
max_current_a: 0.021
voltage_ranges_n: 0
current_ranges_n: 8
power_envelope_n: 0
sweep_kind: software
nplc_min: 0.01
nplc_max: 5
high_z_off: false
ovp: false
ovp_trip: false
remote_sense_control: false
compliance_trip: false
fleet: meter
# --- end generated ---
---

# Keithley 6485

A 5½-digit picoammeter: one BNC input, current only, from 20 fA to
21 mA on eight ranges. It has no voltage source and no voltmeter. It
sets nothing.

That is what puts it in the **meter** fleet beside the
[34401A](keysight-34401a.md), and not in the SMU fleet with the
[487](keithley-487.md) and the [B2987A](keysight-b2987a.md). Those two
are picoammeters as well, but each has a voltage source beside its
ammeter and answers every question of the voltage half of the SMU
contract. The 6485 answers none of them. See
[A meter sets nothing](../architecture/devices.md#a-meter-sets-nothing).

**Driver only, for now (decided 2026-11-19).** Every experiment refuses
it at Connect, with the meter's own reason. The role a picoammeter is
for - in series with a source, reading the current far below what an
SMU resolves - needs an experiment that drives a source and a meter
together, which none does yet, and is its own discussion.

Joining as a current meter made `BaseMeter` read current as well as
voltage: a pair of range methods, `set_voltage_range()` and
`set_current_range()`, and a neutral layer the checkup uses so it does
not care which quantity a meter reads. That changed `base_meter.py`, so
the 34401A reads stale until its next checkup.

Written from the *Model 6485 Picoammeter Instruction Manual* (2001)
before the unit had been asked anything. The command and reset tables
it was written from are in
[6485 command summary](../reference/manuals/6485-commands.md).

## Identity and envelope

**`*IDN?` is answered, so it is auto-detected.** The manual gives
`KEITHLEY INSTRUMENTS INC.,MODEL 6485,<serial>,<firmware>`. `MODEL_IDS`
matches on `MODEL 6485`, which no other reply contains - the 6487, a
6485 with a voltage source, says `MODEL 6487`. The real reply goes in
`idn` above at the first checkup.

**The GPIB language has to be SCPI** (or 488.1, which still takes SCPI
commands). The third choice, DDC, emulates the old Model 485, and in it
`*IDN?` is never answered, so Connect latches the link. If Connect
hangs, check *COMM → CONFIG* on the front panel first. Changing the
language resets the instrument. RS-232 is SCPI only.

GPIB address 14 from the factory. Only one of GPIB and RS-232 is
enabled at a time, chosen in the COMM menu.

| | |
|---|---|
| Current ranges | 2 nA, 20 nA, 200 nA, 2 µA, 20 µA, 200 µA, 2 mA, 20 mA; 5% over-range |
| Resolution | 10 fA on 2 nA, a decade coarser per range |
| Accuracy (1 year) | 0.4% + 400 fA on 2 nA; 0.1% + 1 µA on 20 mA |
| Integration time | 0.01 to 5 power-line cycles at 50 Hz (6 at 60 Hz), continuous |
| Voltage burden | under 200 µV, under 1 mV on 20 mA |
| Input limits | 220 V peak, 21 mA; input LO within 42 V of chassis |

`LIMITS` holds the input's ratings, not a source envelope: a meter has
none.

## What this means for your data

Nothing yet, because no window will take it. When a role arrives, these
are the facts it will have to carry:

- **Zero check makes every reading look fine.** With zero check on, the
  input is shunted to low inside the meter and every reading is the
  meter's own offset - a few femtoamps, not an error. `*RST` leaves it
  **on**. `reset()` turns it off as its last command and the checkup
  reads it back. Nothing in the data can tell a shunted input from an
  open one.
- **Zero check goes back on at the end.** The manual says to leave it on
  while connecting or disconnecting the input, so disconnecting in the
  app, or the end of a checkup, turns it on. Switching it either way
  puts a short transient on the input through an internal resistance:
  11 MΩ on the nA ranges, down to 500 Ω on the mA ranges.
- **Autozero triples the reading time.** It is on by default, and the
  manual says to switch it off only briefly, because the zero and gain
  references drift without it.
- **The source in series has to stay under about 20 mA.** 21 mA or
  220 V peak damages the input. On the 2 mA and 20 mA ranges, more than
  60 V across the input switches it from a current limit to a 1-3 MΩ
  input (OVRVOLT on the display). Whatever role pairs it with a source
  has to set that source's compliance accordingly.

## Reset defaults that had to be overridden

`*RST` leaves zero check **on**. `reset()` sends `SYST:ZCH OFF` as its
**last** command, after everything that shapes a reading.

`FORM:ELEM READ` is sent so `READ?` answers one number. The manual's
reset table says all four elements (reading, units, timestamp, status)
are the default, which would put a timestamp where the reading should
be.

Every other reset default is sent explicitly too, so that no reading
depends on a setting nobody sent (fault 17): autorange with its limits
at 2 nA and 20 mA, 5 PLC, autozero on, median and averaging filters off,
mX+b off, Rel off, zero correct off, one immediate arm and trigger, no
trigger delay.

Rel (`CALC2:NULL:STAT OFF`) and zero correct (`SYST:ZCOR OFF`) matter
most of those. A Rel value, or an acquired zero, left on by the last
person subtracts from every reading without a word, and the reset table
is not clear that `*RST` clears either.

## Decisions and deviations

- **No zero correct (decided 2026-11-19).** As for the 487: zero check
  off at reset, back on at release, and no zero-correct step until a
  bench shows the offset matters. It would cost a sequence at every
  reset (zero check on, set the range, trigger, acquire, zero check off)
  and a re-zero whenever the range moves down.
- **The integration time is clamped, not snapped.** The 6485 takes any
  value from 0.01 to 5 PLC, so a request outside that span is moved to
  its nearer end and anything inside it is sent as asked. The
  specifications page says 50 PLC at 50 Hz; the SCPI table says 5, and
  5 is what is followed until the bench says otherwise.
- **A fixed range is sent after `RANG:AUTO OFF`**, rather than relying
  on the range command to switch autorange off by itself.
- **The read timeout grows with the integration time**, as the 34401A's
  does. At 5 PLC with autozero and autoranging a reading is about 0.6 s
  by the driver's arithmetic.
- **A units suffix is stripped.** If the units element were ever in
  force, the reading would arrive as `+1.234E-12A`; the parse tolerates
  it. Several elements are refused rather than guessed at.
- **`output_off()` sends nothing**, because there is nothing to switch
  off. It succeeds, since every exit path calls it. Every source method
  refuses.
- **Refused at Connect by the meter caveat, `measures_only`**, as the
  34401A is. See [technical debt](../open/technical-debt.md) for why it
  is a caveat and not a capability.

## Open questions

All of these are for the bench. `probes/6485-first-session.txt` asks
Q1 to Q8 through `tools/scpi_console.py`. Probe scripts are not
committed, so copy the file to the bench PC along with the branch. The
checkup covers the rest.

1. **What does this unit's `*IDN?` say?** It sets the `idn` field and
   confirms `MODEL_IDS`.
2. **What does `*RST` leave?** Zero check, the elements of a reading,
   the integration time and the autorange limits, in the instrument's
   own spelling.
3. **What does a reading with zero check on look like,** next to the
   same open input with it off?
4. **Does `READ?` return a Rel'd reading when Rel is on?** The manual
   sends Rel'd readings through `CALC2:DATA?` and does not say what
   `READ?` returns. `reset()` turns Rel off either way.
5. **Is an integration time above 5 PLC accepted?** The SCPI table says
   5 at 50 Hz, the specifications page 50.
6. **Does a fixed range switch autorange off by itself over the bus?**
7. **How long is a reading at 0.01, 1 and 5 PLC, with and without
   autozero?** The timeout is built on 50 Hz arithmetic and a factor of
   three for autozero.
8. **How long does `*RST` take?** The 34401A held the bus for about
   340 ms after it.
9. **Does a quiet bus after a query raise an error, as it did on the
   TSX-P?** The checkup pauses after a reading and asks.
10. **Does an unpaced configuration block drop commands?** The burst
    check asks. `WRITE_DELAY_S` is zero until it shows otherwise.
