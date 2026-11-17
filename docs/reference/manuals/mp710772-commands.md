---
type: reference
title: "MP710772 command summary"
---

# Multicomp Pro MP710772 — command summary

**There is no manual to transcribe.** This table is what the instrument
answered when asked, on 2026-11-17 at firmware V1.14, by
`tools/bench_mp710772.py`. The report is
`checkups/20261117/bench_MP710772_20261117_124656.md`. The only document
with commands in it, *IP LAN Communication Protocol*, covers the network
settings and nothing else.

The dialect is the [72-13200's](72-13200-commands.md), confirmed command
by command rather than assumed from the shared maker.

## What the driver uses

| Command | Query | Meaning |
|---|---|---|
| — | `*IDN?` → `MP710772 V1.14 SN:0000023205` | identity; a sentence with no brand |
| `:INPut ON\|OFF` (also `:INP 1\|0`) | `:INPut?` → `ON`/`OFF` | enable/disable the input |
| `:FUNCtion CV\|CC` | `:FUNCtion?` → `CV`/`CC` | regulation mode |
| `:VOLTage <NR2>V` | `:VOLTage?` → `2.3400V` | CV setpoint; unit mandatory |
| `:CURRent <NR2>A` | `:CURRent?` → `0.2340A` | CC setpoint; unit mandatory |
| — | `:MEASure:VOLTage?` → `05.034V` | terminal voltage, zero-padded |
| — | `:MEASure:CURRent?` → `00.199A` | sink current, positive |
| — | `:MEASure:POWer?` → `00.999W` | power |
| `:VOLTage:UPPer <NR2>V` | `:VOLTage:UPPer?` → `150.00V` | voltage ceiling; writable |
| `:CURRent:UPPer <NR2>A` | `:CURRent:UPPer?` → `40.000A` | current ceiling; writable |

## What the probe established

| Asked | Found |
|---|---|
| `:FUNC CV`, `:FUNC CC`, `:FUNC CV` | moved CV, CC, CV; the screen agreed |
| `:MODE CV/CC` (the community driver) | ignored; `:MODE?` never answers |
| `:FUNC VOLT/CURR`, `:MODE VOLT/CURR` | ignored |
| `:CURR 0.123` / `:VOLT 1.23` | ignored - the unit is mandatory |
| `:CURRent 0.345A` / `:VOLTage 3.45V` | land - long headers work |
| `:VOLT 0.05V`, `0.01V`, `0V` | clamp to `0.1000V`; `:VOLT:LOW?` says 0.1 V |
| `:CURR:UPP 3A`, then `:CURR 10A` | ceiling 3 A, setpoint clamped to 3 A |
| `:VOLT:UPP 18V`, then `:VOLT 20V` | ceiling 18 V, setpoint clamped to 18 V |
| `:CURR:UPP 5A`, `:VOLT:UPP 30V` | land - intermediate ceilings accepted |
| `*RST` after `:CURR 0.321A` | nothing changed |

## Present and deliberately unused

| Command | Why not |
|---|---|
| `:RES?`, `:POW?` → `50.200OHM`, `12.100W` | CR and CW setpoints; those modes are not reachable from the driver |
| `:RES:UPP?`, `:POW:UPP?` → `7500.0OHM`, `500.10W` | their ceilings, likewise |
| `:STATus?` → `1,4,0,0,0,0` | undocumented |
| `:SYST:DEVINFO?` | **answers on seven lines** - DHCP, IP, netmask, gateway, MAC, port, baud rate. A reader expecting one line takes the second as the next query's reply |
| `:SYST:IPADdress`, `:SMASK`, `:GATEway`, `:DHCP`, `:PORT`, `:BAUDrate`, `:FACTRESET` | the LAN settings, from the protocol document; not this driver's business |

## What is absent, and matters

| Missing | Consequence |
|---|---|
| `:SYST:ERR?`, `*STB?`, `*ESR?` | never answered: no error queue, so a wrong header is ignored in silence and readback is the only check |
| a working `*RST` | inherited state is structural, as on the 72-13200 |
| remote sense | front panel only: Config > Remote Comp |
