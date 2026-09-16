# Instrument checkup - GW Instek GSM-20H10

- **Result:** PASS WITH WARNINGS
- **When:** 2026-09-16 16:08:17
- **Address:** USB0::8580::125::gew852313::0::INSTR
- **Driver:** `GWInstekGSM20H10`
- **Write pacing:** 5 ms after each write, as the driver declares
- **Code:** `5d32980234ae` **plus uncommitted changes**
- **Firmware:** V1.16
- **`bench_code`:** `4137020573fa`
- **Uncommitted when this ran:**
    - `?? 20h10_delay5.txt`
    - `?? 20h10_doubled.txt`
    - `?? 20h10_named.txt`
    - `?? 20h10_stale.txt`
- **Checks:** 73 passed, 5 warned, 0 failed, 5 skipped

> This checkup assumes **nothing is connected to the output**. The measurement checks expect open-circuit behaviour, so a connected sample will produce warnings that are not faults.

## Warnings

- **sub-count voltage levels** - UNMEASURED on this model. Every fixed-range converter has a bottom count; below it a commanded level is offset residue whose sign is not commanded, which on the one instrument where this was measured drove the output to the range rail. Nothing in this suite puts a floor under a source voltage here, and nothing has measured where the floor is. Closed by one bench measurement: command plus and minus a small fraction of a count on a wide range and see whether the output follows the sign
- **range readback: measure current** - reports 0.000105 A against 0.0001 A, but this readback has never been checked against a value this instrument was known to hold, so the agreement is not evidence
- **a current range wider than the old compliance survives the new one** - reports 0.00105 A against 0.001 A, but this readback has never been checked against a value this instrument was known to hold, so the agreement is not evidence
- **a voltage range wider than the old compliance survives the new one** - reports 21 V against 20 V, but this readback has never been checked against a value this instrument was known to hold, so the agreement is not evidence
- **voltage probe level is expressible on the active range** - probing at 0.1 V, and this model declares no floor: what a source level below one count of the active range does here is UNMEASURED. On the one instrument where it has been measured the output was offset residue whose sign was not the one commanded. Nothing here says this level is in that regime - it says nobody can tell

## Tier 1 - identity and declarations

| Check | Result | Detail |
|---|---|---|
| identify() | pass | GWInstek,GSM-20H10,GEW852313,V1.16 |
| identity resolves to this driver | pass | GWInstekGSM20H10 |
| sweep kind | pass | hardware |
| reset() | pass |  |
| error queue after reset() | pass |  |
| sweep_note() | pass | instrument staircase sweep accepted (runs off the SMU's own timebase) |
| declared limits | pass | 210.0 V, 1.05 A, 7 current range(s) |
| probe levels | pass | source 0.1 V / 1e-06 A, compliance 0.0001 A / 1 V - no nominal level is outside this model's declared envelope, and none had to be substituted for one the active range could express, so all four are the nominal values |
| sub-count current levels | pass | measured on this model, and this driver refuses a level below its declared floor before the output is energised |
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
| apply_ranges()  [sourcing voltage] | pass | source I=not sourced V=0.1, measure I=0.0001 V=auto |
| error queue after apply_ranges while sourcing voltage | pass |  |
| set_current_limit()  [sourcing voltage] | pass |  |
| error queue after set_current_limit while sourcing voltage | pass |  |
| set_voltage_level(0)  [sourcing voltage] | pass |  |
| error queue after set_voltage_level(0) while sourcing voltage | pass |  |
| apply_ranges()  [sourcing current] | pass | source I=1e-06 V=not sourced, measure I=auto V=1 |
| error queue after apply_ranges while sourcing current | pass |  |
| set_voltage_limit()  [sourcing current] | pass |  |
| error queue after set_voltage_limit while sourcing current | pass |  |
| set_current_level(0)  [sourcing current] | pass |  |
| error queue after set_current_level(0) while sourcing current | pass |  |
| set_source_delay() | pass |  |
| error queue after set_source_delay | pass |  |
| apply_ranges(all AUTO) | pass | source I=auto V=auto, measure I=auto V=auto |
| error queue after apply_ranges(all AUTO) | pass |  |
| compliance survives ranging | pass | 0.0001 A |
| error queue after compliance survives ranging | pass |  |
| range readback: source current | skip | not sourced was requested, so there is no value to confirm against |
| range readback: source voltage | skip | GW Instek GSM-20H10 has no confirmed query for this range, so what it is actually on is unknown |
| range readback: measure current | warn | reports 0.000105 A against 0.0001 A, but this readback has never been checked against a value this instrument was known to hold, so the agreement is not evidence |
| range readback: measure voltage | skip | auto was requested, so there is no value to confirm against |
| a current range wider than the old compliance survives the new one | warn | reports 0.00105 A against 0.001 A, but this readback has never been checked against a value this instrument was known to hold, so the agreement is not evidence |
| a voltage range wider than the old compliance survives the new one | warn | reports 21 V against 20 V, but this readback has never been checked against a value this instrument was known to hold, so the agreement is not evidence |
| power limit is where the driver put it | skip | GW Instek GSM-20H10 has no power-limit setting |
| a sub-count current level is refused | pass | 3.05176e-11 A against a 3.05176e-10 A floor: GW Instek GSM-20H10: a current level of 3.05176e-11 A is below the smallest this instrument can express on any range this model has - its narrowest is 1e-06 A (3.05176e-10 A). One count of that range is 3.05176e-11 A and this driver requires at least 10. Below a count the output is offset residue whose sign is not commanded - the instrument ignores the one you asked for. Refusing before the output is energised. |
| a sub-count voltage level is refused | skip | this model declares no source voltage floor - see the tier 1 entry for what that means here |
| set_nplc(0.01)  [declared limit] | pass |  |
| error queue after set_nplc(0.01) | pass |  |
| set_nplc(10)  [declared limit] | pass |  |
| error queue after set_nplc(10) | pass |  |
| set_nplc(0.01)  [restored for measuring] | pass |  |
| set_voltage_protection('20') | pass |  |
| error queue after set_voltage_protection() | pass |  |
| set_output_off_mode(high_z=True) | pass |  |
| error queue after set_output_off_mode() | pass |  |
| set_output_off_mode(high_z=False) | pass |  |
| compliance_tripped() | pass | False with the output off |
| link: the query after an unpaced configuration burst | pass | burst 4 of 10: the query after 22 consecutive writes was never answered, and 3 before it were. The link is now out of step - reconnect before using this instrument again, and power-cycle it if it will not answer. This is the fault the 5 ms pause this driver declares prevents, so the declaration matches the instrument |

## Tier 3 - live measurement

| Check | Result | Detail |
|---|---|---|
| voltage probe level is expressible on the active range | warn | probing at 0.1 V, and this model declares no floor: what a source level below one count of the active range does here is UNMEASURED. On the one instrument where it has been measured the output was offset residue whose sign was not the one commanded. Nothing here says this level is in that regime - it says nobody can tell |
| output_on() | pass |  |
| error queue after output_on() | pass |  |
| measure() at 0 V | pass | (5.9e-05, -6.7e-09) |
| measure() at 0.1 V | pass | (0.1000125, -3.6e-09) |
| open-circuit current is near zero | pass | -3.6e-09 A at 0.1 V |
| error queue after measure() | pass |  |
| configure for current sourcing: set_source_function('current') | pass |  |
| configure for current sourcing: apply_ranges()  [current mode] | pass | source I=1e-06 V=not sourced, measure I=auto V=1 |
| configure for current sourcing: set_voltage_limit(1) | pass |  |
| current probe level is expressible on the active range | pass | 1e-06 A is at or above the 3.05176e-10 A this instrument can express on the range the plan landed on |
| configure for current sourcing: set_current_level(1e-06) | pass |  |
| output_on()  [after the mode change] | pass |  |
| output gap across a source-function change | pass | 78 ms de-energised |
| measure() sourcing 1e-06 A into open circuit | pass | (1.000016, -4.98e-10) |
| compliance reached on open circuit | pass | 1 V against a 1.0 V limit, settled (sign not checked - a railed output saturates whichever way the loop happens to go) |
| compliance_tripped() while clamping | pass | reported True while riding the voltage limit |
| time per reading at NPLC 0.01 | pass | 14.4 ms (2.9 s for a 200-point sweep), steady state - the first reading is reported separately below |
| first reading after the output comes up | pass | 278.8 ms, 19x the steady state |
| start_linear_sweep()  [hardware] | pass |  |
| sweep completes | pass | 5 points in 0.10 s |
| read_sweep() returns the right shape | pass | 5 pairs |
| the sweep actually moved | pass | -6.2e-05 to 0.1001 V |
| error queue after the sweep | pass |  |
| driver note after the sweep | pass | the buffer held 60 readings for a 5-point sweep; the 55 after the first 5 are left over from an earlier, longer sweep (this model keeps them through TRAC:CLE and *RST) and were discarded |
| output_off()  [cleanup] | pass |  |

## Command trace

```
    11.5 ms  *IDN?  [?]
             -> GWInstek,GSM-20H10,GEW852313,V1.16
     1.5 ms  *IDN?  [?]
             -> GWInstek,GSM-20H10,GEW852313,V1.16
    10.3 ms  *IDN?  [?]
             -> GWInstek,GSM-20H10,GEW852313,V1.16
    10.8 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.5 ms  SOUR:SWE:SPAC LIN
     5.6 ms  SOUR:SWE:POIN 2
    19.6 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.4 ms  *CLS
     5.7 ms  *RST
     5.4 ms  SYST:CLE
     5.6 ms  SYST:BEEP:STAT 1
     5.6 ms  OUTP:ENAB 0
     5.5 ms  SYST:LFR:AUTO 1
     5.5 ms  SOUR:CLE:AUTO 0
     5.5 ms  ROUT:TERM FRON
     5.4 ms  TRAC:FEED:CONT NEV
     5.6 ms  FORM:ELEM VOLT,CURR
   108.5 ms  SYST:ERR?  [?]
             -> 0,"No error"
    10.0 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.6 ms  SOUR:SWE:SPAC LIN
     5.7 ms  SOUR:SWE:POIN 2
    19.7 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.6 ms  OUTP 0
    15.2 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SYST:RSEN 0
    15.1 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.7 ms  SENS:FUNC:CONC ON
     5.5 ms  SENS:FUNC:ON "VOLT","CURR"
     5.6 ms  SOUR:FUNC VOLT
     5.4 ms  SOUR:CLE:AUTO 0
    29.6 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SENS:FUNC:CONC ON
     6.0 ms  SENS:FUNC:ON "VOLT","CURR"
     5.5 ms  SOUR:FUNC CURR
     5.5 ms  SOUR:CLE:AUTO 0
    28.0 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.6 ms  SENS:FUNC:CONC ON
     5.6 ms  SENS:FUNC:ON "VOLT","CURR"
     5.7 ms  SOUR:FUNC VOLT
     5.7 ms  SOUR:CLE:AUTO 0
    28.6 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.4 ms  SOUR:VOLT:RANG:AUTO OFF
     5.5 ms  SOUR:VOLT:RANG 1.000000e-01
     5.5 ms  SENS:CURR:DC:RANG:AUTO OFF
     5.5 ms  SENS:CURR:DC:RANG 1.000000e-04
     5.5 ms  SENS:VOLT:DC:RANG:AUTO ON
   124.7 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.4 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     5.5 ms  SENS:CURR:DC:RANG 1.000000e-04
    19.9 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.6 ms  SOUR:VOLT 0.000000e+00
    14.7 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SENS:FUNC:CONC ON
     5.9 ms  SENS:FUNC:ON "VOLT","CURR"
     5.7 ms  SOUR:FUNC CURR
     5.7 ms  SOUR:CLE:AUTO 0
    28.6 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SOUR:CURR:RANG:AUTO OFF
     5.5 ms  SOUR:CURR:RANG 1.000000e-06
     5.5 ms  SENS:CURR:DC:RANG:AUTO ON
     5.7 ms  SENS:VOLT:DC:RANG:AUTO OFF
     5.7 ms  SENS:VOLT:DC:RANG 1.000000e+00
   124.2 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.4 ms  SENS:VOLT:DC:PROT:LEV 1.000000e+00
     5.6 ms  SENS:VOLT:DC:RANG 1.000000e+00
    18.9 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.2 ms  SOUR:CURR 0.000000e+00
    15.2 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SENS:FUNC:CONC ON
     5.8 ms  SENS:FUNC:ON "VOLT","CURR"
     5.5 ms  SOUR:FUNC VOLT
     5.4 ms  SOUR:CLE:AUTO 0
    29.2 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.4 ms  SOUR:DEL:AUTO 0
     5.7 ms  SOUR:DEL 0.01000
    19.5 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.6 ms  SOUR:CURR:RANG:AUTO ON
     5.6 ms  SOUR:VOLT:RANG:AUTO ON
     5.4 ms  SENS:CURR:DC:RANG:AUTO ON
     5.7 ms  SENS:VOLT:DC:RANG:AUTO ON
    29.1 ms  SYST:ERR?  [?]
             -> 0,"No error"
    10.0 ms  SENS:CURR:DC:PROT:LEV?  [?]
             -> +1.000000e-09
     5.3 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     5.5 ms  SOUR:VOLT:RANG:AUTO OFF
     5.5 ms  SOUR:VOLT:RANG 1.000000e-01
     5.3 ms  SENS:CURR:DC:RANG:AUTO OFF
     5.5 ms  SENS:CURR:DC:RANG 1.000000e-04
     5.5 ms  SENS:VOLT:DC:RANG:AUTO ON
   131.3 ms  SENS:CURR:DC:PROT:LEV?  [?]
             -> +1.000000e-04
     5.4 ms  SOUR:VOLT:RANG:AUTO OFF
     5.3 ms  SOUR:VOLT:RANG 1.000000e-01
     5.2 ms  SENS:CURR:DC:RANG:AUTO OFF
     5.6 ms  SENS:CURR:DC:RANG 1.000000e-04
     5.6 ms  SENS:VOLT:DC:RANG:AUTO ON
     5.7 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     5.5 ms  SENS:CURR:DC:RANG 1.000000e-04
    42.2 ms  SYST:ERR?  [?]
             -> 0,"No error"
    10.2 ms  SENS:CURR:DC:RANG?  [?]
             -> 1.050000E-04
     5.2 ms  SENS:FUNC:CONC ON
     5.7 ms  SENS:FUNC:ON "VOLT","CURR"
     5.7 ms  SOUR:FUNC VOLT
     5.5 ms  SOUR:CLE:AUTO 0
     5.5 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
    34.2 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SOUR:VOLT:RANG:AUTO OFF
     5.5 ms  SOUR:VOLT:RANG 1.000000e-01
     5.7 ms  SENS:CURR:DC:RANG:AUTO OFF
     5.6 ms  SENS:CURR:DC:RANG 1.000000e-03
     5.9 ms  SENS:VOLT:DC:RANG:AUTO ON
     5.5 ms  SENS:CURR:DC:PROT:LEV 1.000000e-03
     5.2 ms  SENS:CURR:DC:RANG 1.000000e-03
   149.5 ms  SENS:CURR:DC:RANG?  [?]
             -> 1.050000E-03
     5.3 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     5.5 ms  SENS:CURR:DC:RANG 1.000000e-03
   101.5 ms  SYST:ERR?  [?]
             -> +824,Cannot exceed compliance range
    10.1 ms  SYST:ERR?  [?]
             -> +824,Cannot exceed compliance range
    10.0 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SENS:FUNC:CONC ON
     5.6 ms  SENS:FUNC:ON "VOLT","CURR"
     5.3 ms  SOUR:FUNC CURR
     5.6 ms  SOUR:CLE:AUTO 0
     5.6 ms  SENS:VOLT:DC:PROT:LEV 1.000000e+00
    34.8 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.2 ms  SOUR:CURR:RANG:AUTO OFF
     5.4 ms  SOUR:CURR:RANG 1.000000e-06
     5.4 ms  SENS:CURR:DC:RANG:AUTO ON
     5.6 ms  SENS:VOLT:DC:RANG:AUTO OFF
     5.5 ms  SENS:VOLT:DC:RANG 2.000000e+01
     5.4 ms  SENS:VOLT:DC:PROT:LEV 2.000000e+01
     5.6 ms  SENS:VOLT:DC:RANG 2.000000e+01
   134.2 ms  SENS:VOLT:DC:RANG?  [?]
             -> 21
     5.2 ms  SENS:VOLT:DC:PROT:LEV 1.000000e+00
     5.4 ms  SENS:VOLT:DC:RANG 2.000000e+01
    20.6 ms  SYST:ERR?  [?]
             -> +826,Attempt to exceed power limit
     9.9 ms  SYST:ERR?  [?]
             -> +826,Attempt to exceed power limit
    10.2 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SENS:FUNC:CONC ON
     5.2 ms  SENS:FUNC:ON "VOLT","CURR"
     5.2 ms  SOUR:FUNC VOLT
     5.4 ms  SOUR:CLE:AUTO 0
     5.3 ms  SOUR:VOLT:RANG:AUTO OFF
     5.3 ms  SOUR:VOLT:RANG 1.000000e-01
     5.6 ms  SENS:CURR:DC:RANG:AUTO OFF
     5.3 ms  SENS:CURR:DC:RANG 1.000000e-04
     5.4 ms  SENS:VOLT:DC:RANG:AUTO ON
     5.8 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     5.7 ms  SENS:CURR:DC:RANG 1.000000e-04
   154.3 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.6 ms  SENS:FUNC:CONC ON
     5.9 ms  SENS:FUNC:ON "VOLT","CURR"
     5.4 ms  SOUR:FUNC CURR
     5.5 ms  SOUR:CLE:AUTO 0
    29.2 ms  SYST:ERR?  [?]
             -> 0,"No error"
     9.9 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SENS:FUNC:CONC ON
     5.5 ms  SENS:FUNC:ON "VOLT","CURR"
     5.6 ms  SOUR:FUNC VOLT
     5.5 ms  SOUR:CLE:AUTO 0
    30.0 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SENS:CURR:DC:NPLC 0.0100
     5.5 ms  SENS:VOLT:DC:NPLC 0.0100
    19.9 ms  SYST:ERR?  [?]
             -> 0,"No error"
     7.3 ms  SENS:CURR:DC:NPLC 10.0000
     7.9 ms  SENS:VOLT:DC:NPLC 10.0000
    15.1 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SENS:CURR:DC:NPLC 0.0100
     5.6 ms  SENS:VOLT:DC:NPLC 0.0100
     5.5 ms  SOUR:VOLT:PROT 20
    24.7 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.8 ms  OUTP:SMOD HIMP
    14.2 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.4 ms  OUTP:SMOD NORM
    14.8 ms  SOUR:FUNC?  [?]
             -> VOLT
    10.3 ms  SENS:CURR:DC:PROT:TRIP?  [?]
             -> 0
     5.3 ms  SENS:FUNC:CONC ON
     5.4 ms  SENS:FUNC:ON "VOLT","CURR"
     5.5 ms  SOUR:FUNC VOLT
     5.5 ms  SOUR:CLE:AUTO 0
     5.6 ms  SOUR:VOLT:RANG:AUTO OFF
     5.4 ms  SOUR:VOLT:RANG 1.000000e-01
     5.5 ms  SENS:CURR:DC:RANG:AUTO OFF
     5.5 ms  SENS:CURR:DC:RANG 1.000000e-04
     5.5 ms  SENS:VOLT:DC:RANG:AUTO ON
     5.5 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     5.6 ms  SENS:CURR:DC:RANG 1.000000e-04
     5.7 ms  SOUR:VOLT 0.000000e+00
     5.5 ms  OUTP 1
    71.6 ms  SYST:ERR?  [?]
             -> 0,"No error"
    22.5 ms  READ?  [?]
             -> +5.900000e-05,-6.700000e-09
     5.4 ms  SOUR:VOLT 1.000000e-01
    14.1 ms  READ?  [?]
             -> +1.000125e-01,-3.600000e-09
     1.6 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.6 ms  SOUR:VOLT 0.000000e+00
     5.4 ms  OUTP 0
     5.5 ms  SENS:FUNC:CONC ON
     5.5 ms  SENS:FUNC:ON "VOLT","CURR"
     5.3 ms  SOUR:FUNC CURR
     5.5 ms  SOUR:CLE:AUTO 0
     5.3 ms  SOUR:CURR:RANG:AUTO OFF
     5.5 ms  SOUR:CURR:RANG 1.000000e-06
     5.6 ms  SENS:CURR:DC:RANG:AUTO ON
     5.7 ms  SENS:VOLT:DC:RANG:AUTO OFF
     5.7 ms  SENS:VOLT:DC:RANG 1.000000e+00
     5.6 ms  SENS:VOLT:DC:PROT:LEV 1.000000e+00
     5.5 ms  SENS:VOLT:DC:RANG 1.000000e+00
     5.4 ms  SOUR:CURR 1.000000e-06
     5.6 ms  OUTP 1
   184.2 ms  READ?  [?]
             -> +9.999860e-01,-8.150000e-10
    14.0 ms  READ?  [?]
             -> +1.000016e+00,-4.980000e-10
     1.7 ms  SOUR:FUNC?  [?]
             -> CURR
    10.1 ms  SENS:VOLT:DC:PROT:TRIP?  [?]
             -> 1
     5.7 ms  SOUR:CURR 0.000000e+00
     5.5 ms  OUTP 0
     5.6 ms  SENS:FUNC:CONC ON
     5.4 ms  SENS:FUNC:ON "VOLT","CURR"
     5.5 ms  SOUR:FUNC VOLT
     5.6 ms  SOUR:CLE:AUTO 0
     5.4 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     6.0 ms  OUTP 1
   278.7 ms  READ?  [?]
             -> -6.300000e-06,-5.830000e-10
    14.3 ms  READ?  [?]
             -> +8.170000e-05,+6.700000e-11
    14.4 ms  READ?  [?]
             -> +1.740000e-05,+2.790000e-10
    14.6 ms  READ?  [?]
             -> -5.340000e-05,-4.660000e-10
    14.9 ms  READ?  [?]
             -> +4.000000e-07,-4.400000e-10
    13.7 ms  READ?  [?]
             -> -5.900000e-05,+4.680000e-10
     1.4 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.5 ms  TRAC:FEED:CONT NEV
     5.6 ms  TRAC:FEED SENS1
    20.0 ms  SYST:ERR:ALL?  [?]
             -> -140
,Character data error
    10.0 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.2 ms  TRAC:FEED:CONT NEV
     5.3 ms  TRAC:FEED SENSe1
    20.4 ms  SYST:ERR:ALL?  [?]
             -> -140
,Character data error
     9.9 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.3 ms  TRAC:FEED:CONT NEV
     5.6 ms  TRAC:FEED SENS
    20.5 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
    10.4 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.2 ms  SOUR:VOLT:STAR 0.000000e+00
     5.5 ms  SOUR:VOLT:STOP 1.000000e-01
     5.5 ms  SOUR:SWE:SPAC LIN
     5.6 ms  SOUR:SWE:POIN 5
     5.5 ms  SOUR:SWE:DIR UP
     5.6 ms  SOUR:SWE:RANG BEST
     5.5 ms  SOUR:VOLT:MODE SWE
     5.6 ms  SOUR:DEL 0.01000
     5.2 ms  ARM:COUN 1
     5.5 ms  TRIG:COUN 5
     5.5 ms  TRAC:FEED:CONT NEV
     5.5 ms  TRAC:CLE
     5.5 ms  TRAC:POIN 5
     5.5 ms  TRAC:FEED SENS
     5.5 ms  FORM:ELEM VOLT,CURR
     5.5 ms  TRAC:FEED:CONT NEXT
    98.4 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.7 ms  INIT
    75.4 ms  TRAC:POIN:ACT?  [?]
             -> 60
     1.2 ms  TRAC:POIN:ACT?  [?]
             -> 60
    13.2 ms  TRAC:DATA?  [?]
             -> -6.200000e-05,-1.340000e-10,+9.910000e+37,+2.501910e-02,+1.860000e-10,+9.910000e+37,+4.999930e-02,-3.240000e-10,+9.91000
     5.9 ms  SOUR:VOLT:MODE FIX
     6.0 ms  TRIG:COUN 1
     6.0 ms  ARM:COUN 1
    19.8 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.5 ms  OUTP 0
    15.7 ms  *IDN?  [?]
             -> GWInstek,GSM-20H10,GEW852313,V1.16
     0.2 ms  OUTP 0
     0.1 ms  *CLS
     0.1 ms  *RST
     0.1 ms  SYST:CLE
     0.2 ms  SYST:BEEP:STAT 1
     0.2 ms  OUTP:ENAB 0
     0.1 ms  SYST:LFR:AUTO 1
     0.1 ms  SOUR:CLE:AUTO 0
     0.1 ms  ROUT:TERM FRON
     0.2 ms  TRAC:FEED:CONT NEV
     0.2 ms  FORM:ELEM VOLT,CURR
     0.1 ms  SENS:FUNC:CONC ON
     0.1 ms  SENS:FUNC:ON "VOLT","CURR"
     0.1 ms  SOUR:FUNC VOLT
     0.1 ms  SOUR:CLE:AUTO 0
     0.1 ms  SOUR:VOLT:RANG:AUTO OFF
     0.1 ms  SOUR:VOLT:RANG 1.000000e-01
     0.1 ms  SENS:CURR:DC:RANG:AUTO OFF
     0.1 ms  SENS:CURR:DC:RANG 1.000000e-04
     0.1 ms  SENS:VOLT:DC:RANG:AUTO ON
     0.1 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     0.1 ms  SENS:CURR:DC:RANG 1.000000e-04
     0.2 ms  SOUR:VOLT 0.000000e+00
   376.0 ms  *IDN?  [?]
             -> GWInstek,GSM-20H10,GEW852313,V1.16
     0.4 ms  *CLS
     0.3 ms  *RST
     0.3 ms  SYST:CLE
     0.2 ms  SYST:BEEP:STAT 1
     0.2 ms  OUTP:ENAB 0
     0.2 ms  SYST:LFR:AUTO 1
     0.2 ms  SOUR:CLE:AUTO 0
     0.2 ms  ROUT:TERM FRON
     0.3 ms  TRAC:FEED:CONT NEV
     0.2 ms  FORM:ELEM VOLT,CURR
     0.2 ms  SENS:FUNC:CONC ON
     0.3 ms  SENS:FUNC:ON "VOLT","CURR"
     0.2 ms  SOUR:FUNC VOLT
     0.1 ms  SOUR:CLE:AUTO 0
     0.1 ms  SOUR:VOLT:RANG:AUTO OFF
     0.1 ms  SOUR:VOLT:RANG 1.000000e-01
     0.1 ms  SENS:CURR:DC:RANG:AUTO OFF
     0.1 ms  SENS:CURR:DC:RANG 1.000000e-04
     0.1 ms  SENS:VOLT:DC:RANG:AUTO ON
     0.1 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     0.1 ms  SENS:CURR:DC:RANG 1.000000e-04
     0.1 ms  SOUR:VOLT 0.000000e+00
   287.5 ms  *IDN?  [?]
             -> GWInstek,GSM-20H10,GEW852313,V1.16
     0.3 ms  *CLS
     0.2 ms  *RST
     0.2 ms  SYST:CLE
     0.2 ms  SYST:BEEP:STAT 1
     0.2 ms  OUTP:ENAB 0
     0.2 ms  SYST:LFR:AUTO 1
     0.2 ms  SOUR:CLE:AUTO 0
     0.2 ms  ROUT:TERM FRON
     0.3 ms  TRAC:FEED:CONT NEV
     0.2 ms  FORM:ELEM VOLT,CURR
     0.2 ms  SENS:FUNC:CONC ON
     0.2 ms  SENS:FUNC:ON "VOLT","CURR"
     0.2 ms  SOUR:FUNC VOLT
     0.4 ms  SOUR:CLE:AUTO 0
     0.3 ms  SOUR:VOLT:RANG:AUTO OFF
     0.2 ms  SOUR:VOLT:RANG 1.000000e-01
     0.1 ms  SENS:CURR:DC:RANG:AUTO OFF
     0.1 ms  SENS:CURR:DC:RANG 1.000000e-04
     0.1 ms  SENS:VOLT:DC:RANG:AUTO ON
     0.3 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     0.2 ms  SENS:CURR:DC:RANG 1.000000e-04
     0.1 ms  SOUR:VOLT 0.000000e+00
   272.0 ms  *IDN?  [?]
             -> GWInstek,GSM-20H10,GEW852313,V1.16
     0.3 ms  *CLS
     0.3 ms  *RST
     0.2 ms  SYST:CLE
     0.2 ms  SYST:BEEP:STAT 1
     0.1 ms  OUTP:ENAB 0
     0.1 ms  SYST:LFR:AUTO 1
     0.2 ms  SOUR:CLE:AUTO 0
     0.2 ms  ROUT:TERM FRON
     0.1 ms  TRAC:FEED:CONT NEV
     0.1 ms  FORM:ELEM VOLT,CURR
     0.1 ms  SENS:FUNC:CONC ON
     0.1 ms  SENS:FUNC:ON "VOLT","CURR"
     0.1 ms  SOUR:FUNC VOLT
     0.1 ms  SOUR:CLE:AUTO 0
     0.1 ms  SOUR:VOLT:RANG:AUTO OFF
     0.1 ms  SOUR:VOLT:RANG 1.000000e-01
     0.1 ms  SENS:CURR:DC:RANG:AUTO OFF
     0.1 ms  SENS:CURR:DC:RANG 1.000000e-04
     0.1 ms  SENS:VOLT:DC:RANG:AUTO ON
     0.1 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     0.1 ms  SENS:CURR:DC:RANG 1.000000e-04
     0.1 ms  SOUR:VOLT 0.000000e+00
  4024.1 ms  *IDN?  [?]
             -> !! TransportDesynchronised: A command was sent while exchanging '*IDN?' and its reply never arrived (VisaIOError: VI_ERROR_TMO (-1073807339): Timeout expired before operation completed.). No later reply can be trusted to belong to the question that asked for it, so this transport refuses to read. Reconnect the instrument.
     0.1 ms  OUTP 0
```
