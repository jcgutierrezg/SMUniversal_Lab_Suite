---
type: architecture
title: "Direct NI GPIB-USB-HS transport"
---

# Direct NI GPIB-USB-HS transport

An optional, explicitly selected transport for a bench machine that needs
a genuine NI GPIB-USB-HS but must not carry NI-VISA or NI-488.2.
`NIUSBGPIBTransport` wraps `ni-gpib-usb-hs==0.1.0` behind the same
`Transport` contract the drivers already use.

**Commissioned on Windows against a Keysight B2901A**, 2026-08-18: a
genuine `3923:709b` revision `0x0101` through WinUSB and bundled libusb,
Tiers 1, 2 and 3 all passing. What is still open is in
[Known technical debt](../open/technical-debt.md).

## It is optional and never implicit

- `uv sync` does not install the third-party driver; use
  `uv sync --extra direct-gpib`
- the connection panel starts on **VISA** and never falls back to direct
  USB control
- `tools/smu_checkup.py` infers `visa` from a GPIB resource unless
  `--transport gpib-hs` is written explicitly
- USB probing happens only after that transport is selected, and never
  scans GPIB addresses
- drivers and experiments are unchanged

The upstream package is GPL-2.0-only. Local bench use copies none of its
implementation into this repository, but redistributing or bundling the
optional dependency has to respect that licence.

## Windows prerequisite

The adapter must be reachable through libusb. Bind the genuine
GPIB-USB-HS (`3923:709b`) to the Windows **WinUSB** driver, for example
with Zadig. That replaces the driver association for this adapter on
that installation, so a machine later needing NI's own driver has to
restore it. `libusb-package` supplies the libusb DLL.

## The IFC pulse

Upstream 0.1.0 advertises macOS and Linux. On Windows its constructor
opened the adapter but the first GPIB command returned `NO_BUS` — a bare
UNL failed identically, which excludes the instrument address and the
SCPI layer. Sending the NI USB `IBSIC` operation
(`0f 00 00 00 04 00 00 00`) pulsed IFC, and UNL succeeded immediately
afterwards.

`NIUSBGPIBTransport` performs that pulse after every controller
construction. See
[Direct GPIB-HS opened but returned NO_BUS](../faults/27-direct-gpib-hs-missing-ifc.md).

## Upstream scope limits

Primary addressing only. No serial poll, SRQ, parallel poll, secondary
addressing or multi-controller sharing. **If a driver later depends on
one of those, this transport must refuse that use rather than emulate it
invisibly.**

## Changing this transport

The hardware is optional; the software tests are not. Beyond the normal
[Delivering work](../workflow/delivering-work.md) rules, mutate each
guarantee separately and require a red test for each: make direct GPIB
the default, move its package into normal dependencies, remove the
timeout restoration, change the device-clear command, break the shared
GPIB ownership key, and make a normal VISA refresh probe the direct
adapter.

`tests/test_ni_gpib_usb_hs_transport.py` covers byte-level behaviour;
`tests/test_direct_gpib_optional.py` separately guards the opt-in policy
and the dependency boundary. Keeping them apart makes a failure say
whether the adapter contract broke or the application quietly started
using it by default.
