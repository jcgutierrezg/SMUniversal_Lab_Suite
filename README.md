# SMUniversal Lab Suite

> **Continuing this work in a new conversation? Read `HANDOFF.md` first.**
>
> | File | Read it when |
> |---|---|
> | `HANDOFF.md` | changing the code — architecture, house rules, traps |
> | `INSTRUMENTS.md` | using or debugging an SMU — measured facts per instrument, and a plain-language guide to accurate measurements that assumes no SMU knowledge |
> | `PORTING_NOTES.md` | old saved data disagrees with new, or a design choice looks arbitrary |
> | `tests/README.md` | writing or running tests |

Modular Tkinter apps for SMU-based measurements. One repository holds all
instrument drivers; each measurement is a self-contained experiment that
plugs into a shared app shell.

## Running

```powershell
uv sync
uv run main.py                # experiment picker
uv run main.py vanderpauw     # straight into one
uv run main.py hall
uv run main.py iv_sweep
uv run main.py ossila_4pp
```

## Tests

```powershell
uv run python run_tests.py           # default; skips the slow ones
uv run python run_tests.py --all
```

Use `run_tests.py` rather than plain `pytest`. Twelve test files build
real Tk windows, and a single Windows process does not survive that many
Tcl interpreters being created and torn down; the runner gives each of
those files its own process. `uv run pytest tests/test_hall_math.py` is
fine while iterating on one file. See `tests/README.md` for the detail.

CI runs the same command on Windows and Linux for every push and pull
request.

VISA needs a backend. `pyvisa-py` (pure Python, in the dependencies) covers
TCP and serial. For GPIB you'll want NI-VISA or Keysight IO Libraries
installed separately — `pyvisa-py` can't drive a GPIB card on its own.

## Layers

Dependencies point one way only:

```
experiments/  →  drivers/  →  core/transports/
```

Nothing in `core/` imports from `experiments/`, and no driver imports an
experiment. If breaking that ever feels necessary, something is in the
wrong layer.

| Layer | Knows about | Does not know about |
|---|---|---|
| `core/transports/` | GPIB, USB, TCP, serial | SCPI, TSP, instruments |
| `drivers/` | command dialects, hardware limits, capability declarations | experiments, GUI |
| `experiments/` | measurement sequences, panels | command syntax, transports |

`core/` also holds the run lifecycle, which is shared by every experiment:

| Module | Holds |
|---|---|
| `core/run_control.py` | run states and legal transitions, per-run IDs and cancellation tokens, provisional readings, the atomic commit gate, and the completion policy |
| `core/ownership.py` | exclusive, application-wide instrument ownership, keyed on the physical connection |

`LabApp` is handed its driver registry and its ownership manager rather
than importing them (`LabApp(root, cls, registry=..., ownership=...)`,
both defaulting to the real thing), which is what keeps the one-way rule
true for `core/base_app.py` as well. HANDOFF.md has the reasoning under
"Run control".

Shared GUI parts live in `core/gui/`: the connection panel, the console,
the temperature-stage panel, and the corner diagram that Van der Pauw and
Hall both draw. They depend only on the experiment *interface*
(`exp.col_left`, `exp.log`, `exp.app`), never on a particular experiment, so
the one-way rule holds.

`devices/` sits outside that chain. It holds hardware that is *not* an
instrument in the driver sense — things that don't answer `*IDN?` and
don't resolve to a driver. The Seeeduino Xiao temperature stage is the
first: it free-runs a status line at 10 Hz rather than answering queries,
so it owns its own serial port instead of going through `Transport`. See
the header of `devices/temperature_control.py` for why.

## Window layout

Panels are spread across three columns that read left to right in the
order the work happens:

| Column | Holds | Question it answers |
|---|---|---|
| `col_left` | diagram, position, temperature stage | what is the sample doing |
| `col_mid` | measurement setup, Run / OFF | what am I about to run |
| `col_right` | results table, calculation | what came out |

A panel picks its column by packing into the matching attribute, on its
first line — there's no registry to keep in step. Within a column,
`PANELS` order is top-to-bottom order. The containers are built once in
`Experiment.build_panels()`, so both experiments share one layout;
override `on_panels_built()` for anything that has to happen after the
widgets exist.

Spare width goes to `col_right`; the other two are fixed-content forms
that would only gain whitespace. The console at the bottom folds away via
its checkbox, which is worth ~150 px on a short screen.

`tests/test_layout.py` asserts both windows stay landscape and inside a
1600×1000 budget. That guard exists because the failure is silent: one
extra panel pushes the Run button off the bottom of somebody's screen and
nothing anywhere reports an error.

## Saving

Runs are **not** written to disk as they finish. They collect in the
results table, and nothing is saved until you press **Save → CSV**. A run
spoiled by a misaligned sample or a poorly seated contact gets ticked,
**Delete ticked**, and never leaves a file behind.

Save writes **one CSV per sample name**, holding both the raw readings
and the calculated results:

```
# Hall effect - carrier density and mobility
# sample: wafer_A
# runs: 4
#
# --- calculated ---
# V_H_V: -0.0102361
# carrier_type: n-type (electrons)
# Rs_ohm_per_sq: 4532.36
# ...
#
run_timestamp,meas_number,position,b_polarity,...,point,voltage_V,current_A
...
```

The `#` header carries the per-sample results; the table is one row per
raw reading, with the per-run values repeated alongside. That is
redundant on disk and the right shape for plotting:

```python
df = pd.read_csv("wafer_A_hall.csv", comment="#")
df.groupby(["meas_number", "current_polarity"])["voltage_V"].mean()
```

Because the header is the same `# key: value` convention as everything
else here, Hall reads a sheet resistance straight out of a Van der Pauw
CSV with no extra parsing.

**The trade-off:** an unsaved run exists only in memory. Closing the
window with unsaved runs prompts first, but a crash or power cut loses
them. At 200 points and a 2 s settle that can be a quarter of an hour of
measuring.

## IV sweep

Linear voltage or current sweeps. Pick the mode on the left, set start/stop/points/delay in the
middle, press **Run**.

Sweeps run on any SMU in the suite. On a 2611A the sweep runs *inside the
instrument* — `start_linear_sweep()` fires its own `SweepVLinMeasureI` /
`SweepILinMeasureV`, the points land in `nvbuffer1` at the SMU's own
timebase, and the app polls `nvbuffer1.n` until they have all arrived. On an
instrument without a hardware sweep, the same three methods fall back to
stepping the source point by point from Python. The experiment cannot tell
the difference. Each run records which mechanism produced it in its
`sweep_kind` field — the two give equally accurate *levels* but not equally
trustworthy *timing*, so check that column before comparing datasets taken on
different instruments.

Completion is detected by polling the buffer rather than by sleeping a
calculated duration, so a short sweep cannot be read before the instrument
has finished filling it.

Each sweep is one row in the results table and one dataset in the plot.
Tick rows and press **Copy ticked → Plot** to overlay them; that is the same
button the other experiments label **Copy ticked → Calc**, since a sweep's fit
is per-sweep and the plot is where ticked runs go instead. A straight-line fit gives R and R2 per
sweep, shown in the table and written into the CSV header.

The fit is a toggle, because not every sample is ohmic. Fitting a line
through a diode returns a number that is meaningless but looks like a result
once it reaches the CSV. Untick **Linear fit** for those: the raw points are
stored exactly as they would be otherwise, and only the fitted columns are
left empty, so the sweep can still be re-examined later.

**Periodic measurement** is the long-bias mode: hold the sample at a bias
(or idle) for a set period, sweep, repeat. In the two biased modes the
output deliberately stays on across the standby-to-sweep boundary —
dropping it would discharge whatever is being measured.

Sensing is an explicit checkbox, applied on every sweep and recorded with the
data. It defaults to 4-wire, matching how the rigs are wired.

Three more per-run instrument settings sit alongside it, all applied on every
run rather than once at connect — otherwise the instrument keeps whatever the
last experiment left it in, and the same sample reads differently depending on
history:

- **Integration time (NPLC)** — how many mains cycles the ADC averages per
  reading. At 1 NPLC the mains hum on the leads completes a whole number of
  cycles inside the window and averages to zero, which is why 1 is the default
  rather than merely a middling value. Shutter speed on a camera: longer
  exposure, less grain, but nothing that moves stays sharp. Shared with Van
  der Pauw and Hall.
- **High-Z output off** — whether "output off" opens the output relay and
  disconnects the sample, or just sources 0 V into it. Light switch versus
  pulling the plug out of the wall. Defaults **off**, because the relay has a
  finite number of operations in it and a periodic run can cycle the output
  hundreds of times.
- **Overvoltage protection** — a hard ceiling on the source, separate from
  compliance. The case it earns its place for is a 4-wire sense lead falling
  off mid-run: the instrument reads 0 V at the sample, decides it is
  undershooting, and winds the output up to compensate.

Each is offered only on instruments whose driver declares it, and greys out to
`n/a` on the rest. All three land in the CSV.

## Ossila 4-point probe

Sources current through the outer two probes, measures voltage across the
inner two, fits a line to get resistance, then corrects it for the sample's
thickness and shape.

```
Rs = (π / ln2) · R · F_thickness(t/s) · F_geometry(W/s, L/W)
```

`π/ln2` is the ideal case — an infinitely thin, infinitely wide sheet. The two
correction factors pull that back to a real sample, and both come from
interpolated tables in `fourpp_math.py`. When a sample falls outside a table
the run still produces a number, but the result is flagged: too thick, or too
small for the geometry table. Take those warnings seriously — an unflagged
out-of-range geometry factor of 1.0 would over-report sheet resistance.

**Probe spacing is fixed at 1.27 mm** and shown on screen. It is not a
parameter with a default: both tables are indexed by t/s and W/s, so a
different probe head needs different tables, not a different number.

**W is the short side, L the long side** — there's a diagram in the panel
because it matters. The geometry correction is indexed by L/W and is simply
wrong if they're swapped, so the experiment refuses a run where L < W.

Two sweep shapes. **Current list** is the spot check: a handful of currents,
one voltage each. **Triangular** runs 0 → −I → +I → 0 and keeps only the
middle leg, which shows whether a hysteretic sample returns to where it
started.

**Reversals per point** alternate ±I at each current and average the result.
Contact junctions between dissimilar metals generate their own voltage, which
adds to every reading regardless of current direction; reversing flips the
sign of the real signal but not the offset, so the offset subtracts out. Set
it to 1 to disable. The cancelled offset is recorded per point — a large one
usually means a warm or poorly seated probe.

Each reading also carries the resistance implied at *that* current. If those
disagree by more than 2% the console says so: a single fitted slope hides
current-dependence inside its R², and drifting resistance is the signature of
self-heating or non-ohmic contacts.

**Calculate** is separate from the run on purpose. Change W, L or t and press
it to see the new sheet resistance without re-measuring — or type in a
resistance measured elsewhere.

## Van der Pauw → Hall

Hall needs a sheet resistance it can't measure itself, so the usual order
is a Van der Pauw run first, on the same sample.

Pressing **Save → CSV** in Van der Pauw writes `<sample>_vanderpauw.csv`,
whose header holds Rh, Rv, Rs and rho once Calculate has been pressed. In
Hall, **Load from VdP...** next to the Rs box reads that file back.

The file is the entire interface between the two - they're separate
windows that never share memory, and in practice the two runs may be days
apart. Hall records which file it used in its own saved data, so a result
can be traced back to the run that supplied its Rs, and warns if the
thickness, sample name or stage temperature don't match.

## Adding things

**A new SMU** — one file in `drivers/`, one line in
`drivers/registry.py`, one entry in a test ledger. Nothing in
`experiments/` changes. In order:

1. **`drivers/<model>.py`**, subclassing `BaseSMU`. Implement the mandatory
   methods (the ones `BaseSMU` leaves raising `NotImplementedError`), set
   `MODEL_IDS` so `*IDN?` finds it, and fill in `LIMITS` including the power
   envelope so the range dropdowns and the safety gate work.
2. **Declare optional capabilities.** `NPLC_RANGE`, `OVP_CHOICES`,
   `HIGH_Z_OFF`, `SWEEP_KIND`. Declaring one obliges you to implement its
   method, and implementing a method obliges you to declare it — the panel
   reads the *declaration* to decide whether to offer a control, so a working
   feature with no declaration stays greyed out forever.
3. **Register it** in `KNOWN_DRIVERS`.
4. **Add it to `LEDGER`** in `tests/test_driver_contract.py`, recording each
   capability as `True` or `False` with a comment saying why for the Falses.
   The test fails until you do, on purpose.
5. **Run `tests/test_driver_contract.py`.** It checks the mandatory methods,
   that declarations and implementations agree, that your `MODEL_IDS` resolve
   to *your* driver rather than poaching another's, that `LIMITS` is internally
   consistent, and that your method signatures match the rest of the suite.
6. **Write `tests/test_<model>.py`** with a fake transport, following
   `test_gsm20h10.py`. Assert the *exact command spellings*, not just that a
   sweep came back — a wrong SCPI header is logged and ignored by the
   instrument rather than raising, so a test that only checks the result will
   pass against a driver that silently does nothing.

If the model has a hardware sweep, override `start_linear_sweep`,
`sweep_points_ready` and `read_sweep` and set `SWEEP_KIND = "hardware"`.
If it doesn't, do nothing: the software fallback in `BaseSMU` is inherited
automatically and the experiment cannot tell the difference.

**A new panel** — write `build_x_panel(exp, parent)` under the
experiment's `panels/`, pack it into `exp.col_left`, `exp.col_mid` or
`exp.col_right`, and add it to that experiment's `PANELS` list. The list
is order-independent: layout containers are created before any panel
runs.

**A new experiment** — a folder under `experiments/` with an `Experiment`
subclass declaring `ROLES`, `PANELS` and `run()`, added to `EXPERIMENTS` in
`main.py`. Read the house-rules section of `HANDOFF.md` first: landscape
layout, the console, and explicit save-to-CSV results handling are
requirements, not defaults to opt into.

**A control that several experiments want** — put it in `core/gui/widgets.py`
as a `*_row()` builder plus `refresh_*()` and `apply_*()` helpers, driven by a
driver capability declaration. NPLC and the high-Z checkbox both work this
way. Three copies of one control is how the original scripts ended up with six
drifting versions of `LabeledEntry`.

## Multiple instruments

An experiment declares what it needs:

```python
ROLES = {"source": "Source SMU", "monitor": "Monitor SMU"}
```

The connection panel generates one row per role automatically, each with
its own transport, address, and auto-detection. Measurement code asks for
`self.instrument("monitor")`. This is what will collapse the dual-SMU IV
script's duplicated `_2611`/`_2401` function pairs into single routines.

## Safety gate

Before anything is sourced, `app.check_source_point()` validates the
requested operating point against the connected driver's `LIMITS` and
refuses outright rather than clipping. Limits include a power envelope,
because most SMUs can't reach max voltage and max current simultaneously
(a 2450 does 210 V at 105 mA *or* 21 V at 1.05 A).

Range dropdowns are repopulated from the connected instrument in
`on_connected()`, so values it can't reach are never offered.

## Demo mode (no hardware)

Pick **Demo** in the transport dropdown, or accept the offer when a
connection attempt fails. Either way you get `DummySMU`: a simulated
resistive sample that sources, clamps at compliance, and returns noisy
readings.

Demo goes through the *same* connect path as real hardware — `NullTransport`
identifies as a dummy via `*IDN?`, and the registry resolves it like any
other instrument. So the demo exercises the real connection, threading, and
panel-refresh code rather than a special case beside it.

The default sample is symmetric, which makes it a self-check as well as a
stand-in. A Van der Pauw run where all four positions read the same R has a
closed-form answer:

```
Rs = pi * R / ln(2)     # 1000 ohm sample -> 4532.36 ohm/square
```

`tests/test_demo_mode.py` drives a full four-position run and checks against
that. Tweak `SAMPLE_RESISTANCE`, `NOISE_FRACTION`, or `ANISOTROPY` at the top
of `drivers/dummy_smu.py` while developing (setting anisotropy away from 1.0
drops the analytic check, since the closed form no longer applies).

Real hardware can never land in simulation by accident: `DummySMU.MODEL_IDS`
matches only the ID string `NullTransport` returns.

## Tests

```powershell
uv run pytest tests/test_units.py                    # SI label round-trip
uv run pytest tests/test_dialects.py                 # same experiment code over SCPI and TSP
uv run pytest tests/test_demo_mode.py                # full VdP run vs the analytic answer
uv run pytest tests/test_temperature.py              # stage parsing, limits, wire format
uv run pytest tests/test_hall_math.py                # Hall arithmetic, 2000 random cases
uv run pytest tests/test_hall_demo.py                # full Hall run + copy/calculate pipeline
uv run pytest tests/test_hall_handoff.py             # carrier type + VdP→Hall Rs handoff
uv run pytest tests/test_layout.py                   # windows stay landscape and on-screen
uv run pytest tests/test_saving.py                   # no auto-save, grouped CSV, close guard
uv run pytest tests/test_iv_math.py              # sweep fit: R, R2, degenerate inputs
uv run pytest tests/test_iv_demo.py              # full IV sweep run, both modes, CSV
uv run pytest tests/test_sweep_fallback.py       # software sweep on a non-sweeping SMU
uv run pytest tests/test_2401_driver.py          # 2401 SCPI dialect + inherited sweep
uv run pytest tests/test_4pp.py                  # 4PP corrections, reversals, full run
uv run pytest tests/test_gsm20h10.py             # GSM dialect, staircase sweep, NAN guards
uv run pytest tests/test_shared_controls.py      # NPLC + high-Z across all 3 experiments
uv run pytest tests/test_u2722a.py               # U2722A channel list, ranging, limit order
uv run pytest tests/test_minismu.py              # miniSMU library wrapper, firmware gates
uv run pytest tests/test_2611a_driver.py         # TSP measure.iv() pair order
uv run pytest tests/test_visa_backends.py        # multi-backend VISA discovery
uv run pytest tests/test_checkup.py              # the commissioning tool, fault injection
uv run pytest tests/test_checkup_all_drivers.py  # it runs on all seven drivers
uv run pytest tests/test_scpi_console.py         # the bench console
uv run pytest tests/test_timing_scan.py          # the timing fit and its failure detection
```

All twenty-five run without hardware. Run them after pulling a change; you
do not need them day to day.

`test_dialects.py` uses a fake transport, so it needs no hardware. It's
the regression guard for the driver abstraction: if a change breaks the
seam, the two dialects stop producing identical results.

`test_driver_contract.py` is the one to know about when touching `drivers/`.
It holds a **ledger** of which optional capability each driver has, and fails
when reality and ledger disagree in either direction. Change a driver and it
tells you which of the other four you just left behind — the alternative being
five hand-written dialects drifting apart quietly, which is how the original
scripts died. Its own history is the argument for it: writing it immediately
exposed that `reset()` was never called by anything, which would have stopped
the GSM's output turning on at all at the bench.

## Bench tools

Four command-line tools in `tools/`. Unlike `tests/`, these talk to real
instruments and are the ones you actually run.

```powershell
uv run tools/smu_checkup.py --list          # what each transport can see
uv run tools/smu_checkup.py --demo          # self-test, no hardware
uv run tools/smu_checkup.py --address <addr>  # commission an instrument
```

| Tool | Use it when |
|---|---|
| `smu_checkup.py` | commissioning a new instrument, or one whose data looks wrong |
| `visa_doctor.py` | an instrument is plugged in and not in the address dropdown |
| `scpi_console.py` | a command hangs and you need to bisect by hand |
| `timing_scan.py` | before trusting any per-reading timing figure |

`smu_checkup.py` walks the whole driver contract against live hardware,
asking the instrument after each command whether it understood, then
sources small levels and checks the readings against open-circuit
expectations. It writes a Markdown report and a JSON sidecar so runs can
be compared. **Nothing should be connected to the outputs** — it prompts
to confirm.

It found nine real faults across the five instruments, four of which
produced plausible-looking wrong data rather than an error. See
`INSTRUMENTS.md`.

## Status

- **Van der Pauw** — sheet resistance from four contact positions. Feeds Rs
  to the Hall experiment.
- **Hall effect** — carrier density, mobility and type. Can load Rs from a
  saved Van der Pauw CSV.
- **IV sweep** — voltage or current sweeps, optional linear fit, and a
  periodic/long-bias mode. Runs on any SMU: instruments without a hardware
  sweep get the software fallback in `BaseSMU`.
- **Dual-SMU long bias** — not built. The `Keithley2401` driver exists, so it
  can be added if the requirement returns; see `PORTING_NOTES.md`.
- **Ossila 4-point probe** — sheet resistance, resistivity and conductivity.
  Both sweep shapes (current list and triangular), polarity-reversal
  averaging, and the geometry and thickness corrections.

**Instruments** — five SMUs, all commissioned against hardware: Keithley
2401, 2611A, Keysight U2722A, Undalogic miniSMU MS01, GW Instek
GSM-20H10. Measured behaviour and per-instrument quirks are in
`INSTRUMENTS.md`; that file also has a section on getting accurate
measurements written for someone who does not know how an SMU works.

**Instruments:** Keithley 2450, 2401 and 2611A, GW Instek GSM-20H10, and the
simulated `DummySMU`. Three SCPI dialects and one TSP. The GSM's driver is
verified against its command reference but has not yet run against the
instrument — see the bench checklist in `HANDOFF.md`.
