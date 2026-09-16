# Instrument checkup - GW Instek GSM-20H10

- **Result:** FAIL
- **When:** 2026-09-16 14:11:50
- **Address:** USB0::8580::125::gew852313::0::INSTR
- **Driver:** `GWInstekGSM20H10`
- **Write pacing:** 5 ms after each write, as the driver declares
- **Code:** `3c2164e48fcb` **plus uncommitted changes**
- **Firmware:** V1.16
- **`bench_code`:** `4893dc090952`
- **Uncommitted when this ran:**
    - `?? 20h10_delay5.txt`
    - `?? 20h10_named.txt`
- **Checks:** 70 passed, 5 warned, 1 failed, 6 skipped

> This checkup assumes **nothing is connected to the output**. The measurement checks expect open-circuit behaviour, so a connected sample will produce warnings that are not faults.

## Failures

- **read_sweep() returns the right shape** - 10 sourced, 10 measured, expected 5 of each

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
| link: the query after an unpaced configuration burst | skip | skipped on request (--skip-burst), so whether this instrument drops commands sent in a burst was not tested |

## Tier 3 - live measurement

| Check | Result | Detail |
|---|---|---|
| voltage probe level is expressible on the active range | warn | probing at 0.1 V, and this model declares no floor: what a source level below one count of the active range does here is UNMEASURED. On the one instrument where it has been measured the output was offset residue whose sign was not the one commanded. Nothing here says this level is in that regime - it says nobody can tell |
| output_on() | pass |  |
| error queue after output_on() | pass |  |
| measure() at 0 V | pass | (2.65e-05, 3.1e-09) |
| measure() at 0.1 V | pass | (0.1000866, -5.8e-09) |
| open-circuit current is near zero | pass | -5.8e-09 A at 0.1001 V |
| error queue after measure() | pass |  |
| configure for current sourcing: set_source_function('current') | pass |  |
| configure for current sourcing: apply_ranges()  [current mode] | pass | source I=1e-06 V=not sourced, measure I=auto V=1 |
| configure for current sourcing: set_voltage_limit(1) | pass |  |
| current probe level is expressible on the active range | pass | 1e-06 A is at or above the 3.05176e-10 A this instrument can express on the range the plan landed on |
| configure for current sourcing: set_current_level(1e-06) | pass |  |
| output_on()  [after the mode change] | pass |  |
| output gap across a source-function change | pass | 80 ms de-energised |
| measure() sourcing 1e-06 A into open circuit | pass | (0.999979, 1.432e-09) |
| compliance reached on open circuit | pass | 1 V against a 1.0 V limit, settled (sign not checked - a railed output saturates whichever way the loop happens to go) |
| compliance_tripped() while clamping | pass | reported True while riding the voltage limit |
| time per reading at NPLC 0.01 | pass | 17.4 ms (3.5 s for a 200-point sweep), steady state - the first reading is reported separately below |
| first reading after the output comes up | pass | 282.9 ms, 16x the steady state |
| start_linear_sweep()  [hardware] | pass |  |
| sweep completes | pass | 5 points in 0.10 s |
| read_sweep() returns the right shape | fail | 10 sourced, 10 measured, expected 5 of each |
| error queue after the sweep | pass |  |
| driver note after the sweep | pass | the buffer returns 3 values per reading, not 2 - `FORM:ELEM VOLT,CURR` is accepted and ignored on this model, and `FORM:ELEM?` reports the requested list rather than the one it sends. Stride counted from 30 values over 10 readings |
| output_off()  [cleanup] | pass |  |

## Command trace

```
    12.3 ms  *IDN?  [?]
             -> GWInstek,GSM-20H10,GEW852313,V1.16
     1.4 ms  *IDN?  [?]
             -> GWInstek,GSM-20H10,GEW852313,V1.16
    10.1 ms  *IDN?  [?]
             -> GWInstek,GSM-20H10,GEW852313,V1.16
    10.9 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.6 ms  SOUR:SWE:SPAC LIN
     5.5 ms  SOUR:SWE:POIN 2
    19.6 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.8 ms  *CLS
     5.5 ms  *RST
     5.5 ms  SYST:CLE
     5.6 ms  SYST:BEEP:STAT 1
     5.5 ms  OUTP:ENAB 0
     5.6 ms  SYST:LFR:AUTO 1
     5.5 ms  SOUR:CLE:AUTO 0
     5.5 ms  ROUT:TERM FRON
     5.6 ms  TRAC:FEED:CONT NEV
     5.7 ms  FORM:ELEM VOLT,CURR
   107.9 ms  SYST:ERR?  [?]
             -> 0,"No error"
    10.1 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.5 ms  SOUR:SWE:SPAC LIN
     5.5 ms  SOUR:SWE:POIN 2
    19.6 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.2 ms  OUTP 0
    15.8 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.6 ms  SYST:RSEN 0
    15.4 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.6 ms  SENS:FUNC:CONC ON
     5.6 ms  SENS:FUNC:ON "VOLT","CURR"
     5.7 ms  SOUR:FUNC VOLT
     5.5 ms  SOUR:CLE:AUTO 0
    28.4 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SENS:FUNC:CONC ON
     5.5 ms  SENS:FUNC:ON "VOLT","CURR"
     5.8 ms  SOUR:FUNC CURR
     5.4 ms  SOUR:CLE:AUTO 0
    29.0 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SENS:FUNC:CONC ON
     5.6 ms  SENS:FUNC:ON "VOLT","CURR"
     5.5 ms  SOUR:FUNC VOLT
     5.5 ms  SOUR:CLE:AUTO 0
    29.5 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.7 ms  SOUR:VOLT:RANG:AUTO OFF
     5.5 ms  SOUR:VOLT:RANG 1.000000e-01
     5.5 ms  SENS:CURR:DC:RANG:AUTO OFF
     5.6 ms  SENS:CURR:DC:RANG 1.000000e-04
     6.4 ms  SENS:VOLT:DC:RANG:AUTO ON
   122.7 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     5.7 ms  SENS:CURR:DC:RANG 1.000000e-04
    19.4 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.4 ms  SOUR:VOLT 0.000000e+00
    15.4 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.7 ms  SENS:FUNC:CONC ON
     5.3 ms  SENS:FUNC:ON "VOLT","CURR"
     5.5 ms  SOUR:FUNC CURR
     5.6 ms  SOUR:CLE:AUTO 0
    29.1 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.4 ms  SOUR:CURR:RANG:AUTO OFF
     5.5 ms  SOUR:CURR:RANG 1.000000e-06
     5.6 ms  SENS:CURR:DC:RANG:AUTO ON
     5.5 ms  SENS:VOLT:DC:RANG:AUTO OFF
     5.5 ms  SENS:VOLT:DC:RANG 1.000000e+00
   124.7 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.6 ms  SENS:VOLT:DC:PROT:LEV 1.000000e+00
     5.9 ms  SENS:VOLT:DC:RANG 1.000000e+00
    19.2 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.5 ms  SOUR:CURR 0.000000e+00
    16.4 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.3 ms  SENS:FUNC:CONC ON
     5.7 ms  SENS:FUNC:ON "VOLT","CURR"
     5.5 ms  SOUR:FUNC VOLT
     5.6 ms  SOUR:CLE:AUTO 0
    27.7 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.7 ms  SOUR:DEL:AUTO 0
     5.5 ms  SOUR:DEL 0.01000
    19.7 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.2 ms  SOUR:CURR:RANG:AUTO ON
     5.2 ms  SOUR:VOLT:RANG:AUTO ON
     5.4 ms  SENS:CURR:DC:RANG:AUTO ON
     5.6 ms  SENS:VOLT:DC:RANG:AUTO ON
    29.8 ms  SYST:ERR?  [?]
             -> 0,"No error"
    10.3 ms  SENS:CURR:DC:PROT:LEV?  [?]
             -> +1.000000e-09
     5.2 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     5.5 ms  SOUR:VOLT:RANG:AUTO OFF
     5.5 ms  SOUR:VOLT:RANG 1.000000e-01
     5.9 ms  SENS:CURR:DC:RANG:AUTO OFF
     5.6 ms  SENS:CURR:DC:RANG 1.000000e-04
     5.5 ms  SENS:VOLT:DC:RANG:AUTO ON
   138.8 ms  SENS:CURR:DC:PROT:LEV?  [?]
             -> +1.000000e-04
     6.1 ms  SOUR:VOLT:RANG:AUTO OFF
     6.4 ms  SOUR:VOLT:RANG 1.000000e-01
     5.9 ms  SENS:CURR:DC:RANG:AUTO OFF
     5.7 ms  SENS:CURR:DC:RANG 1.000000e-04
     5.7 ms  SENS:VOLT:DC:RANG:AUTO ON
     5.8 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     5.4 ms  SENS:CURR:DC:RANG 1.000000e-04
    32.4 ms  SYST:ERR?  [?]
             -> 0,"No error"
     9.2 ms  SENS:CURR:DC:RANG?  [?]
             -> 1.050000E-04
     5.7 ms  SENS:FUNC:CONC ON
     5.4 ms  SENS:FUNC:ON "VOLT","CURR"
     5.6 ms  SOUR:FUNC VOLT
     5.5 ms  SOUR:CLE:AUTO 0
     6.0 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
    33.0 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.7 ms  SOUR:VOLT:RANG:AUTO OFF
     5.5 ms  SOUR:VOLT:RANG 1.000000e-01
     5.7 ms  SENS:CURR:DC:RANG:AUTO OFF
     6.0 ms  SENS:CURR:DC:RANG 1.000000e-03
     5.5 ms  SENS:VOLT:DC:RANG:AUTO ON
     5.7 ms  SENS:CURR:DC:PROT:LEV 1.000000e-03
     5.5 ms  SENS:CURR:DC:RANG 1.000000e-03
   134.0 ms  SENS:CURR:DC:RANG?  [?]
             -> 1.050000E-03
     5.7 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     5.5 ms  SENS:CURR:DC:RANG 1.000000e-03
   109.5 ms  SYST:ERR?  [?]
             -> +824,Cannot exceed compliance range
     8.8 ms  SYST:ERR?  [?]
             -> +824,Cannot exceed compliance range
    10.5 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.7 ms  SENS:FUNC:CONC ON
     5.9 ms  SENS:FUNC:ON "VOLT","CURR"
     5.5 ms  SOUR:FUNC CURR
     5.7 ms  SOUR:CLE:AUTO 0
     5.9 ms  SENS:VOLT:DC:PROT:LEV 1.000000e+00
    32.8 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.6 ms  SOUR:CURR:RANG:AUTO OFF
     5.5 ms  SOUR:CURR:RANG 1.000000e-06
     5.6 ms  SENS:CURR:DC:RANG:AUTO ON
     5.8 ms  SENS:VOLT:DC:RANG:AUTO OFF
     5.7 ms  SENS:VOLT:DC:RANG 2.000000e+01
     5.6 ms  SENS:VOLT:DC:PROT:LEV 2.000000e+01
     5.8 ms  SENS:VOLT:DC:RANG 2.000000e+01
   132.8 ms  SENS:VOLT:DC:RANG?  [?]
             -> 21
     5.4 ms  SENS:VOLT:DC:PROT:LEV 1.000000e+00
     5.9 ms  SENS:VOLT:DC:RANG 2.000000e+01
    19.6 ms  SYST:ERR?  [?]
             -> +826,Attempt to exceed power limit
    10.0 ms  SYST:ERR?  [?]
             -> +826,Attempt to exceed power limit
    10.3 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.8 ms  SENS:FUNC:CONC ON
     5.8 ms  SENS:FUNC:ON "VOLT","CURR"
     5.4 ms  SOUR:FUNC VOLT
     5.6 ms  SOUR:CLE:AUTO 0
     5.6 ms  SOUR:VOLT:RANG:AUTO OFF
     5.7 ms  SOUR:VOLT:RANG 1.000000e-01
     5.9 ms  SENS:CURR:DC:RANG:AUTO OFF
     6.1 ms  SENS:CURR:DC:RANG 1.000000e-04
     6.3 ms  SENS:VOLT:DC:RANG:AUTO ON
     5.6 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     5.5 ms  SENS:CURR:DC:RANG 1.000000e-04
   150.3 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.9 ms  SENS:FUNC:CONC ON
     6.0 ms  SENS:FUNC:ON "VOLT","CURR"
     5.6 ms  SOUR:FUNC CURR
     5.5 ms  SOUR:CLE:AUTO 0
    27.8 ms  SYST:ERR?  [?]
             -> 0,"No error"
     9.8 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.9 ms  SENS:FUNC:CONC ON
     5.6 ms  SENS:FUNC:ON "VOLT","CURR"
     5.4 ms  SOUR:FUNC VOLT
     5.7 ms  SOUR:CLE:AUTO 0
    29.1 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.6 ms  SENS:CURR:DC:NPLC 0.0100
     5.5 ms  SENS:VOLT:DC:NPLC 0.0100
    19.3 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.7 ms  SENS:CURR:DC:NPLC 10.0000
     6.0 ms  SENS:VOLT:DC:NPLC 10.0000
    18.3 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.2 ms  SENS:CURR:DC:NPLC 0.0100
     5.8 ms  SENS:VOLT:DC:NPLC 0.0100
     5.8 ms  SOUR:VOLT:PROT 20
    24.3 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.4 ms  OUTP:SMOD HIMP
    14.4 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.5 ms  OUTP:SMOD NORM
    14.5 ms  SOUR:FUNC?  [?]
             -> VOLT
    10.3 ms  SENS:CURR:DC:PROT:TRIP?  [?]
             -> 0
     6.0 ms  SENS:FUNC:CONC ON
     6.0 ms  SENS:FUNC:ON "VOLT","CURR"
     6.1 ms  SOUR:FUNC VOLT
     5.4 ms  SOUR:CLE:AUTO 0
     5.5 ms  SOUR:VOLT:RANG:AUTO OFF
     5.6 ms  SOUR:VOLT:RANG 1.000000e-01
     5.4 ms  SENS:CURR:DC:RANG:AUTO OFF
     5.9 ms  SENS:CURR:DC:RANG 1.000000e-04
     5.6 ms  SENS:VOLT:DC:RANG:AUTO ON
     5.8 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     5.6 ms  SENS:CURR:DC:RANG 1.000000e-04
     5.8 ms  SOUR:VOLT 0.000000e+00
     5.5 ms  OUTP 1
    68.7 ms  SYST:ERR?  [?]
             -> 0,"No error"
    23.6 ms  READ?  [?]
             -> +2.650000e-05,+3.100000e-09
     5.2 ms  SOUR:VOLT 1.000000e-01
    14.4 ms  READ?  [?]
             -> +1.000866e-01,-5.800000e-09
     1.9 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.4 ms  SOUR:VOLT 0.000000e+00
     5.6 ms  OUTP 0
     5.9 ms  SENS:FUNC:CONC ON
     5.8 ms  SENS:FUNC:ON "VOLT","CURR"
     5.8 ms  SOUR:FUNC CURR
     5.5 ms  SOUR:CLE:AUTO 0
     5.5 ms  SOUR:CURR:RANG:AUTO OFF
     5.5 ms  SOUR:CURR:RANG 1.000000e-06
     5.5 ms  SENS:CURR:DC:RANG:AUTO ON
     5.5 ms  SENS:VOLT:DC:RANG:AUTO OFF
     5.6 ms  SENS:VOLT:DC:RANG 1.000000e+00
     5.7 ms  SENS:VOLT:DC:PROT:LEV 1.000000e+00
     5.7 ms  SENS:VOLT:DC:RANG 1.000000e+00
     5.5 ms  SOUR:CURR 1.000000e-06
     5.7 ms  OUTP 1
   183.0 ms  READ?  [?]
             -> +9.999600e-01,-3.460000e-10
    14.6 ms  READ?  [?]
             -> +9.999790e-01,+1.432000e-09
     1.7 ms  SOUR:FUNC?  [?]
             -> CURR
    10.4 ms  SENS:VOLT:DC:PROT:TRIP?  [?]
             -> 1
     6.0 ms  SOUR:CURR 0.000000e+00
     6.1 ms  OUTP 0
     5.4 ms  SENS:FUNC:CONC ON
     5.5 ms  SENS:FUNC:ON "VOLT","CURR"
     5.5 ms  SOUR:FUNC VOLT
     5.5 ms  SOUR:CLE:AUTO 0
     6.0 ms  SENS:CURR:DC:PROT:LEV 1.000000e-04
     6.0 ms  OUTP 1
   282.9 ms  READ?  [?]
             -> +1.131000e-04,+6.470000e-10
    14.2 ms  READ?  [?]
             -> -4.040000e-05,+2.140000e-10
    13.9 ms  READ?  [?]
             -> +4.300000e-05,-1.515000e-09
    14.4 ms  READ?  [?]
             -> -1.450000e-05,-6.200000e-11
    30.6 ms  READ?  [?]
             -> +2.620000e-05,+1.214000e-09
    13.8 ms  READ?  [?]
             -> +9.210000e-05,-1.408000e-09
     1.8 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.4 ms  TRAC:FEED:CONT NEV
     5.5 ms  TRAC:FEED SENS1
    20.0 ms  SYST:ERR:ALL?  [?]
             -> -140
,Character data error
    10.2 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.4 ms  TRAC:FEED:CONT NEV
     6.0 ms  TRAC:FEED SENSe1
    19.3 ms  SYST:ERR:ALL?  [?]
             -> -140
,Character data error
    10.1 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.2 ms  TRAC:FEED:CONT NEV
     5.3 ms  TRAC:FEED SENS
    21.0 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
    10.2 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.6 ms  SOUR:VOLT:STAR 0.000000e+00
     5.4 ms  SOUR:VOLT:STOP 1.000000e-01
     5.5 ms  SOUR:SWE:SPAC LIN
     5.6 ms  SOUR:SWE:POIN 5
     5.5 ms  SOUR:SWE:DIR UP
     6.0 ms  SOUR:SWE:RANG BEST
     5.5 ms  SOUR:VOLT:MODE SWE
     6.2 ms  SOUR:DEL 0.01000
     5.7 ms  ARM:COUN 1
     5.6 ms  TRIG:COUN 5
     5.5 ms  TRAC:FEED:CONT NEV
     5.8 ms  TRAC:CLE
     5.5 ms  TRAC:POIN 5
     5.9 ms  TRAC:FEED SENS
     5.6 ms  FORM:ELEM VOLT,CURR
     5.6 ms  TRAC:FEED:CONT NEXT
    95.5 ms  SYST:ERR:ALL?  [?]
             -> 0,"No error"
     5.9 ms  INIT
    76.6 ms  TRAC:POIN:ACT?  [?]
             -> 10
     1.3 ms  TRAC:POIN:ACT?  [?]
             -> 10
    10.8 ms  TRAC:DATA?  [?]
             -> +1.243000e-04,-2.960000e-10,+9.910000e+37,+2.502370e-02,-4.000000e-12,+9.910000e+37,+5.001480e-02,+4.740000e-10,+9.91000
     5.4 ms  SOUR:VOLT:MODE FIX
     5.4 ms  TRIG:COUN 1
     5.6 ms  ARM:COUN 1
    23.9 ms  SYST:ERR?  [?]
             -> 0,"No error"
     5.6 ms  OUTP 0
```
