---
type: instrument
title: "Undalogic miniSMU MS01"
driver_class: UndalogicMiniSMU
idn: "Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: 2026-09-04
bench_notes: "2026-09-04 checkup at 7f09e21: 61 pass, 2 warn, 0 fail, 14 skip. the only model here with no source current ranges, so the sub-count question does not arise on that axis - the 2026-09-01 envelope agrees, having followed the commanded sign down to 95 pA without reaching a floor. The two warnings are both the unmeasured voltage floor. It reports neither a compliance limit nor a compliance flag, the only model on this bench blind to both. Sourcing 1 uA into an open circuit it settled at -1.020 V against a 1.0 V limit, a 2.0% overshoot where every other instrument here held to 0.05%; the morning run of this day read -1.022 V, so it reproduces"
bench_code: "5b52e6925fa0"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "6.3 ms at the OSR floor, no first-read cost - and the NPLC beside it is an equivalent window, not a measured integration time, so this cell is not comparable with the others"
resolution: "about -1.5 mV voltage offset, confirmed three ways"
best_for: "small, portable, quick; not for single-point small voltages"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/undalogic_minismu.py
model_ids: "['MINISMU MS01', 'MINISMU', 'MS01']"
max_voltage_v: 12
max_current_a: 0.18
voltage_ranges_n: 4
current_ranges_n: 5
power_envelope_n: 2
sweep_kind: hardware
nplc_min: 0.0005
nplc_max: 16.384
high_z_off: false
ovp: false
remote_sense_control: true
compliance_trip: false
# --- end generated ---
---

# Undalogic miniSMU MS01

The fastest and smallest instrument here, and **the only one not driven
over a text protocol.** There was no original script: the driver was
written from the vendor's `minismu_py` library, its published docs and
the MS01 spec sheet.

## Identity and envelope

12 V, 180 mA, 2.1 W per channel, five current ranges, two channels.
Firmware 1.4.6; onboard sweeps need 1.3.4+ and 4-wire needs 1.4.3+, both
checked at connect.

Note the identity string carries **two version-shaped tokens** —
`v1.1` is the hardware revision and `v1.4.6` the firmware. The last one
wins, and a test pins that so a hardware rev cannot masquerade as
firmware.

## Reset defaults that had to be overridden

**Deviation 28 — `reset()` deliberately does not reset.**
`minismu_py`'s `reset()` sends `*RST`, which **reboots the MS01** and
invalidates the open connection; over USB the port re-enumerates.
`LabApp` calls `driver.reset()` on every connect, so wiring the obvious
thing through would have made every miniSMU connection die the moment it
succeeded, with a symptom indistinguishable from a bad cable.

The driver's `reset()` instead drops the output, restores autoranging
and the AUTO voltage range, and clears any leftover 4-wire mode.
`reboot()` exists separately and is called by nothing. The fake raises
if `client.reset()` is ever called, so a future edit that "fixes" this
fails loudly.

## Decisions and deviations

**Deviation 27 — driven through a library, not a wire protocol.** The
MS01's documented interface is `minismu_py`, which opens the port
itself, so `MiniSMUTransport` wraps the library object rather than
moving text. Its `_write`/`_read` raise; only `*IDN?` is mapped, to keep
driver auto-detection on the same path as every other instrument.

A native SCPI-style driver is possible — the spellings are visible in
the library source — but they are not published as a command reference,
and the library carries chunked-USB handling, fragmented TCP JSON
reassembly, a firmware-dependent command terminator and truncation
detection that would all have to be rebuilt.

`minismu-py` is a mandatory dependency and is still imported **lazily**
inside `connect()`: installed is not the same as importable, and a
broken wheel should fail at connect time naming the instrument rather
than stopping the app and taking the other instruments down with it.

**Deviation 29 — capabilities depend on firmware, not model.** The
version is parsed from `*IDN?` at connect and both features degrade
rather than fail. **An unparseable identity counts as too old** — it is
not evidence of a recent build, and a fallback that works beats a
feature that dies mid-run.

**Deviation 30 — sweep kind varies per run.** The onboard sweep is
voltage-only, so a voltage sweep runs on the instrument and a current
sweep falls back to software on the same connection. This is the first
instrument where two datasets from the same box can honestly disagree
about `sweep_kind`.

**Deviation 31 — NPLC is a translation of the oversampling ratio.**
There is no NPLC setting; the knob is `MEAS<n>:OSR`, 0–15, roughly
2^OSR samples. A requested NPLC is treated as an integration window and
mapped to the nearest OSR in log space, and `clamp_nplc()` returns the
window actually achievable — so a requested 1 NPLC is recorded as 0.8.

**Deviation 32 — voltage range is always AUTO.** The instrument takes
AUTO, LOW or HIGH and **no published document defines LOW or HIGH in
volts.** Guessing would risk a clipped sweep that still looks clean, so
the driver sends AUTO in every case and gives up some resolution.

Checked against Undalogic's published material on 2026-08-15, and the
answer is that there is nothing to find:

- The **technical specifications** page gives a single voltage range,
  ±12.0 V, and says nothing about a LOW/HIGH split.
- The **library README's API reference** does not list
  `set_voltage_range` at all, although current-range control is
  documented in detail.
- The **method exists** in the installed library and its docstring is
  the whole of the documentation: `range_type: 'AUTO', 'LOW', or
  'HIGH'`, sending `SOUR<n>:VOLT:RANGE <type>`. No thresholds, no
  accuracy implication, no default stated.

So this is not a gap in our reading. It is undocumented upstream, and
the only routes to an answer are asking Undalogic or measuring the
resolution step at each setting against a known source. Until then AUTO
is the honest choice, and the driver says so at the call site.

**Deviation 33 — 4-wire mode costs channel 2.** `SYST:4WIR ENA` is
system-wide, not per-channel: CH2 becomes the sense channel, CH2
commands are blocked, and OUTP1 then switches both channels together.
Ticking the sensing box is not free here.

**Deviation 34 — the 12 V DC adapter is a requirement, not an option.**
USB-powered operation is limited to 50 mA per channel against 180 mA on
the adapter, and the instrument reports no way to tell which supply it
is on. Rather than add a setting that could be set wrong, the driver
declares the full 180 mA envelope and states the requirement in the
console on every connect.

**Deviation 42 — the driver rejects a transport it cannot drive.** The
MS01 answers `*IDN?` over plain serial, so `SerialTransport` connects
and auto-detection correctly identifies a miniSMU — and then every
method call fails, reporting that a connected, working transport is "not
connected". Checked at construction now, with a message naming the fix.
On the command line: `--transport minismu`.

**Deviation 49 — the OSR-to-NPLC mapping has no sound basis, and
`SAMPLE_RATE_HZ` was wrong three times.** See below. This is the entry
that produced `tools/timing_scan.py` and the rule that a two-point fit
proves nothing.

**The current range list matches the library exactly, and was
checked.** `LIMITS.current_ranges` is
`[1e-6, 25e-6, 650e-6, 15e-3, 180e-3]`, which is identical to
`minismu_py.CURRENT_RANGE_LIMITS`. Verified programmatically rather than
by eye, because a range list that does not match the instrument is
fault 16 — the 2635B's `LIMITS` problem — and it produces a sourced
level that was clamped rather than an error.

Worth not confusing with a similar-looking table: the specifications
page publishes **accuracy bands** (0–500 nA, 500 nA–20 µA, 20 µA–0.5 mA,
0.5 mA–13 mA, 13 mA–180 mA) which are *not* the switchable ranges and do
not line up with them. Two tables of the same shape describing different
things is exactly how a wrong range list gets written.

**`LIMITS.voltage_ranges` is a convenience ladder, not a range list.**
It holds `[0.1, 1.0, 5.0, 12.0]`, and this instrument has no
correspondingly-named voltage ranges — only AUTO, LOW and HIGH. Those
values populate the sourced-level and compliance dropdowns in Van der
Pauw, Hall and IV sweep, and every one of them is reachable within
±12 V, so nothing sources a level it did not ask for. But the field is
named for a capability this instrument does not expose, which is the
same one-list-two-meanings conflation the 2635B's D15 records. Recorded
rather than changed: renaming the field is a shared-layer change across
every driver.

**The sentinel exemption.** This is one of two drivers exempt from <!-- lint-ok -->
`test_sentinel_handling.py`, because it is driven through a library
rather than a text protocol and hands back Python floats — there is no
reply to parse. The test guards the exemption list itself, so the
exemption cannot silently widen.

## Bench findings

### 2026-09-04 — fleet round: what this instrument measured

Descriptive measurements from the round of 2026-09-04, run at commit
`727022f`. **Not a commissioning record**, and deliberately not copied
into `last_bench` / `bench_code` / `bench_result`: the readback fix that
followed changed `drivers/base_smu.py`, which every driver's
fingerprint covers, so this round no longer describes the code that is
running. A fresh round is owed once the driver work lands.

| Measured | Value |
|---|---|
| Steady-state reading at the declared NPLC floor | 6.3 ms |
| First reading after the output comes up | none — 6.5 ms, 1× the steady state |
| Output gap across a source-function change | 71 ms de-energised |
| Open-circuit current at 0.1 V | 151 nA, at 0.09984 V |
| Settled voltage against a 1.0 V compliance | **−1.022 V** |

**On this instrument the reading-time axis is not even the same
quantity.** There is no NPLC setting: the knob is `MEAS<n>:OSR`, an
oversampling ratio, and the driver maps a requested NPLC onto the OSR
whose window is closest. That mapping is not synchronised to the mains,
so the number beside a reading here is an *equivalent* window and, in
the driver's own words, its absolute value is not a measured
integration time. Comparing 6.3 ms here against a Keithley's figure at
a true NPLC compares two different things. Every instrument in the
round ran at its own declared minimum, and those minima span 0.0004 to
1 on the instruments where the unit means anything at all.

#### The compliance overshoot: −1.022 V against a 1.0 V limit

Sourcing into an open circuit with a 1.0 V voltage compliance, this
instrument settled at **−1.022 V — a 2.2% overshoot**. Every other
instrument in the round held within 0.05% of its limit: the GSM-20H10,
the 2401, the 2635B and the B2901A all settled at 1.000 V, the 2611A at
1.001 V, the U2722A at 0.9992 V.

The check **passed**, and correctly: it tolerates sign here, because a
railed output saturates whichever way the servo loop happens to go, and
its ceiling is 1.25× the limit, set clear of exactly this overshoot.
So nothing is wrong and nothing is owed.

The number is recorded anyway, because a compliance is what protects a
sample. A limit set at the value a device tolerates will be exceeded by
about 2% on this instrument, and 2% of a limit chosen for a fragile
sample is a real margin. Set the limit here with that headroom in mind
rather than at the boundary.

#### The 180 mA declaration, and the supply it assumes

The MS01 delivers its full **180 mA per channel only on the 12 V DC
adapter**. On USB-C power alone it is limited to **50 mA**, and **it
cannot report which supply it is on** — there is no command to ask.

**The decision is to keep the 180 mA declaration and document the
caveat.** The alternative — declaring 50 mA — would be wrong on a
correctly powered instrument every time, and would silently truncate
the envelope for every user who has plugged in the adapter as the
vendor intends. Declaring what the hardware can do, and saying loudly
what makes it untrue, puts the one fact the software cannot determine
in front of the person who *can* determine it by looking at the bench.

What it costs is a failure mode worth recognising on sight: on bus
power, a sweep asking for more than 50 mA folds back silently, and the
resulting curve looks like a sample going into compliance at a current
nobody set. The driver prints the assumption to the console on every
connect so that possibility is on screen before the first sweep rather
than diagnosed from the data afterwards.

Nothing here is a defect and nothing is pending. This is a limit of
what the instrument can be asked, recorded so it is not rediscovered.

#### It reports neither the limit value nor a compliance flag

`compliance_tripped()` is not implemented, and the compliance limit
cannot be read back, so both compliance checks skip. This instrument
and the 2401 are the two that are blind in both senses — unlike the
2611A, 2635B and B2901A, which report the flag. The checkup's skip
message now says which case it is looking at rather than giving all
five the same sentence; see
[fault 45](../faults/45-one-message-for-two-different-gaps.md).

### 2026-09-01 — noise/rate envelope and sub-count floor

100 uA into 9958 ohm, 2 V compliance.

| OSR (as NPLC) | per reading | rate | RSD |
|---|---|---|---|
| 0.0005 | 6.0 ms | 166 Hz | 0.053% |
| 0.004 | 7.2 ms | 140 Hz | 0.010% |
| 0.032 | 10.9 ms | 92 Hz | 0.004% |
| 0.256 | 34.1 ms | 29 Hz | 0.005% |
| 2.05 | 73.0 ms | 14 Hz | 0.005% |
| 16.4 | 165 ms | 6.1 Hz | 0.004% |

**Its noise floor is reached early and stays there.** RSD stops
improving beyond about 0.03 OSR - unlike every other instrument here,
more integration buys nothing after that point. It is also the only one
that never reports a quantised rung, so the readings keep moving where
others have run out of codes.

**No sub-count floor was found.** The sign still followed at 95 pA,
where the probe stops because it has walked down a million-fold from the
bias. That is the tool running out of ladder, not the instrument running
out of resolution - the real floor is somewhere below.

- **2026-08-21:** the checkup at `7dc6264` passed every check, 3 skips,
  no failures.

- **The shared-knob reconciliation resolves to `AUTO` here too, and it
  is harmless.** Sourcing 1 µA, `apply_ranges()` reports `measure
  I=auto` taking the knob from the fixed source range. Recorded
  2026-08-21 as the same D7 defect that produced four `-222` failures
  on the U2722A, harmless here because the autorange is real. <!-- lint-ok -->

- **2026-08-27: the reason above was wrong, and so was the comparison.**
  The current range on this instrument is a **measurement** range. It is
  not shared with a source current range, because there is no source
  current range. Read out of the commands the vendor library sends:

  ```
  set_voltage_range  -> SOUR1:VOLT:RANGE AUTO      source-side
  set_current_range  -> CH1:IRANGE 3               channel-level
  set_autorange      -> CH1:AUTORANGE:ENA          channel-level
  ```

  The voltage range is a `SOUR:` command and the current range is not,
  and `set_autorange`'s docstring says it switches range *"for the
  measured current"*.

  So `AUTO` costs nothing here not because a real autorange rescues a
  small source level, but because **the source level is never judged
  against this range at all**. This instrument and the U2722A were
  never in the same situation. On the U2722A one knob genuinely serves
  both, which is why a source level could land below a count of it.

  The 2026-08-21 note also called the U2722A's `-222` failures a live
  defect. They were fixed on 2026-08-25 by deviation 52, which takes the
  range from the compliance limit and forces it.

- **Three ranging methods this driver depends on are absent from the
  vendor's public API reference.** `set_autorange`,
  `set_current_range_by_limit` and `get_current_range_limit` are all in
  the shipped library and none appear in the documented API table, which
  lists only `set_voltage_range`. Worth knowing before a version bump:
  undocumented surface carries no compatibility promise.

  `set_current_range_by_limit` also takes `disable_autorange=True` by
  default — it turns autoranging off as a side effect of setting a
  range. The driver now passes it explicitly so a change to that default
  cannot alter behaviour silently.

- **`get_current_range_limit(index)` is a lookup table, not a readback.**
  It takes a range *index* and returns that range's full scale from a
  module constant, with no device I/O. A probe on 2026-08-27 passed it a
  channel number and read a plausible, constant 25 µA — the answer to
  "what is range 1?" — which looked exactly like a range that would not
  move. There is no way to ask this instrument which current range is
  active.

- **A healthy clamp sits slightly beyond the limit.** −1.023 V against a
  1 V limit, with the compliance working. Worth knowing because it sets
  the tolerance any "is the compliance in force" check has to allow: the
  U2722A's failing case was 2.0 V against the same limit.

- **No command trace is recorded for this instrument.** `--trace`
  returns the `*IDN?` and nothing else, because `MiniSMUTransport` does
  not feed the recorder. Every other driver can be audited from a bench
  report against the exact strings it sent; this one cannot. Recorded as
  C9.

**The OSR question, settled as far as it can be.** Three values of
`SAMPLE_RATE_HZ` were tried and all three were wrong, because **the
underlying model is wrong.** A six-point timing scan:

| OSR | samples | reading | implied rate |
|---|---|---|---|
| 0 | 1 | 6.2 ms | — |
| 6 | 64 | 12.4 ms | 10 kS/s |
| 9 | 512 | 34.4 ms | 18 kS/s |
| 12 | 4096 | 75.0 ms | 60 kS/s |
| 15 | 32768 | 162.6 ms | 210 kS/s |

Eight times the samples costs about 2.2× the time, and the implied rate
climbs twentyfold. If a reading cost `overhead + samples ÷ rate`, every
row would give the same rate. **No single rate can describe this**, so
the NPLC equivalence orders the settings correctly and its absolute
value means nothing.

The spec sheet's 1000 S/s is the *streaming* rate — how fast finished
readings leave the instrument — and is unrelated to how long one
oversampled reading takes. That mismatch was merely the first wrong
answer, not the explanation.

Both earlier "confirmations" came from **two-point fits**, which have
zero degrees of freedom and pass through both points by construction.
They cannot fail and cannot be checked. That is why
`tools/timing_scan.py` refuses fewer than three points and prints the
residuals.

Two free observations already in the data: **OSR 0 and OSR 3 take the
same 6.2 ms**, so running at OSR 0 is strictly wasteful — up to 2.8×
less noise for no time at all. And below about OSR 6 the reading time is
set by the link, not the measurement.

**What would settle it**, if anyone cares enough: a noise scan —
standard deviation of a few hundred readings into a known resistor at
each OSR. If σ falls as 2^(−OSR/2) the sample-count claim is right.
Better still, look for a **dip** rather than a monotonic fall: averaging
over exactly one mains period nulls 50 Hz hum, so a local minimum pins
the integration window to 20 ms at that OSR and fixes the whole scale
with no timing at all. Or ask Undalogic what `MEAS:OSR` does.

**Do not re-derive this from timings.** It has been done three times.

## What this means for your data <!-- bench -->

**Use the 12 V DC adapter.** On USB-C power alone it is limited to 50 mA
per channel instead of 180 mA, and it cannot report which supply it is
on. A sweep asking for more than 50 mA on bus power quietly folds back
and looks like a sample going into a compliance nobody set.

**It has a roughly −1.5 mV voltage offset**, confirmed three ways. It
cancels in anything taken from a *slope* — both 10 kΩ sweeps recovered
the resistor to better than 0.1% — but **not in a single-point voltage
reading.** That matters for four-point-probe and Hall voltages, which
are often smaller than the offset itself.

**Its `nplc` column is not a real integration time.** Higher still means
quieter and the ordering is correct, but the absolute number is
unfounded and must not be compared against a true-NPLC instrument. Any
miniSMU data whose metadata matters needs that column caveated or
removed.

Related: true NPLC integrates over whole mains periods, which is what
nulls 50 Hz hum. This instrument's oversampling is not
mains-synchronised, so an "equivalent 1 NPLC" here rejects hum less well
than 1 NPLC on a Keithley. The number in the file is a truthful
integration time, not a promise of the same noise floor.

**Its compliance overshoots by about 2%.** Measured 2026-09-04: a 1.0 V
limit settled at −1.022 V into an open circuit, where every other
instrument in that round held within 0.05% of its own limit. The clamp
is working — the checkup's ceiling is set clear of exactly this — but a
limit set at the value your sample tolerates will be exceeded by
roughly that margin. Leave headroom rather than setting the limit at
the boundary.

**On USB-C power it stops at 50 mA, and it will not tell you.** The
declared envelope is 180 mA per channel and needs the 12 V adapter;
there is no command that reports which supply is connected, so the
software assumes the adapter and says so on every connect. On bus power
a sweep asking for more folds back silently, and the curve looks like a
sample going into compliance at a current nobody set. If a run flattens
at about 50 mA, check the barrel jack before the sample.

**4-wire costs you channel 2.** It is a system-wide setting, not a
per-channel one.

**Pick the "miniSMU" transport, not "Serial".** Serial will appear to
work — the instrument answers `*IDN?` over it and auto-detection
succeeds — and then every method call fails with a message saying a
connected, working transport is not connected.

## Upstream: the library is a dependency with its own faults

`minismu-py` is pinned at `>=0.4.0`, and the 0.4.0 changelog is worth
knowing because two of its fixes are the same failure class this project
exists to catch:

- **Sweep data truncated by the firmware's ~5.7 kB TCP response limit**
  (firmware v1.5.0 and earlier) now raises a descriptive error instead
  of returning incomplete data. Before that, a long onboard sweep over
  WiFi came back short and looked like a shorter sweep. That is the
  GSM's deviation 50 arriving from a completely different direction.
- **Device-reported errors now raise** rather than being silently
  ignored.

This bench connects over USB, where the TCP limit does not apply, so
nothing here is known to have been affected. It matters if anyone moves
to the WiFi transport — and it is the reason the pin is a floor rather
than a compatibility note.

Also fixed in 0.4.0: CSV sweep retrieval returning only the first data
point, `run_iv_sweep()` polling exiting early or looping forever, and
streaming desynchronising the connection. The suite does not stream.

## Open questions

- **What are the LOW and HIGH voltage ranges, in volts?** Still open,
  and now known to be undocumented rather than merely unfound — see
  deviation 32. An email to Undalogic is the cheap route; a resolution
  scan against a known source at each setting is the route that does not
  need them. Fixing the range would buy resolution on small sweeps.
- The exact commissioning date was not recorded, so this driver reads as
  stale regardless — see [checkup-owed](../open/checkup-owed.md).
