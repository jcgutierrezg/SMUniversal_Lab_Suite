---
type: reference
title: "Instrument ownership"
---

# Instrument ownership

`core/ownership.py`. Exclusive, application-wide, and keyed on the
*connection* rather than on the driver object.

## The hotel key

An instrument is a room. A tab wanting to measure takes the key; while
it holds the key nobody else gets in; when the run ends the key goes
back automatically, because it was borrowed inside a context manager
rather than handed over.

The important part of the analogy is the last one. The claim is released
by the run's `ExitStack` unwinding, so a run that crashes mid-way still
returns the key. Ownership that depends on the borrower remembering to
return it is ownership that leaks the first time something raises.

## Why keyed on the connection, not the object

Two tabs can hold two `Keithley2611A` objects pointing at the same
`GPIB0::26::INSTR`. As Python objects they are unrelated; as hardware
they are one instrument, and driving both at once interleaves two
command streams into one session.

So `Transport.connection_key()` produces the identity — transport type
plus address — and that is what the registry locks on.

**Demo mode falls back to identity**, because `NullTransport` has no
address. Two demo windows are therefore two simulated samples rather
than two claimants contending for one imaginary instrument, which is
what you want: the point of demo mode is to exercise the real paths, not
to inherit a constraint that has no physical meaning.

## What it prevents

`InstrumentBusy` is raised at claim time, not discovered at command
time. The alternative — two runs writing to one instrument and finding
out from the data — is the failure this whole codebase is arranged
against: no error, and two datasets that each look fine.
