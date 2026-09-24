---
type: reference
title: "72-13200 command summary"
---

# Multicomp Pro 72-13200 — command summary

Transcribed from *Communication Commands with Computer V2.10*, the
command table only. The PDF is not committed; see `manuals/README.md`.

**The document is written for a product family, not for this model.**
Its examples answer `>150V` and `>300W` where the 72-13200 is 120 V and
150 W. Nothing in [the driver's](https://github.com/jcgutierrezg/SMUniversal_Lab_Suite/blob/main/smuniversal_lab_suite/drivers/multicomp_72_13200.py)
`LIMITS` comes from here — the envelope is transcribed from the
72-13200's own specification table.

The source PDF uses a full-width `？` (U+FF1F) in several headers, an
artefact of a Chinese-language original. The real character is an ASCII
`?`; a query sent with U+FF1F would never be answered, and an unanswered
query latches the transport.

## What the driver uses

| Command | Query | Meaning |
|---|---|---|
| — | `*IDN?` | product information |
| `:INPut <Boolean>\|OFF\|ON` | `:INPut?` | enable/disable the input |
| `:FUNCtion CV\|CC` — **not** the documented `VOLT\|CURR` | `:FUNCtion?` → `CV`/`CC` | regulation mode. See the correction below |
| `:VOLTage <NR2>` | `:VOLTage?` | CV setpoint |
| `:CURRent <NR2>` | `:CURRent?` | CC setpoint |
| — | `:MEASure:VOLTage?` | terminal voltage, e.g. `1.4999V` |
| — | `:MEASure:CURRent?` | sink current, e.g. `0.789A` |
| — | `:MEASure:POWer?` | power, e.g. `1.1968W` |
| `:VOLTage:UPPer <NR2>V` | `:VOLTage:UPPer?` / `:LOWer?` | voltage ceiling / floor. **Settable**, despite the table |
| `:CURRent:UPPer <NR2>A` | `:CURRent:UPPer?` / `:LOWer?` | current ceiling / floor. **Settable**, despite the table |

## Corrections, measured 2026-09-15 on firmware V3.30

The table above is what the driver sends. It is **not** in every case
what this document says, and the differences were found at the bench
rather than read:

| The document says | The instrument does |
|---|---|
| `:FUNCtion` takes `VOLT\|CURR\|RES\|POW\|SHORT`, example `:FUNCtion VOLT` | takes **`CV`/`CC`**. `VOLT` and `CURR` are accepted and ignored — the mode does not move and nothing is said |
| `:FUNCtion?` → `VOLT` | → `CV` or `CC`. Set and query share one vocabulary; the document's example contradicts its own table |
| `:VOLTage <NR2>` | the unit suffix is **mandatory**. `:VOLTage 6.789` is ignored; `:VOLTage 6.789V` lands |
| nothing about a minimum | the CV setpoint **clamps silently at 0.1 V**. 0.05 V, 0.01 V and 0 V all leave `:VOLTage?` reading `0.1000V`. `:VOLTage:LOWer?` reports 0.1 V and is honest. The CC axis has no such floor |
| `:CURRent:UPPer` / `:VOLTage:UPPer` are query-only ("Setup: no") | **both are settable.** `:CURRent:UPPer 3A` moves the ceiling; the unit suffix is mandatory (`:CURRent:UPPer 3` is ignored) and `:CURR:UPP 3A` works. Verified twice over: the query reports it, and an over-large setpoint then clamps to it |
| the ceilings are the two ranges in the spec table | intermediate values are accepted too — 5 A and 15 A land exactly. What that means for the full-scale accuracy term is unmeasured |
| `*IDN?` returns product information | returns a **sentence**, not the four comma-separated fields of the standard: `Multicomp Pro 72-13200 V3.30 SN:00028215` |
| — | `*RST` is absent **and inert**: sent after a distinctive setpoint, the setpoint was unchanged |

The `:FUNCtion` error is the one that cost something. A driver written
from this document alone runs every voltage sweep as a constant-current
sink and returns a full set of plausible readings, because there is no
error queue for the instrument to object with.

## Present and deliberately unused

| Command | Why not |
|---|---|
| `:FUNCtion SHORT` | shorts whatever is attached — the user manual says it makes the equipment "output the max current". Not a measurement mode |
| `:LIST`, `:RCL:LIST` | a real hardware stepper, but it steps **current** in whole-second dwells with **no measurement buffer**, so the host still polls and loses track of which step a reading belongs to |
| `:OCP`, `:OPP` | **not protection setters.** These run a test profile that ramps a DUT until *its* protection trips. Easy and dangerous to misread as limit setting |
| `:BATTery`, `:BATT:TIM`, `:BATT:CAP` | battery discharge; no experiment here uses it |
| `:DYNamic` | dynamic/pulse/flip modes |
| `:RESistance`, `:POWer` | CR and CW regulation — real, but not reachable from the driver |
| `*SAV`, `*RCL` | 100 setup memories, front-panel workflow |
| `*TRG` | external trigger, pulse/flip modes only |
| `:SYSTem:BEEP\|BAUD`, `:STATus?` | buzzer and baud rate |

## What is absent, and matters

| Missing | Consequence |
|---|---|
| **`:SYST:ERR?` or any error queue** | a wrong header is ignored in silence. `:STATus?` returns the buzzer state and baud rate and says the rest is "to be determined". Readback is the only verification available |
| **`*RST`** | nothing resets anything. [Fault 6](../../faults/06-inherited-state.md) is structural here |
| **Remote sense** | 4-wire is the front-panel "remote compensation function" (SHIFT+CW). No command exists |
| **Integration time** | no NPLC or aperture control of any kind |
| **Source delay** | no settle-time command; the software sweep applies its delay host-side |
| **Range selection** | the per-quantity ceilings are entered at the front panel (SHIFT+CV). Whether `:CURRent:UPPer?` reports that ceiling or the fixed hardware maximum is the first open question in the [instrument note](../../instruments/multicomp-72-13200.md) |

## Reply format

Every reply carries its unit: `0.789A`, `1.4999V`, `20OHM`, `5.00AH`,
`5.00M`. The note in the source document lists volts, amps, A/µs,
ohms, watts, seconds or minutes, amp-hours and per cent.

This is unique in the fleet and it is a trap rather than a nuisance: a
raw `'0.789A'` passed to `BaseInstrument.drop_sentinel()` fails to parse
inside its `except (TypeError, ValueError)` and comes back `None` — a
reading that existed, discarded, with nothing raised and nothing logged.
The driver strips the unit **before** the sentinel check.
