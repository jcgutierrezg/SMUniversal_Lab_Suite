---
type: instrument
title: "TDK-Lambda Z36-24"
driver_class: TDKLambdaZ36_24
idn: "TDK-LAMBDA,Z36-24,817A137-0013,2.231"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: false
last_bench: null
bench_notes: "no checkup yet. The driver was written from the Z+ manual and two probe sittings with tools/bench_z36.py on 2026-11-17, on COM7 with nothing attached: 03e6c87b81b2 (checkups/20261117/bench_Z36-24_20261117_150156.md) and f953dd6cc2c6 (bench_Z36-24_20261117_151543.md)"
bench_code: null
bench_result: null
bench_result_note: null
bench_revalidated: null
reading_time: "10 to 16 ms per query (probe, 2026-11-17), two queries per reading - but the meter refreshes only about every 210 ms, so readings faster than that repeat"
resolution: "readback to 0.1 mV and 0.1 mA. A setting lands up to about 0.6 mV and 0.4 mA below what was sent (probe, 2026-11-17)"
best_for: "holding a rail or driving a heater, up to 36 V and 24 A - an auxiliary, not a measuring instrument"
connection: "USB serial"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/tdk_lambda_zplus.py
model_ids: "['Z36-24']"
max_voltage_v: 36
max_current_a: 24
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

# TDK-Lambda Z36-24

An 864 W bench power supply: 0 to 36 V at 0 to 24 A, the whole rectangle
at once. One of the twenty TDK-Lambda Z+ low-voltage models, which share
a manual and a command set. It joins the supply fleet beside the two
[Aim-TTi TSX-P](aimtti-tsx3510p.md) units, on the same terms: an
auxiliary, refused by every experiment except Fixed sourcing vs time.

The driver is `drivers/tdk_lambda_zplus.py`: a Z+ class with the command
set, and this model's class with its envelope. Only the Z36-24 is
registered, because it is the only Z+ that has been on a bench.

## How it was written

From the *Z+ User Manual, low-voltage models 10 V to 100 V* - chapter 7
for the commands, chapter 9 for the registers - and from two probe
sittings with [`tools/bench_z36.py`](../architecture/tools.md#bench_z36py--the-connection-before-there-is-a-driver)
on 2026-11-17, before the driver existed. The manual's commands are
accurate. What it leaves unclear is the connection, and that is what
the probe was for. The command table, with what the bench corrected, is
in [Z+ command summary](../reference/manuals/zplus-commands.md).

## Connection

- **USB**, on the rear Type B socket. It enumerates as `2504:0001`, and
  Windows binds its own "USB Serial Device" driver to it - the TDK
  driver is not needed. The address list names the port "TDK-Lambda
  Z36-24" from those ids.
- **The baud does not matter over USB.** The front panel says 9600; it
  answered at 115200 too, so the suite's Serial transport works as it
  is.
- **Nothing is heard until the supply is selected.** `INST:NSEL 1` has
  to come first - `*IDN?` before it is silence. The selection survives
  a reopened port and `*RST`, and is lost at power-off. So the registry
  sends `INST:NSEL 1` before `*IDN?` to any serial port with this
  supply's USB ids, and the driver sends it again in `identify()` and
  `reset()`.
- **Its bus address is 1** (factory 6), set at the front panel under
  REM. The driver's `BUS_ADDRESS` is this bench's value; change one and
  the other has to follow.
- **The language is SCPI**, which is what the front panel was set to.
  In GEN the supply answers every command `OK`, and nothing here would
  work.

## What the probe found

**Errors are off until enabled.** In the first sitting every refused
setting was ignored in silence - `CURR 30`, `VOLT 40`, a trip of 1 V, an
unknown header, a voltage above 95% of the trip - with `SYST:ERR?`
reading `0,"No error"` and `*ESR?` 0 after each, and the setting left
as it was. The second sitting sent `SYST:ERR:ENAB` first, and the same
commands were reported:

| Sent | Reported |
|---|---|
| `VOLT:NOSUCH 1` | `-100,"Command Error;address 1"`, `*ESR?` 32 |
| `CURR 30`, `VOLT 40`, `VOLT:PROT:LEV 1` | `-222,"Data Out Of Range;address 1"`, `*ESR?` 16 |
| a trip below 105% of the voltage | `+304,"OVP Below PV;address 1"`, `*ESR?` 8 |
| a voltage above 95% of the trip | `+301,"PV Above OVP;address 1"`, `*ESR?` 8 |

The enable survives `*RST` and is lost at power-off. `reset()` sends it
on every connect, and the checkup's error probe (`CURR 30`, expecting
-222) is what proves it took.

**It accepts 5% over rated.** `VOLT? MAX` reads 37.8 and `CURR? MAX`
25.2, and `VOLT 37` and `CURR 25` landed. The driver's envelope is the
rated 36 V and 24 A.

**A setting lands just below what was sent:** `VOLT 1.23456` reads back
1.2340, `VOLT 11` 10.9995, `CURR 0.123456` 0.1232, `CURR 0.0021` 0.0020.
`CURR 0` lands, so there is no current floor. Settings survive
power-off, each read back a fraction of a millivolt lower after it
(1.9997 V became 1.9985 V over two put-backs and a power cycle).

**`*RST`** leaves 0 V, 0 A, the trip at 40 V and the output off, and
returns the front panel to local. Auto-restart read off before and
after.

**`SYST:REM LOC` hands the front panel back** - the REM LED went out -
and a query leaves it there; the next setting takes it back to remote.
The app sends it when it disconnects.

**After a power cycle** the output was off (safe start), the settings
were the last ones, and `SYST:REM?` read REM.

**Open circuit, output on at 1 V:** `OUTP:MODE?` CV, `STAT:OPER:COND?` 5
(4 with the output off), `STAT:QUES:COND?` 0 either way, `MEAS:CURR?`
0.0000 five times out of five. The manual's current readback accuracy
is 0.1% of the reading plus 72 mA; no offset showed.

**Timing.** A query takes 10 to 16 ms. The meter's reading changes in
steps about 210 ms apart, so a poll faster than that repeats it. The
output is quicker than the meter: 1 V to 5 V was there by the next
refresh, 5 V to 1 V took about 0.3 s, and off from 1 V fell to 1.6 mV in
about 0.26 s - all with nothing attached. `SETTLING_S` is 0.5 s.

## What the driver does with it

- **`reset()`**: `INST:NSEL 1`, `*RST`, `*CLS` (150 ms to execute),
  `SYST:ERR:ENAB`, then the trip at 40 V and auto-restart off, sent
  explicitly.
- **The voltage and the trip** are checked against each other before
  anything is sent: a voltage above 95% of the trip, or a trip below
  105% of the voltage, is refused with the reason and the number to
  fix.
- **Regulation** is `OUTP:MODE?`, a state read now. There are no limit
  events, so a crossover between two polls is not caught.
- **A trip** is the fault register, `STAT:QUES:COND?`, latched from the
  output going on, because the register clears when the cause does.
  The supply also files 320-327 in the error queue.
- **Writes are paced 50 ms.** Not measured either way; the probe left at
  least 150 ms after every write. The first checkup can try less.
- **The setpoint readback is not trusted yet.** A value set at the front
  panel has to be read back over the bus first, as was done for the
  TSX-Ps.

## Not done yet

- **A checkup.** Owed before anything relies on the driver.
- **The current limit clamping into a load.** Every measurement so far
  is open circuit, so CC, the current reading under load and the sign of
  a sourced current are the manual's word.
- **A trip.** No protection has fired. What the fault register, the
  queue and the link do during one is unknown.
