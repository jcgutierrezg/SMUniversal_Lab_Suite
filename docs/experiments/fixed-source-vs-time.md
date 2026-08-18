---
type: experiment
title: "Fixed sourcing vs time"
module: experiments/fixed_source
origin: "New experiment"
---

# Fixed sourcing vs time

Hold one source level and watch the other quantity against the clock.
Sourcing voltage, it is the current over time; sourcing current, the
voltage. Leakage, bias stress, relaxation after a bias, self-heating,
and anything else whose interesting axis is time rather than level.

## Everything here is a decision

There is no original script. Every other experiment in this vault is a
port, and a port has an answer to "why this number" even when the answer
is only *that is what it did before*. This one does not, so the choices
are written down here and each was signed off before the code existed.

| | Decision | Chosen |
|---|---|---|
| 1 | duration or sample count authoritative | duration |
| 2 | what an early stop does with the data | two controls, two answers |
| 3 | where t = 0 sits | the output-on instant, no settle |
| 4 | a compliance trip mid-run | recorded per sample, run continues |
| 5 | output state at the end | always de-energised |
| 6 | what the plot draws | the measured quantity; the sourced one opt-in |
| 7 | a read that fails mid-series | sampling stops, earlier samples kept |
| 8 | compliance watching | per sample, and switchable |

## Duration is authoritative, and that is a safety property

Two of {duration, interval, sample count} can be chosen and the third
follows. This asks for duration and interval; the count is whatever
lands.

The reason is not statistical. **The duration is how long the sample
spends energised**, and the field exists so that nobody walks away from
a live fixture. A count-authoritative run — "take 3600 samples" — runs
for however long that takes on this instrument at this integration time,
which is precisely the property a timer is meant to remove. A 60 s run
at a 5 ms interval on an instrument that needs 50 ms per reading would
hold the output on for ten minutes.

So the loop is bounded by the **clock**, not by its position on the
nominal grid. A slow instrument delivers fewer samples inside the same
window rather than the same samples over a longer one.

There is no cap on the duration field. An overnight bias-stress run is a
real experiment and the software has no business refusing one; a
confirmation dialog above ten minutes catches the extra zero instead.

### What replaces `expect()`

Every other experiment here hands `RunContext.expect()` an exact count,
and a run that returns fewer is refused — a sweep that returns a third
of its points and fits a beautiful line is a real failure mode on this
bench. That check cannot work here, because the honest sample count is
not knowable before the run.

The guard is a **floor**, and it is conditional:

- a run that reached its **duration** must have collected at least half
  the nominal count. Less than that means the instrument could not meet
  the requested rate, and a trace at an unknown fraction of it is worse
  than no trace;
- a run the **operator** ended, or one cut short by a **read error**,
  needs only two samples. The operator chose the length; two is what
  makes the data a time series at all.

## Two ways to stop, and they are not the same

Everywhere else in this suite Stop means cancel, and a cancelled run's
data is discarded whatever its progress. That is right for a sweep: half
an IV curve is not a shorter IV curve.

A fixed-source run is different in kind — its readings are independent
samples of the sample's behaviour over time, so twenty minutes of an
hour is twenty real minutes. So there are two controls:

```
Finish and save     stop sampling, put the output away, keep the data
Stop and discard    the house Stop, unchanged
```

**Stop keeps its meaning**, which is the load-bearing half. An operator
who has pressed Stop a hundred times on Van der Pauw must not discover
that here it means something else; the new operation gets a new word.

Neither button talks to the instrument. Both set a flag; the worker
notices at its next loop boundary and de-energises **on the thread that
owns the session**. That is the discipline Wave 6 established when it
removed the OFF buttons (decision W6-2) — the old one called into the
driver from a second thread while the worker was mid-`measure()` on the
same session. Finish is a new control but not a new race.

Closing the window **cancels**, it does not finish. A window being torn
down is not an operator deciding they have enough data.

## Two faults this experiment could reproduce, in a new place

**The time column is measured, never `i × interval`.** A reconstructed
axis is [Reconstructed x-axes](../faults/09-reconstructed-x-axes.md) wearing different clothes: it
describes the schedule that was *requested*, so every reason the loop
fell behind becomes invisible in the one column you would look at to
find out. Each row carries `time_s`, when the reading was asked for, and
`read_s`, how long it took.

**The schedule aims at absolute deadlines, not at gaps.** Sleeping the
interval between readings accumulates each reading's cost as drift, so a
nominal 1 Hz run silently becomes 0.8 Hz — [Sweep completion slept rather than polled](../faults/05-slept-not-polled.md) in a
new place. Samples that land more than half an interval late are counted,
the worst is recorded, and the **achieved** mean interval is stored
beside the requested one.

### The same fault, twice, through two doors

`0.3 / 0.1` is `2.9999999999999996`. A plain `int()` on that gives three
samples where four were asked for, and the sampling loop — doing the
same division — dropped the sample due at t = 0.3. A 60 s run at 0.1 s
lost its last sample the same way. The run was short by one, entirely
plausibly, and the nominal count that would have revealed it was
computed from the same wrong division, so the two agreed.

Both now carry a tolerance far below any interval an operator can type
and far above the representation error of a decimal like 0.1.

It came back. The clock ceiling had no such grace, and the sample due at
exactly `duration` is the one it lands on: any lateness at all in the
final wait puts elapsed past the ceiling before the sample due *inside*
the window has been taken. Windows CI found it and Linux could not
reproduce it — Windows' default timer granularity is about 15.6 ms, so a
10 ms final wait overshoots by 5 ms and an eleven-sample run returns ten.
The run looked healthy, was one sample short, and sat comfortably inside
the shortfall floor that would otherwise have refused it.

The ceiling now carries a grace of one interval, so **a run may exceed
its requested duration by up to one interval**. That is the stated cost
of not dropping the final sample. It does not weaken what the ceiling is
for: a slow instrument falling a whole interval behind the agreed window
is the runaway case, and it is still stopped there.

Both are the same mistake: a comparison sitting exactly on a boundary,
fixed by deciding what the boundary is *for* rather than by nudging the
number. A sample due at `duration` is inside the window the operator
agreed to.

## Timing is host-stepped, on every instrument

No driver in this suite exposes a hardware sample timer, so the interval
is only as good as the host and the bus. Every run records
`timebase: host` for the same reason a sweep records `sweep_kind`: the
two are not equally trustworthy measurements and a file has to say which
it is.

Some of these instruments could do better — the 2611A has a TSP trigger
timer and timestamped buffers, and the B2901A can fetch a time array —
and adding that is a driver change rather than an experiment one.

## Two things the drivers cannot currently say

**Whether voltage and current are measured at the same instant.** The
U2722A has no combined read: `MEAS:VOLT?` then `MEAS:CURR?`, two round
trips. On a sweep that is harmless, because the level is static and
settled. On a time series of a *changing* sample the two halves of a row
are from different moments, so a per-row V/I is not the resistance at
that time. `read_s` bounds how far apart they could be; a declared
capability would say it outright, and that is an open item.

**Whether a compliance trip happened.** `compliance_tripped()` returns
`None` on instruments that cannot answer, and the run says so at connect
rather than writing a reassuring blank.

## What this means for your data <!-- bench -->

**The time column is what happened, not what was asked for.** If the
instrument could not keep up, the gaps in `time_s` say so and
`interval_achieved_s` in the header says so more compactly. Compare it
against `interval_requested_s` before trusting any rate you derive.

**A run that ended early says how.** `ended_by` is `duration`,
`operator` or `read_error`. A trace that stops early looks identical to
a complete one on a plot, so check that column before concluding
anything from the length of a run.

**"Finish and save" keeps your data; "Stop and discard" does not.** The
two buttons sit next to each other. On every other tab in this suite,
Stop discards — that is deliberate and unchanged, and it is why the
button that keeps your data is called something else.

**Compliance is watched per sample unless you switched it off.**
`compliance_watched` records which you chose. A blank compliance column
with watching on means the instrument cannot report a trip at all —
which is not the same as no trip, and must not be read as one.

**A blank reading is a blank cell, never a missing row.** Sample indices
stay contiguous, so a gap in the trace is visible rather than closing up
and shifting everything after it earlier in time.

**The turn-on transient is inside the data.** t = 0 is the output-on
instant and there is no settle before the first sample, so the first few
rows include whatever the sample did as the level arrived. That is
deliberate; discard them if you want the steady state.

**A run can overshoot its duration by up to one sample interval.** The
timer is a ceiling with a small, bounded grace, not a hard cut — the
alternative was dropping the sample due at exactly the duration.

**This has never been run against hardware.** Everything above is
verified against the simulated instrument and the test suite. The first
bench session is expected to find something — commissioning a new path
always has.

## Open questions

- **Hardware timebases are not used.** Every run is host-stepped even on
  the instruments that could sample on their own clock.
- **Simultaneous V and I is undeclared.** See
  [Keysight U2722A](../instruments/keysight-u2722a.md) for the instrument that makes it matter.
- **A read timeout stops the run rather than resynchronising.** The
  transport can send a device clear, but reaching it from an experiment
  would skip the driver layer, so this waits for a driver-level
  `resynchronise()` if it turns out to bite.
