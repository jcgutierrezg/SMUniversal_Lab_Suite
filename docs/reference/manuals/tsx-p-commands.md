---
type: reference
title: "TSX-P command summary"
---

# Aim-TTi TSX-P — command summary

Transcribed from the *TSX-P Instruction Manual*, Issue 18: the remote
command list, the status registers and the remote-operation part of the
specification. The PDF is not committed; see `manuals/README.md`.

[The driver](https://github.com/jcgutierrezg/SMUniversal_Lab_Suite/blob/main/smuniversal_lab_suite/drivers/aimtti_tsx_p.py)
was written from this page before either unit had answered a query. The
TSX1820P has since had a bench session, on 2026-10-08, and every command
in the first table below was sent and understood. Where the instrument
differed from the manual, the difference is in *Corrections*, as for the
[72-13200](72-13200-commands.md). The TSX3510P has not been tried.

The manual covers both models, the TSX3510P (35 V, 10 A) and the
TSX1820P (18 V, 20 A). They share every command and differ only in the
numbers.

## It is not SCPI

There is no command tree and no colon. A command is a short word, a
space and a number: `V 12.5`. Commands are case-insensitive, may be
joined with `;`, and end with a line feed. `<nrf>` below is a number in
any format; the instrument converts it to the precision the setting has
and rounds it.

## What the driver uses

| Command | Reply | Meaning |
|---|---|---|
| `*IDN?` | `<name>,<model>P,0,<version>` | identity. The third field is a literal `0` on these units |
| `*RST` | — | output off, voltage to minimum, current to minimum, over-voltage trip to maximum, meter damping off |
| `*CLS` | — | clears the event, limit, execution-error and query-error registers |
| `V <nrf>` | — | set the output voltage, in volts |
| `VV <nrf>` | — | set the voltage and wait for the output to settle to within 5% or 3 counts; gives up after 5 s and sets bit 3 of the event register |
| `I <nrf>` | — | set the current limit, in amps |
| `OVP <nrf>` | — | set the over-voltage trip, in volts |
| `V?` | `V 12.55` | the voltage setting |
| `I?` | `I 1.000` | the current limit setting |
| `OVP?` | `OVP 33.00` | the over-voltage trip setting |
| `VO?` | `12.55V` | the output voltage, read back |
| `IO?` | `0.934A` | the output current, read back |
| `POWER?` | `175.3W` | the output power |
| `OP <nrf>` | — | output on (`1`) or off (`0`) |
| `DAMPING <nrf>` | — | current-meter damping on (`1`) or off (`0`) |
| `LSR?` | `<nr1>` | limit event register, cleared by reading |
| `*ESR?` | `<nr1>` | standard event register, cleared by reading |
| `EER?` | `<nr1>` | number of the last execution error, cleared by reading |
| `QER?` | `<nr1>` | number of the last query error, cleared by reading |
| `*STB?` | `<nr1>` | status byte |

Two things about the replies. A **reading** carries its unit on the end
and a **setting** carries its header on the front, so neither parses as
a bare number. And the manual's syntax line for `V?` reads `V<nr2>`
with no space where its own example has one; the driver takes the last
number in the reply and so does not depend on which is right.

## Corrections, measured 2026-10-08 on a TSX1820P, firmware 1.20

| The manual says | The instrument does |
|---|---|
| a number is "converted to the required precision ... then rounded up" | **voltage rounds to the nearest step** - `V 1.004` lands as 1.00, `V 1.005` and `V 1.006` as 1.01 - and **current rounds down**: `I 0.104` and `I 0.106` both land as 0.10, and `I 0.009` is refused with error 103 rather than becoming 0.01 |
| `I?` answers `I 1.000`, three decimals | two: `I 0.05`, `I 20.20`. `V?` and `OVP?` answer to two, as printed |
| every out-of-range setting is an execution error | all but one. `OVP 25.01` is accepted with no error and lands as `OVP 25.00`. `OVP 0.99` gives 107, `V 18.16` gives 100, `I 20.21` gives 101, `V -1` gives 102 |
| the limit register's bits are set "when output enters" a limit | a bit is set **for as long as** the output is in that limit: read and cleared, it is back at the next read. The first read after a change of mode gives both bits, `3` |
| reading the output voltage back can cost 500 ms | a query takes 22 to 60 ms |
| after a 10 V step the output is within a digit "in typically 150ms" | a 9 V step up took about 1.3 s to settle with a 50 mA current setting, passing through current limit as the output capacitor charged |
| `*IDN?` is `<NAME>,<model>P,0,<version>` | `THURLBY-THANDAR,TSX1820P,0,1.20` |
| nothing about a query error without a lost reply | `*ESR?` read 4 and `QER?` read 3, "unterminated", twice in one session in which every query had been answered. Not explained |
| after a trip the system "will then attempt to recover" | with the trip at 5 V and 6 V asked for, the next query was never answered. Whether it answers again once the setting is back under the trip is not known |

Confirmed as printed: errors 100, 101, 102, 103 and 107; a command
error for a word that is not a command; the reset values; `VV`
returning once the output has settled; and `V?` and `I?` reading back a
value set by hand at the front panel.

## The registers

**Standard event register, `*ESR?`**

| Bit | Value | Meaning |
|---|---|---|
| 7 | 128 | power on — set by switching the instrument on, not an error |
| 5 | 32 | command error: a syntax error in something received |
| 4 | 16 | execution error: the number is in `EER?` |
| 3 | 8 | verify time-out: a `VV` did not settle in 5 s |
| 2 | 4 | query error: the number is in `QER?` |
| 0 | 1 | operation complete, set only by `*OPC` |

**Limit event register, `LSR?`**

| Bit | Value | Meaning |
|---|---|---|
| 2 | 4 | an output trip has occurred |
| 1 | 2 | the output entered voltage limit |
| 0 | 1 | the output entered current limit |

Both bits 0 and 1 are worded as **entering** a limit, and there is no
query for which mode the output is in. On the 1820 a bit comes back
after being read for as long as the supply stays in that limit, so in
practice the register *is* that query - see *Corrections*. The driver's
`_poll_limit_events()` was written to be right under either reading.

**Execution errors, `EER?`**

| Number | Meaning |
|---|---|
| 1 | checksum error in non-volatile memory at power-on |
| 2 | output stage failed to respond |
| 3 | output stage has tripped and is trying to recover |
| 100 | maximum set voltage exceeded |
| 101 | maximum set current exceeded |
| 102 | minimum set voltage exceeded |
| 103 | minimum set current exceeded |
| 104 | maximum delta voltage exceeded |
| 105 | maximum delta current exceeded |
| 107 | minimum set OVP exceeded |
| 108 | maximum set OVP exceeded |
| 109 | minimum delta current exceeded |
| 110 | minimum delta voltage exceeded |
| 114 | illegal bus address requested |
| 115 | illegal store number |
| 116 | recall of an empty store requested |
| 117 | stored data is corrupt |
| 118 | output stage has tripped (over-voltage or temperature) |
| 119 | value out of range |

**Query errors, `QER?`**: 1 interrupted, 2 deadlock, 3 unterminated.

Each of these registers holds **one** value. Of two rejected settings
in a row, only the second is still there to be read.

## Reset and power-on

| Setting | After `*RST` | At power-on |
|---|---|---|
| output | off | off |
| voltage | minimum | **as last set** |
| current limit | minimum, which is 10 mA | **as last set** |
| over-voltage trip | maximum | **as last set** |
| meter damping | off | as last set |
| bus address, interface | unchanged | as last set |

Settings are held in non-volatile memory, so a unit comes up with
whatever the last person left, output aside. `*RST` is the only thing
that starts a session from known values. Its trip value is the least
protective one there is, so the driver sends the trip explicitly after
a reset rather than relying on it.

## Specification figures the driver depends on

| | TSX3510P | TSX1820P |
|---|---|---|
| Output voltage | 0 V to 35.3 V | 0 V to 18.15 V |
| Output current | 0.01 A to 10.2 A | 0.01 A to 20.2 A |
| Over-voltage trip | 1 V to 40 V | 1 V to 25 V |
| Setting resolution | 10 mV, 10 mA | 10 mV, 10 mA |
| Setting accuracy | ±(0.1% + 10 mV), ±(0.2% + 20 mA) | the same |
| Readback resolution | 10 mV, 10 mA | 10 mV, 10 mA |
| Readback accuracy | ±(0.2% + 1 digit), ±(0.5% + 1 digit) | the same |

Timing, both models: a command is acted on within 50 ms; a step up
settles with a time constant of about 22 ms, so about 150 ms to within
a digit after a 10 V step. A step **down** matches that only with an
amp or more flowing, and is slower at light load. The meters update at
4 Hz, and the manual gives 500 ms as what reading the output voltage
back can cost.

## Present and deliberately unused

| Command | Why the driver never sends it |
|---|---|
| `INCV`, `INCVV`, `DECV`, `DECVV`, `INCI`, `DECI` | relative steps. At the end of the range the value stops there and no error is generated, so the level is no longer known without reading it back |
| `DELTAV <nrf>`, `DELTAI <nrf>`, `DELTAV?`, `DELTAI?` | the step size for the above |
| `*SAV <nrf>`, `*RCL <nrf>` | the 25 stores. A recall restores the stored **output state** with the levels, so it can switch the output on |
| `*LRN?`, `LRN`, `STO?`, `STO` | the whole set-up or all stores as a binary block; GPIB only, and the same hazard as a recall |
| `BUZZER <nrf>`, `BUZZ` | the buzzer |
| `*ESE`, `*SRE`, `LSE`, `*PRE` and their queries | enable registers for a service request and parallel poll. Nothing in this suite listens for one; the registers are polled |
| `*OPC`, `*OPC?`, `*WAI`, `*IST?`, `*TST?` | every command is sequential, so the first three do nothing useful; the self-test only reports whether error 2 has occurred |

## The two interfaces

Selected at the front panel with the I/F key: `488` for GPIB, `232` for
serial. Only one is live at a time.

- **GPIB.** One primary address, 0 to 30, default 11. A reply ends with
  a line feed and EOI. There is no output queue, so a query whose reply
  is never read holds up every command behind it.
- **RS-232.** 300 to 9600 baud, 8 data bits, no parity, 1 stop bit,
  XON/XOFF only. A reply ends with carriage return and line feed. The
  port also carries a daisy-chain addressing protocol in the control
  codes below 20H; a unit powers up outside it and works as a plain
  serial port, which is the only way the driver would use it.

Any command puts the instrument in remote and locks the front panel.
The LOCAL key gives it back until the next command arrives. These units
have no bus command that returns control.

## The newer generation

Units made from 2017 — Series II, with USB and LAN — number every
command by output: `V1`, `I1`, `V1O?`, `I1O?`, `OP1`, `OVP1`. Their
manual says the spellings above are still accepted. Their settings
answer with a numbered header, `V1 12.55` and `VP1 33.00`, and they add
`OP1?`, `LOCAL`, and the LAN configuration commands. The driver's reply
parser reads both forms, and nothing else about Series II has been
tried.
