---
type: instrument
title: "Dummy SMU (demo mode)"
driver_class: DummySMU
idn: "Anthropic Lab Suite,DUMMY SMU,0,1.0"
idn_confirmed: true
physical: false
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: false
last_bench: null
bench_notes: "simulated - there is no instrument to commission"
bench_code: null
bench_result: null
bench_result_note: null
bench_revalidated: null
reading_time: "instant"
resolution: "exact"
best_for: "development and demo without hardware"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/dummy_smu.py
model_ids: "['DUMMY SMU']"
max_voltage_v: 200
max_current_a: 1
voltage_ranges_n: 5
current_ranges_n: 9
power_envelope_n: 2
sweep_kind: hardware
nplc_min: 0.01
nplc_max: 10
high_z_off: true
ovp: true
remote_sense_control: true
compliance_trip: false
# --- end generated ---
---

# Dummy SMU (demo mode)

A simulated resistive sample that sources, clamps at compliance, and
returns noisy readings. `physical: false`, so it is excluded from the
bench chooser table and from [checkup-owed](../open/checkup-owed.md) — offering a simulated SMU
as a measurement option, or demanding a bench session for a thing with
no bench, would both be wrong.

It still gets a note, and the driver↔note bijection still applies to it.
Demo mode is not allowed to quietly diverge from the real drivers.

## Identity and envelope

Declares a 200 V / 1 A envelope with a two-corner power envelope and a
full complement of capabilities, so demo exercises the same GUI paths
a real instrument would.

## Decisions and deviations

**Demo mode goes through the normal connect path**, deliberately.
`NullTransport` answers `*IDN?` with a dummy identity and the registry
resolves it like any real instrument, so demo exercises the *real*
connect, threading and dropdown-refresh code. Bugs there surface at the
desk rather than only on the bench.

**The default sample is symmetric, which makes it a self-check as well as a
stand-in.** A Van der Pauw run where all four positions read the same R has a
closed-form answer:

```
Rs = pi * R / ln(2)     # a 1000 ohm sample -> 4532.36 ohm/square
```

`tests/test_demo_mode.py` drives a full four-position run and checks against
it, so the demo is not merely something that returns numbers — it is
something whose numbers are known in advance. `SAMPLE_RESISTANCE`,
`NOISE_FRACTION` and `ANISOTROPY` at the top of `drivers/dummy_smu.py` are
the knobs while developing. Setting anisotropy away from 1.0 drops the
analytic check, deliberately: the closed form no longer applies, and a check
that kept running there would be comparing against the wrong answer.

**Real hardware can never land in simulation by accident.**
`DummySMU.MODEL_IDS` matches only the identity string `NullTransport`
returns, so nothing that answers `*IDN?` for itself can resolve here.

**Its ownership key falls back to identity.** `NullTransport` has no
address, and `Transport.connection_key()` normally keys on transport
type plus address. So two demo windows are two simulated samples rather
than two claimants contending for one imaginary instrument.

**It is one of two drivers exempt from the sentinel test**, alongside <!-- lint-ok -->
[Undalogic miniSMU MS01](undalogic-minismu.md), because it computes its readings rather than
parsing a reply. The test guards the exemption list itself.

## What this means for your data <!-- bench -->

**Nothing here is a measurement.** If a saved file names this driver,
the numbers came from a simulation.

Demo mode is genuinely useful for learning the interface, checking a
save path, or rehearsing a run sequence before the sample is mounted.
Pick **Demo** in the transport dropdown, or accept the offer when a
connection attempt fails.

## Open questions

None. It is a fake, and it is meant to be.
