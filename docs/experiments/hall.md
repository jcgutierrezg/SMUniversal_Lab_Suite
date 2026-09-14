---
type: experiment
title: "Hall effect"
module: experiments/hall
origin: "Hall_v4.ipynb"
consumes: sheet_resistance
---

# Hall effect

Carrier density, mobility and carrier type from the Hall voltage, using
a sheet resistance measured by [Van der Pauw](van-der-pauw.md). Ported from
`Hall_v4.ipynb`.

## What it measures

Eight readings again — `v13p`, `v31p`, `v24p`, `v42p` and their negative
counterparts — combined by `hall_voltage()` so that the resistive offset
cancels and the Hall component survives. Then sheet carrier density from
current, field and Hall voltage; mobility from that and the sheet
resistance; bulk density and resistivity if a thickness is given; and
carrier type from the sign.

Every one of those is behind a golden file — `hall_voltage`,
`hall_sheet_carrier_density`, `hall_mobility`, `hall_bulk_carrier_density`,
`hall_resistivity`. Five of the nine goldens in the suite are this
experiment's, which is proportionate: it is the one whose arithmetic is
least checkable by eye.

## Why precision is the whole story here

**The Hall voltage sits underneath a resistive offset 100–1000× larger
and is recovered by subtracting nearly-equal numbers.** So the precision
of the *difference* is far worse than the precision of either reading,
and a floor on the readings becomes a much bigger floor on the result.

`Hall_v4.ipynb` wrote its measured voltages at `%.6g` into the
calculation boxes, imposing roughly a 0.1% floor on V_H before any
physics happened. Deviation 2 raised it to nine figures.

The instrument end of the same problem is in [Keithley 2611A](../instruments/keithley-2611a.md): that
driver never set `format.asciiprecision`, whose reset default is 6, so
**the instrument itself was returning six figures** regardless of what
the software did with them. Two independent six-figure ceilings on the
same measurement, found eight months apart, and each one hid the other.
If you have Hall results that looked noisy or irreproducible before
August 2026, that is the likeliest reason.

## The handoff

There was no original for this. The two notebooks were separate
programs, and the sheet resistance moved between them **by being read
off a screen and typed into a box.**

The first port replaced that with a file: Van der Pauw wrote
`<sample>_vanderpauw.csv`, Hall's *Load from VdP...* button parsed the
`# Rs_ohm_per_sq:` header out of it, and recorded the file path as
`# Rs_source:`. Wave 5c deleted that interface. The sheet resistance now
crosses **in memory**, as the result object that produced it, and a
saved Hall file records:

```
# input_sheet_resistance_from: res-20260813-a1b2c3d4 (vdp_sheet_resistance:1,
#     runs: vanderpauw-0001-... vanderpauw-0002-... ...)
```

**Why.** A file path is not provenance. It names a location, and
locations get renamed, moved, copied into a folder called `old`, and
overwritten by the next session's save. A result id and the run ids
behind it name the measurement itself, and stay true whatever happens to
the filesystem.

**What it costs, stated plainly.** A Van der Pauw run measured last week
can no longer supply a Hall run today. That was decided, not overlooked:
the two are one session on one mounted sample with the same contacts,
and there is never a Monday Van der Pauw and a Tuesday Hall. Keeping the
CSV path as a fallback would have left two routes to one number — which
is the failure this codebase is built around. They drift, and the one
that drifts is the one nobody is watching.

**Reading old files.** Nothing parses `# Rs_source:` any more, but old
files still carry it and it still means what it meant. A Hall file with
`Rs_source` predates Wave 5c; one with `input_sheet_resistance_from`
follows it. Neither spelling appears in both.

### Operating it

**Take Rs from VdP**, next to the Rs box on the Hall tab, fills it from the
Van der Pauw tab's calculation. Three things it refuses or flags, and why
each one exists:

- **Nothing calculated yet.** Press Calculate on the Van der Pauw tab first.
  The boxes can be full with no result behind them, which is not the same
  state and must not read as one.
- **A stale sheet resistance.** If the Van der Pauw inputs moved after it was
  calculated, the value is refused and the message names which input moved. A
  stale result already cannot reach its own CSV; this stops it reaching
  Hall's arithmetic through a side door instead.
- **Stage temperature drift.** Warns, does not refuse. Carrier density and
  mobility are strongly temperature-dependent, so an Rs measured at 25 °C
  applied to a Hall run at 80 °C describes two different samples — but a
  deliberate temperature series is exactly that shape, so the operator
  decides.

Typing over the Rs box drops the citation: the header then says the value was
typed rather than naming a run that did not supply it. Renaming the sample
between the two calculations refuses the transfer, because the rename makes
the Van der Pauw result stale; renaming *after* the transfer refuses the Hall
calculation instead, since a carrier density computed against another film's
sheet resistance is arithmetically perfect and physically meaningless.

**One sample name per mounted sample**, not per batch and not per session.
The name is what the software mints a sample identity from, so two different
coupons typed under one name are one sample as far as every check here is
concerned — and an Rs from the first would carry silently onto the second.

## Two things found while building the handoff

**A warning that could never fire.** The design had a sample-name
mismatch warning at the transfer and a refusal at the calculation. The
warning turned out unreachable: Van der Pauw's staleness signature
includes the sample name, so renaming the session strip makes its result
stale, and a stale result is refused at the transfer before any mismatch
check runs. The behaviour is *stricter* than designed, and the dead
check was deleted rather than left in.

A check that cannot fire is worse than no check. It teaches whoever
reads the code that the case is handled *by it*, and nobody looks there
again when the rule that actually handles it changes.

**A test that would have passed either way.** The first version of the
mixed-sample guard measured Hall's own runs before renaming the sample,
so the pre-existing source-run check refused the calculation on its own
and the new upstream check was never exercised. Confirmed by deleting
the new check and watching the test stay green.

That is the third time this project has shipped an assertion that was
true whether or not the code worked, and the pattern each time was the
same: **a test written from the intent of a change rather than from what
would distinguish it.**

## What this means for your data <!-- bench -->

**Hall results from before August 2026 have two independent precision
floors on them**, one in the software and one in the instrument, both at
six significant figures. Because the Hall voltage is a small difference
between large readings, that is roughly a 0.1% floor on V_H and
everything derived from it. Noisy or irreproducible old Hall numbers are
more likely to be this than the sample.

**Van der Pauw and Hall must be run in the same session, on the same
mounted sample.** The sheet resistance is carried in memory, not read
from a file, so yesterday's Van der Pauw cannot feed today's Hall. If
you need to, re-run it — it takes minutes and it is measuring the same
contacts you are about to use.

**Check the carrier type against what you expect.** It comes from the
sign of the Hall voltage, and a sign flip is what a swapped pair of
contacts looks like. It is the cheapest sanity check available on a Hall
run.

## Open questions

None specific to this experiment. The sample-labelling gap in
[Van der Pauw](van-der-pauw.md) applies here and is where it does the most damage,
since this is the experiment that carries a number across from another.
