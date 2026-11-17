---
type: reference
title: "34401A command summary"
---

# 34401A command summary

Transcribed from the *Agilent 34401A User's Guide*: chapter 4's command
summary (pp. 105-111), the measurement-configuration reference
(pp. 121-123), the power-on and reset table (p. 101) and chapter 5's
error list. What the first bench session (2026-11-16) found when it was
compared with real replies is in the
[instrument note](../../instruments/keysight-34401a.md#bench-answers-2026-11-16).

## Syntax

Ordinary SCPI. Keywords take a long or short form (`VOLTage` /
`VOLT`), `[SENSe:]` is optional, and a query ends in `?`. Over GPIB,
addressing the meter is enough to put it in remote. The `SYSTem:REMote`
step in the RS-232 examples is error 514 on GPIB.

## The commands the driver sends

| Command | Reply | Meaning | Sent |
|---|---|---|---|
| `*IDN?` | `HEWLETT-PACKARD,34401A,0,<firmware>` | identity (later units say Agilent) | identify |
| `*RST` | - | the reset state below | reset |
| `*CLS` | - | clears the error queue and status registers | reset |
| `FUNC "VOLT:DC"` | - | DC volts | reset |
| `FUNC?` | a quoted string | the function | checkup |
| `VOLT:DC:RANG:AUTO ON\|OFF` | - | autorange | reset, `set_voltage_range` |
| `VOLT:DC:RANG:AUTO?` | `0` / `1` | | checkup |
| `VOLT:DC:RANG <volts>` | - | 0.1, 1, 10, 100 or 1000 | `set_voltage_range` |
| `VOLT:DC:RANG?` | `+1.00000000E+01` | | checkup |
| `VOLT:DC:NPLC <n>` | - | 0.02, 0.2, 1, 10 or 100 power-line cycles | reset, `set_nplc` |
| `VOLT:DC:NPLC?` | number | | checkup |
| `ZERO:AUTO ON\|OFF` | - | autozero | reset, `set_autozero` |
| `ZERO:AUTO?` | `0` / `1` | `0` for both OFF and ONCE | checkup |
| `INP:IMP:AUTO ON\|OFF` | - | >10 GΩ on 100 mV, 1 V, 10 V (ON) or 10 MΩ everywhere (OFF) | reset (last), `set_high_impedance` |
| `INP:IMP:AUTO?` | `0` / `1` | | checkup |
| `ROUT:TERM?` | `FRON` / `REAR` | the front-panel switch; query only | checkup |
| `TRIG:SOUR IMM` | - | internal trigger | reset |
| `TRIG:DEL:AUTO ON` | - | automatic trigger delay (1.5 ms at ≥1 PLC, 1 ms below) | reset |
| `TRIG:COUN 1`, `SAMP:COUN 1` | - | one reading per `READ?` | reset |
| `CALC:STAT OFF` | - | math off, so no null offset is subtracted | reset |
| `READ?` | `+1.23456789E+00` | trigger, wait, fetch | `measure` |
| `SYST:ERR?` | `-113,"Undefined header"` | one entry off the queue | `read_error` |

### Never sent

| Command | Why |
|---|---|
| `CONFigure:...`, `MEASure:...?` | preset the input to 10 MΩ, and preset autozero, trigger and sample count with it |
| `SYSTem:REMote`, `SYSTem:LOCal`, `SYSTem:RWLock` | RS-232 only; error 514 over GPIB |
| `L1`, `L2`, `L3` | switch the interface language; after `L2` or `L3` nothing SCPI is understood |
| `TRIGger:SOURce BUS` | `READ?` with a bus trigger is a trigger deadlock: the reading never comes |
| `CALCulate` other than `:STAT OFF` | a null offset or limit test silently changes what a reading means |
| `INITiate`, `FETCh?`, `DATA:POINts?` | reading memory (512 readings); a reading per `READ?` is all the driver needs |
| `CALibration:...` | calibration, and its security code |
| `*TST?` | the complete self-test takes long enough to look like a dead link |
| `DISPlay`, `DISPlay:TEXT`, `SYSTem:BEEPer` | nothing a measurement needs |

## Power-on and reset state (p. 101)

Bullets in the manual mark the settings held in non-volatile memory;
those are the I/O settings and the beeper. Everything a reading depends
on is volatile and returns to this at power-on or `*RST`:

| Setting | Reset state | `reset()` |
|---|---|---|
| Function | DC volts | sent |
| Range | autorange | sent |
| Resolution | 5½ digits, slow mode | follows from the integration time |
| Integration time | 10 PLC | sent |
| Autozero | on | sent |
| Input resistance | 10 MΩ, fixed for all DC volts ranges | **overridden**: >10 GΩ on the three low ranges, sent last |
| AC filter | 20 Hz (medium) | not used |
| Math | off, null; registers cleared | `CALC:STAT OFF` sent |
| Samples per trigger | 1 | sent |
| Trigger delay | automatic | sent |
| Trigger source | immediate (remote) / auto (front panel) | `IMM` sent |
| Display | on | not touched |
| GPIB address | 22 (non-volatile) | - |
| Language | SCPI (non-volatile) | - |

## Reading times (chapter 8, operating characteristics)

DC volts, readings per second at 60 Hz (50 Hz in brackets), autozero
**off**: 0.6 (0.5) at 100 PLC, 6 (5) at 10 PLC, 60 (50) at 1 PLC, 300
at 0.2 PLC, 1000 at 0.02 PLC. Autozero on takes a zero reading for every
signal reading, about doubling the time. Range change under 30 ms.

## Errors the driver can meet (chapter 5)

| Code | Text | When |
|---|---|---|
| -113 | Undefined header | a command it does not know - the checkup's error probe |
| -222 | Data out of range | a numeric parameter outside the command's range |
| -224 | Illegal parameter value | a discrete parameter not on the list |
| -230 | Data stale | `FETCh?` with reading memory empty |
| -350 | Too many errors | more than 20 queued; later errors are lost |
| -410 | Query INTERRUPTED | a new query arrived before the last reply was read |
| -420 | Query UNTERMINATED | addressed to talk with nothing to send |
| 514 | Command allowed only with RS-232 | `SYST:REM`, `SYST:LOC`, `SYST:RWL` over GPIB |
| 532 | Cannot achieve requested resolution | an impossible `CONF` resolution |
| 540 | Cannot use overload as math reference | a null taken on an overload |
| 550 | Command not allowed in local | `READ?` or `MEAS?` in local (RS-232) |

The queue holds 20. `*CLS` empties it; `*RST` does not.
