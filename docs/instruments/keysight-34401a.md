---
type: instrument
title: "Keysight 34401A"
driver_class: Keysight34401A
idn: "HEWLETT-PACKARD,34401A,0,11-5-3"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: 2026-11-16
bench_notes: "2026-11-16 first session at d8e4e370c6b5, GPIB0::22 through the GPIB-USB-HS adapter, nothing attached, firmware 11-5-3: 62 pass, 10 warn, 0 fail. All ten warnings were the integration-time and range readbacks, then untrusted; they were trusted the same day on the evidence of the probe script (probes/34401a-first-session.txt), which staled this record. Burst check 10 of 10 on bursts of up to 16 writes, no pacing. 23 ms a reading at 0.02 PLC; 4.05 s at 100 PLC against 4.10 s expected"
bench_code: "2b6f8b5b1107"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "19 ms at NPLC 0.02 (autozero on, nothing attached, 2026-11-16); 0.42 s at the reset 10 PLC and 4.02 s at 100 PLC with autozero, 2.22 s without - a 50 Hz mains, plus about 18 ms per READ?"
resolution: "6.5 digits; 100 nV on the 100 mV range at 100 PLC (manual)"
best_for: "nothing yet - a driver only, refused by every window until a role for a meter is decided"
connection: "GPIB (GPIB-USB-HS adapter, direct)"

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

Written from the *Agilent 34401A User's Guide*, then checked at the
bench on 2026-11-16 with a checkup and a probe script. The command and
reset tables it was written from are in
[34401A command summary](../reference/manuals/34401a-commands.md).

## Identity and envelope

**`*IDN?` is answered, so it is auto-detected**, unlike the
[487](keithley-487.md). This lab's unit has a Keysight badge and answers
`HEWLETT-PACKARD,34401A,0,11-5-3`, firmware 11-5-3. Later units may say
Agilent. `MODEL_IDS` matches on `34401A` alone, so every badge resolves.

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
- **An open input on the >10 GΩ setting reads like a voltage.** With
  nothing attached it read −14 mV, drifting to −128 mV within about 8 s
  (measured). A lead that has come off reads tens of millivolts that
  look plausible. On 10 MΩ the same open input read −35 µV.
- **Switching back to 10 MΩ leaves charge behind.** Straight after
  turning the high-impedance input off, an open input read −0.89 mV.
  It took about 5 s to drain to −37 µV.
- **Autozero doubles the reading time.** It is on by default, and it
  removes the input's offset drift. Measured: 4.02 s a reading at
  100 PLC with it, 2.22 s without.
- **An over-range reading has a sign.** Over range, the meter returns
  −9.9E+37 for a negative input, not only the +9.9E+37 the manual
  prints. Either one becomes an empty cell, never a number.
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

Measured `*RST` state on this unit: DC volts (`FUNC?` says `"VOLT"`),
autorange on, 10 PLC, autozero on, input 10 MΩ, immediate trigger, one
sample. `reset()` takes about 0.37 s. The meter is still working
through `*RST` when the next commands arrive, and holds the bus for
about 340 ms partway through them. Nothing is lost.

## Decisions and deviations

- **No `CONFigure` and no `MEASure?`.** The manual says both preset the
  input to 10 MΩ (and preset autozero and the trigger with it), so a
  `MEAS?` per point would undo `reset()` on every reading. The bench
  confirmed it: the input read high-impedance after `FUNC "VOLT:DC"`
  and 10 MΩ after `CONF:VOLT:DC`. The driver configures with the
  individual `[SENSe:]` commands and reads with `READ?`.
- **An integration time between two menu entries moves up**, never to
  the nearest: more integration than asked for is a slower reading,
  less is a noisier one nobody asked for. Only menu values are sent.
- **A fixed range is sent after `RANG:AUTO OFF`.** The bench showed the
  range command turns autorange off by itself over the bus too, so the
  extra write is redundant. It is kept: it costs 3 ms and says what is
  meant.
- **The read timeout grows with the integration time.** At 100 PLC with
  autozero, a reading takes 4.02 s (measured; the bench mains is
  50 Hz), longer than the 3 s every other driver is called with. A
  reading that outlives its timeout desynchronises the link.
- **The configuration readbacks are trusted** (since 2026-11-16).
  `VOLT:DC:NPLC?` was checked against how long readings took at 0.02,
  10 and 100 PLC. It also kept reporting 10 after an off-menu `NPLC 5`,
  so it reports the meter's state, not the last command. `VOLT:DC:RANG?`
  was checked by an overload on the 100 mV range. The range evidence is
  the thinner of the two.
- **`output_off()` sends nothing**, because there is nothing to switch
  off. It succeeds, since every exit path calls it. Every source method
  refuses.
- **Refused at Connect by a caveat, `measures_only`.** Strictly it is a
  capability, since a meter *cannot* set an operating point, but
  declaring a capability means editing `BaseInstrument`, and that would
  stale the whole fleet. See
  [technical debt](../open/technical-debt.md).

## Bench answers (2026-11-16)

The nine questions the manual left open, asked by the first checkup
and by `probes/34401a-first-session.txt` through
`tools/scpi_console.py`. Probe scripts are not committed.

| Question | Answer |
|---|---|
| What does `*IDN?` say? | `HEWLETT-PACKARD,34401A,0,11-5-3` |
| What does `FUNC?` return for DC volts? | `"VOLT"` |
| Does `FUNC "VOLT:DC"` keep the input mode, and does `CONF:VOLT:DC` reset it? | Yes to both, so `CONF` stays unsent |
| Is an off-menu integration time refused or rounded? | Neither shows: `NPLC 5` raised no error and read back 10, which was already set. Still open, and moot, since the driver never sends one |
| Does a fixed range turn autorange off by itself over the bus? | Yes |
| How long is a reading at 100 PLC? | 4.02 s with autozero, 2.22 s without; 0.42 s at 10 PLC, 19 ms at 0.02 PLC. The mains is 50 Hz |
| What does an open input read? | −35 µV on 10 MΩ; on >10 GΩ it floats, −14 mV to −128 mV |
| Does a quiet bus after a query raise an error? | No |
| Does an unpaced configuration block drop commands? | No: 10 of 10 bursts answered, up to 16 writes each. `WRITE_DELAY_S` stays zero |

Also seen: `SYSTem:BOGus` gives −113 and `SYST:REM` gives +514
("allowed only with RS-232"). Both are as the driver expects.