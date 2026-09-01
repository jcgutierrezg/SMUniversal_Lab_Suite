---
type: manual
instrument: gwinstek-gsm20h10
title: "GSM-20H10 — buffer feed and error queue"
---

# GSM-20H10 — buffer feed and error queue

Transcribed 2026-08-27 from the GSM-20H10 programming manual, with what
firmware **V1.16** actually does recorded alongside. They differ, and
the difference cost a bench session.

## `:TRACe:FEED <name>`

> Selects the source of readings to be placed in the buffer. With
> `SENSe[1]` selected, raw readings are placed in the buffer when
> storage is performed. With `CALCulate[1]`, math expression results
> (Calc1) are placed in the buffer. With `CALCulate2`, Calc2 readings.
> **`TRACe:FEED` cannot be changed while buffer storage is active.**

| `<name>` | effect |
|---|---|
| `SENSe1` | raw readings in buffer |
| `CALCulate1` | Calc1 readings in buffer |
| `CALCulate2` | Calc2 readings in buffer |

Manual's example: `:TRACe:FEED SENSe1`

### What V1.16 accepts — measured 2026-08-27

| written | result | `TRAC:FEED?` afterwards |
|---|---|---|
| `SENS` | accepted | `SENSe1` |
| `SENSe1` | **`-140` Character data error** | unchanged |
| `SENS1` | **`-140`** | unchanged |
| `SENSE1` | **`-140`** | unchanged |
| `RAW` | **`-140`** | unchanged |
| `CALCulate1` | accepted | `CALCulate1` |

**The firmware rejects the exact token the manual gives as its example,
and the exact token the instrument itself reports.** `TRAC:FEED?`
returns `SENSe1`; writing `SENSe1` back is refused. It is not a general
long-mnemonic problem, because `CALCulate1` is accepted in full with its
suffix.

`SENS` is the form that works.

### `:TRACe:FEED?` exists and answers

Undocumented in the section above, but present, and it replies in about
10 ms. It reports the active feed source, which is the only way to know
what the buffer is actually storing.

**This matters more than the spelling.** A buffer left on `CALCulate1`
returns math results where the suite expects raw readings — plausible
numbers, wrong ones, with nothing in the data to say so. An instrument
can be left that way by anything that touched it previously.

## `:SYSTem:ERRor` family

| Command | Function |
|---|---|
| `:SYSTem:ERRor[:NEXT]?` | Oldest message, removed from the queue. FIFO, holds up to 10. |
| `:SYSTem:ERRor:ALL?` | All messages, all removed. |
| `:SYSTem:ERRor:COUNt?` | Decimal count of messages in the queue. |
| `:SYSTem:ERRor:CODE[:NEXT]?` | Oldest code only, message omitted, cleared from the queue. |
| `:SYSTem:ERRor:CODE:ALL?` | All codes only. |

The manual does not say what `[:NEXT]?` returns when the queue is empty.
Measured 2026-08-27: it returns `0,"No error"` in about 8 ms, the same
as `:ALL?`.
