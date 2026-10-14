---
type: reference
title: "Keithley 487 command summary"
---

# Keithley 487 command summary

Transcribed from the *Model 486 Picoammeter / Model 487 Picoammeter/Voltage
Source Instruction Manual*, Section 4 and Appendix A. The copy on hand is a
scan whose text layer is an OCR with errors, and its figures are images:
**Figures 4-1, 4-6 and 4-7 below were read off the page by eye on
2026-10-14**, and the tables were checked against the section prose where
the OCR garbled them (Appendix A's trigger table is offset by one line in
the OCR; Section 4.2.18 is what is given here).

Nothing here has yet been compared with a real reply. The open questions
are in the [instrument note](../../instruments/keithley-487.md#open-questions).

## Syntax

A command is one capital letter and its option; `X` executes everything
received since the last `X`. Within one `X`-terminated string, commands
execute **simultaneously** (except `L` and then `H`, which run last), and
**one invalid command voids the whole string** - an IDDC or IDDCO flag,
and none of it is executed. Repeating a command in one string keeps only
the last. Spaces are ignored.

The driver sends one command per `X`, for both reasons.

## The commands the driver sends

| Command | Meaning | Sent as |
|---|---|---|
| `B0` | readings from the A/D (not the data store) | reset |
| `C0` / `C1` / `C2` | zero check off / on / on and zero-correct this range | `C0` at reset |
| `F0` / `F1` | V/I ohms off / on | `F0` at reset |
| `G0` | ASCII readings with prefix | reset |
| `K0` | EOI on, bus hold-off on `X` | reset |
| `M0` | no SRQ | reset |
| `O0` / `O1` | source standby / operate | |
| `P0` | digital and analog filters off | reset |
| `R0` | autorange | |
| `R1`-`R7` | 2 nA, 20 nA, 200 nA, 2 µA, 20 µA, 200 µA, 2 mA | |
| `R10` | autorange off, stay on the present range | not sent |
| `S0` / `S1` | integration 1.6 ms (4½ d) / one line cycle (5½ d) | |
| `T1` | trigger one-shot on talk | for the one talk that fetches a reading |
| `T3` | trigger one-shot on GET | reset, and after every reading - the idle mode |
| `U0`-`U9` | send a status word (below) on the next talk | |
| `Vn,r,l` | source level `n` (V), range `r` (0 = 50 V, 1 = 500 V), limit `l` (0 = 25 µA, 1 = 2.5 mA) | |
| `W` | trigger delay, 0 to 999.999 s | `W0` at reset |
| `Y0` | terminator CR LF | reset |
| `Z0` | relative off | reset |

Omitted `V` fields keep their present value, but the commas before a
field that is sent are required. A `V` level beyond ±505 V is an IDDCO; a
level beyond the selected range is a **CONFLICT**, and either way the
whole command is ignored.

### Never sent

| Command | Why |
|---|---|
| `L0` | restores the factory defaults **and saves them over the stored set** |
| `L1` | saves the present state as the power-up and device-clear default |
| `L2`-`L6` | recall, and calibration |
| `H` | presses a front-panel key |
| `D` | writes to the display |

### Trigger modes (`T`)

| | on talk | on GET | on `X` | on external | on operate |
|---|---|---|---|---|---|
| multiple | `T0` | `T2` | `T4` | `T6` | `T8` |
| one-shot | `T1` | `T3` | `T5` | `T7` | `T9` |

In `T0` and `T1` **every** talk is a trigger, including one that fetches
a status word, and a talk that arrives while a conversion is still
running is refused as a trigger overrun - for a reading, that means no
reading at all. Measured on the bench, 2026-10-14; see the instrument
note. Hence the idle mode.

## Readings (`G0`) - Figure 4-1

```
N DCI ±1.23456E±03
│ └── DCI = DC current, OHM = V/I ohms
└──── N = normal, Z = rel'd, O = overflow (or underflow, in V/I ohms)
```

`G2` adds `,000` (the A/D) or `,001`-`,512` (a buffer location). An
overflowed reading also carries ±9.87E37 in its number field.

## Status words

### U0 - machine status (Figure 4-6)

Each field is the letter of the command it reports and that command's
option. The factory-default word as printed:

```
487 A0 B0 C1 F0 G0 H** J0 K0 M000 N000 O0 P3 R11 S1 T6 V01 Y0 Z0 c*
```

| Field | Digits | Meaning |
|---|---|---|
| `A` | 1 | display intensity |
| `B` | 1 | reading source |
| `C` | 1 | zero check: 0 off, 1 on |
| `F` | 1 | V/I ohms: 0 off, 1 on |
| `G` | 1 | data format |
| `H` | 2 | last key pressed |
| `J` | 1 | self-test: 0 none, 1 ROM, 2 RAM, 3 both |
| `K` | 1 | EOI and hold-off |
| `M` | 3 | SRQ mask |
| `N` | 3 | data store size, 000 wrap-around |
| `O` | 1 | 0 standby, 1 operate |
| `P` | 1 | filters |
| `R` | 2 | *m* 0 autorange off, 1 on; *n* the range now in use, 1-7 |
| `S` | 1 | integration |
| `T` | 1 | trigger mode |
| `V` | 2 | *m* 0 50 V range, 1 500 V; *n* 0 25 µA limit, 1 2.5 mA |
| `Y` | 1 | terminator |
| `Z` | 2 | *m* current rel, *n* V/I ohms rel: 0 off, 1 on |
| `c` | 1 | calibration lock switch: 0 locked, 1 enabled |

The figure prints the `V` *n* = 1 limit as "25mA"; Section 4.2.20 and the
datasheet make it 2.5 mA. It also shows the factory word with `V01` - the
2.5 mA limit - where Table 4-3 says 25 µA. The driver states the limit at
every reset, so it depends on neither.

### U1 - error status (Figure 4-7)

`487` followed by thirteen 0/1 flags, in this order. Reading the word
clears every flag.

| # | Flag | Set when |
|---|---|---|
| 1 | IDDC | an illegal command, e.g. `E1X` |
| 2 | IDDCO | an illegal option, e.g. `T10X` |
| 3 | No Remote | a command arrived with the instrument in local |
| 4 | Self-Test | a ROM or RAM self-test failed |
| 5 | Trigger Overrun | a trigger arrived while a reading was in progress |
| 6 | Conflict | a calibration value too large for the range |
| 7 | Cal Locked | calibration with the switch locked |
| 8 | Zero Check | calibration with zero check on |
| 9 | Calibration | a calibration constant out of limits |
| 10 | E²PROM Defaults | the stored defaults failed their checksum at power-up |
| 11 | E²PROM Cal Constants | the calibration failed its checksum at power-up |
| 12 | V-Source Conflict | a source level beyond the selected range |
| 13 | V-Source | operate refused because the interlock is open |

### U2 - model and firmware

`487A03` and two trailing blanks, for firmware A03.

### U8 - source value

`VS=+20.000E+00V` on the 50 V range, `VS=+020.00E+00V` on the 500 V.
Not used by the driver: `U0` carries the range directly.

### U9 - source errors

`487` followed by two flags, latched until read:

| # | Flag |
|---|---|
| 1 | in current limit, now or since last read |
| 2 | the enabled interlock is open, now or since last read |

## Reset defaults (Table 4-3)

A DCL or SDC returns the instrument to the **saved** defaults, which are
these only until someone stores another set with `L1`.

| Command | Factory default |
|---|---|
| `A0` | normal display |
| `B0` | readings from the A/D |
| `C1` | **zero check on** |
| `F0` | V/I ohms off |
| `G0` | ASCII with prefix |
| `K0` | EOI and hold-off on |
| `M000` | SRQ disabled |
| `N` | data store unarmed |
| `O0` | **standby** - after every clear, whatever was saved (Section 4.2.13) |
| `P3` | **both filters on** |
| `R0` | autorange |
| `S1` | line-cycle integration |
| `T6` | **multiple on external trigger** |
| `V0,0,0` | 0 V, 50 V range, 25 µA limit (but see U0 above) |
| `Y0` | CR LF |
| `Z0` | rel off |

The table marks with an asterisk the settings `L1` can save, and the
scan does not show which rows carry one. Each command's own section in
4.2 says it "returns to the option saved as the default condition", so
the driver treats every one of them as possibly saved - which is why it
sends them all.

The IEEE-488 address and the line frequency are set at the front panel
only and survive everything.
