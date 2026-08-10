# HANDOFF — read this first

Context for continuing this project in a fresh conversation.

**All four measurement experiments are ported, tested and working.** There is
no porting work left. What follows describes the repo as it stands and the
rules for adding to it.

The original scripts are **not** in this repo and won't be uploaded again.
Work from the current code.

## The four documents

| File | Read it when |
|---|---|
| **HANDOFF.md** (this) | changing the code — architecture, house rules, traps |
| **INSTRUMENTS.md** | using or debugging an instrument — measured facts per SMU, plus a plain-language guide to getting accurate measurements |
| **PORTING_NOTES.md** | old saved data disagrees with new, or a design choice looks arbitrary |
| **README.md** | running the app, adding an experiment, file formats |

Each exists so the others don't have to carry its contents. If you find
yourself adding an instrument's measured behaviour here, it belongs in
`INSTRUMENTS.md`.

---

## Who you're working with

Electronics/mechanical engineer. Strong Python and C++, but self-describes as
having little background in software architecture or good practices. Works on
Windows, uses `uv` as environment manager. Prefers:

- Answers straight to the point
- Analogies for complex concepts
- Clarifying questions asked *before* long solutions
- Quality-of-life additions offered proactively

**When debugging, one command at a time.** Anything where the next move
depends on what the terminal prints — a failed `git apply`, a wedged
stash, an unexpected `git status` — give a single command, wait for the
output, then decide. Do not pre-empt with "if you see X do this, if you
see Y do that": that is guessing at branches instead of reading the
actual output, and it buries the one command that matters.

**Routine sequences go in one block.** Apply the patch, run the tests,
commit, push — that is a known-good path with nothing to diagnose, and
drip-feeding it wastes everyone's time.

Terminal commands must be complete and copy-pasteable, with the exact
flags. `git` especially: this is the part of the work furthest from his
background, and a vague instruction there is where time gets lost.
Plain `git` only — see "How work is delivered" below.

He does **not** run the experiments himself day to day — colleagues do. So when
a question turns on actual bench workflow, say that it needs checking with them
rather than assuming. He has been reliably good at giving direct corrections;
apply them cleanly without over-explaining.

Runs a lab with 5+ SMU models doing IV sweeps, Van der Pauw, and 4-point-probe
measurements. Has a Seeed Xiao (SAMD21) based hot/cold temperature stage he
built himself.

---

---

## The goal

One modular repository, replacing a pile of one-off Tkinter measurement
scripts, where:

- Every SMU driver lives in one place and is reusable
- Each measurement is a self-contained experiment
- Someone can add a GUI panel or a new instrument without understanding the
  whole codebase
- Instrument capability limits are enforced automatically

---

## Current state

### Working and tested

- **Core layers**: transports, drivers, experiments, app shell, launcher
- **Run control** (Wave 1, rolled out Waves 3 and 5a): `core/run_control.py`
  — one state machine, one run ID and cancellation token per run,
  provisional readings, and a single atomic commit gate. **All four
  experiments are on it.** Ossila 4PP first (Wave 3), then Van der Pauw
  (5a-i) and Hall (5a-ii). Each has a cancellation matrix that presses
  Stop at every boundary review §8 names — `test_*_lifecycle.py`
- **Calculation integrity** (Wave 4, rolled out Wave 5a):
  `core/calculation.py` — structured calculation inputs, mixed-sample
  refusal, a provenance chain from a derived value back to the runs and
  readings behind it, method version tags with golden-file guards, and a
  staleness gate that makes a result whose inputs have moved
  *structurally unable* to reach a saved file. Wired into 4PP, Van der
  Pauw and Hall; the IV sweep computes a fit rather than a derived
  physical quantity and is not on it
- **Instrument ownership** (Wave 1): `core/ownership.py` — exclusive,
  application-wide, keyed on the physical connection
- **Transports**: `VisaTransport` (pyvisa — GPIB/USB/TCPIP), `SerialTransport`
  (pyserial), `NullTransport` (demo mode)
- **Drivers**: `Keithley2450` (SCPI), `Keithley2401` (older 2400-series SCPI),
  `Keithley2611A` (TSP), `GWInstekGSM20H10` (a third SCPI dialect),
  `KeysightU2722A` (a fourth, channel-addressed),
  `UndalogicMiniSMU` (not a dialect at all - see below), `DummySMU`
- **Experiments**: `vanderpauw`, `hall`, `iv_sweep`, `ossila_4pp`
- **Sweeps on any SMU**: hardware sweep where the instrument has one, software
  fallback in `BaseSMU` where it doesn't — same three-method contract either
  way, so experiments never branch on model
- **Temperature stage**: `devices/temperature_control.py` + shared panel,
  available to any experiment in one line
- **Shared per-run instrument controls**: integration time (NPLC) and the
  high-Z output-off checkbox, both defined once in `core/gui/widgets.py` and
  used by `vanderpauw`, `hall` and `iv_sweep`. Driven by driver capability
  declarations (`NPLC_RANGE`, `HIGH_Z_OFF`), greyed out on instruments that
  lack them, applied every run and recorded in every CSV
- **Auto-detection**: `*IDN?` → driver, with manual-select and demo fallbacks
- **Driver contract test**: `tests/test_driver_contract.py` holds a LEDGER of
  which optional capability each driver has. Add a capability to one driver and
  the test fails for the others until each is implemented or recorded as
  deliberately absent — so drift between five hand-written drivers becomes a
  failing test rather than a bench surprise
- **Limit gate**: refuses out-of-range source points before anything is sourced
- **Demo mode**: full development without hardware

### What each experiment does

| Experiment | Measures | Notes |
|---|---|---|
| `vanderpauw` | Sheet resistance, 4 contact positions | Feeds Rs to Hall; NPLC control |
| `hall` | Carrier density, mobility, type | Can load Rs from a VdP CSV; NPLC control |
| `iv_sweep` | V or I sweeps, optional linear fit | Periodic/long-bias mode; runs on any SMU. Optional NPLC and OVP controls appear only on instruments that have them |
| `ossila_4pp` | Sheet resistance, resistivity, conductivity | Current list or triangular sweep; reversal averaging; geometry + thickness corrections |

### Verified by test, not just written

| Check | Result |
|---|---|
| Same experiment code over SCPI and TSP | Identical R (1234.0) from both |
| VdP solver vs original | Bit-identical |
| Full demo VdP run vs analytic `Rs = πR/ln2` | typically <0.05% error |
| Hall maths vs original | Bit-identical across 2000 random cases |
| Hall chain vs known carrier density | `n_s` recovered exactly |
| VdP → Hall sheet-resistance handoff | Round-trips through a real save/load |
| Stage protocol parse / limits / wire format | No failures |
| IV sweep fit vs known resistor | Recovers R to <0.05%, both directions |
| Software sweep on a 2450 (no hardware sweep) | Full experiment runs; 2200.0 Ω recovered |
| Sweep abort mid-run | Stops promptly, keeps points already taken |
| 2401 driver dialect vs the 2450's | Different commands; 470 Ω recovered end-to-end |
| 4PP reversal averaging | Recovers 5 mV signal under a 1 mV offset exactly |
| 4PP correction-table edges | Return a number and a warning, never raise |
| 4PP plot filtering | Ticks and overlap toggle both honoured |
| Window layout | All four landscape, inside 1600×1000 |
| No auto-save; grouped CSV; close guard | All hold |
| GSM-20H10 dialect vs the other three | Distinct spellings; 470 Ω via hardware sweep |
| GSM staircase rejected by the instrument | Falls back to software, run still completes |
| GSM NAN/over-range sentinels in a sweep | Dropped in pairs; fit still recovers R |
| NPLC + high-Z across all three experiments | Applied, clamped, and recorded in every CSV |
| Cross-driver capability ledger | Matches reality for all 5 drivers |
| `reset()` runs on connect | Called exactly once, logged to the console |
| U2722A channel list on every command | Present, comma form; queries use the space form |
| U2722A compliance after a range change | Survives; a driver that stops re-sending it fails |
| U2722A source range vs the sweep | Chosen once before the first point, never mid-sweep |
| U2722A sensing greyed out and pinned | CSV records `4-wire (hardwired)`, not the checkbox |
| U2722A end to end through `iv_sweep` | 470 Ω recovered, NPLC rounded to an integer in the file |
| GSM buffer stride | Counted from the data; a 3-column buffer does not decimate the sweep |
| GSM sweep restores what it changed | `MODE FIX`, `TRIG:COUN 1` — else the next reading breaks |
| miniSMU `reset()` never reboots | `client.reset()` is not called; the fake raises if it is |
| miniSMU firmware gating | 1.2.0 falls back to software sweep; unknown version does too |
| miniSMU sweep kind per mode | Voltage → hardware, current → software, same instrument |
| miniSMU NPLC↔OSR | The achievable window is recorded, not the number typed |
| miniSMU transport refuses text | Only `*IDN?` is answered; writes raise |
| miniSMU 12 V adapter note | Stated first in the console on every connect, any firmware |
| VISA backends are merged | An instrument only pyvisa-py can see still reaches the dropdown |
| A broken backend doesn't hide the others | Its error is reported, the working one still lists |
| `::RAW` resources are listed | The default `?*::INSTR` filter would hide them |
| Connect falls through backends | Records which one worked; failure names each error |
| Checkup catches a rejected command | Via the error queue, which the method call alone cannot see |
| Checkup catches a sweep that never moves | Point count alone would call it a pass |
| Checkup leaves the output off | Even when a check crashes mid-tier |
| Checkup runs on all seven drivers | Against each one's own fake; no crashes, all tiers |
| Compliance vs a stuck source | A short sweep at compliance is not called a fault |
| 2611A `measure.iv()` pair order | Current first, voltage second — a transposition fails loudly |
| Output re-enabled after a mode change | Or the 2401's `:READ?` hangs with no error |
| One timeout ≠ several faults | A device clear resyncs; if it can't, later failures are flagged as suspect |
| Read timeouts scale with NPLC | Not left at `measure()`'s 3 s default |
| miniSMU firmware parse | The last version token wins; a hardware rev can't masquerade as firmware |
| Compliance polarity | Judged by magnitude only — a railed output's sign means nothing |
| Every illegal run-state transition | Refused — the table is the specification, not documentation |
| A cancelled run one instruction before commit | Commits nothing; the check is inside the gate, under the same lock |
| A worker that never checks its token | Still cannot commit — cancellation doesn't rely on good manners |
| An obsolete worker during a later run | Refused at every checkpoint, though nothing is cancelled |
| Cancellation during a 5 s settle | Noticed in under 1 s, not after the full wait |
| Cleanup vs. the return to idle | Ownership is released *before* the state reads IDLE |
| A cleanup that throws | Logged; the controller still reaches IDLE and accepts the next run |
| Twenty threads claiming one instrument | Exactly one wins |
| Two windows, one GPIB address | The second is refused by name, not by traceback |
| An instrument that rejected `output_off()` | Caught via the error queue — the call itself returns cleanly |
| A failed mandatory reset | Blocks runs on that instrument until a clean reconnect |

Twenty-nine test files in `tests/`, none needing hardware. See the sanity check
at the bottom.

The last two rows are worth a note. `test_driver_contract.py` was written at
the end of this stretch and immediately found that `reset()` had never been
called by anything — every driver had one, two were tested, and no code path
invoked them. On the GSM that would have stopped the output turning on at all.
It was also mutation-tested: four deliberate regressions introduced and all
four caught, because a test that has never failed hasn't been tested.

---

## House rules — apply these to every new experiment

These were each asked for explicitly by the user. They are not stylistic
preferences to be re-litigated; treat them as requirements for the IV sweep and
everything after it.

### 1. Landscape three-column layout

Monitors are wide and short. Before this was fixed, Hall's window was
**1333 × 1219** — taller than a 1080p desktop, so the Run button sat below the
bottom edge and nothing reported an error.

`Experiment.build_panels()` builds three columns. **Do not override it** — if
you need to do something once the widgets exist, override `on_panels_built()`
instead, which it calls at the end. (An override of `build_panels` that forgot
`super()` would silently produce no columns and every panel would fail looking
for them.)

A panel picks its column by packing into the matching attribute on its first
line:

| Column | Holds | Question it answers |
|---|---|---|
| `exp.col_left` | diagram, position, temperature stage | what is the sample doing |
| `exp.col_mid` | measurement setup, Run / Stop | what am I about to run |
| `exp.col_right` | results table, calculation, plots | what came out |

Reading order is left to right in workflow order. Within a column, `PANELS`
order is top-to-bottom order.

Budget: **≤1600 × 1000 px, aspect ≥1.2.** `tests/test_layout.py` enforces it —
**add the new experiment to its `EXPERIMENTS` list** or it isn't covered.

If a column gets too wide, look at which one is *short*: the trick that saved
350 px on both setup panels was converting side-by-side pairs into a single
column of rows, spending height in the column that had it spare.

### 2. Console stays

`core/gui/console_panel.py` is built by `LabApp` for every experiment — nothing
to do per experiment, and **don't remove it**. The user likes it and wants it on
all future experiments. It's collapsible via its checkbox (worth ~150 px on a
short screen), and `app.log()` is safe from any thread.

### 3. Results and saving — no auto-save, ever

Runs are **not** written to disk as they complete. A run spoiled by a
misaligned sample or a badly seated contact must be discardable without ever
leaving a file behind.

The mechanism is in `core/run_store.py` and mostly inherited. To wire a new
experiment in:

```python
class MyExperiment(Experiment):
    CSV_SLUG = "iv_sweep"                 # -> <sample>_iv_sweep.csv
    CSV_TITLE = "IV sweep"                # header line in the file

    def calculated_fields(self):
        """Ordered mapping of derived results for the CSV header."""
        return dict(self._calculated)
```

and at the end of a run:

```python
run = Run(
    sample=sample,
    metadata={...},      # per-run values, repeated on every CSV row
    readings=[{...}],    # one dict per raw reading -> CSV columns
)
self.app.ui(self._record_run, row_values, run)
```

`_record_run` inserts the table row and registers the run under the **same
Treeview item id**, so a row and its raw data can't drift apart.

`save_runs()`, `delete_ticked()` and `clear_output()` are inherited — **do not
reimplement them.** The results panel needs these four buttons, in this order:

```
Copy ticked → Calc  |  Save → CSV  |  Delete ticked  |  Clear all
```

Save writes **one CSV per sample name**: a `# key: value` header of calculated
results, then a long-form table, one row per raw reading with per-run values
repeated alongside. Verified to load as `pd.read_csv(path, comment="#")` into a
clean numeric frame that `groupby` works on directly.

Calculated results attach **only** to the sample currently named in the setup
panel — the calculation panel holds one set of numbers, and copying them onto
every sample in the table would invent results for samples never calculated.

**Known cost, already accepted by the user:** an unsaved run exists only in
memory. `has_unsaved_runs()` drives a confirmation on close and on Clear all,
but a crash or power cut loses unsaved work. If this ever bites, the fix to
offer is a quiet session-recovery file written as runs complete and deleted on
successful save — crash safety without the clutter, since it never accumulates.
Deliberately not built; it wasn't asked for.

### 4. Temperature stage is one line

```python
from core.gui.temp_panel import build_temp_panel
PANELS = [..., build_temp_panel, ...]
```

`self.temp_ctrl` exists on every experiment already, and
`Experiment.shutdown_devices()` turns the PID off and closes the port. Record
the temperature per run in `metadata` (see `_stage_temperature()` in either
experiment) — it belongs with the data, not in a separate header.

### 5. Units: SI inside, convert only at the edges

Added in Wave 2 (review §54). Three lines, and `tests/test_parameters.py`
enforces the second one:

1. **Internally, everything is SI base.** Amps, volts, seconds, metres,
   tesla, ohms, kelvin. Not millimetres, not gauss, not milliseconds.
2. **Every numeric field of a parameter or result object names its
   unit**: `settle_s`, `thickness_m`, `field_t`, `compliance_v`. A
   dimensionless count takes `_n` — `points_n`, `reversals_n` — which is
   an explicit statement that there is no unit rather than an omission
   that might mean anything. The suffix table is
   `core.units.UNIT_SUFFIXES`; add to it before inventing a suffix.
3. **Convert at the boundary and nowhere else.** The panel parses what
   the operator typed into SI on the way in. If a downstream module
   wants something else — `fourpp_math` takes mm and µm, because the
   Ossila correction tables are published that way — the conversion goes
   in one named method on the parameter object, not inline at the call
   site. See `FourPointProbeParameters.as_math_geometry()`.

`test_every_numeric_field_declares_its_unit` walks every class listed in
`PARAMETER_CLASSES` in `tests/test_parameters.py`. **Add new parameter
classes to that list** or they are not covered.

### 6. Operator input goes through `core.validation`

Added in Wave 2 (review §24). `int(float(text))` accepted `2.5` as 2 at
five call sites, so a decimal in an integer box produced a different
experiment from the one requested, silently.

```python
from core.validation import whole_number, positive_number, si_level

reversals = whole_number(self.reversals_var.get(), "Reversals",
                         minimum=1, even_above_one=True,
                         reason="so that each polarity is measured the "
                                "same number of times.")
```

`ValidationError` subclasses `ValueError`, so the existing
`except ValueError` around form reading already shows these in a dialog.
It also carries `.field`, so a panel can highlight the offending box.

**This is for operator input only.** The seven `int(float(...))` calls
in drivers parse SCPI error codes, where truncation is the intended
reading. Do not route those through this module.

### 7. A run is a transaction — use `begin_run()`

Added in Wave 3. 4PP is the worked example; copy its shape.

```python
def _do_run(self, params):
    with self.begin_run(parameters=params) as run:
        run.on_cleanup(lambda: self.app.ui(self._end_run))
        run.enter(self.app.claim_instrument("source", run.run_id))
        smu = self.instrument("source")
        run.expect(params.points_n)
        try:
            ...                       # checkpoint before anything energising
            run.start()
            ...
        finally:
            report = run.confirm_shutdown(smu, log=self.log)
            if report.uncertain:
                self.app.report_uncertain_shutdown("source", report)
        run.commit(record, lambda r: self.app.ui(self._record_run, r, ...))
```

Four rules that are not obvious from the code:

- **`run.checkpoint()` goes before every step that energises or alters
  the output** — output-on, source-function change, each new level, each
  polarity flip, after every long wait, and immediately before commit.
  That list is review §8's, not a suggestion.
- **Register `on_cleanup` before the claim.** An `ExitStack` unwinds in
  reverse, so the UI must be told "idle" *after* the instrument has been
  handed back, not before.
- **The commit sink must not block.** The controller's lock is held
  while it runs, so post to the UI thread and return.
- **There is one Stop and it discards.** Do not add an OFF button to a
  new experiment. Cancellation is a token; the worker de-energises in
  its own cleanup, on the thread that owns the session. Nothing else may
  talk to the instrument during a run.

### 8. `app.ui()` is a queue, not a direct callback

Also Wave 3. Measurement threads hand work back with `app.ui(fn, ...)`
and `app.log(...)`; both put onto a queue that the main thread drains
every `UI_PUMP_MS`. Workers never call into Tcl.

This replaced a direct `root.after(0, ...)` from the worker, which is
not thread-safe — `after()` registers a Tcl command and Tcl is
single-threaded. The application only survived it because the main
thread sits inside `mainloop()`.

**What this means for tests.** Anything that drives the loop with
`root.update()` rather than `mainloop()` must drain explicitly:

```python
exp.app.drain_ui_now()
```

Sixty back-to-back `update()` calls take well under one pump interval,
so without the drain a committed row is still sitting in the queue when
the assertions run. Three existing test files needed this line added.

### 9. Converted values are compared with a tolerance, never `==`

Wave 3 measured it: a round trip through a power of ten is exact for
most doubles but not all. On realistic typed values — integers and one
or two decimals — `x/1e6` then `*1e6` fails to return `x` for about
2.9% of entries, and `x*1e-6` then `*1e6` for 28.7%. `core/units.py`
uses the better one; the residue is inherent and no arrangement of the
arithmetic removes it.

180 µm typed in comes back as 179.99999999999997. Scientifically
irrelevant, legible enough to matter when someone opens the CSV. If a
test asserts on a geometry value that has been through the snapshot, use
`math.isclose`.

### 10. A derived value carries its provenance — use `core/calculation.py`

Added in Wave 4, wired into 4PP, Van der Pauw and Hall in Wave 5a. If a
new experiment computes a physical quantity from measured runs, it goes
through this layer rather than reading widget strings and writing label
strings.

The shape, in the order a calculation goes through it:

1. Build a `CalculationInput` on the main thread — SI values **and the
   text the operator typed**, plus a `SourceRow` per contributing run.
2. `validate(calc, distinct_runs=...)`. Refuses mixed samples, missing
   or non-finite values, and one run backing two inputs. The message
   names the specific incompatibility, because a mixed-sample
   calculation is arithmetically perfect and the operator has nothing
   else to go on.
3. `require_set()` where the inputs must be a complete set — Van der
   Pauw's Pos1-4, Hall's four (position, field sign) combinations.
   **At copy time, not calculate time**: an operator may legitimately
   type one value in, and refusing that enforces traceability rather
   than correctness.
4. `derive(calc, outputs)` returns a frozen `DerivedResult` carrying a
   result id, the sample identity, the source run and reading ids, and
   the method and version. `to_metadata()` is what reaches the CSV
   header.

Three rules that are not obvious and were each learned the hard way:

- **Provenance is all-or-nothing per run.** Where one run fills several
  boxes, typing over any one of them drops that run as a source
  entirely. A chain that is half true reads exactly like one that is
  whole.
- **The staleness signature must include every input the result depends
  on, not just the numbers.** Hall's `sample_type` changes which
  carrier density is reported by a factor of the thickness and moves
  none of the eight voltages.
- **`calculated_fields()` returns `{}` when the result is stale.** The
  grey text on the panel is advice; this is the part that cannot be
  ignored. Raw data still saves.

The keys in the signature and in `CalculationInput.values` must match
exactly. Wave 5a-i shipped a version where one said `thickness_m` and
the other `thickness_um`: every result then read as permanently stale
and silently stopped reaching the CSV — no error, no dialog, just a
header with no Rs in it. `signature_difference()` now reports a disjoint
field set as a wiring fault rather than an edit, and every wired
experiment has a `test_..._is_never_stale` regression guard. Add one.

Method versions live in `core.calculation.METHODS`, and
`tests/golden/*.json` is what makes them load-bearing: change a formula
without bumping its version and the golden file stops reproducing. A new
method with neither golden cases nor a written reason in
`NOT_YET_COVERED` fails the suite.

### 11. Everything else

- One-way dependencies: `experiments/ → drivers/ → core/transports/`
- Every path that sources current goes through `app.check_source_point()` first
- Demo mode must work end to end before you claim anything is done
- `python3 -m py_compile` after every edit pass

---

## Architecture — and why

Read `README.md` for the layout. The reasoning behind it, which matters more:

### One-way dependency rule

```
experiments/  →  drivers/  →  core/transports/
```

Nothing in `core/` imports from `experiments/`; no driver imports an
experiment. The driver registry lives in `drivers/registry.py` for this
reason - it imports every driver module, so while it sat in `core/` the
dependency ran core -> drivers and importing anything from the core
pulled all seven drivers in with it. `core.driver_registry` still works
as a deprecated shim.

That last step is done as of Wave 1. `LabApp` is *handed* its registry
and its ownership manager rather than importing them:

```python
LabApp(root, ExperimentCls, registry=..., ownership=...)
```

Both default to the real thing, so `main.py` is unchanged, and
`core/gui/connection_panel.py` reaches the registry through
`app.registry`. Nothing under `core/` imports a driver module any more.
The immediate payoff is in the tests: `tests/test_wave1_wiring.py` hands
the app a registry holding one deliberately broken driver, which is not
something a monkeypatch of a module-level import does cleanly.

This is the single rule that keeps the thing maintainable as
experiments accumulate. If breaking it ever feels necessary, something is in
the wrong layer.

Shared GUI parts in `core/gui/` depend only on the experiment *interface*
(`exp.col_left`, `exp.log`, `exp.app`), never on a specific experiment — which
is why the rule still holds with panels shared between VdP and Hall.

### Why drivers, not just "SMU commands"

The 2611A speaks **TSP** (Lua-flavoured: `smu.source.leveli = 1e-4`). The 2450
and 2401 speak **SCPI** (`:SOUR:CURR:LEV 1e-4`). Same concept, incompatible
syntax. The driver layer exists so measurement code says
`smu.set_current_level(1e-4)` and never learns which.

This is what will collapse the dual-SMU script's `_2611`/`_2401` duplication
into single routines.

### Sweeps work on every SMU, not just the 2611A

Worth understanding before touching the driver layer.

The 2611A runs a sweep *inside the instrument*: one command starts it, the
points land in `nvbuffer1`, and the point-to-point spacing comes off the SMU's
own clock. Most SMUs, including the 2450, cannot do this — they can only be
stepped one point at a time from the PC.

The first version of this port only implemented the TSP path and left
`BaseSMU.start_linear_sweep()` raising `NotImplementedError`. The result was
that the IV experiment connected to a 2450, warned, and refused to Run. That
quietly gave up the whole point of the driver abstraction: one experiment,
any instrument in the lab.

`BaseSMU` now implements the sweep contract as a **software fallback** —
step the source, wait, measure, repeat, on a worker thread. It is built from
primitives every driver already has (`set_voltage_level`, `measure`,
`set_source_delay`), so any SMU gets a working sweep for free, including ones
not written yet.

Both mechanisms sit behind the same three methods:

| | `start_linear_sweep` | `sweep_points_ready` | `read_sweep` |
|---|---|---|---|
| **Hardware** (2611A) | fires `SweepVLinMeasureI` | reads `nvbuffer1.n` | reads the buffer |
| **Software** (everything else) | starts a worker thread | counts points collected | joins, returns lists |

`start_linear_sweep()` returns immediately in *both* cases — that is what lets
the experiment poll for completion identically either way, and it is why the
software version needs a thread at all. `IVSweepExperiment` contains no
branch on instrument model.

**The two are not equivalent, and the difference is recorded.** Levels are
equally accurate — the instrument is told each one explicitly. *Timing* is
not: software per-point spacing depends on host and bus latency, so a
GPIB hiccup stretches an interval. Every run therefore carries a `sweep_kind`
field in its CSV, and the console says which one is in use at connect time.
For anything timing-sensitive, prefer the 2611A and check that field before
comparing datasets taken on different instruments.

`supports_sweep()` still exists but is now true for every driver. It is kept
as the hook for an instrument that genuinely cannot sweep, which should say so
up front rather than fail mid-run. A new driver that can do better overrides
the three methods and sets `SWEEP_KIND = "hardware"`.

Covered by `tests/test_sweep_fallback.py`, which drives a real `Keithley2450`
over a fake transport holding a 2.2 kΩ resistor.

### Why limits live in drivers

Each driver declares an `SMULimits` with its hardware envelope. Two consumers:
the GUI (populates range dropdowns from the *connected* instrument) and the
safety gate (refuses out-of-range points before sourcing).

Note the power envelope: most SMUs can't reach max voltage and max current
simultaneously. A 2450 does 210 V @ 105 mA *or* 21 V @ 1.05 A. A flat
max_v/max_i pair would happily allow an impossible request.

### Why demo mode goes through the normal connect path

`NullTransport` answers `*IDN?` with a dummy ID; the registry resolves it like
any real instrument. Demo therefore exercises the *real* connect, threading,
and dropdown-refresh code, so bugs there surface at the desk rather than only
on the bench.

### Panel pattern

`build_x_panel(exp, parent)` attaches widgets as attributes on the experiment
and packs into one of the three column frames. The columns are created in
`Experiment.build_panels()` *before* any panel runs, so the `PANELS` list is
order-independent — reordering or removing a panel can't break the ones after
it. This was a deliberate fix; an earlier draft had the first panel create the
containers and was fragile.

### Run control — one lifecycle, not four sets of booleans

**Wave 1 built this; the experiments do not use it yet.** They still run on
their own `measuring` / `polling` flags. That split is deliberate: the review
asks for the infrastructure to exist and be provable *before* any scientific
behaviour changes, so a bad lifecycle design is found in a unit test rather
than in four half-converted experiments. Wave 2 migrates them one at a time,
simplest first.

**The problem it replaces.** Run state was a handful of per-experiment
booleans, combined differently in each. IV and 4PP had explicit run guards;
Van der Pauw and Hall did not. Scattered flags fail in ways a code review does
not show and a bench does: the UI reads idle while a worker is still alive, OFF
turns the output off and the worker turns it straight back on, or a run is
cancelled and a row is committed anyway.

**The analogy.** A run is a bank transaction, not a running total. Readings
accumulate in a private ledger nothing else can see; at the end one atomic
commit moves the whole thing into `run_store`, or nothing moves at all. A run
cancelled at 99 of 100 points commits nothing, exactly like a transfer
interrupted halfway leaves both accounts as they were. That is the project's
stated rule — *all cancelled runs are discarded regardless of experiment or
progress* — turned from a habit each experiment has to remember into a
mechanism.

**The states**, in `core/run_control.py`:

```
IDLE -> PREPARING -> RUNNING -> COMPLETED -> IDLE
          |             |
          |             +-----> FAILED     -> IDLE
          +---> CANCELLING ---> CANCELLED  -> IDLE
```

`RUNNING -> IDLE` is **not** legal, and neither is `CANCELLING ->
COMPLETED`. Both absences are load-bearing: the first would let a run end
without cleanup or a recorded status, the second would let a cancelled run
commit. The transition table is the specification, and every pair not in it is
asserted to raise.

**The shape a migrated experiment has:**

```python
with self.begin_run(parameters=snapshot) as run:
    run.enter(self.app.claim_instrument("source", run.run_id))
    run.start()
    run.expect(points * 2)                  # a short sweep is a refusal

    for level in levels:
        run.checkpoint("sourcing")          # cancellation + generation
        smu.set_current_level(level)
        run.sleep(settle_s)                 # wakes early on cancel
        run.add_reading({...})

    run.confirm_shutdown(smu, log=self.log)
    run.commit(built_run, lambda r: self.app.ui(self._record_run, row, r))
```

Everything after the block is automatic: terminal status, discarding
provisional readings, releasing the instrument, and only then returning to
idle. **Commit last** — a commit cannot be undone, so anything raised after it
is recorded on the status rather than pretending the row was discarded.

**Four things worth knowing before you touch it:**

- **`run.checkpoint()` does two jobs.** It raises if cancellation was
  requested, *and* it refuses to let an obsolete worker continue. A thread that
  outlived its run and woke during the next one holds a token the controller no
  longer recognises. A single global `stop_requested` cannot catch that — by
  then it has been cleared for the new run, which the stale worker reads as
  permission to carry on. Call it before anything that energises: output-on, a
  source-function change, a new level, a polarity flip, the start of a sweep,
  and immediately before commit.
- **`run.sleep()` instead of `time.sleep()`.** Van der Pauw settles for two
  seconds. With a plain sleep, OFF looks dead for that long, which is when an
  operator presses it twice or reaches for the instrument's own output key.
  Waiting on the cancel event costs nothing and makes the button feel instant.
- **Cancellation does not rely on the worker being well behaved.** A sequence
  with no checkpoints at all runs to the end and is still refused at the commit
  gate, because the check is inside the gate under the same lock cancellation
  takes. A missed checkpoint costs a wasted measurement, never a bad row.
- **`CompletionPolicy` decides what "completed" means, once.** Empty runs,
  short point counts, recorded errors, missing metadata and unconfirmed
  shutdowns are all refused, and the refusal lists *every* unmet condition
  rather than the first. Override it per experiment only with a reason written
  where you override it — IV periodic bias will need
  `require_shutdown_confirmed=False` because it deliberately holds the output
  on between runs.

### Three endings, not one

Cancellation, failure, and an unverifiable shutdown share a cleanup path and
must not share a message.

| Ending | What the operator is told | What happens to the instrument |
|---|---|---|
| Operator cancellation | "Run cancelled. No measurements were retained." No traceback — pressing OFF is a normal action | released normally |
| Run failure | names the stage, and states whether shutdown was confirmed | released normally |
| Uncertain shutdown | a modal warning: the output may still be energised | **blocked** until a clean reconnect |

The third is the one that matters. `confirm_output_off()` does not trust
`output_off()` returning cleanly: a SCPI instrument logs a command it did not
understand and carries on, so the write succeeds and the output is still on.
It asks the error queue afterwards. Being unable to *ask* is not evidence of a
fault — that is `read_error()`'s own documented rule — so an unreadable queue
is recorded and does not fail the run.

### Instrument ownership — a hotel key, not a queue ticket

`Transport` already serialises individual calls. That protects the wire and not
the experiment; every call below is individually thread-safe and the result is
nonsense:

```
Run A: configure voltage source
Run B: configure current source
Run A: set level
Run B: output on
Run A: measure
```

Run A measured a current source it did not configure, at a level it did not
set, with an output somebody else turned on, and nothing errored. So the unit
that gets locked in `core/ownership.py` is the whole run, from first
configuration command to verified shutdown. The key goes back at checkout —
after the room is tidy, not when the guest decides to leave — which is why
`run.enter(app.claim_instrument(...))` releases during run cleanup and the
state reads IDLE only afterwards.

**Keys name physical connections, not driver objects.** Two `Keithley2450`
instances pointing at one GPIB address are two Python objects and one
instrument; keyed on identity, two windows would both claim it successfully.
`Transport.connection_key()` supplies the key, defaulting to transport type
plus address. `NullTransport` has no address and falls back to identity, so two
demo windows are two simulated samples rather than contending for an imaginary
shared one.

Two limits, stated rather than hidden. The same box reached two ways (`COM3`
through `SerialTransport`, `ASRL3::INSTR` through VISA) produces two keys and
would not collide — nobody has been bitten by it, and that is where the fix
goes if anyone is. And ownership is process-wide: two *separate* copies of the
suite cannot see each other's claims. VISA usually refuses the second
connection itself, but that is the instrument's doing, not ours.

### A blocked instrument, and how to unblock it

Two things block an instrument, and both mean its state is unknown:

- **a failed mandatory reset** (Wave 1, issue A9). This used to be a logged
  warning saying the instrument "may be in whatever state it was left in" —
  the right description and the wrong response. On the GSM-20H10 it is not
  academic: `reset()` disables the output-enable interlock, so a reset that
  quietly failed produced a run of zeros rather than an error.
- **an output that could not be confirmed off** (issue A10).

A blocked instrument stays *connected* — you can talk to it, run the checkup,
retry — but any run that claims it is refused with the reason. The only remedy
is a reconnect that resets cleanly, which is deliberate: the block means
somebody should look at the hardware, and a reconnect is evidence they were at
the bench. There is no "clear warning" button and there should not be one.

### Streaming devices sit outside the driver stack

`devices/` holds hardware that isn't an instrument in the driver sense — no
`*IDN?`, no driver. The Xiao stage broadcasts a status line at 10 Hz and
acknowledges nothing, so `Transport.query()` has no meaning for it: it owns its
own serial port and a reader thread instead. If another streaming device turns
up, copy that shape rather than bending `Transport`.

---

## Next steps

Nothing is half-finished. These are options, not a queue.

### GSM-20H10 — checked against the full command reference

Every command the driver sends has been verified against the manual, argument
values included. Nothing is left inferred. The runtime probe stays in anyway: a
command existing in a manual and being accepted by the instrument in front of
you are different claims.

One genuine ambiguity remains. `:ABORt` is **absent from the command list** but
is mentioned in the `:MEASure?` prose as something performed internally, so
whether it is accepted over the bus is unclear. The driver stops sweeps with
`:TRIGger:CLEar`, which is documented outright.

**What to do on the bench:** connect the GSM in `iv_sweep` and read the console
line about the staircase sweep. That single line confirms the whole sequence
subsystem.

### Open questions for the lab — worth asking before more code

- **Was any 20H10 data taken near compliance?** The original script's `MEAS?`
  per point was resetting the compliance it had just set (deviation 11 in
  PORTING_NOTES.md). Runs that never approached compliance are unaffected;
  runs that did were not limited where they were supposed to be. Worth asking
  whoever owns that data.
- **Which OVP setting does the 20H10 rig actually want?** The original pinned
  `SOUR:VOLT:PROT MIN`, which the manual defines as **20 V** (not "the lowest
  possible"), with `DEF` — 210 V — commented out beside it. 20 V is preserved
  as the default, but it reads like a bench decision made for a reason that
  isn't written down.
- **Which experiments actually need high-Z off?** Now a checkbox, defaulting
  off, on all three experiments. Worth finding out which measurements genuinely
  need the sample isolated between readings so the default can be per-experiment
  rather than global if that turns out to be the better answer.
- **Is the 4-wire default right?** `iv_sweep` now defaults to 4-wire on every
  sweep. It matches how the rigs are described as wired, but nobody has
  confirmed it against a sample of known resistance. Partially answered for
  the U2722A: that one is hardwired 4-wire and has no command to change it,
  so the control is greyed out and pinned there. The question stands for the
  other four.
- **Was any U2722A data taken near compliance?** The original set the current
  limit before the range, and on this model the limit is clamped to whatever
  range is active at the time — R1uA with a 100 nA limit after `*RST`. Runs
  that never approached compliance are unaffected; runs that did were limited
  far below where they were supposed to be. Deviation 21 in PORTING_NOTES.
- **What are the miniSMU's LOW and HIGH voltage ranges, in volts?** No
  published document says, so the driver always selects AUTO. Worth an
  email to Undalogic; fixing the range would buy resolution on small
  sweeps.
- **Does anyone want the U2722A's other two channels?** The driver takes a
  `channel` argument defaulting to 1, which is what the original hardcoded.
  Two channels driving two roles at once is the dual-SMU experiment in
  disguise, and that is still unported.
- **Carrier-type sign calibration.** The Hall panel states carrier type in
  bold, but the sign depends on contact numbering, field direction and current
  polarity. Software cannot verify it. Has the lab ever confirmed it against a
  sample of known type?
- **Dual-SMU experiment.** Deliberately not ported — the requirements were no
  longer remembered. The `Keithley2401` driver exists, so if it is ever wanted,
  it can be built from clear requirements. Background in PORTING_NOTES.md.

### Possible work

- **Wave 2: migrate the experiments onto the run lifecycle.** The
  infrastructure is built and tested (`core/run_control.py`,
  `core/ownership.py`); the four experiments still use their own `measuring`
  flags. The review's own sequence is worth following — pilot it on **one**
  simple experiment first (4PP, or basic IV; *not* IV periodic bias, whose
  output continuity is the awkward case), prove it cannot retain partial data
  or accept a second run, then do Van der Pauw and Hall. Per experiment the
  work is: capture the parameters before the worker starts, claim the
  instrument, stage readings provisionally, make OFF call `cancel_run()`
  before sending the output-off, and commit once at the end. The shape is in
  "Run control" above.
- **Stabilise-before-measure**: block Run until |T − setpoint| is within
  tolerance for N seconds. Offered twice, deferred twice — the stage is
  currently logged but not waited on, so you can set 80 °C and immediately
  measure at 24 °C.
- **Ossila 4PP on the temperature stage**: currently has no stage panel, by
  request, since it is a bench spot-check. One line in `PANELS` if that changes.
- **New drivers**: see the walkthrough below. One file, one registry line, one
  ledger entry. The software sweep is inherited automatically.
- **Ossila 4PP NPLC**: the only experiment without the control. Left out
  because it is a bench spot-check, but it is two lines if that changes —
  `nplc_row()` in the panel, `apply_nplc()` in the run.
- **OVP elsewhere**: `OVP_CHOICES` is declared per driver but only the
  GSM-20H10 has any, and only `iv_sweep` offers the control.

### Adding the next SMU — the whole procedure

This is the path most likely to be walked next, so here it is in full.

**1. Get the script and the manual.** Ask for the working script *and* the
manual's Command List (the summary tables, not the prose pages). Both have
earned their place: the script shows what the lab actually does, the command
list settles argument values. Pasted text beats screenshots — SCPI ambiguity
between `:` and `;`, or `l` and `1`, is exactly the kind of error that fails
silently. Also ask for the `*IDN?` reply, which is the one thing no document
provides and which pins `MODEL_IDS` down from a guess to a fact.

**2. Decide what it is before writing anything.** A different instrument is
*never* a new experiment — that is what the driver layer is for. The test:

- Same measurement, different box → **driver only**, nothing else changes.
- Same result columns, different sweep shape (log, list, pulsed, hysteresis)
  → **a feature in the existing experiment**, not a subclass. Precedent: three
  IV scripts collapsed into one experiment with optional panels.
- Different *derived quantity* → **new experiment folder**. That is what earns
  `vanderpauw`, `hall` and `ossila_4pp` theirs.

**3. Read the original for the recurring faults.** Every script ported so far
has carried at least one. The checklist is in PORTING_NOTES under "Faults to
check for in any new original" — check it before writing the driver, not
after, because two of them change what the data means.

**4. Write the driver, the registry line, and the ledger entry.** README's
"Adding things" section has the ordered steps. The ledger entry in
`tests/test_driver_contract.py` is not optional bookkeeping: it is the thing
that forces a decision about the other four drivers when this one gains a
capability they lack.

**5. Test the command spellings, not just the results.** A wrong SCPI header
is logged by the instrument and ignored — no exception, no warning, the
previous setting simply stays in force. A test asserting only that a sweep
came back will pass against a driver that silently does nothing. Assert the
exact strings, and assert that the *other* dialects' spellings are absent.
`tests/test_gsm20h10.py` is the model.

**6. Where a command is inferred rather than documented, verify at runtime.**
The GSM's staircase sweep sends a probe command at connect and reads
`SYST:ERR?`, falling back to the software sweep if the instrument objects.
That turns a guess from a silent wrong answer into a logged, self-healing
case. Worth doing whenever the manual is incomplete.

---

## Gotchas discovered — don't rediscover these

**Don't assert against a displayed value.** `test_hall_handoff` failed roughly
one run in sixteen and looked like dummy-noise flakiness. It wasn't. The test
compared the VdP→Hall round trip against `vdp.rs_var`, which is the *label*
string formatted to 6 significant figures, while the CSV and the loader both
carry 9. Below ~1000 Ω/□ the truncation is invisible; above it, the gap
exceeds the 1e-6 tolerance and the test fails. So it would have failed forever
on high-resistance samples while passing on low ones.

The round trip was never the lossy step — the reference was. Assert against
`vdp._calculated["Rs_ohm_per_sq"]`, the value that actually gets written.
Display strings are for humans; tests should compare what goes in the file.


**The VdP script had a delay unit bug.** The original computed
`delay_us = ms × 1000` and sent it to `:SOUR:DEL`, but that command takes
**seconds** on the 2450 family (range 0–10000 s). A 2000 ms setting was
sending `2000000`. The instrument was almost certainly erroring or clamping.
The real settle came from the host-side `time.sleep(ms/1000)`, which was
correct — which is why it worked anyway. **Now implemented correctly (seconds).**
Intentional deviation #1. The user has been told.

**Don't lower `VOLTAGE_FIGURES` in the Hall experiment.** It is 9, not the
usual 6, and that is load-bearing: the Hall voltage sits under a resistive
offset 100–1000× larger, and the eight-term average recovers it by subtracting
nearly-equal numbers. Six significant figures put a ~0.1% floor on V_H before
any physics.

**Don't add a background `:READ?` poller.** A thread issuing `:READ?` while the
measurement loop is also issuing `:READ?` doubles the instrument's work and
makes point-to-point timing unpredictable. It isn't corrupting — the socket
lock makes each read atomic — but it buys nothing and costs timing.

**The VdP instrument model is an inference, not confirmed.** `:SOUR:CURR:VLIM`
is 2450/2460/2470-specific syntax, so the driver was written as a 2450. If it's
actually a 2460 or 2470, commands are the same but `LIMITS` needs adjusting —
one file, no experiment changes. **Worth confirming with the user.**

**The VdP SMU was originally on a raw TCP socket** (`169.254.43.121:5025`).
The user briefly asked to convert it to raw serial, then realised he'd confused
"SCPI" with "TCP", then settled on pyvisa. pyvisa handles the original address
natively as `TCPIP0::169.254.43.121::5025::SOCKET`. Note that `::SOCKET`
resources need `read_termination` set explicitly — VISA can't infer it the way
it can for `::INSTR`. Already handled in `VisaTransport.connect()`.

**Streaming devices don't fit `Transport`.** The abstraction assumes
request-response. Anything that broadcasts unsolicited needs a reader thread
and a snapshot, not `query()`. See `devices/temperature_control.py`.

**Tk `after` callbacks must be cancelled before the window dies.** The
temperature readout polls at 5 Hz; a tick scheduled just before close used to
fire into a dead interpreter and make Tk print `invalid command name ...`,
which looks like a crash and isn't. Cancelled in `shutdown_devices()`. Any new
polling panel needs the same.

**Modal dialogs block headless tests forever.** `tests/test_saving.py` and
`tests/test_hall_handoff.py` monkeypatch the `messagebox` module inside the
module under test. Copy that pattern — a test that hangs with no output is
almost always an unstubbed dialog.

**Watch which module a dialog lives in — there are three, not two.**
`save_runs()` lives in `experiments/base_experiment.py` and
`LabApp.on_close()` lives in `core/base_app.py`, each with its own
`messagebox` import. Stubbing only the experiment module catches neither.

The `on_close()` one is nasty because of *how* it fails. Every test that
records a run and then closes its window hits the unsaved-runs confirmation.
Unstubbed, the suite blocks forever on the **second** test — with the first
test's output already printed and reading as a clean pass. It looks like a
slow test, not a hang. Stub all three:

```python
import experiments.iv_sweep.experiment as iv_experiment
import experiments.base_experiment as base_experiment
import core.base_app as base_app
iv_experiment.messagebox = dialogs
base_experiment.messagebox = dialogs
base_app.messagebox = dialogs
```

**The sandbox shell is `dash`, not `bash`.** Brace expansion silently fails —
`mkdir -p foo/{a,b}` creates a literal directory named `{a,b}`. This already
caused one stray `{core` folder that had to be cleaned out of a delivered zip.
Use explicit paths or `bash -c`.

**Always compile-check after edits.** A `str_replace` during a docstring pass
once silently deleted a `self.client.connect(...)` line and broke indentation.
`python3 -m py_compile` caught it immediately. Cheap insurance.

**String replacements fail silently.** A `CSV_SLUG` override never landed
because the anchor text didn't match, and the experiment quietly used the base
class default — caught only because a test asserted the filename. Grep for the
new text after any scripted edit.

**The miniSMU is driven through a library, not a wire protocol.** It is
the one instrument here whose transport doesn't move text.
`MiniSMUTransport` wraps `minismu_py` and exposes it as `.client`; the
driver calls methods. `minismu-py` is a mandatory dependency, but it is still imported lazily
inside `connect()`: installed is not the same as importable, and a
broken or unloadable wheel should fail at connect time naming the
instrument rather than stopping the app and taking the other four
instruments down with it. Two traps are documented at length in the driver and worth
knowing before touching it: `client.reset()` reboots the box and kills
the connection (deviation 28), and its capabilities depend on the
firmware version rather than the model (deviation 29).

**The checkup works on every driver, not just the new ones.** It is
written entirely against the `BaseSMU` contract and the capability
declarations, so it drives all seven.
`tests/test_checkup_all_drivers.py` runs it against each driver's own
fake and asserts it completes, exercises all three tiers, and leaves the
output off. What differs between instruments shows up as *skips* - no
OVP, no high-Z, fixed sensing - never as failures.

**`set_source_function()` leaves the output state undefined — call
`output_on()` afterwards.** Changing the source function drops the output
on the 2400 family, and the drivers disable auto output-off so a sweep
holds its level between points. The 2401's documentation is explicit:
*"if auto output-off is disabled, then the output must be turned on
before you can perform a :READ?"*. Miss it and `:READ?` never answers —
it is `:INITiate` then `:FETCh?`, and `:FETCh?` only runs once the
source-measure operations complete, which with the output off they never
do. It surfaces as a VISA timeout, i.e. as a dead instrument. Every
experiment already does this correctly; `tools/smu_checkup.py` did not,
and that was the entire 2401 "current-source hang".

**A timed-out read desynchronises the session.** The instrument
finishes late, the reply lands in the output buffer, and the next query
collects the *previous* command's answer — so everything after runs one
step out of phase and nothing about the numbers says so. `Transport.clear()`
sends a device clear to resync (VISA implements it; the base returns
False rather than pretending). The checkup calls it on any timeout and
records whether it worked, so one slow reading stops reading as three
independent faults.

**Commission a new instrument with `tools/smu_checkup.py` before
trusting it.** The offline suite proves every driver has the right shape
and sends the right strings *to a fake*. It cannot prove real hardware
agrees, and the U2722A and miniSMU command spellings have never been
answered by an instrument. The checkup connects, auto-detects exactly as
the app does, walks the whole `BaseSMU` contract asking the instrument
after each command whether it understood, then sources small levels and
checks the readings against open-circuit expectations. It writes a
Markdown report and a JSON sidecar, so a later run can be diffed against
a known-good one.

    uv run tools/smu_checkup.py --list
    uv run tools/smu_checkup.py --demo
    uv run tools/smu_checkup.py --address ... --nplc 25
    uv run tools/smu_checkup.py --address USB0::0x0957::0x4118::MY62030002::INSTR

`--trace` logs every command and reply with its elapsed time and
appends the whole exchange to the report and the JSON. Use it when a
check hangs or times out: a result row names the *check* that failed,
which on a timeout says nothing about which of half a dozen commands
caused it.

`--nplc` sets the integration time for the Tier 3 measurements, which
otherwise runs at the fast end of the model's range. Giving it also makes
the checkup time readings at *both* that value and the fast end, and
report **apertures per reading** — about 1 means one integration per
reading, about 2 means voltage and current are integrated separately.
Measured in a single run on purpose: per-reading overhead varies by
machine and port (6.4 ms on one, 53 ms on another), so comparing two
separate runs is unreliable.

**Nothing should be connected to the output when it runs** - it prompts
to confirm. An open circuit is a DUT whose answers are known in advance,
which is what lets the readings be checked rather than merely recorded.
If you cannot unplug the rig, pass `--sample-connected` and those checks
are skipped rather than reported as faults. It also forces 2-wire where
the driver allows it, because open sense leads on an unconnected
instrument can slew the output to compliance; the U2722A and miniSMU
cannot be forced, and the report says so.

**`read_error()` is now part of the driver contract**, not an informal
habit. It is what lets the checkup ask "did you understand that?" rather
than merely observing that nothing crashed - a SCPI instrument logs an
unrecognised command and carries on, so the write returns normally and
nothing downstream can tell. All seven drivers implement it: `:SYST:ERR?`
on the SCPI ones, `print(errorqueue.next())` on the TSP 2611A, and a
constant empty queue on the miniSMU (whose library raises at the call
site instead) and the simulated driver.

**VISA is several implementations, and they see different
instruments.** `VisaTransport` no longer assumes one. It asks every
backend in `BACKENDS` (`""` for the system default, `"@py"` for
pyvisa-py), merges the answers for the dropdown, and at connect tries
them in order until one opens the resource. It also scans `?*` as well
as `?*::INSTR`, because a `::RAW` device is invisible under the default
filter. If a backend opens an instrument and then misbehaves - which the
U2722A has a history of - pick **"VISA (pyvisa-py)"** in the transport
dropdown, which never consults the vendor library at all.

**pyvisa-py cannot see USB instruments without `pyusb` and a libusb.**
It reports no error while finding nothing, which is the quietest of the
failure modes and exactly how a working, plugged-in U2722A goes missing
from the dropdown. Both are now hard dependencies (`pyusb`,
`libusb-package` - the latter ships the binary so Windows needs no
manual DLL). Run `uv sync` after pulling this.

**`uv run tools/timing_scan.py` before trusting any per-reading timing
number.** The checkup's two-point figure fits two parameters to two
points: zero degrees of freedom, so it passes through both by
construction and can neither be wrong nor be checked. It is enough to
catch a gross error — it found the miniSMU's — and not enough to pin the
value. This scans four or more integration times and reports the
residuals, which is the only thing that says whether the linear model
holds at all. It also refuses `--points 2`, and says why.

**`uv run tools/scpi_console.py` when the checkup cannot reach it.**
Sends commands one at a time and prints replies with timing, checking the
error queue after each write so a rejection is reported at the command
that caused it. A hung read is interruptible and triggers a device clear,
so a bisect session survives the failure it is investigating — which
matters, because the commands *after* the hang are the ones that identify
the cause. `--script` runs a file; `tools/probes/` holds prepared ones.

**`uv run tools/visa_doctor.py` when an instrument won't appear.** It
prints what every backend sees under every pattern, checks the USB layer
directly, and with `--idn` sends `*IDN?` to everything it finds. It
distinguishes the four causes of an empty dropdown, which the GUI cannot.

**Pick the "miniSMU" transport for the miniSMU — "Serial" will appear
to work.** The MS01 answers `*IDN?` over a plain serial connection, so
`SerialTransport` connects, auto-detection correctly identifies a
miniSMU, and the driver is handed a transport it cannot drive. The
symptom was "miniSMU transport is not connected" about a transport that
was connected and working. The driver now refuses at construction with a
message naming the fix. On the command line: `--transport minismu`.

**`tools/smu_checkup.py` no longer defaults to VISA.** It used to, which
meant pointing it at `COM3` reported "No VISA backend could open 'COM3'"
— blaming the backend for a transport the tool chose silently. A VISA
resource string is now recognised and used automatically; anything else
must state `--transport`, and the refusal says which to use. `--list`
prints the flag next to each address.

**Instrument-specific facts live in `INSTRUMENTS.md`, not here.** The
measured envelopes, per-reading costs, resolutions, offsets, slew rates
and command quirks for all five SMUs are in that file, with a
plain-language section for people who want good measurements and do not
care how an SMU works. Two general lessons from producing those numbers
are worth keeping in front of a developer, though:

**A two-point fit proves nothing.** Fitting `overhead + N × aperture` to
two timings fits two parameters to two points — zero degrees of freedom,
so it passes through both by construction and can neither fail nor be
checked. Two such fits were reported here as confirmed and both were
wrong; a six-point scan then showed the model itself did not hold.
`tools/timing_scan.py` refuses fewer than three points and prints the
residuals for exactly this reason.

**A timing fit is only as good as integration ÷ overhead, and timings
are only comparable within one run.** Per-reading overhead on the
miniSMU varied from 6 ms to 29 ms between sessions. The U2722A's 500 ms
aperture survived a cross-session comparison; the miniSMU's 5 ms
aperture against the same drift did not, and the resulting number was
wrong by a factor of five. `smu_checkup --nplc <slow>` takes both points
in one run, and says so when less than half a reading was integration.

## Commissioning status — all five instruments verified

Every driver has been run against its instrument with
`tools/smu_checkup.py`. As of 2026-08-06 all five pass with zero
failures.

**The per-instrument findings live in `INSTRUMENTS.md`.** Read that
before using or changing any driver — it has the measured envelopes,
timings, resolutions and quirks, and a plain-language section on getting
accurate measurements that assumes no knowledge of how an SMU works.

What belongs here is the part that generalises.

**Nine real faults were found, and the offline suite could not have
caught any of them** — every one was an instrument disagreeing with an
assumption, not a driver disagreeing with itself. Four of the nine
produced **plausible-looking wrong data rather than an error**: a sweep
of the right length all at 0 V; a sweep silently reduced to a third of
its points whose survivors fitted a perfect line; a sweep clipped by a
range that never widened; voltage and current for one point taken half a
second apart.

Three consequences worth keeping:

- **Check that a sweep *moved* and returned the *right number of
  points*, not merely that it completed.** The point-count check alone
  caught two of the four silent faults. Both checks are in
  `core/checkup.py` and both have looked redundant at times.
- **An instrument's account of itself can be wrong in both
  directions.** The GSM accepts `FORM:ELEM VOLT,CURR`, ignores it, and
  then answers `FORM:ELEM?` with `VOLT,CURR` while sending three
  columns. Where it matters, count what arrived rather than asking.
- **Ask the documentation before theorising from a trace.** Two of the
  hardest faults were solved by one sentence in a command reference,
  after several plausible and wrong theories had been built from traces.
  Traces narrow the question; manuals answer it.

**`set_source_function()` leaves the output state undefined — call
`output_on()` afterwards.** Instruments in the 2400 family drop the
output when the source function changes, and these drivers disable auto
output-off so a sweep holds its level between points. Miss it and the
next reading blocks until the VISA timeout with no error, looking
exactly like a dead instrument. Every experiment does this correctly;
the commissioning tool did not, and that cost two rounds of diagnosis.

**A timed-out read desynchronises the session.** The instrument replies
late, the reply lands in the output buffer, and the next query collects
the *previous* command's answer — so everything after runs one step out
of phase and nothing in the numbers says so. `Transport.clear()` sends a
device clear to resync; VISA implements it, the base class returns False
rather than pretending.

## Sanity check before changing anything

```powershell
uv sync
uv run python run_tests.py --all
```

One command, 245 tests. It must end with `All groups passed.`

Use `run_tests.py`, not plain `pytest`. Thirteen test files build real Tk
windows, and one Windows process does not survive that many Tcl
interpreters being created and destroyed - it fails with
`invalid command name "tcl_findLibrary"` or a complaint about a Tcl file
that is demonstrably present, in whichever test happens to run after the
runtime gives out. The runner gives each of those files its own process,
which is what the suite had implicitly when it was 25 separate scripts.

While iterating on one file, `uv run pytest tests/test_hall_math.py -v`
is fine. `tests/README.md` has the rest.

The same command runs in CI on Windows and Linux for every push and pull
request, so a break is caught before it reaches the bench.

## How work is delivered — git, patches and CI

Recorded here because it is not guessable from the repo, and getting it
wrong costs real time.

### Patches, not zips

Work arrives as a `.patch` file applied with `git apply`. A patch
expresses deletions, renames and moves; a zip cannot, which is how the
orphaned `temp_panel.py` survived Wave 0b's zip and was caught only by a
test.

**Confirm the base commit before generating anything.** The one failed
application in Wave 0 was an assumed base:

```bash
git switch main
git pull --ff-only
git log --oneline -1
```

`.patch` files are gitignored and must not be committed.

**Branch before applying, not after.** Applying first and branching
afterwards leaves the work on `main` and the branch pointing at the old
commit — recoverable with `git branch -f <branch> <commit>` and
`git reset --hard origin/main`, but avoidable:

```bash
git switch -c wave-name
git apply --check wave-name.patch
git apply wave-name.patch
uv run python run_tests.py
```

`git apply --3way` is the fallback if `--check` complains about context
or line endings. If that also fails, stop — a patch that will not apply
to a confirmed-clean base means the base assumption is wrong, and that
is worth catching rather than routing around.

### Plain `git` only

The user works through the GitHub **web UI** for pull requests and
merges. Do not give `gh` CLI commands; it is not installed and there is
no reason for it to be.

`git push` prints a "Create a pull request" link on a branch's first
push. Failing that:
`https://github.com/jcgutierrezg/SMUniversal_Lab_Suite/compare/main...<branch>`

### The PR is what runs CI

`.github/workflows/tests.yml` triggers on `pull_request` and on pushes
to `main`. **Pushing a feature branch alone runs nothing.** Open the PR
to get the four matrix cells.

Windows CI is load-bearing: it found a `ZeroDivisionError` and 15.6 ms
clock quantisation that a Linux container structurally cannot reproduce.
A red Windows job is information, not noise — read the log rather than
re-running it.

After a squash merge:

```bash
git switch main
git pull --ff-only
git branch -d wave-name
```

### Generated output in the working tree

`tools/smu_checkup.py` writes into `checkups/`, which is untracked. On
Windows a held handle in that directory can wedge `git stash -u` partway
through — it takes the untracked files, fails to remove the now-empty
directory, and leaves the tracked changes in place. Nothing is lost;
`git stash show --include-untracked --name-only "stash@{0}"` shows what
was captured.

Worth checking once: `git config status.showUntrackedFiles`. If it
prints `no`, untracked files are invisible in `git status`, which is
exactly how an orphaned file survives a wave.

## Starting a new conversation

Upload this repo, or point at it on GitHub. A suggested opening:

> Continuing a project — see HANDOFF.md in the attached repo, and
> WAVE_PLAN.md for where the structured work has got to. [what you want
> to do next]

`WAVE_PLAN.md` is the live document for the wave sequence: what each
wave shipped, what it deliberately left, and the decisions taken so they
are not reopened. Read it before proposing work — several questions that
look open have already been settled there, with reasons.

You should not need to upload the original scripts. If a question turns on
what an original did, PORTING_NOTES.md is in the repo and answers most of it.

If the next job is another instrument, say so and attach its script — there is
a step-by-step in "Adding the next SMU" above, and the useful first question
is always whether it is really a new experiment or just a new driver. It is
almost always just a new driver.

**Then commission it on the bench before trusting it.** Adding a driver is
half the job; `tools/smu_checkup.py` is the other half. Nine faults were
found that way across the existing five instruments, and none were
reachable from the offline suite. Add a row to the table in
`INSTRUMENTS.md` when it passes.

### What not to spend time on again

- **The miniSMU's OSR-to-NPLC scale.** Three values were tried and the
  underlying model was then disproved outright. The conclusion — the
  `nplc` column orders the settings correctly and means nothing
  absolutely — is in `INSTRUMENTS.md`, along with the one experiment that
  would settle it if anyone needs to. Do not re-derive it from timings.
- **Whether the U2722A's compliance reading is sign-inverted.** It is
  not. A railed output saturates whichever way its loop happens to go;
  a 10 kΩ resistor confirmed conventional polarity.
- **Whether `FORM:ELEM` can be made to work on the GSM.** It cannot, and
  querying it back does not reveal that. The stride is counted instead.
