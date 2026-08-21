---
type: instrument
title: "Keithley 2635B"
driver_class: Keithley2635B
idn: "Keithley Instruments Inc., Model 2635B, 4126721, 3.2.2"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: 2026-08-21
bench_notes: "2026-08-21 checkup at 7dc6264: 59 pass, 2 skip, no failures. source.compliance read true at 0.9981 V. First reading after output_on cost 1098 ms against a 17 ms steady state - the largest first-read penalty in the fleet"
bench_code: "050c9201873c"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "17 ms at NPLC 0.001, +1.1 s first read"
resolution: "measures to 100 pA; sources only to 1 nA"
best_for: "high-resistance samples and sub-nanoamp currents"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/keithley_2635b.py
model_ids: "['MODEL 2635B', '2635B']"
max_voltage_v: 200
max_current_a: 1.5
voltage_ranges_n: 4
current_ranges_n: 11
power_envelope_n: 2
sweep_kind: software
nplc_min: 0.001
nplc_max: 25
high_z_off: true
ovp: false
remote_sense_control: true
compliance_trip: true
# --- end generated ---
---

# Keithley 2635B

The second TSP instrument, and the low-current one: it measures down to
**100 pA** where the [Keithley 2611A](keithley-2611a.md) stops at 100 nA. That is the
reason to pick it for a high-resistance sample.

**Written from the Series 2600B Reference Manual with no original lab
script behind it.** Nothing here is a departure from working code — each
item is a decision made from a manual, signed off individually before
the driver was written, and recorded so the reasoning outlives whoever
made it. Where a decision could not be closed from the manual, it was
left open and taken to the bench rather than guessed.

## Identity and envelope

200 V, 1.5 A DC, eleven **sourceable** current ranges.

The `*IDN?` reply above was read off the unit on 13 August 2026. Note
`Model` rather than `MODEL`, and spaces after the commas — the registry
matches case-insensitively, so `MODEL_IDS` needed no change, but the
observed string is what belongs here rather than the family convention.

`MODEL_IDS` claims `2635B` only — not `263`, not `2600B`. The 2636B is
dual-channel and would be driven on one channel with the other silently
ignored; the 2634B lacks the 100 pA measurement range altogether. An
unclaimed instrument gets the manual driver dropdown; a wrongly claimed
one gets silently wrong limits.

## Reset defaults that had to be overridden

This is the longest such table in the suite, which is what a driver
written from a manual looks like when the reset table is read properly.

| Attribute | Resets to | Set to | Why |
|---|---|---|---|
| `format.asciiprecision` | 6 | 16 | six significant figures is below what Hall needs |
| `source.offmode` | `OUTPUT_NORMAL` | stated | "off" is a driven source |
| `source.offfunc` | `OUTPUT_DCVOLTS` | stated | selects 0 V rather than 0 A off-state |
| `source.offlimiti` | 1 mA | stated | the compliance across the sample when off |
| `measure.autozero` | — | `AUTOZERO_AUTO` | accuracy over timing, written rather than assumed |
| `source.highc` | — | `DISABLE` | high-capacitance mode changes the loop |
| `source.limitp` | 0 | 0, explicitly | non-zero power compliance overrides V and I limits |
| `sense` | `SENSE_LOCAL` | restated | 2-wire measures the leads as well as the sample |
| all four autorange flags | mixed | `AUTORANGE_ON` | `source.rangeY` documents a fixed 1 nA source current default |

**`measure.delay` is the one that vindicated the architecture.** It
resets to `DELAY_OFF` on a 2611B and to `DELAY_AUTO` on a 2635B. Same
attribute, same spelling, opposite default. That difference surfaced
during the decision review and settled the subclassing question on its
own — see below.

**A default that is never sent is a default nobody chose.** Several of
these writes are no-ops against current firmware and are kept anyway,
because firmware revisions move defaults and a value nobody stated is a
value nobody owns. That is fault 17, and this driver is where it was
first written down.

## Decisions and deviations

**D0 — standalone file, not a subclass of the 2611A.** The two speak the
same dialect and share perhaps 80% of their command text, so subclassing
was on the table and was rejected. The justification arrived almost
immediately in the `measure.delay` divergence above: a subclass would
have inherited the 2611A's assumptions about a family member that does
not share them.

The counter-argument is real and not dismissed — drifting copies is how
the original scripts died. The answer is that a shared `TSPSourceMeter`
base is the right eventual shape, but extracting it means refactoring a
bench-verified driver in the same patch that introduces an unverified
instrument, and a red test afterwards would not say which change caused
it. Deferred to its own wave.

**D1 — the output-off state is configured, not inherited.** Nothing
self-energises here: `source.output` resets to OFF and stays there. But
`offmode` resets to `OUTPUT_NORMAL`, `offfunc` to `OUTPUT_DCVOLTS` and
`offlimiti` to 1 mA, so an output that is "off" is still **actively
sourcing 0 V into the sample with a milliamp of compliance available**.
A driven low-impedance path, not an open circuit.

The suite's Stop-de-energises guarantee is therefore true in letter and
misleading in spirit, and it matters more here than next door: this is
the instrument bought for high-resistance samples, and a 1 mA path
across one between runs is six to nine orders of magnitude above
anything the measurement cares about. The temperature stage sharpens it
— a Peltier cycling under a shorted sample is exactly when a
thermoelectric EMF has somewhere to go.

**D2 — the off-state compliance stays at 1 mA**, deliberately rather
than lowered. The alternative off-state function, `OUTPUT_DCAMPS`,
sources 0 A and lets the terminals float to the 40 V `offlimitv`
default, which on a high-impedance sample is worse than a short: 0 V
with a limit at least holds the sample at a known potential. The manual
also warns that limits below 1 mA interfere with contact check. Exposed
as `OFF_STATE_CURRENT_LIMIT_A` so it is one constant to change.

**D3 — high-Z stays routed through `offmode`.** The manual offers a
second route, assigning `OUTPUT_HIGH_Z` directly to `source.output`,
which reaches high-Z without touching `offmode`. Deliberately unused, so
the suite expresses the idea one way rather than two. Recorded because
it has a trap in it: reading `source.output` back after that assignment
returns `0`, not `2`, so a future read-back verification must not expect
the value it just wrote.

**D5 — autozero left on AUTO, and written.** The manual describes
exactly the behaviour the 2611A's commissioning measured as a
three-aperture first reading: reference and zero conversions inserted
when they expire. Accuracy over timing — and the 2611A's finding now has
a documented cause rather than an inferred one.

**D6 — `set_source_delay(0)` is honoured as asked.** On this model that
replaces a `DELAY_AUTO` the instrument would otherwise apply: a
current-range-dependent settle inserted before every current
measurement, which on the low ranges is the box protecting the operator
from unsettled readings. Every experiment sets the delay explicitly, so
behaviour is deterministic either way; the point is that zero means
something stronger here than on the 2611A.

**D12 — the hardware sweep is not wired up.** The TSP sweep factories
are the same family the 2611A drives successfully and would very likely
work. "Very likely" is how the GSM's staircase earned three bench-found
deviations. The inherited software fallback reads back every level it
sources, so the measurement is sound and only the timing is
host-dependent. Upgrading is one file and nothing in `experiments/`
changes.

**D13 — no channel alias.** The 2611A sends `smu = smua` once per
connection and writes `smu.` thereafter, because its original scripts
did. There is no original here, so this driver addresses `smua.`
directly. It removes a piece of per-connection state that has to land
before any other command means anything, and it makes each command
self-contained — which is what lets the tests assert strings that read
exactly like the manual page. The failure it prevents is quiet: `smu.`
with no alias defined indexes a nil value in Lua, so the level never
changes and the run continues at whatever was set before.

**D15 — source and measure current ranges are different sets, and
`LIMITS` declares the sourceable one.** The 100 pA range is
measurement-only; the lowest this instrument can source is 1 nA.
`SMULimits.current_ranges` is consumed as the *sourced level* dropdown
by Van der Pauw and Hall, and as the *compliance* dropdown by IV sweep —
never as a measurement range — so it holds source ranges only.

Listing 100 pA would offer an operator a Van der Pauw current the
instrument cannot produce. It would clamp to its lowest source range and
the sheet resistance would be computed from a current that was never
sourced: no error, plausible number, wrong by the clamp ratio. That is
fault 4.

**This is the first instrument in the suite where the two sets differ**,
which is why the conflation went unnoticed across every earlier driver.
The cost is that the 100 pA *measure* range is unreachable from the app;
the fix is a `measure_current_ranges` field on `SMULimits` and a
dropdown to feed from it, which is a shared-layer change and does not
belong in the same patch as an unverified instrument. Still open.

**D16 — `compliance_tripped()` implemented, after the page was read.**
Deliberately left unwired in the first pass: `smuX.source.compliance` is
*named* in the limit-attribute page, but guessing how a Lua boolean
renders through `print()` would have produced a query that silently
always answered "fine". A wrong `False` is worse than an honest `None`.
The attribute's own page settled it, including a worked example whose
output is the bare word `true`. Two things it records that the driver
now documents: reading the attribute updates the status model and the
front-panel indicator as a side effect, and the flag covers the voltage,
current **and power** limits alike — so `True` means "a configured
ceiling is in control of the output" rather than "the compliance this
experiment set was hit".

### Two faults checked and found absent

Recorded as examined rather than unexamined, since both bit other
drivers here.

- **Fault 15 does not apply.** `smuX.source.limitY` states that the SMU
  always autoranges for the limit setting, so a compliance cannot be
  silently clamped by whatever range happens to be active — which is
  exactly what happened on the [Keysight U2722A](keysight-u2722a.md). The same page does
  impose an ordering rule the suite already follows: set the limit
  before turning the source on.
- **Fault 11 does not apply to ranging.** `smuX.measure.rangeY` states
  that setting a measure range explicitly disables autoranging for that
  function, so no `AUTORANGE_OFF` is needed first. The
  [Keysight B2901A](keysight-b2901a.md) needs the opposite, and the driver test asserts
  the absence of that dance so nobody copies the SCPI assumption across.

## Bench findings

- **2026-08-21:** the checkup at `7dc6264` returned 59 pass, 2 skip, no
  failures. `print(smua.source.compliance)` returned `true` at 0.9981 V
  against a 1 V limit.

- **The first reading after `output_on()` cost 1098 ms**, against a
  17 ms steady state — the largest first-read penalty in the fleet, and
  the reason the reported "233.6 ms per reading" is roughly fourteen
  times the real cost. This is the most sensitive instrument here and it
  autoranges the furthest, so it pays the most. Recorded as C6.

- **`limitp` is a third ceiling, and `*RST` is what protects you from
  it.** The 2600B reference lists power compliance alongside `limitv`
  and `limiti`, with the SMU applying whichever is lower — and reading
  `limitv` back reports the programmed value, not the effective one. It
  resets to 0 (disabled), and `Recall setup` is in its *Affected by*
  column, so a saved setup recalled at the front panel can carry a
  nonzero one into a session that never set it. `limitp: 0` is
  therefore a default this driver **depends on**, not one it inherited.

Commissioned 2026-08-13; probed 2026-08-14.

- **`*IDN?` confirmed** and auto-detection verified against it.
- **`measure.autorangeY` is ON at reset**, and **assigning
  `measure.rangeY` disables autorange without an explicit OFF** — the
  opposite of the B2901A, closing a decision that had been open.
- **A too-small measure range returns the 9.91e+37 sentinel rather than
  erroring.** On this instrument a range set too small does not fail: it
  returns a number thirty-seven orders of magnitude out, which parses as
  an ordinary float. Handled by `BaseSMU.drop_sentinel()`, which
  replaces in place rather than filtering — dropping a value by omission
  would shift every later column left and promote the current into the
  voltage's position.
- **Reading time is ~87 ms**, and the reason is a deliberate choice:

| Lowest range autoranging may use | Per reading | 200-point sweep |
|---|---|---|
| **100 pA** (what the driver sets) | 87 ms | ~27 s |
| 1 nA | 30 ms | ~15 s |
| 1 µA, or autorange off entirely | 30 ms | ~15 s |

The whole cost sits below 1 nA — raising the floor to 1 nA recovers all
of it and raising it further recovers nothing. About 20 ms of what
remains is fixed overhead no setting reaches.

## What this means for your data <!-- bench -->

**This is the instrument for high-resistance samples.** It measures to
100 pA where the 2611A stops at 100 nA, and that range is the reason it
is on the bench.

**Readings take about 87 ms, and that is the price of the 100 pA
range.** Autoranging is allowed all the way down, and searching those
bottom decades is where the time goes. Raising the floor does **not**
stop you reading sub-nanoamp currents — 10 pA still resolves on the 1 nA
range — it stops autoranging onto the 100 pA range, where the noise
floor and accuracy are better below roughly 100 pA. Whether that matters
is a property of your sample: at 200 V a 1 GΩ sample draws 200 nA and
the floor is irrelevant, while a 1 TΩ sample draws 200 pA and it is not.

If you are sweeping samples that never draw less than a nanoamp and the
27 seconds is costing you, it is one constant — `MEASURE_LOW_RANGE_FLOOR_A`
in `drivers/keithley_2635b.py`. Change it deliberately and note it in
the run, because it changes what the instrument is *capable of
measuring*, not just how fast it does it.

**It sources down to 1 nA, not 100 pA.** The app's range dropdowns are
fed from one list which drives sourced levels and compliance, so it
holds source ranges only. The 100 pA measure range is not reachable from
the app today.

**"Output off" does not disconnect the sample** — it drives 0 V into it
with 1 mA available. On a high-resistance sample between runs, that is
six to nine orders of magnitude above anything you are trying to
measure, and it matters most if the temperature stage is cycling under
it. Tick high-Z if the sample must genuinely float.

**The 200 V range needs the interlock line held high**, as on the 2611A,
and this bench keeps that line jumpered.

## Open questions

- **The 100 pA measure range is unreachable from the app.** Fixing it
  needs a `measure_current_ranges` field on `SMULimits` and a dropdown
  to feed from it — a shared-layer change wanting its own wave.
- **The driver has changed since 13 August** (Wave 6d added per-axis
  ranging hooks) and has not been re-checked. See [checkup-owed](../open/checkup-owed.md).
- **The 2600B reset table is not yet transcribed** into
  [the manual extracts](../reference/manuals/_index.md), so the table above is
  reconstructed from the driver and the decision record rather than
  quoted from the manual.
