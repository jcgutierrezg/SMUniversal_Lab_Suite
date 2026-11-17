---
type: reference
title: "Z+ command summary"
---

# TDK-Lambda Z+ — command summary

Transcribed from the *Z+ User Manual, low-voltage models 10 V to 100 V*,
chapter 7 (SCPI) and chapter 9 (registers), and corrected where two
probe sittings on a Z36-24 (2026-11-17, firmware 2.231,
`tools/bench_z36.py`) found otherwise. The reports are
`checkups/20261117/bench_Z36-24_20261117_150156.md` and
`bench_Z36-24_20261117_151543.md`.

Commands end in CR or LF; replies end in CR LF. Replies are bare and
zero-padded: `01.2340`, `000.00`.

## What the driver uses

| Command | Query | Meaning |
|---|---|---|
| `INST:NSEL <1-31>` | `INST:NSEL?` → `01` | select the supply. **Nothing else is heard until this is sent**, `*IDN?` included; lost at power-off |
| — | `*IDN?` → `TDK-LAMBDA,Z36-24,817A137-0013,2.231` | identity |
| `*RST` | — | output off, 0 V, 0 A, trip at maximum, front panel to local |
| `*CLS` | — | clear the status structure; 150 ms to execute |
| `SYST:ERR:ENAB` | — | **turn error reporting on.** Off by default: refusals are silent until it is sent. Survives `*RST`, lost at power-off |
| — | `SYST:ERR?` → `-222,"Data Out Of Range;address 1"` | one error, ten deep; 3xx codes carry a `+` |
| `VOLT <V>` | `VOLT?` → `01.2340` | voltage setting; lands a fraction of a step below |
| `CURR <A>` | `CURR?` → `00.1232` | current setting; 0 is accepted |
| `VOLT:PROT:LEV <V>` | `VOLT:PROT:LEV?` → `40.00` | over-voltage trip, 2 to 40 V on the 36 V models |
| `OUTP 1\|0` | `OUTP?` → `1`/`0` | output on/off |
| `OUTP:PON 0` | `OUTP:PON?` → `0` | auto-restart off (safe start); `reset()` sends it |
| — | `OUTP:MODE?` → `CV`/`CC`/`OFF` | regulation, now |
| — | `MEAS:VOLT?` → `01.0003` | output voltage; refreshes about every 210 ms |
| — | `MEAS:CURR?` → `00.0000` | output current, positive out |
| — | `MEAS:POW?` → `000.00` | power |
| — | `STAT:QUES:COND?` | live fault register (below) |
| `SYST:REM LOC` | `SYST:REM?` → `LOC`/`REM` | front panel back to local; a setting returns it to remote |

## The rules between voltage and trip

| Rule | Error | Measured |
|---|---|---|
| voltage at most 95% of the trip | +301 PV Above OVP | `VOLT 11.5` refused with a 12 V trip |
| trip at least 105% of the voltage, and at least 2 V | +304 OVP Below PV | `VOLT:PROT:LEV 10` refused with 10 V set |
| `VOLT:PROT:LEV MIN` | — | puts the trip 5% above the voltage: 11.56 for 10.9995 V |

## Ranges

| | Rated | Accepted (`? MAX`) |
|---|---|---|
| Voltage | 36 V | 37.8 V |
| Current | 24 A | 25.2 A |

The manual allows the 5% but advises against it. The driver's envelope
is the rating.

## Registers

**Fault register**, `STAT:QUES:COND?` (manual table 9-1): 2 AC fail,
4 over-temperature, 8 foldback, 16 over-voltage, 32 shut off, 64 output
off, 128 interlock, 256 under-voltage. Bit 64 read 0 with the output off.

**Operation register**, `STAT:OPER:COND?` (table 9-2): 1 CV, 2 CC, 4 no
fault, 16 auto-start, 32 foldback enabled, 128 local. Read 132 at
power-on in local, 5 with the output on, 4 with it off.

**`*ESR?`**: 32 command error, 16 execution error, 8 device-dependent
error, 128 power-on. Errors set these only once enabled.

## Never sent

| Command | Why |
|---|---|
| `*SAV`, `*RCL`, `LIST:LOAD`, `WAVE:LOAD` | a recall restores the output state and can energise |
| `LIST`, `WAVE`, `TRIG`, `INIT`, `*TRG` | the sequencer; with `INIT:CONT` on no setting can be changed |
| `GLOBal:...` | no acknowledgement, and acts on every supply on the chain |
| `FRST` | factory reset: drops the link |
| `SYST:REM LLO` | locks out the front panel, OUTPUT key included |
| `*PSC`, `*SRE`, `*ESE`, `STAT:...:ENAB` | an enabled register sends `!nn` unasked, which the next query would take as its reply |
| `OUTP:PROT:FOLD`, `VOLT:PROT:LOW`, `OUTP:ILC:MODE`, `OUTP:REL`, `OUTP:TTLT` | foldback trips at the CV/CC crossover; the rest are not this suite's |
| `OUTP:PON 1` | auto-restart would switch the output on after a power cut |
