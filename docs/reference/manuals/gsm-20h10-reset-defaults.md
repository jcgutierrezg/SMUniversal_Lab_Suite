---
type: reference
title: "GSM-20H10 reset defaults"
---

# GSM-20H10 reset defaults

Transcribed from the *GSM-20H10 User Manual*, "Factory Settings",
pp. 160–164. This is the **Bench** factory default table; the manual
states the GPIB defaults are the same content plus the second table
below.

Confirmed against the instrument on 2026-08-20: `*RST` leaves
`SENS:CURR:DC:PROT:LEV?` reading `+1.050000e-04` and
`SENS:VOLT:DC:PROT:LEV?` reading `+2.100000e+01`, which matches the
first two compliance rows.

## The rows that matter most

Read these before writing anything that configures this instrument.

| Setting | Default | Why it matters |
|---|---|---|
| Voltage Cmpl | 105.000 µA | The current limit in force when sourcing voltage if nothing is sent. Full scale of the 100 µA range, not a round number. |
| Current Cmpl | 21.0000 V | The voltage limit when sourcing current. |
| Measure cur-range | Auto | |
| Measure volt-range | Auto | |
| Sense mode | 2 Wire | 4-wire must be asked for on every run. |
| Speed | 1.00 PLC | |
| Source delay | 0.00300 s | With **Auto-delay Enable**, so a delay is applied even when none was chosen. |
| Output | off | |
| Output enable | Disable | The rear-panel interlock is **already ignored** at reset. `OUTP:ENAB 0` in `reset()` is belt-and-braces, not load-bearing. |
| Off state | Normal | V-source selected and set to 0 V when the output is off, so 0 V output-on and output-off are physically indistinguishable. |
| Auto-off | Disable | So the output must be turned on before `:INITiate` or `:READ?`. |
| Abort on compliance | Never | |
| Sweep Pts | 2500 | |
| Source ranging | Best fixed | |
| Voltage protection | NONE | |

The "Off state: Normal" row is worth dwelling on. It means a reading at
0 V with the output **off** and a reading at 0 V with the output **on**
return the same thing, because in both cases the V-source is sitting at
0 V. Any test of whether the output energised must therefore use a
**non-zero** level; at 0 V the two states are indistinguishable and a
probe run there proves nothing.

## GPIB-only additions

| Setting | Default |
|---|---|
| Format: Data FORMat | ASCii |
| Format: ELEMents list | VOLT,CURR,RES,TIME,STAT |
| Format: BORDer | NORMal |
| SENSe1: CONCurrent | ON |
| SENSe1: FUNCtion[ON] | **CURR** |
| SOURce: SWEep DIRection | UP |
| TRACe: FEED | SENSe[1] |
| TRACe: FEED CONTrol | NEVer |
| TRACe: TSTamp FORMat | ABSolute |
| System: TIME RESet AUTO | OFF |
| CALCulate2:FEED | VOLTage |
| CALCulate3:FORMat | MEAN |
| DISPlay subsystem Enable | ON |

Two of these are load-bearing:

**`FUNCtion[ON]` is `CURR` alone.** Voltage is not measured by default,
and with concurrent measurement off the voltage column is filled from
the *source setting* rather than from a measurement. That is
[Concurrent measurement was never enabled](../../faults/02-concurrent-measurement.md), and this table is where the
manual admits it.

**`ELEMents list` is five fields**, `VOLT,CURR,RES,TIME,STAT`. The
driver asks for two and the instrument's replies have been observed at
five regardless — the parser takes the leading pair, so nothing is
currently wrong, but the driver should not claim the reply is fixed to
two fields.

## Full table, as printed

```
Voltage:                  0.0000V
Current:                  0.000uA
Voltage Cmpl:             105.000uA
Current Cmpl:             21.0000V
Measure cur-range:        Auto
Measure volt-range:       Auto
Sync cmpl range:          Disable
Sense mode:               2 Wire
Guard:                    Cable
Speed:                    1.00PLC
Digits:                   5.5
Relative:                 Disable
  value:                  +0.000000
Line frequency:           No effect
Beeper:                   Enable
Digital output:           15
FCTN:                     Power
Filter:                   Disable
  Averaging type:         Repeat
  Count:                  10
GPIB address:             No effect
Limit tests:
  Digout: Size 4bit, Mode Grading, Binning control Immediate,
          Auto clear Disable, Delay 0.00001s, Clear Pattern 15
  H/W Limit: Control Disable, Fail mode In, Cmpl pattern 15
  S/W limits Lim 2,3,5,6,7,8,9,10,11,12:
          Control Disable, Low limit -1.000000, Low pattern 15,
          High limit +1.000000, High pattern 15
  Pass:   Pass pattern 15, Source memory Next
  EOT mode: EOT, Numbers No effect
Ohms source mode:         Auto
Offset compensated ohms:  Disable
Output:                   off
  Output enable:          Disable
  Off state:              Normal
Auto-off:                 Disable
Power-on default:         No effect
Measure ohms range:       AUTO
RS-232:                   No effect
Source delay:             0.00300s
  Auto-delay:             Enable
Sweep:                    Stair
  Voltage start/stop/step: +0.000V
  Current start/stop/step: +0.00000A
  Sweep count:            1
  Sweep Pts:              2500
  Source ranging:         Best fixed
  Abort on compliance:    Never
Voltage protection:       NONE
Triggered voltage:        Control Disable, Scale factor +1.0000
Triggered current:        Control Disable, Scale factor +1.0000
Triggering:
  Arm layer:    Event Immediate, Count 1,
                Output out TL exit Off, Output out TL enter Off
  Trigger layer: Event Immediate, Count 1,
                Output events source/delay/MEAS Off, Delay 0.00000s
```
