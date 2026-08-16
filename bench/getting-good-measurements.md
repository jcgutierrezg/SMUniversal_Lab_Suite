---
type: bench
title: "Getting good measurements"
---

# Getting good measurements

You do not need to know how an SMU works internally to use this suite,
but five things decide whether your numbers are right, and all five are
settings you choose. This section is the whole of it.

## What the instrument is doing

An SMU **forces** one quantity and **measures** the other. Force a
voltage and it reports the current that flowed; force a current and it
reports the voltage that appeared. That is the entire idea.

Which one you force matters more than it looks:

- **Force voltage** on anything that might short. A shorted sample with
  a forced current has nowhere to put it and the voltage runs away to
  the compliance limit.
- **Force current** on anything high-resistance, and for four-point
  probe, Van der Pauw and Hall. Those measure a voltage *difference*,
  so the current has to be the known quantity.

The panel calls this the source mode. Everything else follows from it.

## Compliance is the setting that ruins data

**Compliance is a ceiling on the quantity you are not forcing.** Force
1 V with a 1 mA compliance and the instrument will not let more than
1 mA flow — if the sample wants more, the instrument gives up on the
1 V and holds 1 mA instead.

It exists to protect the sample. It ruins measurements when set too low,
because the curve stops being an I-V curve and becomes a picture of the
limit. The give-away is a sweep that bends over and goes flat.

**Set it just above the largest current you expect, not at the
instrument's maximum.** Too high and a shorted sample takes the full
current; too low and you measure the instrument.

Most of the instruments here cannot tell you they hit compliance —
`compliance_tripped()` returns nothing. The **Reports compliance** column
in [choosing-an-smu](choosing-an-smu.md) says which can, and that column is generated from
the drivers themselves, so it cannot fall out of date. Where the answer
is no, **a flat top on a curve may be the only warning you get.**

## 2-wire measures your cables as well as your sample

In **2-wire**, current flows down the same leads that sense the voltage,
so the reading includes the resistance of the leads and every contact.
On a 10 kΩ sample that is a rounding error. On a 10 Ω sample it can be
most of what you measured.

In **4-wire** (Kelvin), separate leads sense the voltage right at the
sample and carry no current, so lead resistance drops out.

**Use 4-wire for anything below about 100 Ω.** On a 10 kΩ resistor, our
own bench comparison showed 9948.76 Ω 2-wire against 9951.87 Ω 4-wire —
0.03%, invisible. But the scatter was **fifty times lower** in 4-wire
(R² 0.999958 → 0.9999992), so it is worth using even where the mean
agrees.

Per instrument: the U2722A is **permanently 4-wire** by wiring and
cannot be switched. The miniSMU can switch, but 4-wire consumes its
second channel. The three Keithleys switch freely.

## Integration time trades noise against speed

Each reading is an average over a short window. Longer window, quieter
reading, slower sweep. The window is set in **NPLC** — power line
cycles — where 1 NPLC is 20 ms on 50 Hz mains.

Whole numbers of power line cycles matter: mains hum picked up on the
leads averages to almost exactly zero over a whole cycle. That is why
NPLC is measured in cycles rather than milliseconds, and why **1 NPLC is
much quieter than 0.9**.

Rules of thumb:

- **NPLC 1** is the sensible default. Quiet enough for most work.
- **NPLC 0.01–0.1** when you need speed and the signal is large.
- **NPLC 10** and up for small signals — Hall voltages, low-current
  work. Expect a 200-point sweep to take minutes.

Two exceptions to be aware of:

- The **U2722A pays twice**. It has no combined voltage+current read, so
  each point costs two integrations. NPLC 25 there means ~1.06 s per
  point, not 0.5 s.
- The **miniSMU's NPLC number is not real** (see [undalogic-minismu-bench](instruments/undalogic-minismu-bench.md)).
  Higher still means quieter, but the number itself means nothing.

## Settling: the instrument is not the slow part

After the source changes, the sample and the cables take time to reach
the new level. Read too early and you measure the transition.

The panel's **delay** setting is that wait. It matters most for:

- **high-resistance samples**, where cable capacitance charges slowly
- **small currents** — the U2722A slews at only about **1 V/s** when
  sourcing 1 µA, so reaching 1 V takes over a second
- anything with long or coaxial leads

If a sweep looks like it lags — each point resembling the one before —
increase the delay before suspecting anything else.

## The traps that produce wrong data that looks right

These are real faults found on these instruments, all now fixed. They
are listed because they share a shape worth recognising: **none of them
raised an error.**

- A sweep that returned the right number of points, all at 0 V.
- A sweep silently reduced to a third of its points, the survivors being
  genuine readings that fitted a perfect line.
- A sweep clipped by a range that never widened, still fitting cleanly.
- Voltage and current for one "point" measured half a second apart.

The habits that catch this class of problem:

1. **Measure a known resistor first.** A 10 kΩ resistor takes two
   minutes and tests the whole chain — instrument, driver, wiring,
   analysis. Every one of the faults above is obvious against a known
   value and invisible against an unknown sample.
2. **Look at the sweep's endpoints**, not just the fit. If you asked for
   ±5 V and the data spans ±2 V, something clamped it.
3. **Check the point count** matches what you asked for.
4. **Be suspicious of a very good fit.** Several of these faults produce
   *cleaner* lines than real data, because clipped or decimated data has
   less of the sample's own scatter in it.

## Running the health check

Before trusting an instrument — a new one, one that has been moved, or
one whose data looks odd:

```
uv run tools/smu_checkup.py --address <address>
```

Nothing connected to the outputs; it prompts to confirm. Three minutes,
and it writes a report you can compare against a previous one.

It is worth the three minutes: **half the faults this project has found
were found this way**, and none of them could have been found by any
amount of testing without an instrument attached. See
[Running a checkup](running-a-checkup.md), and [checkup-owed](../docs/open/checkup-owed.md) for which drivers are owed
one right now.
