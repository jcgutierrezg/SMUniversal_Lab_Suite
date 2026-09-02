---
type: reference
title: "The core modules"
---

# The core modules

One row per module, answering the question a file list cannot: **what
breaks without it.**

That third column is the one this note was asked for. `core/` has grown
to the point where several files look like dead code from outside, and
two of them genuinely are never called — deliberately. Reading them does
not say so.

| Module | Holds | Called by | Without it |
|---|---|---|---|
| `core/base_app.py` | `LabApp` - the window, the tabs, the UI queue, connections, ownership, saving | everything | there is no application. See [The application shell](app-shell.md) |
| `core/run_control.py` | `RunController`: states, cancellation tokens, provisional readings, the commit gate | every experiment via `begin_run()` | a cancelled run can still commit its data. See [The run lifecycle](run-lifecycle.md) |
| `core/ownership.py` | Exclusive instrument ownership, application-wide | `LabApp.claim_instrument` | two tabs drive one instrument at once. See [Instrument ownership](ownership.md) |
| `core/calculation.py` | `CalculationInput`, `validate`, `derive`, `DerivedResult`, `UpstreamResult`, `METHODS` | 4PP, Van der Pauw, Hall | a derived number has no lineage and no staleness gate. See [Calculation and provenance](calculation-provenance.md) |
| `core/identity.py` | `SampleRef`, `SampleRegistry` - stable ids for samples, runs, readings, results | calculation, run store, the session strip | provenance cites names, and names are not unique |
| `core/ranges.py` | `RangePlan` and its four axes; `for_sourcing()` | every experiment, every driver | source and measure ranges share one ambiguous call. See [The ranging contract](ranging.md) |
| `core/limits.py` | `SMULimits`, the envelope check, `LimitError` | every driver's `LIMITS`, the safety gate | an operating point the instrument cannot reach is accepted |
| `core/parameters.py` | Immutable per-run parameter snapshots, SI-suffixed | every experiment | a widget edited mid-run changes what the run claims it did. See [Units: SI inside, convert only at the edges](../rules/05-si-inside.md) |
| `core/validation.py` | Shared validators for operator-typed fields | every setup panel | `2.5` in an integer box silently becomes 2. See [Operator input goes through `core.validation`](../rules/06-validate-operator-input.md) |
| `core/units.py` | The unit convention and `UNIT_SUFFIXES` | parameters, the unit test | suffixes get invented per experiment |
| `core/run_store.py` | `Run`, `RunStore`, the CSV writer, `unique_filename` | every experiment | runs are written as they complete. See [Results and saving — no auto-save, ever](../rules/03-no-auto-save.md) |
| `core/checkup.py` | `Checkup` - the tiered commissioning probe; `probe_levels_for()` - the levels it sources, reconciled against each driver's envelope | `tools/smu_checkup.py` | a driver is trusted because its tests pass, which is not the same claim. And one probe level for every instrument is a level some instrument cannot express - see [A test level the instrument cannot express](../faults/34-a-probe-the-instrument-cannot-express.md) |
| `core/readback.py` | The five states an instrument's answer about its own state can be in, and which of them is a pass | `BaseSMU.verify_compliance/verify_range/verify_power_limit`, `core/checkup.py` | a setting is a request until something reads it back, and a readback nobody has verified is not evidence. See [A setting reported from the command that was sent](../faults/33-a-setting-never-read-back.md) |
| `core/provenance.py` | `head_commit()`, `firmware_from_idn()`, `describe()` - which code and which firmware a bench report describes | `tools/smu_checkup.py`, via `core/checkup.py`'s report header | a finding is a claim about a version of the code *and* a version of the instrument, and reports recorded neither. Comparing a clean 2026-08-06 GSM-20H10 checkup against a six-failure 2026-08-18 one cost five rounds of hypotheses that a commit sha answers in one line |
| `core/event_log.py` | JSON Lines record of how every run ended | `experiments/base_experiment.py`, via a sink injected into `RunController` | a cancelled or failed run would leave no trace once the window closed. Records *that* a run happened, never what it measured (review §26) |
| `core/launcher.py` | `WINDOWS`, the picker, `main()` | `main.py`, and the `smu-lab-suite` console script | the application would have no importable entry point. A console script must name `module:function`, and pointing one at `main.py` would install a top-level `main` into site-packages |
| `core/single_instance.py` | machine-wide lock, taken by `main.py` before any window | `main.py` | two copies could each open the same instruments, each believing it controlled the output state. The lock is held by the OS, not written down, so a crash cannot leave it stuck |
| `core/version.py` | `__version__`, `app_version()` | `core/run_store.py`, and the event log when Wave 7d lands | stored files could not say which code wrote them. Not read from packaging metadata: `importlib.metadata` needs an installed distribution, and neither a checkout nor a frozen `.exe` is one |
| `core/thread_guard.py` | Tk-access-from-a-worker diagnostic | **nothing, by design** - opt-in and off | nothing at runtime. It is instrumentation, which is why it looks like dead code |
| `core/driver_registry.py` | A deprecation shim re-exporting `drivers.registry` | **nothing inside this repo** - kept for external importers | an outside script importing the old path breaks. Also why it looks deletable |
| `core/gui/connection_panel.py` | One row per role the experiment declares | every experiment | each experiment writes its own connection UI |
| `core/gui/console_panel.py` | The shared scrolling log | `LabApp`, for every tab | see [The console stays](../rules/02-console-stays.md) |
| `core/gui/temp_panel.py` | The stage panel | experiments that list it in `PANELS` | see [The temperature stage is one line](../rules/04-temperature-stage.md) |
| `core/gui/session_strip.py` | What is true of the whole window, not one tab: sample name, folder | `LabApp` | sample identity becomes per-tab and the two can disagree |
| `core/gui/plot_panel.py` | Embedded matplotlib | any experiment producing curves | four copies of the same canvas plumbing |
| `core/gui/corner_diagram.py` | The square with four labelled contacts | Van der Pauw, Hall | the operator guesses which contact is which |
| `core/gui/widgets.py` | Small shared widgets | panels | layout drifts between experiments |
| `core/transports/base.py` | The `Transport` contract | every transport | see [Sweeps and transports](sweeps-and-transports.md) |
| `core/transports/visa_transport.py` | pyvisa, multi-backend merge and fallthrough | most instruments | an instrument visible to one VISA backend is invisible to the app. Deviation 35 |
| `core/transports/ni_gpib_usb_hs_transport.py` | opt-in direct PyUSB/libusb path for a genuine NI GPIB-USB-HS | connection panel and `smu_checkup.py`, only when explicitly selected | a Windows bench with no VISA stack cannot reach its occasional GPIB instrument. Commissioned on Windows against a B2901A, all three tiers; see [Direct NI GPIB-USB-HS transport](direct-gpib-usb-hs.md) |
| `core/transports/serial_transport.py` | Raw pyserial | instruments on a plain serial line | - |
| `core/transports/minismu_transport.py` | Adapter around the vendor library | the miniSMU | see [Undalogic miniSMU MS01](../instruments/undalogic-minismu.md) |
| `core/transports/null_transport.py` | The wire that isn't there | demo mode | demo bypasses the real connect path and stops testing it. See [Dummy SMU (demo mode)](../instruments/dummy-smu.md) |
| `devices/temperature_control.py` | Seeeduino Xiao hot/cold stage over a serial side channel | `temp_panel` | see [Devices — why the stage is not a driver](devices.md) |

## The layering rule

```
experiments/  ->  drivers/  ->  core/transports/
                     ^
                  core/  (shared services: run control, ownership,
                          calculation, identity, ranging, units)
```

Nothing in `core/` imports from `experiments/`, and no driver imports an
experiment. If breaking that ever feels necessary, something is in the
wrong layer.

The concrete reason, rather than the principle: Hall consumes a sheet
resistance from Van der Pauw, and if it did that by naming
`VanDerPauwExperiment`, **no Hall tab could open without dragging Van
der Pauw in** and the two would stop being separable. It asks
`app.provider_of("sheet_resistance")` instead — a capability, not a
class reference. The 4PP computes a sheet resistance too; the day it
shares a window with Hall it declares the same string and nothing else
changes.

## The pattern that keeps recurring

**Declare a capability; never key on a name.** It appears four times:

| Declaration | Consumed by | Instead of |
|---|---|---|
| `PROVIDES` / `provide()` | `app.provider_of(name)` | importing the other experiment |
| `SUMMARY_QUANTITIES` | `write_sample_summary` | a per-experiment summary writer |
| `REMOTE_SENSE_CONTROL`, `HIGH_Z_OFF`, `SWEEP_KIND` | GUI enablement, file columns | `if model == "U2722A"` |
| `MODEL_IDS` in the registry | auto-detection | a hardcoded dropdown |

Each replaced something keyed on a model string or a class name. The
failure that motivates all of them is the same: **a name written in two
places is a name that will disagree with itself**, and the copy that
drifts is the one nobody is watching.

## Two modules that look deletable and are not

`core/thread_guard.py` has no callers because it is opt-in
instrumentation, off by default. It answers "is anything still reading
Tk from a worker?" and exists because that question was once answered
wrongly — see [`app.ui()` is a queue, not a direct callback](../rules/08-ui-is-a-queue.md).

`core/driver_registry.py` is a 34-line shim re-exporting
`drivers.registry`, kept so an external script importing the old path
still works. `tests/test_packaging.py` asserts that nothing *inside* the
repo imports it.
