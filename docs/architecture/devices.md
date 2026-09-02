---
type: reference
title: "Devices — why the stage is not a driver"
---

# Devices — why the stage is not a driver

`devices/temperature_control.py` drives a Seeeduino Xiao (SAMD21) hot/cold
stage over a serial side channel. It sits in its own package rather than
under `drivers/`, and that is a deliberate boundary.

## The distinction

A **driver** is a source-measure unit: it sources into the sample and
measures what comes back, it is claimed exclusively for the duration of
a run, and it is what [Instrument ownership](ownership.md) locks on. Everything under
`drivers/` implements `BaseSMU` and is discovered through the registry.

A **device** is anything else attached to the rig. The stage changes the
sample's temperature; it never carries the measurement current, it is
not claimed per run, and it has no `LIMITS`, no ranging, no compliance
and no sweep.

Putting it under `drivers/` would mean it either implements a contract
that makes no sense for it, or the contract grows optional halves — and
`tests/test_checkup_all_drivers.py` discovers drivers from the registry
precisely so that no driver can quietly opt out of the contract.

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
