---
type: reference
title: "GSM-20H10 output and source commands"
---

# GSM-20H10 output and source commands

Transcribed from the *GSM-20H10 User Manual* command reference,
2026-08-20. Paraphrased where the wording is not load-bearing; the
parameter tables are verbatim.

## `:OUTPut[1][:STATe] <b>`

Turns the source output on or off. **Measurements cannot be made while
the source is off.** Turning the source off places the GSM in the idle
state; the only exception is when source auto-clear is enabled, in which
case the source turns on during each source phase of the SDM cycle and
off after each measurement.

| `<b>` | |
|---|---|
| `0` or `OFF` | source off (standby) |
| `1` or `ON` | source on (operate) |

Example given: `:OUTPut 0`.

> **`:OUTPut?` does not report the truth on this instrument.** Measured
> 2026-08-20 with the output physically on and 10 V sourced from the
> front panel, both `OUTP?` and `OUTP:STAT?` returned `0` while `READ?`
> returned `+9.999960e+00`. Nothing in this suite queries it — the
> checkup infers output state from whether the *write* succeeded — so
> it has never mattered, and it should stay that way. A query that lies
> is worse than no query.

Note the optional `[1]` suffix on the header, and that the manual's
only example uses `0`. `OUTP1 ON` is rejected with `-102 Syntax error`,
so the suffix is not written that way.

## `:OUTPut[1]:ENABle[:STATe] <b>`

Enables or disables the **output enable function**. When enabled, the
SMU cannot output unless the output enable line — pin 11 of the rear
panel DIGITAL I/O interface — is pulled to a logic low state. When that
line goes high, the SMU cannot output. When disabled, the logic level on
the line has no effect.

| `<b>` | |
|---|---|
| `0` or `OFF` | disable the output enable function |
| `1` or `ON` | enable it |

> **Already `Disable` at reset** — see
> [GSM-20H10 reset defaults](gsm-20h10-reset-defaults.md). The `OUTP:ENAB 0` in
> `reset()` is therefore reinforcement rather than a fix, and it is not
> what makes the output usable. It was mistaken for the cause of an
> output failure on 2026-08-20 and disproved by probe.

## `:OUTPut[1]:SMODe <name>`

Selects the output-off mode.

| `<name>` | |
|---|---|
| `HIMPedance` | output relay opens, disconnecting external circuitry from the Input/Output |
| `NORMal` | normal output-off state |
| `ZERO` | zero output-off state |
| `GUARd` | guard output-off state |

With **HIMPedance**, the relay opens when the source is turned off. The
manual warns against using it for tests that turn the output on and off
frequently, to avoid excessive relay wear.

With **NORMal**, the V-Source is selected and set to 0 V when the output
is turned off, and compliance is set to 0.5% of full scale of the
present current range.

With **ZERO**, turning the V-Source output off sets it to 0 V without
changing the current compliance; turning the I-Source output off selects
V-Source mode at 0 V and sets current compliance to the programmed
source-I value or 0.5% of full scale, whichever is greater. Typically
used with V-Source and output auto-on to generate waveforms alternating
between 0 V and the programmed voltage.

With **GUARd**, the I-Source is selected and set to 0 A, and voltage
compliance is set to 0.5% of full scale of the present voltage range.
For 6-wire guarded ohms or other loads that use an active source.

## `:SOURce[1]:CLEar:AUTO <b>`

Controls auto output-off for the source. With it **enabled**, an
`:INITiate` (or `:READ?` or `:MEASure?`) starts source-measure
operation: the output turns on at the beginning of each SDM
(source-delay-measure) cycle and off after each measurement completes.

With it **disabled**, the source output must be on before an
`:INITiate` or `:READ?` can start a source-measure operation.
`:MEASure?` turns the source output on automatically. Once operation has
started, the output stays on even after the instrument returns to idle.

**Auto output-off disabled is the `*RST` and `:SYSTem:PRESet` default.**

| `<b>` | |
|---|---|
| `1` or `ON` | enable auto output-off |
| `0` or `OFF` | disable auto output-off |

> The manual's own warning: with auto output-off disabled the output
> remains on after all programmed source-measure operations complete.

## `:SOURce[1]:CLEar[:IMMediate]`

Turns off the source output, after all programmed source-measure
operations are completed, returning the instrument to idle. If auto-off
is enabled the source output will turn off automatically.

## `:INITiate[:IMMediate]`

Initiates source-measure operation by taking the GSM out of idle.
`:READ?` and `:MEASure?` also perform an initiation.

If auto output-off is disabled (`SOURce1:CLEar:AUTO OFF`), **the source
output must first be turned on before an initiation can be performed**.
`:MEASure?` automatically turns the source on before initiating.

## `:ROUTe:TERMinals <name>`

Selects front or rear panel input/output terminals.

| `<name>` | |
|---|---|
| `FRONt` | front panel terminals |
| `REAR` | rear panel terminals |

## Not present on this instrument

`:ABORt` is **rejected** with `-113 Undefined header`, confirmed by
probe 2026-08-14. `:TRIG:CLE` is the documented route.
