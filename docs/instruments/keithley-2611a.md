---
type: instrument
title: "Keithley 2611A"
driver_class: Keithley2611A
idn: "Keithley Instruments Inc., Model 2611A, 1314733, 2.2.2"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: 2026-08-21
bench_notes: "2026-08-21 checkup at 7dc6264: 59 pass, 2 skip, no failures. source.compliance read true at 0.9997 V against a 1 V limit. The hardware sweep took 2.145 s for 5 points against a 15.9 ms steady-state reading, which is unexplained"
bench_code: "ced16c21b5a7"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "16 ms at NPLC 0.001, +71 ms first read"
resolution: "not range-limited"
best_for: "matched V and I in one conversion; fast hardware sweeps"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keithley_2611a.py
model_ids: "['MODEL 2611A', '2611A']"
max_voltage_v: 200
max_current_a: 1.5
voltage_ranges_n: 4
current_ranges_n: 9
power_envelope_n: 2
sweep_kind: hardware
nplc_min: 0.001
nplc_max: 25
high_z_off: true
ovp: false
remote_sense_control: true
compliance_trip: true
# --- end generated ---
---

# Keithley 2611A

One of two instruments here speaking **TSP** rather than SCPI. TSP is <!-- lint-ok -->
Lua: `smu.source.leveli = 1e-4` rather than `:SOUR:CURR:LEV 1e-4`. Same
concepts, incompatible syntax, which is the entire reason the driver
layer exists.

Ported from the `IV_Meas_2611A_*` scripts and the Ossila 4PP script.

## Identity and envelope

200 V, 1.5 A, nine current ranges. The 10 A range is pulse-mode only and
is correctly absent from `LIMITS`.

Its sweep runs **inside the instrument**: one command starts it, points
land in `nvbuffer1`, and the spacing comes off the SMU's own clock
rather than off host and bus latency. There is ~2.1 s of fixed setup
cost paid once per sweep, so it looks slow on five points and is
genuinely fast on two hundred. Every run records `sweep_kind` in its
CSV, because a hardware sweep and a software one are not equivalent and
the difference is timing.

## Reset defaults that had to be overridden

Four, and three of them arrived as slightly-wrong data rather than as
errors. All were found by writing the [Keithley 2635B](keithley-2635b.md) driver from the
sibling manual. **A new driver written carefully is the most reliable
audit of the existing ones this project has**, and that has now held
three times.

| Attribute | Resets to | Set to | Why it matters |
|---|---|---|---|
| `format.asciiprecision` | 6 | 16 | six significant figures on every reading this driver had ever taken |
| `source.offmode` | `OUTPUT_NORMAL` | stated explicitly | "off" is a driven 0 V source, not a disconnection |
| `source.offlimiti` | 1 mA | stated explicitly | the compliance available across a sample between runs |
| `localnode.linefreq` | auto-detected | **read, then written only if wrong** | writing it disables `autolinefreq` permanently, in nonvolatile memory |

The last row is the delicate one. The 2600A manual states that setting
`linefreq` explicitly sets `autolinefreq` false and keeps it that way. A
driver writing 50 Hz on every connect would silently disable automatic
detection on an instrument somebody had deliberately left detecting, and
nothing would ever turn it back on. So the driver reads first and writes
only on disagreement — worth confirming in a trace, because on a unit
already at 50 Hz the correct behaviour is a read and **no write**.

Source and measure autoranging are re-enabled on all four axes on every
reset. Fault 11 does not apply to ranging on this family: the
`measure.rangeY` page states that setting a range explicitly disables
autoranging for that function by itself, so no `AUTORANGE_OFF` first
step is needed. The B2901A needs the opposite treatment, and the driver
test asserts the absence of the SCPI habit so nobody copies it across.

## Decisions and deviations

**Deviation 39 — `measure.iv()` replaces `measure.v()` then
`measure.i()`.** The original driver said TSP had no matched-pair call.
It does. The bench checkup timed a reading at 1034 ms with NPLC 25 —
exactly two 0.5 s apertures — confirming the voltage was integrated over
the first half-second and the current over the *next* one. Beyond being
twice as slow, the V and I of a single "point" described two different
moments, which matters on a sample that drifts or self-heats and matters
most to Hall. `iv()` returns **current first**, the opposite order, so
the parse is reversed and pinned by test. Verified afterwards: `iv()`
costs exactly one aperture (15.6 ms at NPLC 0.001, 515.6 ms at NPLC 25,
slope 1.00), so the change halved reading time as well — 1034 ms to
516 ms at NPLC 25.

**A1 — replies were truncated to six significant figures.** The 2600A
manual lists `format.asciiprecision` as governing `print`, `printnumber`
*and* `printbuffer`, with a reset default of 6. Nothing in this codebase
had ever set it, so every reading this driver took came back at six
figures — through `measure()` and, because the hardware sweep reads back
with `printbuffer`, through every sweep point too. It arrived as
slightly-wrong data, never as an error, and a *different* six-figure
problem in the same measurement — a test asserting against a display
string — kept it hidden.

**A2 — "output off" was a driven 0 V source.** `set_output_off_mode()`
existed and was correct, but nothing stated the mode or the limit at
reset, so the off-state was whatever reset had left.

The family shape differs here, and that is what vindicates keeping the
two TSP drivers as separate files: the 2600B adds an `offfunc` attribute
selecting between a 0 V and a 0 A off-state; **the 2600A has none** —
normal-off is always 0 V. A subclass would have sent the 2635B's third
attribute into a Lua interpreter with no such field.

**A4 — `compliance_tripped()` implemented.** `smu.source.compliance`,
read-only, a Lua boolean. The 2600A page describes it per source
function — the voltage limit reached when sourcing current, or the
current limit when sourcing voltage — and unlike the 2600B wording says
nothing about a power limit, so nothing is claimed about `limitp`.
Unparseable and failed replies return `None` rather than `False`,
because `False` means "everything was fine" and a wrong reassurance is
worse than an honest silence.

**A5 — the error queue is split on tabs.** `print()` separates arguments
with a tab and `errorqueue.next()` returns four of them, so splitting on
whitespace put severity and node on the end of the message and broke
multi-word messages across fields.

**Wave 6c removed two calls from `start_linear_sweep()`.** It was
setting the source function under a live output, and re-enabling source
autoranging — which silently discarded the source range the experiment
had just fixed through its `RangePlan`. Both removals are right by every
argument available: a sweep that autoranges its source crosses range
boundaries, and each crossing leaves a step where the two segments were
sourced with different gain and offset errors. A straight line fitted
across that step absorbs it as slope, and slope is resistance. No error,
an excellent R², and a wrong answer.

**Deviation 50 applies here by inheritance, not by fault.** The buffer
stride problem was the GSM's; this driver reads back a documented
element list. Recorded because the two TSP drivers share a `REPLY_ORDER`
table in the test suite and the 2611A's reversal is pinned in it twice.

## Bench findings

### 2026-09-01 — noise/rate envelope and sub-count floor

100 uA into 9958 ohm, 2 V compliance, current range pinned to the bias.

| NPLC | per reading | rate | RSD |
|---|---|---|---|
| 0.001 | 6.8 ms | 148 Hz | 0.101% |
| 0.0076 | 12.9 ms | 78 Hz | 0.007% |
| 0.057 | 13.9 ms | 72 Hz | 0.001% |
| 0.44 | 13.5 ms | 74 Hz | 0.000% |
| 3.3 | 76.7 ms | 13 Hz | 0.000% |
| 25 | 513 ms | 1.9 Hz | 0.000% |

**Sub-count floor: 12.2 nA on the 100 uA range - the highest on this
bench, and it is a drift rather than quantisation.** A negative offset
grows as the level falls: at 98 nA the negative leg reads -127 nA, at
24 nA it reads -54 nA, at 12 nA it reads -42 nA. More than three times
the commanded value, with the sign still correct.

That is the dangerous shape. A number that quantises to zero is
obviously unusable; a number that is wrong by a factor and still points
the right way is not. **Below about 100 nA on this instrument the
magnitude should not be trusted.**

- **2026-08-21:** the checkup at `7dc6264` returned 59 pass, 2 skip, no
  failures. `print(smu.source.compliance)` returned `true` at 0.9997 V
  against a 1 V limit — a clamping check that passed because the output
  really was clamping, rails in 66 ms.

  `compliance survives ranging` skipped: this driver reports its trip
  state but not its compliance *level*. That is awkward on this
  instrument in particular, because `source.autorangei` **is** the
  compliance range here — the configuration fault 23 is about — so the
  one collapse worth watching for is the one that cannot be seen.

- **The hardware sweep is unexplained.** 2.145 s for 5 points — 430 ms
  each — against a 15.9 ms steady-state reading, which makes it slower
  per point than the 2401's *software* sweep. Recorded rather than
  guessed at; `choosing-an-smu.md` may be understating a 200-point sweep
  by a large factor. A timing scan with the measure range fixed would
  settle it.

Commissioned 2026-08-13; probed again 2026-08-14.

- **`format.asciiprecision` resets to 6** and governs `print()` and
  `printnumber()` **identically** — closing a decision that had been
  open on whether the two differed. The explicit raise to 16 is
  confirmed necessary.
- **A source-function change does not drop the output** on TSP, unlike
  the 2400 family. The sequence still takes the output down
  deliberately, so behaviour is identical across the fleet.
- **The first reading after any configuration change costs three
  apertures**, not one — measured twice, a day apart, both exactly
  1.000 s longer at NPLC 25. That is autozero measuring an internal
  reference and zero alongside the signal. Not an error; if anything
  that reading is the better one.
- **A reading is one integration**, confirmed by the slope of the
  NPLC-versus-time line.

## What this means for your data <!-- bench -->

**Hall runs taken before 11 August 2026 recorded six significant figures
rather than sixteen.** The instrument was returning six; nothing was
wrong with the wiring or the sample.

For sheet resistance, IV sweeps and four-point probe this makes no
practical difference — six figures is about five parts per million. It
matters for Hall, because the Hall voltage is recovered by subtracting
two nearly-equal readings, so the precision of the *difference* is much
worse than that of either reading. At a raw reading near 1 V, six
figures means steps of about 10 µV, which can be larger than the Hall
voltage being measured. If you have Hall results from that period that
looked noisy or irreproducible, that may be why. Runs from 11 August
onward are unaffected.

**"Output off" does not disconnect the sample.** Off means the
instrument sources 0 V into it with 1 mA of compliance available. Tick
high-Z if the sample must actually be isolated — that opens the output
relay, which has a finite number of operations in it, so it is a setting
to opt into rather than leave on.

**The 200 V range needs the interlock line held high.** The output will
not turn on above ~20 V otherwise, and if a fixture lid opens the output
goes off and *stays* off until the line is set high again. No command
overrides this; it is a physical line on the Digital I/O port. The app
prints one line about it the first time you start a run here.

**On this bench the interlock is jumpered permanently.** The lid-open
cutout the manual assumes is therefore not in circuit, so 200 V at up to
100 mA can stay live on an open fixture. The manual also notes the
interlock line's reliability degrades after roughly 10,000 operations,
which a permanent jumper never exercises — so if the wire is ever
removed, do not assume the line still works without checking it.

**A slow first point is not a fault.** After any configuration change
the first reading takes three integration periods rather than one. On a
software sweep or a bias hold that shows up as one slow point at the
start.

**This is the best instrument here when V and I must describe the same
instant** — one matched conversion, which matters most for Hall.

## Open questions

- **The Wave 6c sweep change has never run on hardware.** It alters the
  hardware sweep on an instrument you own. Worth one bench run before
  trusting a 2611A sweep dataset taken since. Tracked in
  [checkup-owed](../open/checkup-owed.md).
- **Is the off-state limit sufficient on a 2600A?** The off-state
  *function* and *limit* are written here now, but a cross-driver grep
  during the 2635B work found no driver setting an off-state function
  and only two setting the mode. Worth confirming against the 2600A
  reset table, which is not yet transcribed into
  [the manual extracts](../reference/manuals/_index.md).
