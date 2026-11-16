---
type: instrument
title: "Keysight 34401A"
driver_class: Keysight34401A
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
resolution: "6.5 digits; 100 nV on the 100 mV range at 100 PLC (manual)"
best_for: "nothing yet - a driver only, refused by every window until a role for a meter is decided"
connection: "GPIB (GPIB-USB-HS adapter, most likely direct)"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keysight_34401a.py
model_ids: "['34401A']"
max_voltage_v: 1000
max_current_a: 3
voltage_ranges_n: 5
current_ranges_n: 4
power_envelope_n: 0
sweep_kind: software
nplc_min: 0.02
nplc_max: 100
high_z_off: false
ovp: false
ovp_trip: false
remote_sense_control: false
compliance_trip: false
fleet: meter
# --- end generated ---
---

# Keysight 34401A

A 6½-digit bench multimeter, sold under HP, then Agilent, then Keysight
badges with the same insides. It reads DC and AC volts, DC and AC
current, 2- and 4-wire resistance, frequency and period. It sets
nothing.

It is the first instrument in the **meter** fleet - `BaseMeter`, beside
`BaseSMU`, `BaseLoad` and `BaseSupply` - because no existing contract
fits a meter. Each of them is mostly about setting an operating point,
and a meter answers none of those questions. See
[A meter sets nothing](../architecture/devices.md#a-meter-sets-nothing).

**Driver only, for now (decided 2026-11-16).** Every experiment refuses
it at Connect, with the meter's own reason. The driver reads DC volts
and nothing else. Its first real role, most likely a voltmeter beside an
SMU in the four-contact tabs, will come as a role of its own, not as an
invitation into `source`.

Written from the *Agilent 34401A User's Guide* before the unit had been
asked anything. The command and reset tables it was written from are in
[34401A command summary](../reference/manuals/34401a-commands.md).

## Identity and envelope

**`*IDN?` is answered, so it is auto-detected**, unlike the
[487](keithley-487.md). The manual gives
`HEWLETT-PACKARD,34401A,0,<firmware>`. Later units say Agilent, and the
badge on this lab's unit says Keysight. `MODEL_IDS` matches on `34401A`
alone, so all three resolve. The real reply goes in `idn` above at the
first checkup.

**The interface language has to be SCPI.** The front panel offers two
others, HP 3478A and Fluke 8840A emulation, and in either one `*IDN?`
is never answered, so Connect latches the link. SCPI is the factory
setting and is held in non-volatile memory. If Connect hangs on this
meter, check *I/O MENU → LANGUAGE* on the front panel first.

GPIB address 22 from the factory, shown at power-on.

| | |
|---|---|
| DC voltage ranges | 100 mV, 1 V, 10 V, 100 V, 1000 V; 20% over-range except on 1000 V |
| Input resistance | 10 MΩ on every range, or >10 GΩ on 100 mV, 1 V and 10 V |
| Integration time | 0.02, 0.2, 1, 10 or 100 power-line cycles |
| DC current ranges | 10 mA, 100 mA, 1 A, 3 A (not read by this driver) |

`LIMITS` holds the input's ratings, not a source envelope: a meter has
none.

## What this means for your data

Nothing yet, because no window will take it. When a role arrives, these
are the facts it will have to carry:

- **The input resistance is part of the circuit.** On 10 MΩ, a meter
  across a 100 kΩ sample takes 1% of the current. `reset()` selects the
  >10 GΩ input, which covers the three low ranges. On 100 V and 1000 V
  the input is 10 MΩ whatever the setting says.
- **Autozero doubles the reading time.** It is on by default, and it
  removes the input's offset drift.
- **Which terminals are in use is set on the front panel.** The
  front/rear switch cannot be set from the bus. It can be queried, and
  `describe_configuration()` records it.

## Reset defaults that had to be overridden

`*RST` leaves the input at 10 MΩ. `reset()` sends `INP:IMP:AUTO ON` as
its **last** command, after everything that could reset it. Every other
reset default is sent explicitly too, so that no reading depends on a
setting nobody sent (fault 17): DC volts, autorange, 10 PLC, autozero
on, immediate trigger, automatic trigger delay, one trigger, one sample,
math off.

`CALC:STAT OFF` matters most of those. A null offset left on by the
last person subtracts from every reading, without a word.

## Decisions and deviations

- **No `CONFigure` and no `MEASure?`.** The manual says both preset the
  input to 10 MΩ (and preset autozero and the trigger with it), so a
  `MEAS?` per point would undo `reset()` on every reading. The driver
  configures with the individual `[SENSe:]` commands and reads with
  `READ?`.
- **An integration time between two menu entries moves up**, never to
  the nearest: more integration than asked for is a slower reading,
  less is a noisier one nobody asked for. Only menu values are sent.
- **A fixed range is sent after `RANG:AUTO OFF`**, rather than relying
  on the range command to switch autorange off by itself. The manual
  says that much about the front panel and is silent about the bus.
- **The read timeout grows with the integration time.** At 100 PLC with
  autozero, a reading takes about 4 s at 50 Hz, longer than the 3 s
  every other driver is called with. A reading that outlives its timeout
  desynchronises the link.
- **`output_off()` sends nothing**, because there is nothing to switch
  off. It succeeds, since every exit path calls it. Every source method
  refuses.
- **Refused at Connect by a caveat, `measures_only`.** Strictly it is a
  capability, since a meter *cannot* set an operating point, but
  declaring a capability means editing `BaseInstrument`, and that would
  stale the whole fleet. See
  [technical debt](../open/technical-debt.md).

## Open questions

All of these are for the bench. `probes/34401a-first-session.txt`
asks Q1 to Q7 through `tools/scpi_console.py`. Probe scripts are not
committed, so copy the file to the bench PC along with the branch. The
checkup covers the rest.

1. **What does this unit's `*IDN?` say?** It sets the `idn` field and
   confirms `MODEL_IDS`.
2. **What does `FUNC?` return for DC volts?** The manual says only "a
   quoted string". The checkup accepts anything starting `VOLT` without
   `AC` or `RAT`.
3. **Does `FUNC "VOLT:DC"` leave the input mode alone, and does
   `CONF:VOLT:DC` reset it?** The manual says `CONF` resets it. That is
   the reason the driver never sends `CONF`.
4. **Is an off-menu integration time refused or rounded?** The driver
   never sends one; this says what would happen if it did.
5. **Does a fixed range switch autorange off by itself over the bus?**
6. **How long is a reading at 100 PLC, with and without autozero?** The
   timeout is built on 50 Hz arithmetic.
7. **What does an open input read on each input mode?** On 10 MΩ it
   should be near zero; on >10 GΩ it floats.
8. **Does a quiet bus after a query raise an error, as it did on the
   TSX-P?** The checkup pauses after a reading and asks.
9. **Does an unpaced configuration block drop commands?** The burst
   check asks. `WRITE_DELAY_S` is zero until it shows otherwise.
