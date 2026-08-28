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
last_bench: 2026-08-28
bench_notes: "2026-08-28 checkup at 04eec0c: 68 pass, 0 fail, clean tree, no timeouts, median query latency 19.9 ms. The two -140 Character data errors in the trace are BUFFER_FEED_TOKENS probing for the token this firmware accepts, not a fault. Six runs the previous day died at the first SYST:ERR? with a 4 s timeout and four passed this morning with no code change - intermittent, unexplained, and predating Wave 8a; see Bench findings"
bench_code: "19b26cfdaa0d"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "14 ms at NPLC 0.01, +255 ms first read after output-on and a further +319 ms after a source-function change"
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

Per quantity means the driver has to pick which one to ask, and the
manual states the rule in both `TRIPped?` entries: `:CURRent:
PROTection:TRIPped?` reports the compliance state of the **V-Source**,
`:VOLTage:PROTection:TRIPped?` reports the **I-Source**. The limit is
always on the quantity you are not setting. So `compliance_tripped()`
reads `SOUR:FUNC?` and asks the complementary axis — see **Decisions and
deviations** for why it no longer asks both.

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

**The trip query follows the sourced function, and does not OR both
axes.** Until 2026-08-21 `compliance_tripped()` queried
`SENS:CURR:DC:PROT:TRIP?` and `SENS:VOLT:DC:PROT:TRIP?` and returned
True if either was set, on the argument that it cost one extra query and
removed a way to get the answer wrong.

Against the meaning the manual gives these queries it added one. On a
voltage source, the voltage trip describes the **I-Source**, which is
not running. A value left on that flag from an earlier run would be
reported as a clamp that is not happening — and the checkup's clamping
check would then pass on a stale flag while the mechanism the
experiments depend on was broken. A check that passes for free is worse
than no check.

Whether these flags latch on this model is **unmeasured**: the manual's
`TRIPped?` entries have no *Affected by* column. Selecting the axis
makes it moot for this answer, since the inactive flag is never read,
but it is still worth a probe — source current into an open circuit
until it rides the voltage limit and read both, then switch to sourcing
voltage with nothing clamping and read both again. The interesting
answer is the second one; the first passes whether or not the flags are
per-axis.

`MEMory` is a third value of `SOUR:FUNC` on this model — a saved
sequence of setups, recalled in turn — and in it neither trip query
describes what the instrument is doing. The driver returns None there,
which the report renders as "cannot say" rather than as a False nobody
measured.

This is the same rule the B2901A uses under its own spellings. They are
deliberately two implementations rather than one shared helper: the
B2901A's is confirmed against hardware and this one is not, and folding
them together now would mean a red test afterwards could not say which
instrument caused it. The driver contract ledger is what catches drift
between them.

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

### 2026-08-27/28 — `TRAC:FEED` grammar, and a readback nobody was using

`:TRACe:FEED` on V1.16 **rejects the token the manual gives as its own
example, and the token the instrument itself reports.** Measured across
five spellings — full table in
[buffer feed and error queue](../reference/manuals/gsm-20h10-buffer-and-errors.md):

- `SENS` — accepted
- `SENSe1`, `SENS1`, `SENSE1`, `RAW` — all `-140 Character data error`
- `CALCulate1` — accepted, in full long form with its suffix

So it is not a long-versus-short mnemonic rule. `TRAC:FEED?` returns
`SENSe1`; writing `SENSe1` back is refused.

`BUFFER_FEED_TOKENS` in the driver probes `SENS1`, `SENSe1`, `SENS` in
order and caches the first accepted, so the driver already lands on
`SENS`. **The two `-140`s that appear in every GSM checkup trace are
that probe working, not a fault.** Recorded because they read exactly
like a defect, and did: a whole bench session was spent on them.

`:TRACe:FEED?` exists, is undocumented in the manual section, and
answers in ~10 ms. Nothing uses it. It is the only way to know what the
buffer is actually storing, and a buffer left on `CALCulate1` returns
math results where raw readings are expected — plausible numbers with
nothing in them to say so.

### 2026-08-27 — six checkups died at the first query, four passed the next day

Six consecutive runs failed identically: every write of `reset()`
accepted, then `SYST:ERR?` timed out after 4.01 s and the transport
latched. Four runs the following morning passed 68/68 with no timeout,
same backend, same commit.

**Not explained.** What was excluded, each by probe rather than by
argument:

- the command is implemented — the manual documents it and it answers
  interactively
- it is not empty-queue silence — it returns `0,"No error"` on an empty
  queue in 8 ms
- `*RST` is not still executing — `SYST:ERR?` answers 1.7 ms after it
- no single command in the reset block is guilty — all ten answer
  individually
- it is not the rate — the entire session replayed back to back over the
  console answers in 9.9 ms

The pre-patch pair of 2026-08-25 is the useful comparison. The failing
run of that day has a **median query latency of 1.4 ms across 1423
queries** on `libusb-win32`, which is the desynchronised stream in its
pure form — replies arriving twenty times faster than the link's own
latency because they were already buffered. Fifty-six of that run's
"passes" were taken one reply out of step. The clean run 37 seconds
later, on USB-TMC, has a median of 20.1 ms and no timeout at all.

So on `libusb-win32` the fault is established and Wave 8a's latch is
clearly right. On USB-TMC there is no evidence of a pre-existing
swallowed timeout, and the 2026-08-27 failures remain open.


- **2026-08-25:** the checkup at `d332432` returned **64 pass, 0 fail**.
  That is the whole fleet green on this branch, and the first clean run
  this instrument has had since the driver changed under P4.

  **`SOUR:FUNC?` is verified against hardware.** It has been carried as
  unverified since P4 introduced it — the trip-axis rule asks the
  instrument which quantity it is sourcing and then queries the
  *complementary* protection bit, and until now nobody had watched it
  answer. It answered `VOLT` while sourcing voltage and `CURR` after the
  source function changed, tracking correctly across the switch, and the
  complementary trip query followed it. The rule works.

  **The C1 failure of 2026-08-21 is gone.** The checkup no longer asks
  `compliance_tripped()` while the output is ramping, so the question
  that produced a correct `0` and a red line is no longer asked that
  way.

  Timing on the clean run: readings settle around 14 ms, with a 255 ms
  first read after `OUTP 1` and a further 319 ms first read after the
  source function changed — the first-read penalty is per *transition*,
  not once per session.

- **2026-08-24 and 2026-08-25, the transport:** three runs in this round
  hit an intermittent USB read timeout, and one of them wasted a
  diagnosis before it was understood. Recorded in full because the
  symptom is the most dangerous shape this project has: **plausible
  numbers from the wrong question.**

  The instrument is the only one in the fleet on USB-TMC —
  `USB0::8580::125::gew852313::0::INSTR` through pyvisa-py on
  libusb-win32 — while the rest reach their machines over Prologix. It
  is also the only one that failed.

  What happens: a bulk-in read times out, `libusb0-dll:err
  [_usb_reap_async] timeout error`, and **the reply stream is left one
  behind**. Every query after that point returns the *previous*
  command's answer. The instrument says so itself, with `-230, "Data
  corrupt or stale"`, and the timing gives it away unmistakably:

  | Run | Query median before the timeout | After |
  |---|---|---|
  | 2026-08-24 | 12.7 ms | 1.28 ms across 1381 queries |
  | 2026-08-25 (first) | 28.9 ms | 1.42 ms across 1386 queries |

  A reply that arrives in a tenth of the usual time was already sitting
  in the buffer. The clean run of 2026-08-25 has a 20.1 ms median
  throughout and five scattered fast replies — no collapse — which is
  how we know it is a real result and not a desynchronised one that
  happened to look ordinary.

  It is not a command interaction. Three timeouts landed on three
  different commands: `SYST:ERR?` and `SYST:ERR:ALL?` after
  `FORM:ELEM VOLT,CURR`, and `READ?` after `OUTP 1`. An earlier note in
  this round claimed a pattern there; it was reading shifted data, and
  the pattern did not survive a third observation.

  **Everything downstream of a timeout is void.** The 2026-08-24 run was
  read as a driver regression — `measure()` returning nothing, the
  instrument reporting the output off after an `OUTP 1` that queued no
  error — and none of that was real. It was `803` and `-230` from
  earlier in the run, arriving late through a shifted stream. The
  driver's fingerprint is `df15115813d3` in all three runs, so nothing
  about the code changed between the red ones and the green one.

  The checkup **does** detect the desync and says so, warning that
  failures below that point may be consequences rather than separate
  faults. What it does not do is stop: it ran 1386 more queries against
  a stream it had already declared unrecoverable. That gap is the
  subject of its own wave.

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
- **Why does this link time out at all?** Intermittent, roughly one run
  in two or three, and only on this instrument — the one on USB-TMC
  through libusb-win32 rather than Prologix. Whether a vendor VISA with
  a proper USBTMC driver removes it is untested. Until it is understood,
  a GSM checkup should be run twice and only a pair of clean runs
  believed.
- **Can a desynchronised session be resynchronised at all?** Answered by
  Wave 8a: the honest answer is to end the session and reconnect, and
  that is now what happens. `viClear` on this backend was never
  recovering the stream — the 2026-08-25 report says in as many words
  that it could not be resynchronised. No recovery is attempted, because
  a recovery that works sometimes is one nobody can trust, and the
  transport latches until it is reconnected. <!-- lint-ok -->
