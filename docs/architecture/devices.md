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

## Four fleets of driver, one test

"Carries the measurement" is deliberately not "sources into the sample".
An electronic load carries the measurement without sourcing anything -
it sets the operating point by how much it sinks, and the sample is what
pushes. So it is a driver, and it is not an SMU.

That is why `drivers/` forks one level down. `BaseInstrument` holds what
is true of any instrument on a transport: the identity, the no-reading
sentinel, the readback grading, the software sweep engine, and the
optional-capability declarations the GUI reads. `BaseSMU` adds a source
function, levels, a compliance, the four-axis `RangePlan` and a source
converter with a bottom count. `BaseLoad` adds a regulation mode,
operator-set ceilings it can only read, a declared quadrant, and a
headroom floor. `BaseSupply` adds two settings that are each a level and
a compliance at once, a floor under the current, one fixed range, and an
over-voltage trip. `BaseMeter` sets no level at all: it adds a range,
an integration time and an input resistance, each read back.

A load is **not** a `BaseSMU` subclass, and the reason is not tidiness:
`issubclass(load, BaseSMU)` would be true, so any guard written against
that would wave it through in the dangerous direction. The same holds
for a supply. The registry keeps `KNOWN_SMUS`, `KNOWN_LOADS` and
`KNOWN_SUPPLIES` separate and identifies from the union, so the SMU
contract suites are never asked to grade a load or a supply against
questions that do not apply to it.

**Nothing in `experiments/` or `core/gui/` may know which fleet it is
holding.** They ask about declared capabilities - `supports_nplc()`,
`supports_ovp()`, `supports_compliance()` - exactly as they already did,
and `tests/test_instrument_contract.py` scans both packages and fails on
any call that reaches past the shared surface without a recorded reason.

## A supply is a driver that can also be a device

The test at the bottom of this page says a magnet supply is a device,
and it still is: wired to a coil, nothing reads a measurement off it. A
bench supply holding a rail and logging its own voltage and current
*is* carrying that measurement, coarsely. The same instrument is on
both sides of the line depending on what it is wired to.

So it is a driver - it has a contract, a checkup, a note and a
fingerprint - and it is **by invitation**. Being a driver does not make
it suitable for every measurement: it sources and has a compliance, so
on capabilities alone a four-contact tab would accept it and ask a
converter whose smallest step is 10 mA for 100 uA.

`BaseSupply` therefore fills in `ROLE_CAVEATS` (declared, empty, on
`BaseInstrument`) - named limitations, each
with the reason it matters - and an experiment's role takes the
instrument only where `ROLE_ACCEPTS` lists every one. Empty by default,
so an experiment that has not thought about supplies refuses them at
Connect, with the caveat's own text as the reason. It is the mirror of
`ROLE_REQUIRES`: that one is what a role needs an instrument to have,
this is what a role has agreed to put up with. An experiment still
never learns which instruments carry the caveat.

The roles a supply is *for* - a bias rail, a heater, a lamp - are not
the `source` role of any experiment here, and will arrive as roles of
their own.

## An SMU that sources one quantity is still an SMU

The Keithley 487 is a picoammeter with a ±500 V source beside it. It
holds a voltage and measures the current that results, and it cannot
do the reverse. That is a source-measure unit with half its modes
missing, not a fourth fleet: a fleet is for an instrument whose
contract would be half meaningless questions, and the 487 answers every
question of the voltage half.

What it needed instead was a declaration. `SOURCE_FUNCTIONS` on
`BaseInstrument` names the quantities an instrument can hold - both, by
default - and `supports_current_sourcing()` is what Van der Pauw, Hall
and 4PP now require alongside `sourcing`. IV sweep and Fixed Source
grey out the mode the instrument lacks. This is a capability, not a
caveat: a caveat is "it can, but badly", and the 487 cannot.
`MEASURE_FUNCTIONS` is its mirror - what `measure()` returns a number
for - so that the 487's missing voltage reads as an answer and not as a
reply that failed to parse.

Two more declarations came with it, both because its compliance is
unlike every SMU before it. `COMPLIANCE_CHOICES` makes the compliance a
menu where the hardware offers only fixed values (25 uA or 2.5 mA), and
`COMPLIANCE_SETS_MEASURE_RANGE = False` stops the panels deriving the
measurement range from it - which would hold a picoammeter on its
200 uA range.

## An SMU that measures only what it does not source

The Keithley 236 is a full SMU - it holds either quantity - but it
measures only the other one. Sourcing current, the current in its reply
is the programmed value. So it passes `supports_current_sourcing()`, and
the four-contact windows, which divide a measured voltage by a measured
current, would accept it on that alone.

That is a caveat, not a missing capability: it can do the job, with a
programmed number standing in for a measured one. It declares
`sourced_quantity_not_measured` in `ROLE_CAVEATS`; IV sweep and Fixed
Source accept it, because both already record the commanded level where
no measurement of it exists, and the four-contact windows do not.
`measure()` returns None for the sourced quantity, and
`MEASURES_SOURCED_QUANTITY = False` tells the checkup that None is the
answer. Both live on the driver for now, so that no other instrument's
checkup went stale for it - see [technical debt](../open/technical-debt.md).

## A meter sets nothing

The Keysight 34401A reads a voltage across its input and sets nothing.
By the test at the bottom of this page it is a driver whenever its
reading is the measurement - a voltmeter across the sense corners of a
film carries that measurement as surely as the SMU pushing the current
does. But every other fleet's contract is mostly about setting an
operating point, and a meter answers none of those questions. The 487
became an SMU because it answers the voltage half; a meter answers no
half. That is what a fleet is for, so `BaseMeter` is the fourth, even
with one member.

It implements the source methods `BaseInstrument` declares abstract as
refusals, and `output_off()` as a write that has nothing to send and so
always succeeds - every exit path calls it on every instrument. The
shared base was not edited to make room, so adding the fleet staled no
other instrument's checkup.

It is refused by every experiment through a caveat, `measures_only`,
for the reason a supply is refused by most: IV sweep and Fixed Source
require nothing of their `source` role, because a load has to pass, and
on declarations alone they would take a meter and fail at Run. Strictly
that is a capability rather than a caveat; it becomes one at the next
round that edits the shared base (see
[technical debt](../open/technical-debt.md)). The connection check asks
the caveat first, so the operator reads "it is a multimeter" in every
window rather than advice to try an IV sweep.

The role a meter is *for* - most likely a voltmeter beside an SMU in
the four-contact tabs - will be a second role in those experiments,
not an invitation into `source`. `ROLES` has always been a dict for
that reason; no experiment has used two yet.

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
