---
type: reference
title: "Sweeps and transports"
---

# Sweeps and transports

Two seams that both exist for the same reason: the layer above should
not have to know which instrument is underneath.

## Sweeps

Some instruments sweep on their own timebase; the rest are stepped from
the host. `BaseSMU` owns the software sweep, and a driver that has a
hardware one overrides it. `SWEEP_KIND` declares which, and **every run
records it in the CSV.**

That column is not bookkeeping. A hardware sweep's point spacing comes
off the instrument's clock; a software sweep's comes off host and bus
latency, which depends on what else the machine was doing. They are not
equivalent measurements, and a file that does not say which it was
cannot be compared with one that does.

The 2611A pays about 2.1 s of fixed setup for its hardware sweep, so it
looks slow on five points and is genuinely fast on two hundred. The
miniSMU's onboard sweep is **voltage-only**, so a current sweep falls
back to software on the same connection — the first instrument where two
datasets from one box can honestly disagree about `sweep_kind`.

Two hardware sweeps are deliberately not wired up — the 2635B's and the
B2901A's — on the grounds that the GSM's cost three separate bench-found
deviations that no offline test could reach. The inherited software
sweep reads back every level it sources, so the measurement is sound and
only the timing is host-dependent. Upgrading either is one file, and
nothing in `experiments/` changes.

**Anything a sweep changes, a sweep must put back.** See
[State left behind by a sweep](../faults/13-state-left-by-a-sweep.md).

## Transports

`core/transports/base.py` is the contract: open, write, read, query,
clear, and a `connection_key()` that [Instrument ownership](ownership.md) locks on.

The assumption worth naming is **request/response**. One command, at
most one reply, in order. Everything above the transport depends on it,
and three things have broken it:

- **A timed-out query is not a self-contained failure.** The late reply
  sits in the output buffer and the next query collects it, putting the
  session one command out of step. One slow reading on a 2401 became
  three consecutive failures and a warning. `clear()` exists for this.
- **TSP has no query punctuation.** A 2600B replies when the script
  calls `print()`, so a tool deciding what to read by looking for `?`
  sends every `print(...)` as a write and reads the previous line's
  answer thereafter — see
  [A diagnostic tool with the fault it diagnoses](../faults/20-a-tool-with-the-fault-it-diagnoses.md).
- **A library is not a wire.** The miniSMU's documented interface is a
  Python package that opens the port itself, so `MiniSMUTransport` wraps
  an object rather than moving text. Its `_write`/`_read` raise; only
  `*IDN?` is mapped, to keep auto-detection on the same path as every
  other instrument.

`VisaTransport` scans **every** VISA backend and merges the results for
listing, falling through at connect. A vendor library and pyvisa-py do
not enumerate the same instruments, and the symptom is an instrument
plugged in, powered on, and simply absent from the dropdown —
deviations 35 and 36. `tools/visa_doctor.py` is the diagnostic for
exactly that.

`NullTransport` is demo mode, and it goes through the **real** connect
path: it answers `*IDN?` with a dummy identity and the registry resolves
it like anything else, so demo exercises the threading and
dropdown-refresh code rather than bypassing it.
