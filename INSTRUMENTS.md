# INSTRUMENTS — what the bench actually found

Five source-measure units, all commissioned against real hardware in
August 2026 with `tools/smu_checkup.py`. This file is the useful residue
of that: what each instrument does, what it gets wrong, and what that
means for a measurement.

`HANDOFF.md` is for changing the code. This file is for using it.

---

# Part 1 — If you just want accurate measurements

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

Three of the five instruments cannot tell you they hit compliance
(`compliance_tripped()` returns nothing), so a flat top on a curve may
be the only warning you get.

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
- The **miniSMU's NPLC number is not real** (see its section below).
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
and it writes a report you can compare against a previous one. It found
nine real faults across these five instruments.

---

# Part 2 — Per-instrument reference

Everything below was measured on the bench, not taken from a datasheet,
unless stated.

## Keithley 2401

```
KEITHLEY INSTRUMENTS INC.,MODEL 2401,4084766,A01 Aug 25 2011 ...
```

| | |
|---|---|
| Envelope | 21 V, 1.05 A, 7 current ranges |
| Sweep | software (point by point from the PC) |
| Reading | ~44 ms at NPLC 0.01 |
| Sensing | 2-wire / 4-wire switchable |
| Compliance trip | not reported |

Straightforward and reliable. Nothing surprising in commissioning.

**The one rule:** the output turns itself off when the source function
changes, and this driver disables auto output-off so a sweep holds its
level between points. So the output must be turned on *after* changing
mode. The experiments all do this; if you write new code that doesn't,
the next reading blocks forever with no error — the instrument looks
dead. Documented on `BaseSMU.set_source_function`.

## Keithley 2611A

```
Keithley Instruments Inc., Model 2611A, 1314733, 2.2.2
```

| | |
|---|---|
| Envelope | 200 V, 1.5 A, 9 current ranges |
| Sweep | **hardware** — runs on the instrument's own timebase |
| Reading | 1 aperture + ~13 ms overhead |
| Sensing | 2-wire / 4-wire switchable |
| Compliance trip | not reported |

The highest-voltage instrument here and the only one speaking TSP rather
than SCPI. Its hardware sweep has ~2.1 s of fixed setup cost, paid once
per sweep regardless of length — so it looks slow on a 5-point sweep and
is genuinely fast on a 200-point one.

**One integration per reading**, measured: 15.6 ms at NPLC 0.001 and
515.6 ms at NPLC 25. Voltage and current come from a single matched
conversion, which makes this the best instrument here for anything where
V and I must describe the same instant.

**The first reading after any configuration change costs three
apertures**, not one — measured twice, a day apart, both exactly 1.000 s
longer at NPLC 25. That is autozero measuring an internal reference and
zero alongside the signal. Not an error; if anything that reading is the
better one. It shows up as a slow first point on a software sweep or a
bias hold.

## Keysight U2722A

```
AGILENT TECHNOLOGIES,U2722A,MY62030002,R1.10-1.12-1.06
```

| | |
|---|---|
| Envelope | 20 V, 120 mA, 6 current ranges, three channels (only ch 1 used) |
| Sweep | software |
| Reading | **2 apertures** + ~37 ms overhead |
| Sensing | **permanently 4-wire**, by wiring — cannot be switched |
| Compliance trip | not reported |
| NPLC | whole numbers only, 1–255 |

The most quirk-laden instrument in the set, and worth reading before
using.

**Every reading costs two integrations.** There is no combined
voltage+current read, so NPLC is worth twice what it looks like: NPLC 25
is ~1.06 s per point, and a 200-point sweep takes about 3.5 minutes.

**It is a 14-bit instrument.** Every reading is an exact multiple of
range ÷ 16384 — 6.1 nA on the 100 µA range, 122 µV on the 2 V range.
That is the resolution floor **whatever NPLC is set to**; averaging
longer does not add bits. If you need finer resolution, use a smaller
range or a different instrument.

**It slews slowly at low currents.** Its output capacitance is around
1 µF, so sourcing 1 µA into a high-impedance sample moves the voltage at
about **1 V/s**. Allow over a second per point at that level, more on
smaller ranges. This is the instrument most likely to need a generous
delay setting.

**No auto-ranging on the source**, and no overvoltage protection. The
driver picks ranges explicitly.

## Undalogic miniSMU MS01

```
Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
```

| | |
|---|---|
| Envelope | 12 V, 180 mA, 2.1 W per channel, 5 current ranges, 2 channels |
| Sweep | **hardware** for voltage sweeps; software for current sweeps |
| Reading | ~6 ms floor (link-limited) |
| Sensing | switchable, but 4-wire consumes channel 2 |
| Compliance trip | not reported |

The fastest and smallest, driven through the vendor's Python library
rather than a text protocol. Firmware 1.4.6; onboard sweeps need 1.3.4+
and 4-wire needs 1.4.3+, both checked at connect.

**Use the 12 V DC adapter.** On USB-C power alone it is limited to
50 mA per channel instead of 180 mA, and it cannot report which supply
it is on. A sweep asking for more than 50 mA on bus power quietly folds
back and looks like a sample going into a compliance nobody set. Stated
in the console at every connect.

**It has a ~−1.5 mV voltage offset**, confirmed three ways. It cancels
in anything taken from a *slope* — both our 10 kΩ sweeps recovered the
resistor to better than 0.1% — but not in a single-point voltage
reading. Relevant if you use it for four-point-probe or Hall voltages,
which are often smaller than the offset itself.

**Its `nplc` column is not a real integration time.** Higher still means
quieter and the ordering is correct, but the absolute number is
unfounded and must not be compared against a true-NPLC instrument. See
"the OSR question" below. Any miniSMU data whose metadata matters needs
that column caveated or removed.

## GW Instek GSM-20H10

```
GWInstek,GSM-20H10,GEW852313,V1.16
```

| | |
|---|---|
| Envelope | 210 V, 1.05 A, 7 current ranges |
| Sweep | **hardware**, up to **2500 points** (the buffer limit) |
| Reading | ~50 ms at NPLC 0.01 |
| Sensing | 2-wire / 4-wire switchable |
| Compliance trip | **reported** — the only one that can |

Speaks a Keithley-like SCPI dialect but differs in several places, and
those differences caused four of the nine faults found in commissioning.
It is now the best-instrumented driver in the suite as a result.

**Its buffer returns three numbers per reading**, not two — voltage,
current, resistance — regardless of being told otherwise, and it reports
two when asked. The driver counts the stride from the data rather than
believing either. If you ever query the buffer by hand, expect three.

**It is the only instrument that reports compliance**, which makes it
the best choice when you are unsure whether a measurement is hitting its
limit.

---

# Choosing an instrument

| If you need | Use | Because |
|---|---|---|
| High voltage (>21 V) | 2611A or GSM | 200 V and 210 V |
| High current (>180 mA) | 2401, 2611A or GSM | ~1 A each |
| Matched V and I in time | 2611A | one conversion for both |
| Fast sweeps | 2611A or GSM | hardware sweeps |
| To know if you hit compliance | GSM | only one that reports it |
| Small, portable, quick | miniSMU | ~6 ms readings |
| Low-level resolution | not the U2722A | 14-bit floor |
| Long unattended sweeps | GSM | 2500-point hardware sweep |

The U2722A is the most constrained of the five: lowest voltage, lowest
current, coarsest resolution, slowest per reading, and permanently
4-wire. It is fine for what it is — use it when the others are busy or
when the sample suits it.

---

# The OSR question (miniSMU) — for the record

Kept because someone will otherwise repeat the work.

The miniSMU has no NPLC setting. Its noise control is an **oversampling
ratio**, `MEAS:OSR`, from 0 to 15, documented as "approximately 2^OSR
samples". The driver maps that onto the shared NPLC control so the panel
behaves the same on every instrument.

That mapping needs to know how long a sample takes. Three values were
tried and all three were wrong, because **the underlying model is
wrong**. A six-point timing scan showed:

| OSR | samples | reading | implied rate |
|---|---|---|---|
| 0 | 1 | 6.2 ms | — |
| 6 | 64 | 12.4 ms | 10 kS/s |
| 9 | 512 | 34.4 ms | 18 kS/s |
| 12 | 4096 | 75.0 ms | 60 kS/s |
| 15 | 32768 | 162.6 ms | 210 kS/s |

Eight times the samples costs about 2.2× the time, and the implied rate
climbs twentyfold. If a reading cost `overhead + samples ÷ rate`, every
row would give the same rate. **No single rate can describe this**, so
the NPLC equivalence has no sound basis.

The spec sheet's 1000 S/s is the *streaming* rate — how fast finished
readings leave the instrument — and is unrelated to how long one
oversampled reading takes. That mismatch is not the explanation; it was
merely the first wrong answer.

**What would settle it**, if anyone cares enough:

- A **noise scan**: standard deviation of a few hundred readings into a
  known resistor at each OSR. If σ falls as 2^(−OSR/2), the sample-count
  claim is right and the timing anomaly means the reading time is not
  the integration time.
- Better still, look for a **dip** in that curve rather than a monotonic
  fall. Averaging over exactly one mains period nulls 50 Hz hum, so a
  local minimum pins the integration window to 20 ms at that OSR and
  fixes the whole scale with no timing at all.
- Or ask Undalogic what `MEAS:OSR` does. "Approximately 2^OSR samples"
  is doing a lot of work.

Two free observations already in the data: **OSR 0 and OSR 3 take the
same 6.2 ms**, so running at OSR 0 is strictly wasteful — you get up to
2.8× less noise for no time at all. And below about OSR 6 the reading
time is set by the link, not the measurement.

---

# Method notes — how these numbers were obtained

Worth knowing before adding to this file, because two of them cost real
time here.

**A two-point fit proves nothing.** Fitting `overhead + N × aperture` to
two timings fits two parameters to two points: zero degrees of freedom,
so the line passes through both by construction. It cannot fail and it
cannot be checked. Two such fits were reported as confirmed here and
both were wrong. `tools/timing_scan.py` refuses fewer than three points
and prints the residuals, which is the only thing that says whether the
model holds.

**Timings are only comparable within one run.** Per-reading overhead on
the miniSMU varied from 6 ms to 29 ms between sessions — enough to
swamp the signal entirely. The rule of thumb: a timing fit is only as
good as integration ÷ overhead. The U2722A's 500 ms aperture against
35 ms of overhead survived a cross-session comparison; the miniSMU's
5 ms against the same overhead did not.

**An instrument's account of itself can be wrong in both directions.**
The GSM accepts `FORM:ELEM VOLT,CURR`, ignores it, and then answers
`FORM:ELEM?` with `VOLT,CURR` while sending three columns. Neither the
command nor the query described reality. Counting what actually arrived
was the only reliable route.

**Ask the documentation before the bench.** Two of the harder faults —
the 2401's apparent hang and the GSM's rejected sweep setup — were
solved by a sentence in a command reference after several wrong theories
had been formed from traces. Traces narrow the question; manuals answer
it.
