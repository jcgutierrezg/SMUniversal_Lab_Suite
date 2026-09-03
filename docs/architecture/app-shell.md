---
type: reference
title: "The application shell"
---

# The application shell

`core/base_app.py` holds one class, `LabApp`, with enough methods that a
single line cannot say what it is for. They group into seven jobs, and
the grouping is the useful map.

## 1. Tabs and experiment hosting

`experiment`, `experiment_of`, `_build_ui`, `_on_tab_changed`,
`busy_experiment`, `_watch_run_states`, `_refresh_run_gate`

The app hosts experiments; it does not know what any of them measure.
`provider_of(quantity)` is the one place it brokers between them, and it
brokers by **capability string**, not class — see
[The core modules](core-modules.md#the-pattern-that-keeps-recurring).

`_refresh_run_gate` is why a second tab cannot start a run while a
sibling is measuring. It watches run *states*, not a flag anyone sets.

### What a window is, and why one of them is shared

`core/launcher.py`'s `WINDOWS` maps each command-line key to a window:
either one experiment class, or a list of them sharing a window. It is
the only place that decides, and `main.py` re-exports it.

| Key | Window |
|---|---|
| `vdp_hall` | Van der Pauw **and** Hall, as one session |
| `iv_sweep` | the IV sweep alone |
| `ossila_4pp` | the four-point probe alone |
| `fixed_source` | fixed sourcing vs time alone |

`vdp_hall` is a combination rather than a convenience. A Van der Pauw run
always immediately precedes a Hall measurement on the same mounted sample
with the same contacts, so the two share one SMU connection, one sample name
and thickness, one temperature stage and one save folder — the tabs are two
views onto one session. Hall is deliberately not offered on its own: the
sheet resistance crosses in memory from the Van der Pauw tab, so a lone Hall
window could obtain one by no route but the keyboard, and a window that
cannot do the measurement it is named after is a trap rather than a choice.
See [the handoff](../experiments/hall.md#the-handoff).

The other windows stay standalone for the mirror-image reason: different
instruments, different mounting, and nothing carried across. `EXPERIMENTS`
holds only the single-experiment entries, because a combination is not an
experiment class and cannot be constructed like one.

## 2. The UI queue

`ui`, `_drain_ui`, `_schedule_ui_pump`, `_stop_ui_pump`, `drain_ui_now`,
`run_in_background`, `log`, `_append_console`, `_log_direct`

Workers post work; the main thread drains it every `UI_PUMP_MS`.
Full reasoning in [`app.ui()` is a queue, not a direct callback](../rules/08-ui-is-a-queue.md). `drain_ui_now()` exists
for tests that drive the loop with `update()` rather than `mainloop()`.

## 3. Connections

`connect_role`, `connect_role_manual`, `_initialise_driver`,
`disconnect_role`, `is_connected`, `require_instrument`

An experiment declares *roles* (`"source"`, and in principle others) and
the app resolves each to a driver over a transport:

```python
ROLES = {"source": "Source SMU", "monitor": "Monitor SMU"}
```

The connection panel generates one row per role automatically, each with its
own transport, address and auto-detection, and measurement code asks for
`self.instrument("monitor")`. That mechanism is what a dual-SMU experiment
would be built on: the original scripts carried duplicated `_2611`/`_2401`
function pairs differing only in dialect, and roles plus the driver layer
collapse those into single routines. Nothing declares a second role today —
see [Keithley 2401](../instruments/keithley-2401.md) for the one question
that decides whether the dual-SMU long bias is one experiment or two.

`connect_role` auto-detects from `*IDN?` through the registry;
`connect_role_manual` is the fallback when detection fails, which is
what an instrument with an unread identity gets — see
[Keithley 2450](../instruments/keithley-2450.md).

## 4. Ownership

`instrument_key`, `claim_instrument`, `report_uncertain_shutdown`

See [Instrument ownership](ownership.md). `claim_instrument` returns a context manager, which
is what makes the claim release itself when the run's `ExitStack`
unwinds.

## 5. Files and saving

`select_path`, `unique_filename`, `write_atomic`, `write_sample_summary`,
`summary_collision_decision`, `_existing_files_for`,
`_ask_summary_collision`, `note_sample_context_changed`,
`take_meas_number`, `unsaved_state`, `unsaved_run_count`

Data CSVs auto-suffix and cannot be lost; the per-sample summary is the
one file allowed to replace itself. The rules, and the mutation-found
trap in `note_sample_context_changed`, are in
[The per-sample summary, and its one overwrite](../rules/11-summary-and-overwrite.md).

`write_atomic` writes exactly the text it is given — `newline=""`, so
the builder in `core/run_store.py` decides the line endings and the
platform does not. It used to translate them, which meant a saved CSV
did not match the string the code believed it had written. See
[fault 36](../faults/36-two-ends-disagreeing-about-newlines.md) and
[the stored-file schema](../reference/schema.md).

## 6. Safety gates

`check_source_point`, `guard_run`

`check_source_point` is where an operating point is measured against the
connected instrument's `SMULimits` before anything energises. It is the
reason a wrong `LIMITS` matters — see
[One range list standing in for two](../faults/16-one-range-list-for-two.md).

## 7. Shutdown

`on_close`, `_unsaved_data_guard_allows_closing`,
`_wait_for_runs_to_finish`, `shutdown_devices`, `_stage_pid_off`,
`_warn`, `is_closing`, `close_log`

An explicit, bounded, observable sequence rather than a list of side
effects. `on_close` walks it in this order, and the order is the safety
argument:

| Step | What it does | Why it is where it is |
|---|---|---|
| unsaved-data guard | asks before discarding | it can **refuse**, and a refusal must leave the window untouched |
| refuse new runs | `_closing` gates `guard_run` | a run started after the sweep is a worker nobody waits for |
| cancel every run | app first, then each `on_close()` | a subclass that forgets `super()` must not be able to leave one running |
| wait for idle | bounded, draining the UI queue | a run reaches IDLE only after cleanup released the instrument |
| de-energise | the stage, with a confirmed answer | the port closes **after** the answer, not instead of it |
| disconnect, destroy | transports, then the window | nothing here can be undone |

Every step appends to `close_log`, which is how a test reads the
sequence rather than inferring it. Two endings put a modal in front of
the operator and keep it there: a stage that could not be confirmed off,
and a worker still running when `CLEANUP_TIMEOUT_S` expires. Both are
raised directly rather than through `ui()` — see `_warn`.

`unsaved_state` drives the confirmation and is three-valued: an
experiment whose store cannot be read is named rather than counted as
zero. That guard is the accepted cost of
[Results and saving — no auto-save, ever](../rules/03-no-auto-save.md);
what it must never do is fail quietly, which is
[A guard whose own failure reads as all-clear](../faults/30-a-guard-that-fails-to-all-clear.md).
The de-energise half is
[A shutdown path that fails open](../faults/29-a-shutdown-that-fails-open.md).

## Why it is one class and not five

It is a shell, and every one of those jobs is about *the window* rather
than about a measurement. Splitting it would mean each piece holding a
reference to the others, which is the same coupling in more files.

The line that keeps it honest is the layering rule: **`LabApp` knows
about experiments generically and about no experiment specifically.**
Every time that has been tested — the provider handoff, the summary
writer, the run gate — the answer was a declaration on the experiment
rather than a branch in the app.
