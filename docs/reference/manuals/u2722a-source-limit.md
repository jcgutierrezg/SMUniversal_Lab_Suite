---
type: manual-extract
title: "Keysight U2722A — SOURce LIMit commands"
instrument: "Keysight U2722A"
source: "U2722A/U2723A USB Modular Source Measure Unit Programmer's Reference"
transcribed: 2026-08-25
---

# Keysight U2722A — `[SOURce:]CURRent:LIMit` and `[SOURce:]VOLTage:LIMit`

Transcribed from the Programmer's Reference pages. Everything below the
rule is what the manual says. Anything this project *knows* that the
manual does not say is in [the instrument note](../../instruments/keysight-u2722a.md),
marked as measured — this file is not the place for it.

---

## `[SOURce:]CURRent:LIMit`

### Syntax

```
[SOURce:]CURRent:LIMit <value>, (@<ch>)
```

> This command sets the maximum bounds on the output current value.
> Output current level will be clamped to the limit value if the current
> level has exceeded the bounds set.

```
[SOURce:]CURRent:LIMit? (@<ch>)
```

> This will query the current limit setting.

### Parameters

| Item | Type | Range of values | Default value |
|---|---|---|---|
| `<ch>` | NR1 | 1 through 3 | Required parameter |
| `<value>` | NRf | The maximum value is dependent on the current range set | Required parameter |

Returned query format: `<NR3>`

### Examples

```
CURR:LIM 0.8, (@1)
CURR:LIM? (@1)          Typical Response: +8.000000E-01
```

---

## `[SOURce:]VOLTage:LIMit`

### Syntax

```
[SOURce:]VOLTage:LIMit <value>, (@<ch>)
```

> This command sets the maximum bounds on the output voltage value.
> Output voltage level will be clamped to the limit value if the voltage
> level has exceeded the bounds set.

```
[SOURce:]VOLTage:LIMit? (@<ch>)
```

> This will query the set voltage limit.

### Parameters

| Item | Type | Range of values | Default value |
|---|---|---|---|
| `<ch>` | NR1 | 1 through 3 | Required parameter |
| `<value>` | NRf | The maximum value is dependent on the voltage range set | Required parameter |

Returned query format: `<NR3>`

### Examples

```
VOLT:LIM 0.5, (@1)
VOLT:LIM? (@1)          Typical Response: +5.000000E-01
```

---

## What these pages do **not** say

Recorded because each absence cost bench time to establish, and because
an absence is easy to mistake for something nobody looked for.

- **No minimum.** Only "the maximum value is dependent on the range
  set". The floor at a tenth of full scale, which the bench measured on
  2026-08-24 and which the driver depends on, is undocumented behaviour.
- **No reset default.** Both tables say "Required parameter" in the
  *Default value* column, which describes the parameter, not the state
  after `*RST`. The reset values this project uses — 100 nA on R1uA,
  200 mV on R2V — are measured, not read here.
- **No `MIN`/`MAX` parameter form**, so the instrument cannot be asked
  for its own bounds.
- **No negative or low form.** The SOURce subsystem index lists
  `CURRent`, `VOLTage`, `MEMory` and their `RANGe`/`LIMit`/`TRIGgered`
  variants and nothing else. There is no `:LIMit:NEGative` or
  `:LIMit:LOW`. Both pages say **"maximum bounds"**, singular in
  direction, and the bench has since found the negative direction
  behaving differently — see the instrument note.
- **No source-function command anywhere in the subsystem.** Which
  quantity is being sourced is decided by whichever of `SOUR:VOLT` /
  `SOUR:CURR` was written last. It is not a state the instrument has.

## One inconsistency in the page itself

The `CURRent:LIMit` example sets **0.8 A**, and the U2722A's maximum
output current is 120 mA — the value in its own example is one the
instrument cannot accept. Probably inherited from a shared template.
Worth knowing before treating any other number on these pages as
authoritative for this model.
