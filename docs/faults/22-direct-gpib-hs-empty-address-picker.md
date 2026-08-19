---
type: fault
fault: 22
title: "Direct GPIB-HS address picker was empty"
---

# Direct GPIB-HS address picker was empty

## Symptom

After Windows/B2901A commissioning passed, selecting **NI GPIB-HS** in
`main.py` left the address combobox empty. Manually typing
`GPIB0::9::INSTR` connected and completed a run, so the transport and SMU
path were healthy and the defect was limited to GUI address population.

## Cause

The direct transport intentionally returns no instrument resources from
`list_available()`: it can discover the USB controller but does not scan the
IEEE-488 bus for occupied primary addresses. The connection panel used that
same discovery result as the combobox contents, turning the correct "do not
invent discovered instruments" rule into an empty picker.

## Fix

`NIUSBGPIBTransport.address_choices()` now exposes `GPIB0::1::INSTR` through
`GPIB0::30::INSTR` as valid **manual candidates**. `_refresh()` uses those
candidates for the combobox while leaving the discovery result unchanged, so
no address is represented as detected and no address is selected implicitly.
Address 0 is omitted because the direct controller uses primary address 0.
Manual entry remains supported and `connect()` remains the validation authority.

## Guard

`tests/test_direct_gpib_address_choices.py` separately pins the candidate range
and the GUI distinction between zero discovered resources and populated manual
choices. The tests are synchronous and touch no hardware.
