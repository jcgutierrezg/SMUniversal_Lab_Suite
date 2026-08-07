# PORTING NOTES — archaeology of the original scripts

**You do not need this file to work on the project.** HANDOFF.md is the
working document; this is the record of where the code came from and why it
differs from what it replaced.

Keep it for three reasons:

1. **Old saved data.** Several deviations changed what lands in a CSV. If
   someone compares a new file against one from 2023 and the numbers disagree,
   the explanation is here.
2. **"Why is it done this way?"** Some choices look arbitrary until you know
   what the original did. The reasoning is recorded so it doesn't get
   re-litigated or accidentally reverted.
3. **Porting the next script.** "Faults to check for in any new original" at
   the end is a checklist of the mistakes that have turned up in every script
   so far. Read it before writing the next driver — none of them announce
   themselves, and two change what past data means.

The original scripts are **not** in the repository and are not expected to be
uploaded again. Everything below is written to stand on its own without them.

**Deviations 1–43 come from reading the original scripts and the command
references. Deviations 44 onward come from running the drivers against
real instruments** in August 2026, and each of those describes a fault
that existed in the shipped code and has since been fixed. If you are
looking for what an instrument *does* rather than why a driver changed,
that is `INSTRUMENTS.md`.

---

## Where each experiment came from

| Experiment | Original script(s) |
|---|---|
| `vanderpauw` | `VdP_v*.ipynb` |
| `hall` | `Hall_v4.ipynb` |
| `iv_sweep` | `IV_Meas_2611A_-_Basic.py`, `-_Development.py`, `-_Long_bias.py` (merged) |
| `ossila_4pp` | `Ossila_4PP_2611A.py` (+ a later `_Triangular_sine` variant) |
| `Keithley2401` driver | `IV_Meas_2611A_2401_-_Long_bias_Dual_SMU.py` |
| `GWInstekGSM20H10` driver | `IV_Meas_20H10.py` (+ a `_-_RandomBackup.py` predecessor) |
| `KeysightU2722A` driver | `IV_Meas_2722A.py` (+ `_OG.py` and `_OG_2.py`, same program with GUI additions) |
| `UndalogicMiniSMU` driver | No original script. Written from the vendor's `minismu_py` library, its published docs, and the MS01 spec sheet. |

The originals were single-file, globals-heavy Tkinter scripts that duplicated
logic per instrument. The worst case (the dual-SMU one, 1911 lines) had entire
function families suffixed `_2611` / `_2401` differing only in command dialect
— which is the whole reason the driver layer exists.

---

## Deviations from the originals, numbered

These are marked `# DEVIATION n` in the source. The numbering is global.

### Van der Pauw and Hall

1. **Delay units corrected.** The original notebook mixed seconds and
   milliseconds in the settle delay.
2. **Voltage precision raised from 6 to 9 significant figures.** The Hall
   signal rides on top of a much larger resistive offset, so six figures
   quantised the quantity actually being measured.

### IV sweep

3. **Sweep completion is polled, not timed.** The originals slept
   `round(points × delay × 1.30)` seconds. `round()` puts the wait on a
   whole-second grid — a 10-point 0.1 s sweep waited 1 s, not 1.3 s — and
   `waitcomplete()` was sent with `write()` and never read back, so it never
   blocked the host. That sleep was the *only* thing between firing the sweep
   and reading the buffer, so short sweeps could read a partly-filled buffer
   and silently return fewer points than requested. Now polls until the
   requested count arrives.
4. **The x-axis is read back, not reconstructed.** The originals rebuilt it
   with `np.arange(start, stop, step)`, assuming the SMU hit every requested
   level exactly. The instrument is now asked what it actually sourced, with
   the old reconstruction as a logged fallback.
5. **Single-point "sweeps" are refused.** The `Vo == Vf` branch is dropped;
   one version of it crashed on a float/string concatenation the moment
   anyone reached it.
6. **Sensing is explicit and defaults to 4-wire.** The original set
   `SENSE_REMOTE` inside the periodic path and nowhere else, so a *single*
   sweep inherited whatever the instrument was last left in — 4-wire after a
   periodic run, 2-wire after a reset. Same sample, different reading, nothing
   on screen to say so.
7. **The linear fit is a toggle.** One original had it commented out because
   not every sample is ohmic — a diode returns a straight-line resistance that
   is meaningless but looks like a result once it is in the CSV. Now
   per-sample rather than commented-out-permanently.

### Ossila 4-point probe

8. **Thickness correction no longer raises at the top of its table.** The
   original's `else` branch printed a message and left the factor unassigned,
   so the next line raised `NameError` for any sample with t/s > 2. The top of
   the table is held instead, with a warning next to the result.
9. **Out-of-table geometry is flagged, not silent.** The original substituted
   1.0 without comment. 1.0 means "effectively infinite sample", which for a
   sample too *small* for the table is backwards and over-reports sheet
   resistance. Same substitution, but now it says so.
10. **Resistivity is in Ω·m, not Ω·mm.** The original computed `Rs × t` with t
    in millimetres and labelled the result `mΩ/m` — neither what it computed
    nor a unit of resistivity. Its conductivity was right, because the `×1000`
    converted the same figure to S/m.

    ⚠️ **Old saved files differ by 1000× on the resistivity column.** Sheet
    resistance and conductivity are unchanged.

### GSM-20H10 driver

11. **`READ?` instead of `MEAS?` per point.** Identical to the fault found in
    the 2401 original, and found the same way. `MEAS?` is `:CONF` followed by
    `:READ?`, so it reconfigures the instrument on every point and undoes the
    ranging and compliance set beforehand. `IV_Meas_20H10.py` selected a
    current compliance from its dropdown once, before the loop, then called
    `MEAS?` at each point — so the compliance it was asked for was being reset
    before the first reading was taken.

    ⚠️ **Old 20H10 data was taken at whatever compliance and ranging `:CONF`
    defaults to, not at the value selected in that dropdown.** How much this
    matters depends on the sample: a run that never approached compliance is
    unaffected, one that did is not. `FORM:ELEM VOLT,CURR` is now set at reset
    so the two-field reply the original *assumed* is the reply it actually
    gets. Regression guard in `tests/test_gsm20h10.py`.
12. **Source levels are no longer rounded to 4 decimals.** Same change, same
    reason, as the 2401 — the original sent `round(Vo + i*step, 4)`. On the
    200 mV range that quantises to 100 µV, which is 100× coarser than the
    instrument's 1 µV programming resolution.
13. **The instrument's own staircase sweep is used where the original stepped
    the source from Python.** The GSM has a sequence engine (linear/log
    staircase, up to 2500 points); the original ignored it and set each level
    over the bus. Runs now record `sweep_kind` so the two are distinguishable
    in the file rather than only on screen.

    The staircase spellings were originally inferred from the 2400-family
    command set and have since been checked against the manual's Command List —
    `:SOURce:SWEep:SPACing`, `:POINts`, `:RANGing`, `:DIRection`,
    `:SOURce:VOLTage:STARt`/`:STOP` and the `:TRACe:*` buffer commands all
    exist as used. The connect-time probe was kept regardless.
14. **Concurrent measurement is switched on explicitly.** With
    `[:SENSe]:FUNCtion:CONCurrent` off, only one function is measured and the
    other field of the reply is filled from the *source setting*. Sourcing 1 V,
    the voltage column reads back exactly 1.000000 V — the requested value, not
    the value across the sample — so lead and contact drops disappear and a
    4-wire rig silently returns a 2-wire measurement. The original never set
    it, leaving it to whatever the front panel was last in.

    ⚠️ **Any 20H10 4-wire data may in fact be 2-wire**, depending on the
    instrument's state at the time. Compare a known resistor if it matters.
15. **`:ABORt` does not exist on this model** — it is absent from the command
    list, despite being present on the 2400. Sweeps are stopped with
    `:TRIGger:CLEar`. Note `:SOURce:SWEep:CABort` is not the abort action
    despite the name; it configures what a sweep does on hitting compliance.
16. **Line frequency is auto-detected** (`:SYSTem:LFRequency:AUTO`). NPLC only
    cancels mains hum if the instrument knows the mains period, so setting an
    integration time without this is worth less than it looks.
17. **NAN and over-range sentinels are dropped instead of recorded.** The GSM
    reports "no reading" as a *number*: `+9.91e37` for NAN and `+9.9e37` for
    over-range. Nothing raises — they parse as ordinary floats and enter the
    data as points 37 orders of magnitude out, which drags a least-squares fit
    entirely to themselves while still returning a respectable R². The original
    had no guard against this. Dropped in matched pairs so the two columns stay
    aligned, and the count is reported rather than silently swallowed.

    The condition arises whenever a requested element wasn't actually sourced
    or measured — which is exactly what happens with concurrent measurement
    off, so deviations 14 and 17 are two halves of the same hazard.

18. **Output-off mode is a per-run choice, not a fixed one.** The GSM driver
    briefly pinned `OUTP:SMOD HIMP` at reset, and the **2401 driver did so from
    the start**. Both now leave it at NORMal and take the setting from a
    checkbox, defaulting off.

    Reason: HIMPedance opens the output relay to disconnect the sample, which
    is the right thing for some measurements — but the GSM manual explicitly
    warns against it "for tests that turn the output on and off frequently",
    and `iv_sweep`'s periodic mode can cycle the output hundreds of times in an
    unattended run. The relay has a finite number of operations in it, so the
    setting that costs hardware is now one you opt into.

    ⚠️ **This changes 2401 behaviour.** Runs before this used high-impedance
    off; runs after use normal off unless the box is ticked. It affects what
    happens to the sample *between* readings, not the readings themselves, so
    no measured value changes — but if a rig depended on the sample being
    isolated between sweeps, that no longer happens by default. Recorded per
    run in the `output_off_mode` CSV column.

19. **`reset()` is now actually called when an instrument connects.** Every
    driver had one — written, documented, and in two cases tested — and nothing
    in the app ever invoked it. The 2401 spelled its version `configure()`,
    which is how the gap survived: there was no single name to call, so neither
    got called.

    ⚠️ **This would have failed at the bench.** The GSM's `reset()` is where
    `OUTP:ENAB 0` lives, which disables the output-enable interlock. With
    nothing wired to the rear-panel interlock pin, the instrument refuses to
    turn its output on at all — so the first GSM run would have failed with no
    obvious cause. It also carries `SYST:LFR:AUTO` (without which NPLC doesn't
    cancel mains hum), `ROUT:TERM FRON` and `FORM:ELEM`. The 2401 lost
    `:OUTP:ENAB 0` and `:SYST:RSEN 1` the same way.

    Sweeps were unaffected — `start_linear_sweep()` sets `FORM:ELEM` itself.

### U2722A driver

20. **The current-range dropdown becomes the compliance field.** The original
    had a "current range" dropdown driving `SOUR:CURR:RANG` and a separately
    hardcoded `SOUR:CURR:LIM 100mA`. Those are inconsistent below the 120 mA
    range — a 100 mA limit cannot be honoured on the 1 µA range — and the
    instrument silently clamps the limit to the range. The port uses the
    experiment's single compliance field for both, so the two can no longer
    disagree.

21. **Compliance is re-sent after every range change.** `CURRent:LIMit`'s
    accepted maximum depends on the active range, and `*RST` leaves the
    instrument on R1uA with a 100 nA limit. The experiment sets the limit
    before the range, which is right for the other four instruments and wrong
    for this one. The driver caches the requested value and re-sends it, so
    the order the experiment happens to use stops mattering. **This one
    changes what past data means**: a run set up limit-first on this
    instrument had a compliance far below what was asked for. Worth asking
    whoever owns U2722A data whether anything was taken near compliance.

22. **The source range is chosen to cover the whole sweep.** There is no auto
    range on this model and the experiment does not set the swept quantity's
    range, because every other SMU here auto-ranges its source. Left alone, a
    sweep to 5 V would sit on the *RST default R2V and clip at 2 V, returning
    a straight line with an excellent R². `start_linear_sweep()` picks one
    range covering both endpoints before the first point, rather than letting
    the range change partway through a dataset.

23. **Sensing is recorded as wiring, not as a checkbox.** The U2722A has no
    remote-sense command anywhere in its Programmer's Reference; local versus
    remote is decided by how the SENSE terminals are strapped, and this unit
    is wired 4-wire permanently. A new `REMOTE_SENSE_CONTROL` capability
    greys the control out and pins it, and the CSV column reads
    `4-wire (hardwired)`. Accepting the checkbox and ignoring it would have
    written a sensing mode into the file that the measurement did not use.

24. **Per-point averaging is dropped.** The original's "Average mode" used
    `MEAS:ARR:CURR?` with `SENS:SWE:POIN` / `SENS:SWE:TINT` to take N samples
    per point and average them in Python. Removed at the user's request —
    it was implemented but never used in practice. Consequence worth knowing:
    the original CSV never recorded whether the mode was on, so a historical
    file taken with it enabled is indistinguishable from one without.

25. **NPLC is rounded to a whole number.** `SENSe:CURRent[:DC]:NPLCycles`
    takes an integer from 0 to 255. `NPLC_RANGE` is declared as (1, 255)
    rather than (0, 255) on purpose: with a floor of 0 the shared preset menu
    would offer 0.01 and 0.1, both of which round to 0 — no integration at
    all — from a control the operator just used to ask for quieter readings.

26. **No source delay command exists.** The only `SOURce:DELay` entries are
    memory-list ones, which are U2723A features. `set_source_delay()` is a
    documented no-op; the panel's delay field still works because the
    software sweep settles host-side. What cannot be removed is the
    instrument's own auto delay of 0.5–20 ms per point depending on range.
    Reported at connect rather than left to be discovered.

### miniSMU driver

27. **Driven through a library, not a wire protocol.** The MS01's
    documented interface is `minismu_py`, which opens the port itself, so
    `MiniSMUTransport` wraps the library object rather than moving text.
    Its `_write`/`_read` raise; only `*IDN?` is mapped, to keep driver
    auto-detection on the same path as every other instrument. A native
    SCPI-style driver is possible — the spellings are visible in the
    library source — but they are not published as a command reference,
    and the library carries chunked-USB handling, fragmented TCP JSON
    reassembly, a firmware-dependent command terminator, and truncation
    detection that would all have to be rebuilt.

28. **`reset()` deliberately does not reset.** `minismu_py`'s `reset()`
    sends `*RST`, which **reboots the MS01** and invalidates the open
    connection; over USB the port re-enumerates. `LabApp` calls
    `driver.reset()` on every connect, so wiring the obvious thing
    through would have made every miniSMU connection die the moment it
    succeeded, with a symptom indistinguishable from a bad cable. The
    driver's `reset()` instead drops the output, restores autoranging and
    the AUTO voltage range, and clears any leftover 4-wire mode.
    `reboot()` exists separately and is called by nothing.

29. **Capabilities depend on firmware, not model.** Onboard sweeps need
    1.3.4+, 4-wire needs 1.4.3+. The version is parsed from `*IDN?` at
    connect and both degrade rather than fail. An unparseable identity
    counts as *too old* — it is not evidence of a recent build, and a
    fallback that works beats a feature that dies mid-run.

30. **Sweep kind varies per run.** The onboard sweep is voltage-only, so
    a voltage sweep runs on the instrument and a current sweep falls back
    to the software sweep on the same connection. `sweep_kind()` answers
    for the mode currently selected, and the CSV already records it per
    run. This is the first instrument where two datasets from the same
    box can honestly disagree about it.

31. **NPLC is a translation of the oversampling ratio.** There is no NPLC
    setting; the knob is `MEAS<n>:OSR`, 0–15, roughly 2^OSR samples.
    A requested NPLC is treated as an integration window and mapped to
    the nearest OSR in log space, and `clamp_nplc()` returns the window
    actually achievable — so a requested 1 NPLC is recorded as 0.8.
    **The caveat that matters for comparing data:** true NPLC integrates
    over whole mains periods, which is what nulls 50 Hz hum. The
    miniSMU's oversampling is not mains-synchronised, so an "equivalent
    1 NPLC" here rejects hum less well than 1 NPLC on a Keithley. The
    number in the file is a truthful integration time, not a promise of
    the same noise floor. Said in the console at connect.

32. **Voltage range is always AUTO.** The instrument takes AUTO, LOW or
    HIGH and no published document says what LOW and HIGH are in volts.
    Guessing would risk a clipped sweep that still looks clean, so the
    driver sends AUTO in every case and gives up some resolution.

33. **4-wire mode costs channel 2.** `SYST:4WIR ENA` is system-wide, not
    per-channel: CH2 becomes the sense channel, CH2 commands are blocked,
    and OUTP1 then switches both channels together. Ticking the sensing
    box is not free on this instrument.

34. **The 12 V DC adapter is a requirement, not an option.** USB-powered
    operation is limited to 50 mA per channel against 180 mA on the
    adapter, and the instrument reports no way to tell which supply it is
    on. Rather than add a setting that could be set wrong, the driver
    declares the full 180 mA envelope and states the requirement in the
    console on every connect. The failure mode if it is ignored is not
    dangerous, just misleading: a sweep asking for more than 50 mA folds
    back, and the curve looks like a sample going into a compliance
    nobody set.

### 2611A driver

39. **`measure.iv()` replaces `measure.v()` then `measure.i()`.** The
    original driver said TSP had no matched-pair call. It does. The bench
    checkup timed a reading at 1034 ms with NPLC 25 - exactly two 0.5 s
    apertures - confirming the voltage was integrated over the first half
    second and the current over the *next* one. Beyond being twice as
    slow, the V and I of a single "point" described two different
    moments, which matters on a sample that drifts or self-heats and
    matters most to the Hall measurement. **`iv()` returns current
    first**, the opposite order, so the parse is reversed and pinned by
    test. Verified afterwards: `iv()` costs **exactly one aperture**
    (15.6 ms at NPLC 0.001, 515.6 ms at NPLC 25, slope 1.00), so the
    change halved the reading time as well — 1034 ms to 516 ms at
    NPLC 25.

50. **The buffer's element count is read back, not assumed.** Told
    `FORM:ELEM VOLT,CURR`, the GSM-20H10 accepted it, queued no error,
    and returned **three** numbers per reading — voltage, current,
    resistance. A fixed stride of two turned 5 readings (15 numbers)
    into 7 pairs; 4 held the resistance NAN and were dropped; the 3 that
    survived were readings 1, 3 and 5 — genuine V/I pairs, fitting a
    straight line perfectly well. **A silently decimated sweep that
    looked entirely correct.** Only the point-count check caught it, and
    the earlier "3 of 5" symptom was this all along rather than the
    fallback bug it was mistaken for.

    Reading the configuration back does not help either: `FORM:ELEM?`
    answers `VOLT,CURR` — the list it was *given* — while the buffer
    keeps sending three columns. So the instrument's account of itself
    is wrong in both directions and neither the request nor the
    read-back can be trusted.

    What cannot lie is arithmetic. `read_sweep()` now asks how many
    readings the buffer holds, counts the numbers that come back, and
    takes the ratio as the stride; the column order comes from the
    canonical `VOLTage, CURRent, RESistance, TIME, STATus` the family
    documents, truncated to that stride. `FORM:ELEM` is still sent
    before storage is armed — it costs nothing and may work on other
    units — but nothing depends on it any more.

51. **`TRAC:FEED SENS1` really is rejected**, even with storage
    disarmed — the probe fell through to the un-numbered `SENS`, which
    the instrument accepted. So this implementation does not honour the
    SCPI abbreviation for the numbered node, and the manual's `SENSe1`
    is not usable as written. Both readings of the -140 turned out to
    matter: the ordering fix was needed *and* so was the token fallback.

### Transport selection

42. **The miniSMU driver rejects a transport it cannot drive.** The MS01
    answers `*IDN?` over plain serial, so `SerialTransport` connects and
    auto-detection succeeds — and then every method call fails, reporting
    that a connected, working transport is "not connected". Checked at
    construction now, with a message naming the fix.

43. **The checkup CLI has no default transport.** Defaulting to VISA
    turned "you picked the wrong transport" into "No VISA backend could
    open 'COM3'", which sends you debugging a backend that was never
    involved. VISA resource strings are recognised by shape; anything
    else must be stated.

### GSM-20H10 driver

44. **The staircase fallback left the source in sweep mode.** Found on
    the bench 2026-08-05. The instrument refused the staircase setup
    with -140, the driver correctly fell back to the software sweep, and
    left `SOUR:VOLT:MODE SWE` in force. The software sweep steps by
    sending `SOUR:VOLT <level>`, which in SWE mode is read as a sweep
    *endpoint* rather than a level to hold — so the source never moved.
    Five points returned, no error reported, every point at 0 V. The
    fallback that was meant to rescue the run was the thing that broke
    it. `MODE FIX`, `TRIG:COUN 1` and `ARM:COUN 1` are now restored
    before falling through.

45. **A rejected staircase command names itself.** `-140: Character
    data error` identifies a *kind* of mistake, not which of fifteen
    setup commands made it — and several carry character parameters this
    instrument may not accept (`SPAC LIN`, `DIR UP`, `RANG BEST`,
    `MODE SWE`, `FEED SENS1`). On failure only, the setup is replayed one
    command at a time to find the offender, which then appears in the
    sweep note.

46. **Buffer storage must be disarmed before `TRAC:FEED` is changed.**
    The bench reported `-140: Character data error` on
    `TRAC:FEED SENS1`, which looked like a spelling difference. It
    almost certainly is not: the command list states plainly that
    *"TRACe:FEED cannot be changed while buffer storage is active"*, and
    documents `SENSe1` as the correct token. The setup armed storage
    with `CONT NEXT` at the end of every sweep and never turned it off,
    so from the second sweep onward the feed command was refused — and
    took the whole staircase setup down with it, dropping every sweep to
    the software path. `TRAC:FEED:CONT NEV` is now sent in `reset()` and
    again before each setup block. The instrument reporting -140 rather
    than a settings-conflict code is it being loose with error numbers;
    the constraint it enforced was the documented one.

    The parameter question stays open in parallel, because -140 is
    specifically a *character data* error: the driver tries `SENS1`,
    then the manual's literal `SENSe1` (in case this implementation
    matches exactly rather than honouring the SCPI abbreviation), then
    the un-numbered `SENS`. Whichever is accepted is cached. The probe
    deliberately
    runs *before* the staircase error queue is cleared: probing
    mid-setup would swallow a complaint about an earlier command and let
    a half-configured sweep fire, which is exactly what the setup check
    exists to prevent.

47. **Confirmed against the command list, previously inferred:**
    `SOUR:SWE:RANG BEST` selects one fixed range covering the whole
    sweep (as the driver assumed); `SOUR:SWE:DIR UP` means *start level
    to stop level*, not "ascending", so a descending sweep is
    `start > stop` with `DIR` left at `UP` — the driver's load-bearing
    comment is correct, and `DOWn` would have returned the data
    backwards with nothing to say so; `SPAC LIN`, `VOLT:MODE SWEep`,
    `TRAC:POIN:ACT?` and `FORM:ELEM VOLTage,CURRent` are all as sent.
    The buffer maximum is **2500** readings, now enforced.

### miniSMU integration time

49. **The OSR-to-NPLC mapping has no sound basis, and `SAMPLE_RATE_HZ`
    was wrong three times.** The whole
    NPLC↔OSR mapping rests on how fast the oversampling converter runs,
    and the spec sheet's 1000 S/s turned out to be the *streaming* rate.
    The first correction, to 18200 S/s, was also wrong: it came from
    two timings taken in *different sessions*, and per-reading overhead
    on this instrument varies from 6 ms to 29 ms between sessions, so
    most of what looked like integration time was overhead. A single-run
    measurement gave 6.2 ms at OSR 0 and 87.6 ms at OSR 13 — 8191 extra
    samples in 81.4 ms, about 100 kS/s, which predicts 88.1 ms against
    87.6 observed.

    And a six-point scan then disproved the model itself: an eightfold
    increase in sample count costs about 2.2× the time, with the implied
    rate climbing from 10 kS/s to 210 kS/s across the ladder. No single
    rate can describe that, so the NPLC equivalence orders the settings
    correctly but its absolute value means nothing. The driver now says
    so at length, and reports the raw OSR — the one part that is certain
    — in its connect note.

    Both earlier "confirmations" came from two-point fits, which have
    zero degrees of freedom and cannot fail. That is why
    `tools/timing_scan.py` refuses fewer than three points.

    This is exactly the failure a two-point timing measurement is for,
    and it went unnoticed through four checkups because a single timing
    figure cannot expose it. `tools/smu_checkup.py` now warns when
    apertures-per-reading comes out below 0.5 — a reading cannot be
    quicker than the integration it claims, so anything under one means
    the declared aperture is too long and the recorded NPLC with it.

### Output state across a source-function change

48. **The output must be turned on after `set_source_function()`, not
    before.** Changing the source function drops the output on the 2400
    family, and these drivers disable auto output-off (`:SOUR:CLE:AUTO
    0`) so that a sweep holds its level between points. The 2401
    reference: *"if auto output-off is disabled, then the output must be
    turned on before you can perform a :READ?"*. With the output off,
    `:READ?` — `:INITiate` then `:FETCh?` — blocks forever, because
    `:FETCh?` only runs once the source-measure operations complete and
    they never start. It reports as a VISA timeout, indistinguishable
    from a dead instrument, and a device clear does not help because the
    configuration is still wrong.

    The experiments always got this right. `tools/smu_checkup.py` did
    not: it turned the output on once and then switched source function
    for the current-mode checks. That was the whole of the "2401
    current-source hang", which cost two rounds of bench diagnosis and
    was solved by the command reference rather than by guessing. Now
    documented on `BaseSMU.set_source_function` for every driver.

### Comms recovery (all instruments)

40. **`Transport.clear()` added.** A timed-out query is not a
    self-contained failure on GPIB: the late reply sits in the output
    buffer and the next query collects it, putting the session one
    command out of step. A 2401 on the bench turned one slow reading
    into three consecutive failures and a warning, which read as four
    findings. VisaTransport implements a device clear; the base returns
    False rather than silently doing nothing.

41. **Error 823, "Invalid with source read-back on", is a 2400-family
    behaviour, not a GW Instek one.** Both the 2401 and the GSM-20H10
    rejected a *source*-range change with it. `_one_sweep` never makes
    that call — it ranges the measured quantity — so nothing in the app
    was affected; it was the checkup exercising a combination the
    application cannot produce. Fixed by making Tier 2 mode-aware.

### Commissioning (all instruments)

37. **`read_error()` promoted to the contract.** Was an informal habit on
    the two drivers whose spellings were inferred; now mandatory on all
    seven. It is the only way anything above the driver can ask an
    instrument whether it parsed a command, which is what makes
    `tools/smu_checkup.py` more than a smoke test.

38. **`tools/smu_checkup.py` verifies a driver against real hardware.**
    Three tiers - identity and declarations, configuration syntax with
    the output off, then live measurement into an expected open circuit.
    Writes Markdown plus JSON. It assumes nothing is connected, forces
    2-wire where it can, and always leaves the output off, including
    when a check crashes partway through.

### VISA backends (all instruments)

35. **Backends are merged rather than chosen.** A vendor VISA library
    and pyvisa-py do not enumerate the same instruments, and the U2722A
    is the case that forced the issue - it was plugged in, powered and
    absent from the address dropdown. `VisaTransport` now scans every
    backend, merges for listing, and falls through at connect. Both the
    `?*::INSTR` and `?*` patterns are scanned so a `::RAW` device is not
    silently hidden. A pinned `VisaPyTransport` is offered separately for
    the case merging cannot fix: a backend that opens the instrument and
    then goes wrong.

36. **`pyusb` and `libusb-package` are now required.** pyvisa-py finds no
    USB instruments at all without a USB layer beneath it, and reports no
    error while doing so.

### 2401 driver

Not numbered, but the same class of thing:

- **Source levels are no longer rounded to 4 decimals.** The original sent
  `round(Vo + i*step, 4)`, quantising the source to 100 µV. Harmless at ±1 V.
  At ±100 µV over 21 points it collapses to **3 distinct levels** with 18
  duplicates — while the saved x-axis still claims 21 evenly spaced values, so
  the damage is invisible afterwards. **Any low-bias 2401 data from the old
  script is suspect.** There is a regression guard in `tests/test_2401_driver.py`.
- **`:READ?` instead of `MEAS?` per point.** `MEAS?` means "configure, then
  read", so it reset the ranging and compliance that had just been set — on
  every point of the sweep.

---

## Notes on individual originals

Kept because they explain design choices that would otherwise look arbitrary.

### IV sweep — three scripts merged into one

`Basic`, `Development` (identical to a file also called `Improved`) and
`Long_bias` were additive versions of one another, so they became one
experiment with optional panels rather than three subclasses.

The one thing that genuinely differed was `alreadyOn`: with `alreadyOn=False`,
`Long_bias`'s `voltage_sweep` is instrument-identical to `Development`'s — the
guards wrap only the output ON and OFF writes. It is a safe superset, and one
boolean (`hold_output`) carries the difference.

Two unrelated changes had crept in at the `Basic → Development` step, and
those were the interesting ones: the linear fit was commented out in
`Long_bias` (it appended `0.0, 0.0, 0.0`), and the settle wait was rounded to
whole seconds. Both are addressed by deviations 3 and 7.

Also dropped: the **bias-mode lock** ("close the program to change bias mode").
That existed only because the compliance dropdown was *constructed* by the
lock handler. It is built once now and repopulated on mode change, so there is
nothing to protect against. Mode changes are refused while measuring, which is
the real constraint.

### Dual-SMU long bias — deliberately not ported

The `Keithley2401` driver was written; the *experiment* was not. The script
had been run only a few times, years ago, and its requirements are no longer
remembered. Reading the code answered what it did but not what it was *for*,
and porting it would have produced a plausible-looking experiment nobody could
confirm was correct.

If it is ever needed, build it from clear requirements. What the script
actually did, so nobody has to re-derive it:

- The two SMUs ran **sequentially, not simultaneously**. Each periodic cycle
  was: 2611 sweep × iterations → `sleep(0.5)` → 2401 sweep × 1 → `sleep(0.5)`
  → bias or idle for the cycle period. Single-threaded throughout.
- So a `{"source", "monitor"}` role split would be **wrong**. The 2401 did not
  monitor while the 2611 swept. Both were sources running their own
  independent sweeps, interleaved.
- The 2401 side was voltage-sweep only.
- In dual mode the 2401 shared the 2611's dataset name per cycle.
- Layout was mirrored, 1680×900 — already wider than the layout budget, with
  two 600×600 plots.

**Still unanswered:** what the 2401 was measuring while the 2611 applied its
long bias — a second device on the same stage, another terminal of the same
device, or a cross-check. The code cannot say, and it decides whether this is
one experiment with two roles or simply two experiments.

### Ossila 4PP — the first file supplied was mid-edit

The version originally supplied could not run. Two independent crashes sat on
the Run path:

1. `run_func()` tested `if points <= 30:`, but `points` was a (70, 2) geometry
   meshgrid at module scope, not a sweep-point count. Comparing an array
   raises `ValueError` before any measurement starts.
2. `current_sweep()` opened with a loop calling `set_current()`,
   `measure_voltage()` and `save_data_point()` — none of which was defined
   anywhere in the file. `NameError` on the first iteration.

Both look like one accident: a local name shadowed by a module-level one, and
a block of intended helpers left unwritten. That dead loop was also the
clearest surviving statement of intent — it alternated each current's polarity
eight times, which is thermoelectric-offset cancellation, and that is now
implemented properly.

A third inconsistency: the buffer read sliced out "the middle sweep", which
only makes sense against the triangular shape from a generator function that
was written and never called. The visible GUI sourced eight flat current
entries with no leg structure, so that slice would have taken the wrong
region. **Both shapes are now offered, chosen explicitly, and the slicing
follows the choice.**

Later working versions were then supplied and reviewed:

- The **triangular/sine variant** is the one with a working fit, and confirms
  the middle-leg slice: its `start_index = floor(points/2) + 1` matches this
  port's `len(down_leg)` exactly, for odd and even point counts. It still
  reconstructs the x-axis with `np.arange` and rounds resistance to 3 decimals
  before storing — both avoided here.
- The **revised list version** restructured the measurement so each current
  became its own block of 8 alternating readings and its own dataset. Its
  `regresion_mem` is still never appended to, so its plot and calculate paths
  raise `IndexError` — it collects raw data only. **If anyone is still running
  it, their Plot and Calculate buttons do not work.**
- Its per-block fit is **mathematically identical** to the reversal averaging
  used here — verified numerically: both recover R exactly and return the
  offset as the intercept.
- **What was worth taking** was its output *shape*. One fit per current shows
  whether R depends on drive level; a single slope across all currents hides
  that inside its R². Each reading now carries `resistance_at_point_ohm`, and
  a spread above 2% logs a warning about self-heating or non-ohmic contacts.
- `arr_flag`, `sample_number` and `time_between_avg` in the sine variant are
  vestigial — declared global, never used.

### Probe spacing is fixed at 1.27 mm

Not a parameter that happens to have a default. Both 4PP correction tables are
indexed by t/s and W/s, so the spacing is baked into them: a different probe
head needs different tables, not a different number. It is shown on screen as
a note for exactly that reason.

---

## Two originals' habits worth knowing about

**Precision floors.** `Hall_v4.ipynb` wrote measured voltages at `%.6g` into
both the results table and the calculation boxes. Since the Hall voltage sits
under a resistive offset 100–1000× larger and is recovered by subtracting
nearly-equal numbers, six significant figures imposed a ~0.1% floor on V_H
before any physics happened. `VOLTAGE_FIGURES = 9` now. The same class of
mistake appears in the 2401's 4-decimal source rounding, and in the IV
scripts' 6-figure display values being used as calculation inputs.

**Background `:READ?` pollers.** Both notebook originals ran a thread issuing
`:READ?` while the measurement loop was also issuing `:READ?`, discarding the
result. Not corrupting — the socket lock made each read atomic — but it
doubled the instrument's work and made point-to-point timing unpredictable.
Dropped from all ports.

---

## Faults to check for in any new original

Every script ported so far has carried at least one of these, and none of them
announce themselves — each produces data that looks entirely reasonable. Work
through this list *before* writing the driver. Two of them change what past
data means, so finding one is also a question for whoever owns that data.

**1–10 came from reading the original scripts. 11–15 came from running the
finished drivers against real instruments**, and are the ones the offline
test suite cannot reach: they are all cases of an instrument disagreeing
with a reasonable assumption rather than code disagreeing with itself. That
is what `tools/smu_checkup.py` exists to find.

**1. `MEAS?` used per point.** On the 2400 family and its relatives, `MEAS?` is
`:CONFigure` followed by `:READ?` — it resets ranging and compliance to `*RST`
values on *every point*, undoing whatever was set beforehand. On the GSM it
also turns the output on. Found in the 2401 original and again in the 20H10
one. Use `:READ?` against the configuration already in place. Deviations 11
and the 2401 note.

**2. Concurrent measurement never enabled.** With
`[:SENSe]:FUNCtion:CONCurrent` off, only one function is measured and the
other field of the reply is filled from the **source setting**. Source 1 V and
the voltage column reads back exactly 1.000000 V — the number you asked for,
not the number across the sample. Lead and contact drops vanish and a 4-wire
rig silently returns a 2-wire measurement. Deviation 14.

**3. NAN and overflow sentinels treated as data.** "No reading" comes back as a
*number*: `+9.91e37` for NAN, `+9.9e37` for over-range. Nothing raises. One of
these in a sweep dominates the least-squares sum entirely, so the fit runs to
that single point while still reporting a healthy R². Deviation 17.

**4. Source levels rounded before sending.** `round(V, 4)` quantises to 100 µV,
which is invisible at ±1 V and catastrophic at ±100 µV — 21 requested points
collapse to 3 distinct levels while the saved x-axis still claims 21 evenly
spaced values. Deviation 12 and the 2401 note.

**5. Sweep completion slept rather than polled.** `sleep(round(points * delay *
1.3))` reads a partly-filled buffer on short sweeps and silently returns fewer
points than requested. Poll the instrument's own count. Deviation 3.

**6. Instrument state inherited rather than set.** Sensing, NPLC, compliance
and output-off mode all persist between runs. If the original sets one inside
only *some* code paths, the same sample reads differently depending on what
ran before it. Set everything that matters on every run. Deviations 6 and 18.

**7. Line frequency never set.** NPLC only cancels mains hum if the instrument
knows the mains period, so an integration time set without
`:SYSTem:LFRequency` is worth less than it looks. Deviation 16.

**8. `rm.open_resource(instruments[0])`.** Connects to whatever VISA happens to
list first. In a room with five SMUs that is a coin toss, and it explains
otherwise-inexplicable results. The connection panel fixes this; no port
needed, but worth knowing when old data looks wrong.

**9. Reconstructed x-axes.** `np.arange(start, stop, step)` assumes the
instrument hit every requested level exactly. Read back what it actually
sourced. Deviation 4.

**10. A command that exists in the manual but not on the instrument.** SCPI
instruments log unrecognised commands and carry on. Nothing raises, and the
previous setting stays in force. Where a spelling is inferred rather than
documented, send it and then read `SYST:ERR?` — see the GSM's
`_probe_sweep_support()`.

**11. A command the instrument accepts and then ignores.** Worse than 10,
because the error queue stays clean. The GSM accepts
`FORM:ELEM VOLT,CURR`, queues no error, and keeps sending three columns —
*and* answers `FORM:ELEM?` with the list it was given rather than the one
it sends. Neither the command nor the read-back described reality. Where
the shape of a reply matters, count what arrived. Deviation 50.

**12. A setting that only applies before something is armed.** `TRAC:FEED`
cannot be changed while buffer storage is active, and `FORM:ELEM` behaves
the same way in practice. Sent afterwards they are accepted and do
nothing. Order matters even when nothing complains. Deviations 46 and 50.

**13. State left behind by a sweep.** The GSM's staircase sets
`TRIG:COUN` to the sweep length and puts the source in `MODE SWE`. Neither
was restored, so the next single reading took N times as long and the next
level-set was read as a sweep endpoint. Anything a sweep changes, a sweep
must put back. Deviations 44 and the trigger-count note.

**14. Output state assumed across a source-function change.** The 2400
family drops the output when the source function changes. With auto
output-off disabled — which these drivers do, so a sweep holds its level —
`:READ?` then blocks forever with no error, looking exactly like a dead
instrument. Call `output_on()` *after* `set_source_function()`. Deviation
48.

**15. A limit sent before the range that has to hold it.** On the U2722A a
compliance value is clamped to the range active when it arrives, and
`*RST` leaves the smallest range selected. The limit was accepted, silently
clamped, and the sweep ran with a compliance a hundred times lower than
asked for. Widen the range first. Deviation 21.
