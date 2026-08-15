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

Most of the instruments here cannot tell you they hit compliance
(`compliance_tripped()` returns nothing) — only the GSM, the B2901A and
the 2635B can, and the per-instrument tables in Part 2 say which is which. So a
flat top on a curve may be the only warning you get.

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
nine real faults across the instruments it has run against.

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
| Compliance trip | **reported** |

The highest-voltage instrument here, and one of two speaking TSP rather
than SCPI. Its hardware sweep has ~2.1 s of fixed setup cost, paid once
per sweep regardless of length — so it looks slow on a 5-point sweep and
is genuinely fast on a 200-point one.

**One integration per reading**, measured: 15.6 ms at NPLC 0.001 and
515.6 ms at NPLC 25. Voltage and current come from a single matched
conversion, which makes this the best instrument here for anything where
V and I must describe the same instant.

**Readings were truncated to six significant figures until recently.**
`format.asciiprecision` governs everything this driver reads back and
resets to 6; nothing set it. It is now 16. Any Hall or high-resistance
result taken on this instrument before that change carries a ~0.1% floor
on V_H that has nothing to do with the sample — check your run dates.

**"Output off" does not disconnect the sample.** Off means the
instrument sources 0 V into it with 1 mA of compliance available. Tick
high-Z if the sample must actually be isolated; that opens the output
relay, which has a finite number of operations in it.

**The 200 V range needs the interlock line held high.** The output will
not turn on above ~20 V otherwise, and if a test-fixture lid opens the
output goes off and *stays* off until the line is set high again. No
command overrides this — it is a physical line on the Digital I/O port.
The app prints one line about it the first time you start a run on this
instrument.

**On this bench the interlock is jumpered permanently.** That is worth
knowing before you use the 200 V range on a resistive sample: the
lid-open cutout the manual assumes is not in circuit, so 200 V at up to
100 mA can stay live on an open fixture. The manual also notes the
interlock line's reliability degrades after roughly 10,000 operations,
which a permanent jumper never exercises — so if the wire is ever
removed, do not assume the line still works without checking it.

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

## Keithley 2635B

```
Keithley Instruments Inc.,MODEL 2635B,4001234,4.0.2
```

*(IDN not yet confirmed against the unit — see the caveat at the end of
this section.)*

| | |
|---|---|
| Envelope | 200 V, 1.5 A DC, 11 **sourceable** current ranges |
| Sweep | software (point by point from the PC) |
| Reading | one matched conversion, as the 2611A |
| Sensing | 2-wire / 4-wire switchable |
| Compliance trip | **reported** |

**Not yet commissioned.** Everything here is from the Series 2600B
Reference Manual, not the bench — the opposite of the rule at the top of
Part 2, and flagged rather than hidden. Run `tools/smu_checkup.py`
against it before trusting a measurement.

The second TSP instrument here, and the low-current one: it measures
down to **100 pA** where the 2611A stops at 100 nA. That is the reason
to pick it for a high-resistance sample.

**Readings take about 87 ms, and the reason is a deliberate choice.**
Autoranging is allowed all the way down to the 100 pA range, and
searching those bottom decades is where the time goes. Measured on the
bench at the fastest integration:

| Lowest range autoranging may use | Per reading | 200-point sweep |
|---|---|---|
| **100 pA** (what the driver sets) | 87 ms | ~27 s |
| 1 nA | 30 ms | ~15 s |
| 1 µA, or autorange off entirely | 30 ms | ~15 s |

The whole cost sits below 1 nA — raising the floor to 1 nA recovers all
of it and raising it further recovers nothing. About 20 ms of what is
left is fixed overhead in the instrument that no setting reaches.

It is left at 100 pA because that range is the reason this instrument is
on the bench. Raising it does **not** stop you reading sub-nanoamp
currents — 10 pA still resolves on the 1 nA range — it stops autoranging
onto the 100 pA range, where the noise floor and accuracy are better
below roughly 100 pA. Whether that matters is a property of your sample:
at 200 V a 1 GΩ sample draws 200 nA and the floor is irrelevant, while a
1 TΩ sample draws 200 pA and it is not.

If you are sweeping samples that never draw less than a nanoamp and the
27 seconds is costing you, it is one constant —
`MEASURE_LOW_RANGE_FLOOR_A` in `drivers/keithley_2635b.py`. Change it
deliberately and note it in the run, because it changes what the
instrument is capable of measuring, not just how fast it does it.

**It sources down to 1 nA, not 100 pA.** Source and measure ranges are
different sets on this model, and this is the only instrument on the
bench where that is true. The app's range dropdowns are fed from one
list which drives *sourced levels* and *compliance*, so it holds the
sourceable ranges only. The 100 pA measurement range is real hardware
and is currently unreachable from this app.

If you ever need it — an IV sweep on a sample so resistive that the
current is genuinely sub-nanoamp — it is a `measure_current_ranges`
field on `SMULimits` plus a dropdown, not a driver change. Worth doing
when a sample actually needs it and not before.

**"Output off" does not disconnect the sample.** Off means the
instrument sources 0 V into your sample with **1 mA of compliance
available** — a low-impedance path, not an open circuit. That is
Keithley's default and it is deliberate: the alternative (0 A) lets the
terminals float to 40 V, which is worse on a high-impedance sample.

It matters more here than on the 2611A because this is the
high-resistance box, and it matters more again with the temperature
stage running: a Peltier cycling under a shorted sample is exactly when
a thermoelectric EMF has somewhere to go. **Tick high-Z if the sample
must actually be isolated** — that opens the output relay. The relay has
a finite number of operations in it, so it is off by default.

The 1 mA figure is a signed-off choice, not a constant of nature. It is
`OFF_STATE_CURRENT_LIMIT_A` in the driver and can be lowered if a sample
needs it; below 1 mA interferes with the instrument's contact-check
function, which this suite does not use.

**Readings are set to 16 significant figures deliberately.** The
instrument resets to 6, and the Hall measurement needs 9 — V_H sits
under a resistive offset 100–1000× larger and is recovered by
subtracting nearly-equal numbers. Six figures would put a ~0.1% floor on
V_H with no error and no warning.

**It reports compliance**, which makes it one of three instruments here
that can tell you a measurement is clamping rather than leaving you to
infer it from a curve that bends over and goes flat.

One caveat worth knowing: the attribute reports that *a* configured
ceiling was reached, and it covers the voltage, current **and power**
limits alike. It does not say which. So a compliance flag on this
instrument means "one of the three limits is in control of the output",
not necessarily the compliance the experiment set.

**The delay default differs from the 2611A** — same attribute, same
spelling, opposite reset value. This model resets to DELAY_AUTO, which
inserts a current-range-dependent settle before every current
measurement; the 2611A resets to no delay. The experiments set it
explicitly either way, but asking for zero delay is a more consequential
request on this instrument than on that one.

**The 200 V range needs the interlock line held high**, same as the
2611A — the interlock section names the 2635 even though the range table
does not footnote it. See the 2611A entry above, including the note
about this bench's permanent jumper.

**Confirm the IDN.** `MODEL_IDS` is written from the family convention,
not from this unit's reply. If auto-detection fails at the bench, the
app offers a manual driver dropdown — and the fix is one string in
`drivers/keithley_2635b.py`.

## Keysight B2901A

```
Keysight Technologies,B2901A,MY51141631,3.4.2011
```

| | |
|---|---|
| Envelope | 210 V, 3 A DC, the highest current here |
| Sweep | software (its staircase is documented, not wired up) |
| Reading | one matched conversion |
| Sensing | 2-wire / 4-wire switchable — **and it resets to 2-wire** |
| Compliance trip | **reported** |

Not yet commissioned either; written from the manual with no original
script. The highest-current instrument on the bench.

**It energises its own output.** Out of reset, the B2900 series turns
the output on by itself on a measurement trigger. The driver disables
that on every reset, because the suite's guarantee that Stop
de-energises the sample would otherwise stop being true with no command
in the log to explain it. If you drive this instrument from your own
script rather than through the app, send `:OUTP:ON:AUTO 0` first.

**Compliance is sense-side here**, `:SENS:CURR:PROT`, where a 2450 uses
a source limit. Send the Keithley spelling and the B2901A logs it,
ignores it, and leaves the compliance at its 100 µA reset value — and a
sweep that clamps still draws a convincing straight line.

**Its sense-function spelling was resolved by asking the instrument.**
The manual contradicts itself over whether the argument is quoted, so
the driver sends one spelling and reads back the enabled-function count
rather than sending both and hoping.

**It is the second-best choice for compliance-critical work** after the
GSM, and the only choice above 1 A.

**Its compliance flag was wrong when sourcing current, and is fixed.**
It asked the instrument about the current limit regardless of what was
being sourced, so during Van der Pauw and Hall runs - which source
current, against a voltage limit - it reported "not clamping" whatever
was happening. Any B2901A Van der Pauw or Hall result from before this
fix carries no compliance warning even if the instrument was limiting;
IV sweeps sourcing voltage were unaffected. Commissioning caught it on
13 August 2026.

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
| Compliance trip | **reported** |

Speaks a Keithley-like SCPI dialect but differs in several places, and
those differences caused four of the nine faults found in commissioning.
It is now the best-instrumented driver in the suite as a result.

**Its buffer returns three numbers per reading**, not two — voltage,
current, resistance — regardless of being told otherwise, and it reports
two when asked. The driver counts the stride from the data rather than
believing either. If you ever query the buffer by hand, expect three.

**It reports compliance per quantity**, which is what still makes it the
best choice when you are unsure whether a measurement is hitting its
limit. The B2901A and the 2635B report it too now, but the 2635B's flag
covers the voltage, current and power limits together without saying
which — so the GSM remains the one that answers the question directly.

---

# Choosing an instrument

| If you need | Use | Because |
|---|---|---|
| High voltage (>21 V) | 2611A, 2635B, B2901A or GSM | 200–210 V |
| High current (>180 mA) | B2901A, 2401, 2611A, 2635B or GSM | 1–3 A |
| Matched V and I in time | 2611A or 2635B | one conversion for both |
| Fast sweeps | 2611A or GSM | hardware sweeps |
| To know if you hit compliance | GSM, B2901A or 2635B | they report it |
| Small, portable, quick | miniSMU | ~6 ms readings |
| **Currents below 100 nA** | **2635B** | **measures to 100 pA; nothing else here is close** |
| Low-level resolution | not the U2722A | 14-bit floor |
| Long unattended sweeps | GSM | 2500-point hardware sweep |

The 2635B and the B2901A have not been on a bench yet — run
`tools/smu_checkup.py` before trusting either, and expect the
commissioning to find something, because it has every other time.

The U2722A is the most constrained of the seven: lowest voltage, lowest
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

## Ranges: why the app fixes them instead of letting the instrument choose

Most SMUs can pick their own range as a measurement proceeds. The suite
switched that off for the quantity being sourced, and it is worth knowing why
before you turn it back on.

An autoranging source changes range partway through a sweep. Either side of
that change the instrument is sourcing through different gain and offset
errors, so the two halves of the curve sit on slightly different lines. Fit a
straight line across the join and it absorbs the step as extra slope — and in
an IV measurement, slope *is* resistance. Nothing errors, R² still looks
excellent, and the number is wrong.

So each run fixes the source range to the largest magnitude it will reach:
the sweep's end point, or the bias level. One range, one set of errors, one
line. It also stops the instrument spending resolution where nobody wants it —
a run sourcing milliamps gains nothing from microamp resolution merely because
it passes through zero on the way.

Two consequences you may notice at the bench:

- **A run near a range boundary is measured on the wider range.** Slightly
  coarser than autoranging would have given at the quiet end, and correct
  everywhere.
- **On the Keysight U2722A, which has no autorange at all**, the range covering
  the whole sweep is chosen before the sweep starts. If a level would exceed
  what the instrument can reach, that is reported rather than quietly clipped.

The measurement range of the quantity being *sourced* is never set. On most
SMUs that value is read back from the source and has no separate range; the
Keithley 2401 and GW Instek GSM-20H10 reject the attempt outright with error
823, "Invalid with source read-back on".

## Holding a sample under bias between sweeps (IV sweep, periodic runs)

A periodic run holds the sample in a standby state, then sweeps it, then repeats.
Whether the bias is genuinely *continuous* depends on one thing: **does the
standby source the same quantity as the sweep?**

| Standby | Sweep sources | What happens at the boundary |
|---|---|---|
| Bias voltage | voltage | Output stays on. Bias is continuous. |
| Bias current | current | Output stays on. Bias is continuous. |
| Bias voltage | current | Output comes down for the source-function change, then back up. **The sample relaxes before every sweep.** |
| Bias current | voltage | Same. |
| Remain idle | either | Output is off between sweeps by design. |

The mismatched combinations are allowed, and the app warns before starting one.
They are not a degraded version of a continuous run — they measure something
else, because the device is discharged before each sweep.

Two columns in the saved file record which you got, so a file read months later
still says:

* `bias_continuous` — `yes` or `no`
* `bias_gap_s` — blank when continuous; otherwise the **measured** length of the
  interval when the sample was not energised, in seconds. Measured rather than
  estimated: on a slow bus this is dominated by command turnaround, and it is
  worth comparing against your device's relaxation time.

**Stop discards the whole run.** Pressing Stop during a periodic run throws away
every cycle, including ones that had already finished. This is the same rule as
Van der Pauw, Hall and 4-point probe. There is no OFF button on the IV tab; Stop
is what brings the output down.

## A caveat on old Hall data from the 2611A

Hall runs taken on the **Keithley 2611A before 11 August 2026** recorded their
voltages to six significant figures rather than sixteen. The instrument was
returning six; nothing was wrong with the wiring or the sample.

For sheet resistance, IV sweeps and four-point probe this makes no practical
difference — six figures is about five parts per million.

It can matter for Hall. The Hall voltage is recovered by subtracting two
readings that are nearly equal, so the precision of the *difference* is much
worse than the precision of either reading. At a raw reading near 1 V, six
figures means steps of about 10 µV, which can be larger than the Hall voltage
being measured.

If you have Hall results from that period that looked noisy or irreproducible,
that may be why. Runs from 11 August onward are unaffected, and so is anything
measured on the 2635B.
