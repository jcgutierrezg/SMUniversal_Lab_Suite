---
type: instrument
title: "GW Instek GSM-20H10"
driver_class: GWInstekGSM20H10
idn: "GWInstek,GSM-20H10,GEW852313,V1.16"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: 2026-08-21
bench_notes: "2026-08-21 checkup at 7dc6264: 62 pass, 1 fail. "compliance survives ranging" passes on hardware - the first confirmation of NOT_SOURCED against an instrument. The one failure is the checkup tool asking whether the output was clamping while it was still ramping (C1), not a driver fault"
bench_code: "3b4034e6e01d"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "75 ms at NPLC 0.01 (checkup, 2026-08-20)"
resolution: "not characterised"
best_for: "long unattended sweeps; per-quantity compliance reporting"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/gwinstek_gsm20h10.py
model_ids: "['GSM-20H10', 'GSM20H10', '20H10']"
max_voltage_v: 210
max_current_a: 1.05
voltage_ranges_n: 4
current_ranges_n: 7
power_envelope_n: 2
sweep_kind: hardware
nplc_min: 0.01
nplc_max: 10
high_z_off: true
ovp: true
remote_sense_control: true
compliance_trip: true
# --- end generated ---
---

# GW Instek GSM-20H10

Speaks a Keithley-like SCPI dialect and differs from it in several
places. **Those differences caused four of the nine faults found across
all commissioning**, which is why it is now the best-instrumented driver
in the suite.

Ported from `IV_Meas_20H10.py` and a `_-_RandomBackup.py` predecessor.

## Identity and envelope

210 V, 1.05 A, seven current ranges. Hardware staircase sweep up to
**2500 points**, which is the buffer limit and is enforced.

It is the one instrument here that reports compliance **per quantity**,
which makes it the best choice when you are unsure whether a measurement
is riding its limit. The B2901A and the 2635B report it too, but the
2635B's flag covers voltage, current and power together without saying
which — so this one still answers the question most directly.

## Reset defaults that had to be overridden

| Command | Why |
|---|---|
| `OUTP:ENAB 0` | disables the rear-panel output-enable interlock |
| `SYST:LFR:AUTO 1` | NPLC cancels mains hum only if the instrument knows the mains period |
| `SOUR:CLE:AUTO 0` | so a sweep holds its level between points |
| `ROUT:TERM FRON` | front terminals, as the rig is wired |
| `TRAC:FEED:CONT NEV` | buffer storage must be disarmed before `TRAC:FEED` can be changed |
| `FORM:ELEM VOLT,CURR` | sent, and then not trusted — see deviation 50 |

**`OUTP:ENAB 0` is the one that would have stopped everything.**
`reset()` is where it lives, and until Wave 0 nothing in the app called
`reset()` at all — every driver had one, two were tested, and no code
path invoked them. With nothing wired to the rear-panel interlock pin,
the instrument refuses to turn its output on. The first GSM run would
have failed with no obvious cause.

## Decisions and deviations

**Deviation 11 — `READ?` instead of `MEAS?` per point.** `MEAS?` is
`:CONF` followed by `:READ?`, so it reconfigures the instrument on every
point and undoes the ranging and compliance set beforehand. The original
selected a current compliance from its dropdown once, before the loop,
then called `MEAS?` at each point — so the compliance it asked for was
being reset before the first reading was taken. Identical to the fault
in the 2401 original, and found the same way.

**Deviation 12 — source levels are no longer rounded to 4 decimals.** On
the 200 mV range that quantises to 100 µV, a hundred times coarser than
the instrument's 1 µV programming resolution.

**Deviation 13 — the instrument's own staircase sweep is used.** The GSM
has a sequence engine and the original ignored it, setting each level
over the bus. All the staircase spellings have since been checked
against the manual's Command List; the connect-time probe was kept
regardless, because a command existing in a manual and being accepted by
the instrument in front of you are different claims.

**Deviation 14 — concurrent measurement is switched on explicitly.**
With `[:SENSe]:FUNCtion:CONCurrent` off, only one function is measured
and the other field of the reply is filled from the **source setting**.
Sourcing 1 V, the voltage column reads back exactly 1.000000 V — the
requested value, not the value across the sample — so lead and contact
drops disappear and a 4-wire rig silently returns a 2-wire measurement.
The original never set it.

**Deviation 15 — `:ABORt` does not exist on this model**, despite being
present on the 2400. Sweeps are stopped with `:TRIGger:CLEar`. Note that
`:SOURce:SWEep:CABort` is *not* the abort action despite the name; it
configures what a sweep does on hitting compliance.

**Deviation 17 — NAN and over-range sentinels are dropped rather than
recorded.** The GSM reports "no reading" as a number: `+9.91e37` for NAN
and `+9.9e37` for over-range. Nothing raises — they parse as ordinary
floats and enter the data as points thirty-seven orders of magnitude
out, which drags a least-squares fit entirely to themselves while still
returning a respectable R². Dropped in matched pairs so the two columns
stay aligned, and the count is reported rather than swallowed. This
driver handled it from the start, which turned out to be the whole of
the protection across the suite until it was promoted to `BaseSMU`.

**Deviation 18 — output-off mode is a per-run choice.** The driver
briefly pinned `OUTP:SMOD HIMP` at reset. HIMPedance opens the output
relay to disconnect the sample, which is right for some measurements —
but the manual explicitly warns against it "for tests that turn the
output on and off frequently", and IV sweep's periodic mode can cycle
the output hundreds of times in an unattended run. The relay has a
finite number of operations in it, so the setting that costs hardware is
now one you opt into. Recorded per run in the `output_off_mode` column.

**Deviation 44 — the staircase fallback left the source in sweep mode.**
Found on the bench, 2026-08-05. The instrument refused the staircase
setup with `-140`, the driver correctly fell back to the software sweep,
and left `SOUR:VOLT:MODE SWE` in force. The software sweep steps by
sending `SOUR:VOLT <level>`, which in SWE mode is read as a sweep
*endpoint* rather than a level to hold — so the source never moved. Five
points returned, no error, **every point at 0 V**. The fallback meant to
rescue the run was the thing that broke it. `MODE FIX`, `TRIG:COUN 1`
and `ARM:COUN 1` are now restored before falling through.

**Deviation 45 — a rejected staircase command names itself.** `-140:
Character data error` identifies a *kind* of mistake, not which of
fifteen setup commands made it. On failure only, the setup is replayed
one command at a time to find the offender, which then appears in the
sweep note.

**Deviation 46 — buffer storage must be disarmed before `TRAC:FEED` is
changed.** The command list states plainly that it cannot be changed
while storage is active. The setup armed storage with `CONT NEXT` at the
end of every sweep and never turned it off, so from the second sweep
onward the feed command was refused — and took the whole staircase setup
down with it, dropping every sweep to the software path.

**Deviation 50 — the buffer's element count is read back, not assumed.**
Told `FORM:ELEM VOLT,CURR`, the GSM accepted it, queued no error, and
returned **three** numbers per reading: voltage, current, resistance. A
fixed stride of two turned 5 readings (15 numbers) into 7 pairs; 4 held
the resistance NAN and were dropped; the 3 that survived were readings
1, 3 and 5 — genuine V/I pairs, fitting a straight line perfectly well.
**A silently decimated sweep that looked entirely correct.** Only the
point-count check caught it.

Reading the configuration back does not help either: `FORM:ELEM?`
answers `VOLT,CURR` — the list it was *given* — while the buffer keeps
sending three columns. The instrument's account of itself is wrong in
both directions, and neither the request nor the read-back can be
trusted. What cannot lie is arithmetic: `read_sweep()` asks how many
readings the buffer holds, counts the numbers that come back, and takes
the ratio as the stride.

**Deviation 51 — `TRAC:FEED SENS1` really is rejected**, even with
storage disarmed. The probe fell through to the un-numbered `SENS`,
which the instrument accepted, so this implementation does not honour
the SCPI abbreviation for the numbered node and the manual's `SENSe1` is
not usable as written. Both readings of the `-140` turned out to matter:
the ordering fix was needed *and* so was the token fallback.

## Bench findings

- **2026-08-21:** the checkup at `7dc6264` returned 62 pass, 1 fail.
  `compliance survives ranging` **passes on hardware** — 100 µA held
  across the ranging sequence on the instrument where source autorange
  used to reset it. That is the first confirmation of `NOT_SOURCED`
  against real hardware rather than a fake transport, and
  `apply_ranges()` now reports `source I=not sourced V=0.1` where it
  used to report `AUTO`.

  The single failure is not this driver. The checkup asked
  `compliance_tripped()` while the output was still ramping — five
  readings climbing 0.23 V apiece, stopped at 0.9151 V against a 1 V
  limit because the settle loop exits at 80% of the limit rather than
  when the reading stops moving. `0` was the correct answer. Recorded as
  C1 in `docs/open/technical-debt.md`.

  So `compliance_tripped()` on this driver is still **unproven in both
  directions**: it has not yet been asked at a moment when `True` was
  the right answer.

- **This is the slowest output in the fleet to reach compliance.**
  1.294 s to 0.92 V at 1 µA into an open circuit, against 87 ms on the
  2401 and 66 ms on the 2611A. Roughly 1 µF of output capacitance.

> **Everything below was measured on firmware `V1.16`.** GW Instek
> publish `V1.30` (2026-08-12) on the GSM-20H10 download page, with no
> release notes and no published defect list, so whether any of this is
> fixed there is unknown. Upgrading invalidates these findings; re-run
> the checkup and diff against the last `V1.16` report before trusting
> any of them again. Checkup reports record the firmware from `*IDN?`
> as of 2026-08-20.

- **2026-08-05:** four faults, none reachable from the offline suite —
  deviations 44, 45, 46 and 50 above.
- **2026-08-20:** **a source-autorange command silently resets the
  compliance.** One command, no error, and the limit protecting the
  sample drops by five orders of magnitude:

  | source function | command | compliance before | after |
  |---|---|---|---|
  | voltage | `SOUR:CURR:RANG:AUTO ON` | `+1.050000e-04` | `+1.000000e-09` |
  | current | `SOUR:VOLT:RANG:AUTO ON` | `+2.100000e+01` | `+2.000000e-04` |

  Repeatable: setting the compliance back to 100 µA and issuing the
  command again collapses it again, so this is not a reset artefact.
  Written up as [A ranging command that silently resets the compliance](../faults/23-autorange-resets-compliance.md), because
  the shape is not specific to this instrument even if the numbers are.

  **`+824` and `+826` are consequences of this, not causes.** With the
  compliance sitting at 1 nA, narrowing a measurement range to 100 µA
  genuinely does exceed it, so `+824 Cannot exceed compliance range`
  lands on a command that has nothing wrong with it. In current mode
  the same collapse produces `+826 Attempt to exceed power limit` on
  1 µA into 1 V — a microwatt — which is why that code never made
  sense.

  Runs are currently protected only because [Limit sent before the range that has to hold it](../faults/15-limit-before-range.md) puts the
  experiment's own compliance *after* the ranging block, restoring it.
  That is accidental, not designed: nothing today issues a
  source-autorange command after `apply_ranges`, which is a property of
  the present call order rather than a guarantee.

- **2026-08-20:** **a measurement range can be refused and silently
  narrowed.** Asking for `SENS:CURR:DC:RANG 1.000000e-04` with the
  compliance at 10 µA gives `+824` and leaves `SENS:CURR:DC:RANG?`
  reading `1.050000E-05` — a range the operator did not choose, with
  no exception. `apply_ranges` reports what it *sent*, not what the
  instrument accepted, so nothing in the suite would notice.

- **2026-08-20:** **`OUTP?` and `OUTP:STAT?` do not report the truth.**
  With the output physically on and 10 V sourced from the front panel,
  both returned `0` while `READ?` returned `+9.999960e+00`. Nothing in
  `drivers/`, `core/` or `tools/smu_checkup.py` queries them — the
  checkup infers output state from whether the *write* succeeded — so
  this has never affected a measurement, and it is a reason not to add
  an output-state query to `BaseSMU` without checking each instrument
  first.

- **2026-08-20:** setting the measurement range of the quantity being
  sourced is refused with `+823 Invalid with source read-back on`.
  That is the axis `RangePlan.for_sourcing()` deliberately makes
  unrepresentable, and the instrument enforcing it by name is
  confirmation that the ranging contract was designed correctly.

- **2026-08-20:** the checkup went from **six failures to three** once
  `tools/smu_checkup.py` was fixed to apply ranges before limits. Tier
  3 is green: `measure()` returns `(0.1000629, -8.5e-09)` at 0.1 V,
  `compliance_tripped()` reports True while riding the voltage limit,
  the hardware sweep completes, and a reading costs **75.2 ms at NPLC
  0.01**. The three remaining failures are all the compliance collapse
  above.

- **2026-08-14:** `:ABOR` is **rejected** with `-113 Undefined header`,
  confirming deviation 15 from the instrument rather than from the
  absence of a manual entry. `:TRIG:CLE` is the documented and correct
  route.

## What this means for your data <!-- bench -->

**Old 20H10 data was taken at whatever compliance and ranging `:CONF`
defaults to, not at the value selected in the dropdown.** The original
script reset it on every point. A run that never approached compliance
is unaffected; one that did was not limited where it was supposed to be.
Worth asking whoever owns that data whether anything was taken near
compliance.

**Any 20H10 4-wire data may in fact be 2-wire**, depending on what state
the instrument was left in. Concurrent measurement was never enabled by
the original, and with it off the voltage column is filled from the
source setting rather than measured. Compare against a known resistor if
it matters.

**Its buffer returns three numbers per reading**, not two — voltage,
current, resistance — regardless of being told otherwise, and it reports
two when asked. If you ever query the buffer by hand, expect three.

**High-impedance output-off is no longer the default.** Runs before this
change used high-impedance off; runs after use normal off unless the box
is ticked. It affects what happens to the sample *between* readings, not
the readings themselves, so no measured value changes — but if a rig
depended on the sample being isolated between sweeps, that no longer
happens by default. The column `output_off_mode` records which you got.

**This is the instrument to reach for when you need to know whether you
hit compliance**, and for long unattended sweeps: 2500 points on the
instrument's own timebase.

## Open questions

- **Which OVP setting does this rig actually want?** The original pinned
  `SOUR:VOLT:PROT MIN`, which the manual defines as **20 V** — not "the
  lowest possible" — with `DEF` (210 V) commented out beside it. 20 V is
  preserved as the default, but it reads like a bench decision made for
  a reason nobody wrote down.
- **Was any data taken near compliance** under the original script? See
  above; this is a question for whoever owns the files, not for the
  code.
- The driver has changed since 14 August and has not been re-checked —
  see [checkup-owed](../open/checkup-owed.md).
