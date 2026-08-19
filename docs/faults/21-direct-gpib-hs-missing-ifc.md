---
type: fault
fault: 21
title: "Direct GPIB-HS opened but returned NO_BUS"
---

# Direct GPIB-HS opened but returned `NO_BUS`

## Symptom

On the first Windows bench run of the optional direct NI GPIB-USB-HS path,
`NIUSBGPIB()` opened a genuine `3923:709b` adapter through WinUSB/libusb, but the
very first GPIB command failed with `GpibError: command error NO_BUS`. The same
error occurred for a bare UNL (`0x3f`), before any instrument address or SCPI
command was involved. The same Keysight B2901A and IEEE-488 cable were already
known good under NI's driver.

## Isolation

The PyUSB backend, USB descriptors and bulk endpoints were healthy. Re-applying
USB configuration 1 did not change the failure. The decisive probe sent the NI
USB `IBSIC` operation used for interface clear:

```text
OUT 02: 0f 00 00 00 04 00 00 00
IN  84: 0f 00 30 00 ff ff ff ff 04 00 00 00
```

Immediately after that IFC pulse, bare UNL succeeded and a query to GPIB address
9 returned the B2901A identity string. That makes the missing controller/bus
transition causal rather than a timing or SCPI hypothesis.

## Cause

`ni-gpib-usb-hs==0.1.0` initialises the TNT4882 and sets the system-controller
state, but on this Windows/WinUSB path that was not sufficient to make command
transfers usable. The established NI USB-GPIB reference implementation exposes a
separate `IBSIC` operation to pulse IFC. Without that pulse the adapter reported
`NO_BUS`.

## Fix

`NIUSBGPIBTransport` pulses IFC after every new master-controller construction.
That includes the initial connection and the reopen used by timeout recovery. If
the IFC USB transaction fails or returns an unexpected response, the new
controller is closed and the connection fails rather than continuing in a state
that cannot address the bus.

The workaround stays in the optional direct transport. No SMU driver, VISA path,
or experiment knows about it.

## Guard

`tests/test_ni_gpib_usb_hs_transport.py` pins the exact eight-byte IBSIC request,
bulk endpoints, the bench-observed 12-byte response shape, one IFC pulse per
controller construction, and close-on-IFC-failure behavior. These tests are
synchronous and touch no hardware.

## Bench confirmation

After the transport fix was applied, the same Windows bench completed
`tools/smu_checkup.py --transport gpib-hs --address GPIB0::9::INSTR` through
Tiers 1, 2 and 3 against the Keysight B2901A. No further `NO_BUS` occurred.
That closes the observed fault for the validated adapter/revision and confirms
that the IFC pulse belongs in controller bring-up rather than in an instrument
driver or command workaround.
