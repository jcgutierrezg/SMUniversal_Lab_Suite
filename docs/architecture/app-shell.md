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
the app resolves each to a driver over a transport. `connect_role`
auto-detects from `*IDN?` through the registry;
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
`take_meas_number`, `unsaved_run_count`

Data CSVs auto-suffix and cannot be lost; the per-sample summary is the
one file allowed to replace itself. The rules, and the mutation-found
trap in `note_sample_context_changed`, are in
[The per-sample summary, and its one overwrite](../rules/11-summary-and-overwrite.md).

## 6. Safety gates

`check_source_point`, `guard_run`

`check_source_point` is where an operating point is measured against the
connected instrument's `SMULimits` before anything energises. It is the
reason a wrong `LIMITS` matters — see
[One range list standing in for two](../faults/16-one-range-list-for-two.md).

## 7. Shutdown

`shutdown_devices`, `on_close`

Turns the stage PID off, closes ports, and confirms with the operator if
runs are unsaved. `unsaved_run_count` drives that confirmation, and it
is the accepted cost of [Results and saving — no auto-save, ever](../rules/03-no-auto-save.md).

## Why it is one class and not five

It is a shell, and every one of those jobs is about *the window* rather
than about a measurement. Splitting it would mean each piece holding a
reference to the others, which is the same coupling in more files.

The line that keeps it honest is the layering rule: **`LabApp` knows
about experiments generically and about no experiment specifically.**
Every time that has been tested — the provider handoff, the summary
writer, the run gate — the answer was a declaration on the experiment
rather than a branch in the app.
