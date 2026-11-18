---
type: reference
title: "B2987A command summary"
---

# Keysight B2987A — command summary

Transcribed from the *B2980 Series SCPI Command Reference*, Edition 3
(chapter 2's summary tables, which carry the reset values, and chapter
5's error list), and corrected where the probe sitting on a B2987A
(2026-11-18, firmware 2.0.1608.8800, `tools/bench_b2987a.py`) found
otherwise. The report is `checkups/20261118/bench_B2987A_20261118_121508.md`.

SCPI throughout; `*IDN?` answers
`Keysight Technologies,B2987A,MY54320335,2.0.1608.8800`. Replies end in
LF. Numbers come back as `+2.00000000E+001`.

## What the driver uses

| Command | Query | Meaning |
|---|---|---|
| `*RST`, `*CLS` | — | reset; about 330 ms to `*OPC?` |
| — | `SYST:ERR?` → `-222,"Data out of range; Interlock open"` | one error; 2xx device codes carry a `+` |
| — | `SYST:INT:TRIP?` → `1` | the interlock: 1 open, 0 closed |
| `OUTP 0\|1` | `OUTP?` | the source output |
| `OUTP:LOW COMM\|FLO` | `OUTP:LOW?` | the source's low terminal: common, or floating. Only with the output off (+211) |
| `OUTP:OFF:MODE NORM` | `OUTP:OFF:MODE?` | off is 0 V, then the relay opens |
| `INP 0\|1` | `INP?` | the ammeter input switch |
| `SOUR:VOLT:RANG 20\|1000\|-1000` | `SOUR:VOLT:RANG?` | the source range. Only with the output off (+213) |
| `SOUR:VOLT <V>` | `SOUR:VOLT?` | the level |
| `SENS:FUNC "CURR"` | `SENS:FUNC?` → `"VOLT","CURR"` | the functions measured; quoted |
| `SENS:CURR:NPLC <n>` | `SENS:CURR:NPLC?` | integration, any value 5E-4 to 100 at 50 Hz |
| `SENS:CURR:NPLC:AUTO OFF` | `SENS:CURR:NPLC:AUTO?` | automatic aperture; one setting with `APER:AUTO` |
| `SENS:CURR:RANG:AUTO ON\|OFF` | `SENS:CURR:RANG:AUTO?` | current autorange |
| `SENS:CURR:RANG <A>` | `SENS:CURR:RANG?` | a fixed current range; snaps up (3E-9 → 20 nA) |
| `SENS:CURR:AVER:MOV OFF`, `SENS:CURR:MED OFF`, `SENS:CURR:REF:STAT OFF`, `INP:ZCOR OFF` | — | filters, null and zero correct, all off |
| `SOUR:WAIT[:AUTO] ON`, `SENS:WAIT[:AUTO] ON` | — | the instrument's own range-dependent settling waits |
| `FORM ASC`, `FORM:ELEM:SENS CURR,STAT` | `FORM:ELEM:SENS?` → `CURR,STAT` | the reply: the current and its status word |
| — | `MEAS?` → `-4.712900E-14,+0.000000E+00` | one spot reading, as the element list says |

## Source ranges

| Range | Levels | The current it holds |
|---|---|---|
| 20 V | -21 V to +21 V, 700 µV steps | 20 mA (held about 25.5 mA, measured) |
| +1000 V | **-1 V** to +1000 V, 35 mV steps | 1 mA |
| -1000 V | -1000 V to **+1 V**, 35 mV steps | 1 mA |

A level outside the range in force is refused with `-222,"Data out of
range; Source voltage level"` and the previous level stays; the range
does not move. Above 21 V with the interlock open, `-222,"Data out of
range; Interlock open"`. There is no source autorange outside the
instrument's own sweep.

No command sets a current limit. At its limit the source regulates: the
output stays on, status bit 8 is set, and no error is queued.

## The status word

As far as the reference's Table 1-2 can be read; bit 8 confirmed at the
bench.

| Bit | Meaning |
|---|---|
| 0 | current or charge overflow |
| 1 | voltage overflow |
| 2, 3 | current, voltage out of limit (the limit test) |
| 4 | zero correct on |
| 5, 6, 7 | null on, for current, voltage, resistance |
| **8** | **the source at its current limit** |
| 9, 10 | median, moving-average filter on |

`+9.91E+37` is not a number, `±9.9E+37` an infinity.

## Reset values that matter

| Setting | After `*RST` | The driver |
|---|---|---|
| Ammeter input | **off** — and a reading then returns a plausible current (`+2.6E-11`), not "not a number" | on, read back |
| Element list | **not reset** — eight elements on the bench unit | `CURR,STAT`, read back |
| Integration | 0.1 PLC with automatic aperture on: 1.4 s a reading | 1 PLC, auto off, read back |
| Functions | voltage and current | current only |
| Low terminal | common (the summary table; the command's own page says floating) | common, read back |
| Output-off mode | NORM | NORM |
| Source range, level | 20 V, 0 V | the same |
| Settling waits | on, automatic | on, stated |

## Never sent

`SYST:BATT?` — with no battery fitted it queues `-241,"Hardware missing;
Cannot detect battery"`. Also `*SAV`/`*RCL`, `SOUR:VOLT:MODE` (sweep,
list, square wave), `SOUR:VOLT:RLIM` (the 20 MΩ limiting resistor),
`CALC`, `TRIG`/`INIT`/`ARM`, and the communication settings.

## Emergencies

An over-current at the **ammeter** input, an open interlock above 21 V,
or an over-temperature sets the source to 0 V, opens the output switch,
and asks for `*TST?`. They arrive in the error queue as
`Emergency; ...`. None has been provoked at the bench.
