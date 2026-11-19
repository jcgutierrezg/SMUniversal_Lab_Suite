---
type: reference
title: "6485 command summary"
---

# 6485 command summary

Transcribed from the *Model 6485 Picoammeter Instruction Manual*
(Keithley, first printing November 2001): section 14's SCPI reference
tables, the default-settings table (Table 1-3), the zero check and zero
correct commands (Table 2-4), the data-format notes (section 13) and the
specifications (appendix A). Nothing here has been compared with real
replies yet; the first bench session's corrections will go in the
[instrument note](../../instruments/keithley-6485.md).

## Syntax

Ordinary SCPI. Keywords take a long or short form (`CURRent` / `CURR`),
`[SENSe[1]:]` and `[:DC]` are optional, and a query ends in `?`. Over
GPIB, addressing the meter puts it in remote; `SYSTem:REMote`,
`:LOCal` and `:RWLock` are RS-232 only. The GPIB language must be SCPI
or 488.1 - in DDC (Model 485 emulation) none of this is understood.

## The commands the driver sends

| Command | Reply | Meaning | Sent |
|---|---|---|---|
| `*IDN?` | `KEITHLEY INSTRUMENTS INC.,MODEL 6485,<serial>,<firmware>` | identity | identify |
| `*RST` | - | the GPIB defaults below | reset |
| `*CLS` | - | clears the error queue and event registers | reset |
| `FORM:ELEM READ` | - | the reading alone: no units, timestamp or status | reset |
| `CURR:RANG:AUTO ON\|OFF` | - | autorange | reset, `set_current_range` |
| `CURR:RANG:AUTO?` | `0` / `1` | | checkup |
| `CURR:RANG:AUTO:LLIM <amps>` | - | autorange lower limit; -0.021 to 0.021 | reset |
| `CURR:RANG:AUTO:ULIM <amps>` | - | autorange upper limit; -0.021 to 0.021 | reset |
| `CURR:RANG <amps>` | - | 2e-9 ... 2e-2; the range that holds the value | `set_current_range` |
| `CURR:RANG?` | number | the range in force | checkup |
| `CURR:NPLC <n>` | - | 0.01 to 6 (60 Hz) or 5 (50 Hz) power-line cycles | reset, `set_nplc` |
| `CURR:NPLC?` | number | | checkup |
| `SYST:AZER ON\|OFF` | - | autozero | reset, `set_autozero` |
| `SYST:AZER?` | `0` / `1` | | checkup |
| `MED OFF` | - | median filter off | reset |
| `AVER OFF` | - | digital (averaging) filter off | reset |
| `CALC1:STAT OFF` | - | mX+b, m/X+b and log off | reset |
| `CALC2:NULL:STAT OFF` | - | Rel off | reset |
| `ARM:SOUR IMM`, `ARM:COUN 1` | - | one arm cycle, immediately | reset |
| `TRIG:SOUR IMM`, `TRIG:COUN 1`, `TRIG:DEL 0` | - | one reading per `READ?`, no delay | reset |
| `SYST:ZCOR OFF` | - | zero correct off | reset |
| `SYST:ZCH ON\|OFF` | - | zero check: input shunted to low (ON) or measuring (OFF) | reset (OFF, last), `release_front_panel` (ON), `set_zero_check` |
| `SYST:ZCH?` | `0` / `1` | | checkup |
| `READ?` | `+1.234567E-12` | trigger, wait, fetch | `measure` |
| `SYST:ERR?` | `-113,"Undefined header"` | one entry off the queue | `read_error` |

### Never sent

| Command | Why |
|---|---|
| `*SAV`, `*RCL`, `SYSTem:POSetup`, `SYSTem:PRESet` | a recalled or preset setup is one nobody here chose; `PRESet` also leaves autorange off and the byte order swapped |
| `SYSTem:REMote`, `:LOCal`, `:RWLock` | RS-232 only |
| `SYSTem:ZCORrect:ACQuire`, `SYSTem:ZCORrect ON` | zero correct is not used (decided 2026-11-19) |
| `CALCulate` other than switching it off | mX+b, Rel, limit tests and buffer statistics each change or stand in for a reading |
| `TRACe:...` | the 2500-reading buffer; one reading per `READ?` is all the driver needs |
| `FORMat:DATA` other than ASCII, `FORMat:BORDer` | binary transfer; RS-232 is ASCII only |
| `DISPlay:ENABle OFF`, `DISPlay:TEXT` | nothing a measurement needs, and neither is reset by `*RST` |
| `SYSTem:KEY` | simulated key presses |
| `CALibration:...` | calibration (appendix H) |
| `STATus:...:ENABle`, `*SRE` | the status enable registers; nothing here waits on SRQ |

## Default settings (Table 1-3)

Factory (`SYSTem:PRESet`) and GPIB (`*RST`) defaults are the same except
where shown. Only the settings a reading depends on are listed.

| Setting | `*RST` | `SYST:PRES` | `reset()` |
|---|---|---|---|
| Zero check | **enabled** | enabled | **overridden**: off, sent last |
| Zero correct | disabled | disabled | sent |
| Range | auto | auto | sent |
| Autorange limits | 2.1e-9 to 2.1e-2 | same | sent as 2e-9 and 2e-2 |
| Integration time | 6 PLC (60 Hz) / 5 PLC (50 Hz) | same | 5 PLC sent |
| Autozero | on | on | sent |
| Median filter | off, rank 1 | same | sent |
| Digital filter | off, count 10, moving | same | sent |
| mX+b, m/X+b, log | off | off | sent |
| Rel | off, value 0 (Table 5-2); "no effect" in Table 1-3 | | sent |
| Data elements | all four (reading, units, timestamp, status) | same | **overridden**: reading only |
| Byte order | normal | swapped | not used (ASCII) |
| Arm layer | immediate, count 1 | count infinite | sent |
| Trigger layer | immediate, count 1, delay 0 | same | sent |
| Display digits | 5½ | same | not touched |
| GPIB address, language | no effect (14, SCPI at the factory) | | - |

The status registers, the error queue and the buffer are not touched by
`*RST`; `*CLS` empties the error queue.

## Ranges and speed (Tables 4-1, 4-3; appendix A)

| Range | `CURR:RANG` value | Resolution (5½ digits) | Accuracy, 1 year |
|---|---|---|---|
| 2 nA | 2e-9 | 10 fA | 0.4% + 400 fA |
| 20 nA | 2e-8 | 100 fA | 0.4% + 1 pA |
| 200 nA | 2e-7 | 1 pA | 0.2% + 10 pA |
| 2 µA | 2e-6 | 10 pA | 0.15% + 100 pA |
| 20 µA | 2e-5 | 100 pA | 0.1% + 1 nA |
| 200 µA | 2e-4 | 1 nA | 0.1% + 10 nA |
| 2 mA | 2e-3 | 10 nA | 0.1% + 100 nA |
| 20 mA | 2e-2 | 100 nA | 0.1% + 1 µA |

Each range reads to 105%; autorange goes up at 105% and down at the
range value. Integration rates: FAST 0.1 PLC, MED 1 PLC, SLOW 6 PLC
(60 Hz) or 5 PLC (50 Hz). Autozero off reads up to three times faster.
Up to 900 readings per second over GPIB at 0.01 PLC with filters,
display and autozero off, in binary.

## Readings

An overflowed or overvoltage reading is `+9.9E37`; an element with no
valid data is `+9.91E37`. With the units element on, the reading carries
an `A` suffix. The status word's bit 7 (ROF) is reading overflow and
bit 10 (IOV) input overvoltage.

## Input limits (section 2, appendix A)

| Limit | Value |
|---|---|
| Maximum input | 220 V peak, 21 mA - damage beyond either |
| Input LO to chassis | 42 V safe; 500 V breakdown |
| Above 60 V on 2 mA and 20 mA | switches to a 1-3 MΩ input (OVRVOLT) |
| Zero check transient impedance | 500 Ω (mA ranges), 50 kΩ (20/200 µA), 3.5 MΩ (200 nA/2 µA), 11 MΩ (2/20 nA) |

## Errors the driver can meet

| Code | Text | When |
|---|---|---|
| -113 | Undefined header | a command it does not know - the checkup's error probe |
| -222 | Parameter data out of range | a numeric parameter outside the command's range |
| -224 | Illegal parameter value | a discrete parameter not on the list |
| -230 | Data corrupt or stale | `SENS:DATA?` with no reading available |
| -350 | Queue overflow | the queue is full; later errors are lost |
