---
type: reference
title: "Keithley 236 command summary"
---

# Keithley 236 command summary

What the driver for the [Keithley 236](../../instruments/keithley-236.md) sends,
transcribed from the Model 236/237/238 Operator's Manual, 236-900-01
Rev. E, section 3 (`manuals/236 SMU/236_900_01E.pdf`). The PDF carries a
text layer, but it was produced by OCR: `0`/`O`, `1`/`l` and `5`/`S` are
confused throughout, so every spelling below was checked against the
manual's own examples rather than taken from the text layer alone.

The status words and the reading format were compared with a real
unit on 2026-11-16 (firmware A10) and matched; the replies seen are
quoted below.

## The language

A capital letter, its options separated by commas, then `X` to execute.
Spaces are ignored. Numbers may be plain (`.005`) or exponent form
(`5E-3`), and are truncated to five significant digits.

- **One illegal command voids the whole string** (IDDC or IDDCO, flagged
  in `U1`). The instrument checks nothing until the `X`.
- **A string is executed in the instrument's own order**, not the order
  sent (Table 3-5: M, C, F, O, P, Z, S, W, L, B, Q, A, T, R, N, D, Y, K,
  G, V, J, U, H). So the driver sends one command per `X`.
- The bus is held off while a command executes (`K0`): typically 7 to
  65 ms per command (Table 3-8), `L` about 31 ms, `F` about 64 ms.

## Commands the driver sends

| Command | Meaning | Notes |
|---|---|---|
| `F<s>,0` | source V (`0`, measures I) or I (`1`, measures V), dc function | A change of source puts the unit in **standby** and brings back that source's own remembered setup |
| `B<level>,<range>,<delay>` | dc level, source range, dc delay in ms (0-65000) | Range: `0` auto; V `1`=1.1 V, `2`=11 V, `3`=110 V; I `1`=1 nA ... `9`=100 mA. **A level beyond a fixed range is set to the range's full scale**, with VALUE OUT OF RANGE in `U9` |
| `L<level>,<range>` | compliance and measurement range, one command | With a fixed range, compliance range = measurement range. **Below 100 counts it is raised to 100 counts** (`L0E-3,9X` gives 1 mA); beyond the range it is set to full scale. "In dc operation, a change must be triggered to go into effect" |
| `N0` / `N1` | standby / operate | Standby holds 0 V on the 1.1 V range - it does **not** disconnect. With the interlock cable fitted and open, `N1` is refused (`U1` interlock flag) |
| `O0` / `O1` | local / remote sense | Connect the sense leads first: remote sense with nothing on SENSE drives OUTPUT HI and guard to the source's full voltage |
| `S0` `S1` `S3` | integration 416 µs, 4 ms, 20 ms (50 Hz line cycle) | `S2` is 16.67 ms, the 60 Hz line cycle; not used |
| `P0` | filter off | `P1`-`P5` average 2-32 readings |
| `W1` | default delay on | A range-dependent settle added to every cycle: 360 ms on 1 nA, 75 ms on 10 nA, 20 ms on 100 nA, 5 ms on 1 µA, 2 ms on 10 µA, 0 above |
| `Z0` | suppression off | |
| `G5,1,0` | output: source + measure items, ASCII with prefix, no suffix, one line of dc data per talk | Power-up default is `G1,0,0` (source value only) |
| `K0` | EOI on, bus hold-off on X | |
| `Y0` | CR LF terminator | |
| `M0,0` | no SRQ | |
| `R0` / `R1` | triggers off / on | The manual: disable triggers before changing the origin |
| `T4,1,0,0` | trigger origin immediate (`H0X` and the front-panel key only), a trigger starts the source phase, no output triggers | A talk triggers nothing in this origin |
| `H0` | immediate trigger | Starts one source-delay-measure cycle |
| `U0` `U1` `U3` `U4` `U5` `U9` | status words, below | Answered once per `U` command, on the next talk |
| (serial poll) | the status byte | Not a command: polled before every `H0X` for "ready for trigger" |

**Never sent:** `J0X` (factory initialisation - a full power-up sequence,
about 1.1 to 3 s; every setting is sent instead), `C` (calibration), `Q`
and `A` (sweep lists - sweeps are stepped from the PC), `V` (the 237's
1100 V range), `D` (display).

## The source-delay-measure cycle and triggers

Every reading is one cycle: the source phase applies the level, then the
default delay (if `W1`) and the dc delay, then the integration. In dc
operation with a non-continuous input trigger, each trigger runs one
cycle. "If output requests are faster than the reading update rate, the
bus is held off until the reading is available", and each dc reading is
output once.

- A trigger that arrives while a cycle is running is a **TRIG OVERRUN**:
  ignored, flagged in `U1`.
- "While in continuous triggering of the dc mode, the unit can be
  reprogrammed without having to retrigger it" (3.6.18 note 11) - which
  suggests that otherwise it cannot.
- Executing `F`, `R` or `T` places the unit in an untriggered state.
- **A reading coming back does not mean the unit is ready for the next
  trigger.** On 2026-11-16 a trigger 0.4 ms after a reading was lost.
  The serial-poll byte (Figure 3-5) says when it is: bit 4, "ready for
  trigger", cleared while the unit executes a bus or front-panel change
  and by `R0`. Bit 3 is "reading done", bit 5 an error, bit 0 a warning.
  The bits latch with SRQ disabled too, and a poll clears only bit 6.
- **A compliance entered at the front panel is pending until the next
  trigger** (2.12), and a measurement range changed in dc operation
  takes effect at the next trigger too.
- **Over the bus, a level (`B`) and a compliance (`L`) also take effect
  only at the next trigger** - measured 2026-11-17 with a handheld meter
  across a resistor: each, sent alone, left the previous value on the
  output until `H0X`. The unit was ready for that trigger 5 to 14 ms
  after a reading, once 65 ms.

The manual's caution under `B`: changing the level, the output first
holds the old value for 10 ms; after standby, operate brings back the
old level for 10 ms. Set 0 before standby.

## A reading (`G5,1,0`)

Figure 3-3, prefix and no suffix:

```
NSDCV+1.0000E+00,NMDCI+1.23456E-09
```

| Field | Values |
|---|---|
| source status | `N` normal, `O` overlimit (source in compliance) |
| measure status | `N` normal, `O` overlimit / overflow / sweep aborted, `Z` suppressed |
| `S` / `M` | source item / measure item |
| `DC` | dc (`SW` sweep, `PL` pulsed) |
| `V` / `I` | the quantity |

Seen on the unit: `NSDCV+0.1000E+00,NMDCI-000.006E-06` (100 µA range,
fastest integration), `NSDCV+0.0000E+00,NMDCI-01.8621E-09` (autorange),
and `OSDCI+1.0000E-06,OMDCV+0.99977E+00` at compliance - both items `O`.
The mantissa's width follows the range and resolution.

The source value is **the programmed value, not a measurement**. A
reading at compliance is "an actual measurement taken at the compliance
level". An overflow is flagged at 112.5% of the range. Byte counts
(Table 3-7): 16 for the source item, 17 for the measure item.

## Status words

**`U0` - identity.** `236A01` and two trailing blanks.

**`U1` - errors** (Figure 3-15): `ERS` and 26 flags, cleared when read
(and by DCL/SDC). Most significant first: trigger overrun, IDDC, IDDCO,
interlock present, illegal measure range, illegal source range, invalid
sweep mix, log cannot cross zero, autoranging source with pulse sweep,
in calibration, in standby, unit is a 236, IOU DPRAM failed, IOU EEROM
failed, IOU cal checksum error, DPRAM lockup, DPRAM link error, cal ADC
zero, cal ADC gain, cal SRC zero, cal SRC gain, cal common mode, cal
compliance, cal value, cal constants, cal invalid.

**`U3` - machine status** (Figure 3-17), factory defaults shown:

```
MSTG01,0,0K0M000,0N0R1T4,0,0,0V1Y0
```

`G` items (two digits), format, lines; `K`; `M` mask (three digits),
compliance select; `N` operate; `R` triggers; `T` origin, in, out, end;
`V` 1100 V range; `Y` terminator.

**`U4` - measurement parameters** (Figure 3-18): `IMP` while sourcing
voltage, `VMP` while sourcing current.

```
IMPL08F0,0O0P0S0W1Z0
```

`L` compliance/measurement range (two digits, `00` auto), `F` source and
function, `O` sense, `P` filter, `S` integration, `W` default delay, `Z`
suppression. **The comma after `L` is real**: the unit answers
`IMPL,00F0,0O0P0S3W1Z0` after reset.

**`U5` - compliance value** (Figure 3-19): `ICP10.000E-03` (amps) or
`VCP010.000E+00` (volts) in the figure. The unit answered
`ICP0100.00E-06` for 100 µA: a zero-padded mantissa and an engineering
exponent.

**`U9` - warnings** (Figure 3-23): `WRS` and 10 flags, cleared when read.
Uncalibrated, temporary cal, value out of range, sweep buffer filled, no
sweep points, pulse times not met, not in remote, measure range changed,
measurement overflow / sweep aborted, pending trigger.

No word reports the bias (source) range.

## Power-up and DCL/SDC

Table 3-4: a DCL or SDC returns the **power-up** defaults - standby,
`G1,0,0`, local sense, `K0`, no SRQ - and leaves most other settings as
last programmed, per source. The IEEE address and the line frequency are
never changed by a clear or by factory initialisation.
