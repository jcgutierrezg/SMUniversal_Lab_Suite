# Instrument checkup - Undalogic miniSMU MS01

- **Result:** PASS WITH WARNINGS
- **When:** 2026-09-16 14:29:00
- **Address:** COM5
- **Driver:** `UndalogicMiniSMU`
- **Write pacing:** none - writes sent as fast as the bus takes them
- **Code:** `3c2164e48fcb`
- **Firmware:** v1.4.6(6b82396)
- **`bench_code`:** `669d1886baae`
- **Checks:** 61 passed, 2 warned, 0 failed, 17 skipped

> This checkup assumes **nothing is connected to the output**. The measurement checks expect open-circuit behaviour, so a connected sample will produce warnings that are not faults.

## Warnings

- **sub-count voltage levels** - UNMEASURED on this model. Every fixed-range converter has a bottom count; below it a commanded level is offset residue whose sign is not commanded, which on the one instrument where this was measured drove the output to the range rail. Nothing in this suite puts a floor under a source voltage here, and nothing has measured where the floor is. Closed by one bench measurement: command plus and minus a small fraction of a count on a wide range and see whether the output follows the sign
- **voltage probe level is expressible on the active range** - probing at 0.1 V, and this model declares no floor: what a source level below one count of the active range does here is UNMEASURED. On the one instrument where it has been measured the output was offset residue whose sign was not the one commanded. Nothing here says this level is in that regime - it says nobody can tell

## Tier 1 - identity and declarations

| Check | Result | Detail |
|---|---|---|
| identify() | pass | Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396) |
| identity resolves to this driver | pass | UndalogicMiniSMU |
| firmware | pass | (1, 4, 6) |
| sweep kind | pass | hardware |
| reset() | pass |  |
| error queue after reset() | pass |  |
| sweep_note() | pass | requires the 12 V DC adapter - on USB-C power alone the MS01 is limited to 50 mA per channel rather than 180 mA, and rep |
| declared limits | pass | 12.0 V, 0.18 A, 5 current range(s) |
| probe levels | pass | source 0.1 V / 1e-06 A, compliance 0.0001 A / 1 V - no nominal level is outside this model's declared envelope, and none had to be substituted for one the active range could express, so all four are the nominal values |
| sub-count current levels | skip | this model has no source current range for a level to fall below, so the question does not arise in this form. What a sub-count source current would mean here is itself unmeasured |
| sub-count voltage levels | warn | UNMEASURED on this model. Every fixed-range converter has a bottom count; below it a commanded level is offset residue whose sign is not commanded, which on the one instrument where this was measured drove the output to the range rail. Nothing in this suite puts a floor under a source voltage here, and nothing has measured where the floor is. Closed by one bench measurement: command plus and minus a small fraction of a count on a wide range and see whether the output follows the sign |

## Tier 2 - configuration syntax (output off)

| Check | Result | Detail |
|---|---|---|
| output_off() | pass |  |
| error queue after output_off() | pass |  |
| set_remote_sense(False)  [2-wire] | pass |  |
| error queue after set_remote_sense(False) | pass |  |
| set_source_function('voltage') | pass |  |
| error queue after set_source_function('voltage') | pass |  |
| set_source_function('current') | pass |  |
| error queue after set_source_function('current') | pass |  |
| apply_ranges()  [sourcing voltage] | pass | source I=not sourced V=0.1, measure I=0.0001 V=auto (shared knob: I=0.0001, V=auto) |
| error queue after apply_ranges while sourcing voltage | pass |  |
| set_current_limit()  [sourcing voltage] | pass |  |
| error queue after set_current_limit while sourcing voltage | pass |  |
| set_voltage_level(0)  [sourcing voltage] | pass |  |
| error queue after set_voltage_level(0) while sourcing voltage | pass |  |
| apply_ranges()  [sourcing current] | pass | source I=1e-06 V=not sourced, measure I=auto V=1 (shared knob: I=auto, V=1) |
| error queue after apply_ranges while sourcing current | pass |  |
| set_voltage_limit()  [sourcing current] | pass |  |
| error queue after set_voltage_limit while sourcing current | pass |  |
| set_current_level(0)  [sourcing current] | pass |  |
| error queue after set_current_level(0) while sourcing current | pass |  |
| set_source_delay() | pass |  |
| error queue after set_source_delay | pass |  |
| apply_ranges(all AUTO) | pass | source I=auto V=auto, measure I=auto V=auto (shared knob, no conflict) |
| error queue after apply_ranges(all AUTO) | pass |  |
| compliance survives ranging | skip | the Undalogic miniSMU MS01 reports neither its compliance limit value nor a compliance flag, so a collapse here would be invisible |
| range readback: source current | skip | not sourced was requested, so there is no value to confirm against |
| range readback: source voltage | skip | Undalogic miniSMU MS01 has no confirmed query for this range, so what it is actually on is unknown |
| range readback: measure current | skip | Undalogic miniSMU MS01 has no confirmed query for this range, so what it is actually on is unknown |
| range readback: measure voltage | skip | auto was requested, so there is no value to confirm against |
| a current range wider than the old compliance survives the new one | skip | Undalogic miniSMU MS01 has no confirmed query for the measure current range, so whether a refused range stayed narrow cannot be seen |
| a voltage range wider than the old compliance survives the new one | skip | Undalogic miniSMU MS01 has no confirmed query for the measure voltage range, so whether a refused range stayed narrow cannot be seen |
| power limit is where the driver put it | skip | Undalogic miniSMU MS01 has no power-limit setting |
| a sub-count current level is refused | skip | this model declares no source current floor - see the tier 1 entry for what that means here |
| a sub-count voltage level is refused | skip | this model declares no source voltage floor - see the tier 1 entry for what that means here |
| set_nplc(0.0005)  [declared limit] | pass |  |
| error queue after set_nplc(0.0005) | pass |  |
| set_nplc(16.384)  [declared limit] | pass |  |
| error queue after set_nplc(16.384) | pass |  |
| set_nplc(0.0005)  [restored for measuring] | pass |  |
| OVP | skip | not declared for this model |
| high-Z output off | skip | not declared for this model |
| compliance_tripped() | skip | not implemented by this driver |
| link: the query after an unpaced configuration burst | skip | the configuration block never sent two writes in a row through the suite's transport (longest: 0), so no burst formed to test |

## Tier 3 - live measurement

| Check | Result | Detail |
|---|---|---|
| voltage probe level is expressible on the active range | warn | probing at 0.1 V, and this model declares no floor: what a source level below one count of the active range does here is UNMEASURED. On the one instrument where it has been measured the output was offset residue whose sign was not the one commanded. Nothing here says this level is in that regime - it says nobody can tell |
| output_on() | pass |  |
| error queue after output_on() | pass |  |
| measure() at 0 V | pass | (0.001833916, 5.241743e-08) |
| measure() at 0.1 V | pass | (0.1007929, 1.93662e-07) |
| open-circuit current is near zero | pass | 1.94e-07 A at 0.1008 V |
| error queue after measure() | pass |  |
| configure for current sourcing: set_source_function('current') | pass |  |
| configure for current sourcing: apply_ranges()  [current mode] | pass | source I=1e-06 V=not sourced, measure I=auto V=1 (shared knob: I=auto, V=1) |
| configure for current sourcing: set_voltage_limit(1) | pass |  |
| current probe level is expressible on the active range | skip | 1e-06 A; this model has no source current range for a level to fall below, so the question does not arise in this form |
| configure for current sourcing: set_current_level(1e-06) | pass |  |
| output_on()  [after the mode change] | pass |  |
| output gap across a source-function change | pass | 111 ms de-energised |
| measure() sourcing 1e-06 A into open circuit | pass | (-1.020739, 1.115819e-10) |
| compliance reached on open circuit | pass | -1.021 V against a 1.0 V limit, settled (sign not checked - a railed output saturates whichever way the loop happens to go) |
| compliance_tripped() while clamping | skip | this driver does not report compliance - a flat top on a curve may be the only warning you get |
| time per reading at NPLC 0.0005 | pass | 6.0 ms (1.2 s for a 200-point sweep), steady state - the first reading is reported separately below |
| first reading after the output comes up | pass | 6.0 ms, 1x the steady state |
| start_linear_sweep()  [hardware] | pass |  |
| sweep completes | pass | 5 points in 0.08 s |
| read_sweep() returns the right shape | pass | 5 pairs |
| the sweep actually moved | pass | 0.0012 to 0.1011 V |
| error queue after the sweep | pass |  |
| driver note after the sweep | pass | requires the 12 V DC adapter - on USB-C power alone the MS01 is limited to 50 mA per channel rather than 180 mA, and reports no way to tell which it is on; firmware 1.4.6; onboard voltage sweeps available (current sweeps still step point by point from the PC); integration is set by oversampling, which is not synchronised to the mains - an equivalent NPLC here rejects 50 Hz hum less well than a true NPLC; oversampling ratio 0 (the NPLC equivalent shown elsewhere orders these settings correctly but its absolute value is not a measured integration time - see the driver docstring) |
| output_off()  [cleanup] | pass |  |

## Command trace

```
    89.3 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
    89.3 ms  *IDN?  [?]
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
   101.4 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
    89.2 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
     7.1 ms  client.disable_channel(1)
     4.4 ms  client.set_autorange(1, True)
     4.3 ms  client.set_voltage_range(1, 'AUTO')
     4.1 ms  client.get_fourwire_mode()
             -> False
     6.6 ms  client.disable_channel(1)
    19.7 ms  client.set_mode(1, 'FVMI')
    20.7 ms  client.set_mode(1, 'FIMV')
    19.9 ms  client.set_mode(1, 'FVMI')
    16.6 ms  client.set_current_range_by_limit(1, 0.0001, disable_autorange=True)
             -> 2
     4.6 ms  client.set_voltage_range(1, 'AUTO')
     6.1 ms  client.set_current_protection(1, 0.0001)
     6.5 ms  client.set_voltage(1, 0.0)
    20.7 ms  client.set_mode(1, 'FIMV')
     4.3 ms  client.set_autorange(1, True)
     4.5 ms  client.set_voltage_range(1, 'AUTO')
     5.9 ms  client.set_voltage_protection(1, 1.0)
    13.1 ms  client.set_current(1, 0.0)
    20.1 ms  client.set_mode(1, 'FVMI')
     4.5 ms  client.set_autorange(1, True)
     4.6 ms  client.set_voltage_range(1, 'AUTO')
     4.2 ms  client.set_oversampling_ratio(1, 0)
     4.2 ms  client.set_oversampling_ratio(1, 15)
     4.1 ms  client.set_oversampling_ratio(1, 0)
    20.0 ms  client.set_mode(1, 'FVMI')
    16.4 ms  client.set_current_range_by_limit(1, 0.0001, disable_autorange=True)
             -> 2
     4.4 ms  client.set_voltage_range(1, 'AUTO')
     5.9 ms  client.set_current_protection(1, 0.0001)
     6.5 ms  client.set_voltage(1, 0.0)
     6.4 ms  client.enable_channel(1)
     6.2 ms  client.measure_voltage_and_current(1)
             -> (0.001833916, 5.241743e-08)
     7.0 ms  client.set_voltage(1, 0.1)
     6.2 ms  client.measure_voltage_and_current(1)
             -> (0.1007929, 1.93662e-07)
     7.1 ms  client.set_voltage(1, 0.0)
     6.4 ms  client.disable_channel(1)
    21.1 ms  client.set_mode(1, 'FIMV')
     4.3 ms  client.set_autorange(1, True)
     4.1 ms  client.set_voltage_range(1, 'AUTO')
     5.8 ms  client.set_voltage_protection(1, 1.0)
    12.5 ms  client.set_current(1, 1e-06)
     6.6 ms  client.enable_channel(1)
     6.4 ms  client.measure_voltage_and_current(1)
             -> (-1.021055, -2.341904e-09)
     6.2 ms  client.measure_voltage_and_current(1)
             -> (-1.020739, 1.115819e-10)
    12.5 ms  client.set_current(1, 0.0)
     6.7 ms  client.disable_channel(1)
    19.9 ms  client.set_mode(1, 'FVMI')
     5.9 ms  client.set_current_protection(1, 0.0001)
     6.6 ms  client.enable_channel(1)
     5.9 ms  client.measure_voltage_and_current(1)
             -> (-0.000702858, -6.762408e-09)
     5.9 ms  client.measure_voltage_and_current(1)
             -> (0.0005655289, -2.056792e-10)
     6.1 ms  client.measure_voltage_and_current(1)
             -> (-0.001337051, 2.697894e-11)
     5.9 ms  client.measure_voltage_and_current(1)
             -> (-0.001020432, -5.762401e-11)
     5.9 ms  client.measure_voltage_and_current(1)
             -> (0.0008831024, 4.812968e-11)
     5.8 ms  client.measure_voltage_and_current(1)
             -> (0.001517296, 9.043116e-11)
    27.1 ms  client.configure_iv_sweep(auto_enable=False, channel=1, dwell_ms=10, end_voltage=0.1, output_format='CSV', points=5, start_voltage=0.0)
     4.8 ms  client.execute_sweep(1)
     5.2 ms  client.get_sweep_status(1)
             -> SweepStatus(status='RUNNING', current_point=0, total_points=5, elapsed_ms=9, estimated_remaining_ms=0)
     5.5 ms  client.get_sweep_status(1)
             -> SweepStatus(status='RUNNING', current_point=3, total_points=5, elapsed_ms=34, estimated_remaining_ms=22)
     5.4 ms  client.get_sweep_status(1)
             -> SweepStatus(status='COMPLETED', current_point=5, total_points=5, elapsed_ms=60, estimated_remaining_ms=0)
   639.8 ms  client.get_sweep_data_csv(1)
             -> [SweepDataPoint(timestamp=171889212, voltage=0.0011997, current=1.3273e-10), SweepDataPoint(timestamp=171899204, voltage
     6.4 ms  client.disable_channel(1)
    88.7 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
     6.4 ms  client.disable_channel(1)
     6.2 ms  client.disable_channel(1)
     4.1 ms  client.set_autorange(1, True)
     4.1 ms  client.set_voltage_range(1, 'AUTO')
     3.9 ms  client.get_fourwire_mode()
             -> False
    19.8 ms  client.set_mode(1, 'FVMI')
    15.7 ms  client.set_current_range_by_limit(1, 0.0001, disable_autorange=True)
             -> 2
     4.2 ms  client.set_voltage_range(1, 'AUTO')
     6.4 ms  client.set_current_protection(1, 0.0001)
     6.4 ms  client.set_voltage(1, 0.0)
    88.6 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
     6.4 ms  client.disable_channel(1)
     4.2 ms  client.set_autorange(1, True)
     4.1 ms  client.set_voltage_range(1, 'AUTO')
     3.6 ms  client.get_fourwire_mode()
             -> False
    19.2 ms  client.set_mode(1, 'FVMI')
    15.5 ms  client.set_current_range_by_limit(1, 0.0001, disable_autorange=True)
             -> 2
     4.4 ms  client.set_voltage_range(1, 'AUTO')
     5.7 ms  client.set_current_protection(1, 0.0001)
     6.6 ms  client.set_voltage(1, 0.0)
    88.6 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
     6.5 ms  client.disable_channel(1)
     4.3 ms  client.set_autorange(1, True)
     4.1 ms  client.set_voltage_range(1, 'AUTO')
     3.7 ms  client.get_fourwire_mode()
             -> False
    19.2 ms  client.set_mode(1, 'FVMI')
    15.3 ms  client.set_current_range_by_limit(1, 0.0001, disable_autorange=True)
             -> 2
     4.4 ms  client.set_voltage_range(1, 'AUTO')
     6.0 ms  client.set_current_protection(1, 0.0001)
     6.3 ms  client.set_voltage(1, 0.0)
    88.7 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
     6.8 ms  client.disable_channel(1)
     4.2 ms  client.set_autorange(1, True)
     4.1 ms  client.set_voltage_range(1, 'AUTO')
     3.5 ms  client.get_fourwire_mode()
             -> False
    19.3 ms  client.set_mode(1, 'FVMI')
    16.2 ms  client.set_current_range_by_limit(1, 0.0001, disable_autorange=True)
             -> 2
     4.1 ms  client.set_voltage_range(1, 'AUTO')
     5.8 ms  client.set_current_protection(1, 0.0001)
     6.7 ms  client.set_voltage(1, 0.0)
    88.6 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
     6.5 ms  client.disable_channel(1)
     4.2 ms  client.set_autorange(1, True)
     4.1 ms  client.set_voltage_range(1, 'AUTO')
     3.7 ms  client.get_fourwire_mode()
             -> False
    19.1 ms  client.set_mode(1, 'FVMI')
    16.0 ms  client.set_current_range_by_limit(1, 0.0001, disable_autorange=True)
             -> 2
     4.4 ms  client.set_voltage_range(1, 'AUTO')
     5.9 ms  client.set_current_protection(1, 0.0001)
     6.2 ms  client.set_voltage(1, 0.0)
    88.7 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
     6.4 ms  client.disable_channel(1)
     4.1 ms  client.set_autorange(1, True)
     4.0 ms  client.set_voltage_range(1, 'AUTO')
     3.5 ms  client.get_fourwire_mode()
             -> False
    19.1 ms  client.set_mode(1, 'FVMI')
    15.3 ms  client.set_current_range_by_limit(1, 0.0001, disable_autorange=True)
             -> 2
     4.2 ms  client.set_voltage_range(1, 'AUTO')
     5.7 ms  client.set_current_protection(1, 0.0001)
     6.2 ms  client.set_voltage(1, 0.0)
    88.7 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
     6.4 ms  client.disable_channel(1)
     4.3 ms  client.set_autorange(1, True)
     4.3 ms  client.set_voltage_range(1, 'AUTO')
     3.6 ms  client.get_fourwire_mode()
             -> False
    19.1 ms  client.set_mode(1, 'FVMI')
    15.9 ms  client.set_current_range_by_limit(1, 0.0001, disable_autorange=True)
             -> 2
     4.4 ms  client.set_voltage_range(1, 'AUTO')
     5.8 ms  client.set_current_protection(1, 0.0001)
     6.1 ms  client.set_voltage(1, 0.0)
    88.3 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
     6.5 ms  client.disable_channel(1)
     4.2 ms  client.set_autorange(1, True)
     4.1 ms  client.set_voltage_range(1, 'AUTO')
     3.8 ms  client.get_fourwire_mode()
             -> False
    19.3 ms  client.set_mode(1, 'FVMI')
    15.8 ms  client.set_current_range_by_limit(1, 0.0001, disable_autorange=True)
             -> 2
     4.3 ms  client.set_voltage_range(1, 'AUTO')
     5.9 ms  client.set_current_protection(1, 0.0001)
     6.5 ms  client.set_voltage(1, 0.0)
    88.5 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
     6.5 ms  client.disable_channel(1)
     4.2 ms  client.set_autorange(1, True)
     4.1 ms  client.set_voltage_range(1, 'AUTO')
     3.6 ms  client.get_fourwire_mode()
             -> False
    19.3 ms  client.set_mode(1, 'FVMI')
    15.6 ms  client.set_current_range_by_limit(1, 0.0001, disable_autorange=True)
             -> 2
     4.5 ms  client.set_voltage_range(1, 'AUTO')
     6.0 ms  client.set_current_protection(1, 0.0001)
     6.2 ms  client.set_voltage(1, 0.0)
    88.5 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
     6.5 ms  client.disable_channel(1)
     4.2 ms  client.set_autorange(1, True)
     4.2 ms  client.set_voltage_range(1, 'AUTO')
     3.7 ms  client.get_fourwire_mode()
             -> False
    19.2 ms  client.set_mode(1, 'FVMI')
    16.0 ms  client.set_current_range_by_limit(1, 0.0001, disable_autorange=True)
             -> 2
     4.2 ms  client.set_voltage_range(1, 'AUTO')
     6.2 ms  client.set_current_protection(1, 0.0001)
     6.3 ms  client.set_voltage(1, 0.0)
    88.4 ms  client.get_identity()
             -> Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
     0.3 ms  client.close()
```
