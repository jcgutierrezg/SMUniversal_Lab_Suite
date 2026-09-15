---
type: reference
title: "Devices — why the stage is not a driver"
---

# Devices — why the stage is not a driver

`smuniversal_lab_suite/devices/temperature_control.py` drives a Seeeduino Xiao (SAMD21) hot/cold
stage over a serial side channel. It sits in its own package rather than
under `drivers/`, and that is a deliberate boundary.

## The distinction

A **driver** carries the measurement: it sets the operating point and
reads back what happened, it is claimed exclusively for the duration of
a run, and it is what [Instrument ownership](ownership.md) locks on.
Everything under `drivers/` implements `BaseInstrument` and is
discovered through the registry.

A **device** is anything else attached to the rig. The stage changes the
sample's temperature; it never carries the measurement current, it is
not claimed per run, and it has no `LIMITS`, no ranging, no compliance
and no sweep.

Putting it under `drivers/` would mean it either implements a contract
that makes no sense for it, or the contract grows optional halves — and
`tests/test_checkup_all_drivers.py` discovers drivers from the registry
precisely so that no driver can quietly opt out of the contract.

## Two fleets of driver, one test

"Carries the measurement" is deliberately not "sources into the sample".
An electronic load carries the measurement without sourcing anything —
it sets the operating point by how much it sinks, and the sample is what
pushes. So it is a driver, and it is not an SMU.

That is why `drivers/` forks one level down. `BaseInstrument` holds what
is true of any instrument on a transport: the identity, the no-reading
sentinel, the readback grading, the software sweep engine, and the
optional-capability declarations the GUI reads. `BaseSMU` adds a source
function, levels, a compliance, the four-axis `RangePlan` and a source
converter with a bottom count. `BaseLoad` adds a regulation mode,
operator-set ceilings it can only read, a declared quadrant, and a
headroom floor.

A load is **not** a `BaseSMU` subclass, and the reason is not tidiness:
`issubclass(load, BaseSMU)` would be true, so any guard written against
that would wave it through in the dangerous direction. The registry
keeps `KNOWN_SMUS` and `KNOWN_LOADS` separate and identifies from the
union, so the SMU contract suites are never asked to grade a load
against questions that do not apply to it.

**Nothing in `experiments/` or `core/gui/` may know which fleet it is
holding.** They ask about declared capabilities — `supports_nplc()`,
`supports_ovp()`, `supports_compliance()` — exactly as they already did,
and `tests/test_instrument_contract.py` scans both packages and fails on
any call that reaches past the shared surface without a recorded reason.

## What it means in practice

`self.temp_ctrl` exists on every experiment already, and one line in
`PANELS` adds the panel — see [The temperature stage is one line](../rules/04-temperature-stage.md).

The temperature is recorded **per run in `metadata`**, so it lands on
each row rather than in a file header. A stage temperature in a header
describes the session; one on the row describes the reading, and a run
taken while the stage was still settling is only visible in the second
form.

`LabApp.shutdown_devices()` turns the PID off and closes the port, and
is called on close — the app's, not the experiment's, because one window
holds one stage. That matters more than it sounds: a stage left driving
is a heater left on in an empty lab.

It goes through `confirm_pid_off()` rather than `pid_off()`. The board
never acknowledges a command, so a write that returned cleanly is not
evidence a heater stopped; the confirmation waits for a status line the
board broadcast **after** the OFF, reporting a state that is not
`HEATING` or `COOLING`. Anything else is `UNCERTAIN` and the operator
gets a modal warning telling them to switch the stage off at the
controller itself. The bare `pid_off()` stays for the panel's OFF
button, where somebody is watching the readout.

See [A shutdown path that fails open](../faults/29-a-shutdown-that-fails-open.md).

## Why it earns a mention in the architecture

Because the natural instinct when adding hardware is to write a driver
for it. The test is not "does it plug into the rig" but **"does it carry
the measurement?"** A switch box, a magnet supply and a probe station
would all be devices. A second SMU is a driver.
