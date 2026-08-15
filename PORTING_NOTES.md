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

## The B2901A - a driver with no original behind it

Every other driver here was ported from a working script, so the ledger
above records *departures* from code somebody was already using. The
Keysight B2901A had no script. Nothing below is a deviation from
existing practice; each is a decision made from the command reference,
written down so the reasoning outlives whoever made it.

**B1. Automatic output-on disabled.** `:OUTP:ON:AUTO` resets to ON, and
the reference states that with it enabled the source output is turned on
automatically when `:INIT` or `:READ` is sent. This suite guarantees the
output is energised only when a run asked for it, and "OFF turns the
output off and the worker turns it straight back on" is a failure
already seen on a bench here. On this instrument it would happen with no
command to trace it to. Set to 0 after every reset. Chosen, not
inherited.

**B2. The measurement path is `:MEAS?`, not `:READ?`.** Two reasons,
either sufficient. `:READ` and `:INIT` are exactly the two commands that
trigger automatic output-on, so a measurement path that never touches
them means the output state does not depend on B1's setup line having
succeeded. And the reference is explicit that `:MEAS?` measures the
parameters `:SENS:FUNC` specifies using conditions set beforehand - it
is *not* the 2400 family's `MEAS?`, a hidden `:CONFigure` + `:READ?`
that resets ranging and compliance on every point. Fault 1 does not
apply to this instrument, and the driver comment exists so nobody has to
re-derive that.

**B3. Compliance uses the unlicensed spelling.** `:SENS:CURR:PROT`, not
`:SENS:CURR:PROT:BOTH`. The `BOTH` keyword and the
`:NEGative`/`:POSitive` split-polarity forms require licence "SWS" and
firmware 3.1 or later. A driver using them works on some B2901As and not
others, and the failure arrives as a run-time command error on whichever
unit nobody had tested.

**B4. The hardware staircase sweep is not implemented.** The instrument
has one and it is fully documented. It is left out because the GSM's
hardware sweep cost three separate bench-found deviations - state left
behind by the sweep, a buffer setting that only applies before arming,
and an element list accepted and ignored - none of which an offline
suite could have found, and this instrument has not been on a bench. The
inherited software sweep is correct from day one and reads back every
level it sources. Upgrading is one file and nothing in experiments/
changes.

**B5. `MODEL_IDS` claims only the B2901A**, not the series. The B2902A
is two-channel; the B2911A/B2912A add a 10 nA range this model does not
have. Claiming `B2900` would hand a B2911A a range table missing its
most useful range. An unclaimed instrument gets the manual driver
dropdown; a wrongly claimed one gets silently wrong limits.

**B6. Line frequency is declared, not asked.** `:SYST:LFR 50`, because
that is where this bench is. NPLC only cancels mains hum if the
instrument knows the period, so integration time set without it is worth
less than it looks (fault 7). A 60 Hz lab changes one constant.

**B7. The sense-function spelling is probed, not guessed.** The manual
contradicts itself - the parameter table quotes the argument, its own
`:MEASure?` example does not, and both spellings appear across its nine
worked examples. The driver sends one, then asks
`:SENS:FUNC:ON:COUN?` and requires exactly two. Sending both would leave
nobody able to say which the instrument acted on. The clear-first
(`:SENS:FUNC:OFF:ALL`) is load-bearing and the first version omitted it:
reset leaves all six functions enabled, so "at least two" was already
true before anything was sent. The probe returned a fact, but not a fact
about whether the command had worked. Caught by its own test.

**Still unverified, and on the bench list:** whether `:TRIG:ACQ:DEL` -
the settle handed to `set_source_delay()` - applies to the `:MEAS?` path
or only to the `:INIT`/`:FETCh` trigger path. The reference does not
say. If it does not apply, the settle silently does not happen and the
readings look like ordinary noisy data. Deliberately not worked around
by sleeping host-side: that would move *where the settle happens*, which
is a measurement parameter, and that decision is open in WAVE_PLAN
rather than one to make quietly inside a driver.

---

## The 2635B - the second driver with no original behind it

Same situation as the B2901A above: no lab script, so nothing here is a
departure from working code. Each is a decision made from the Series
2600B Reference Manual, signed off individually before the driver was
written, and recorded so the reasoning outlives whoever made it.

**D0. Standalone file, not a subclass of the 2611A.** The two speak the
same TSP dialect and share perhaps 80% of their command text, so
subclassing was on the table and was rejected. The justification arrived
almost immediately: `smuX.measure.delay` resets to `DELAY_OFF` on a
2611B and to `DELAY_AUTO` on a 2635B. Same attribute, same spelling,
opposite default. A subclass would have inherited the 2611A's
assumptions about a family member that does not share them.

The counter-argument is the one this file opens with - six drifting
copies is how the originals died - and it is a real cost, not a
dismissed one. The answer is that a shared `TSPSourceMeter` base is the
right eventual shape, but extracting it means refactoring a
bench-verified driver in the same patch that introduces an unverified
instrument, and a red test afterwards would not say which change caused
it. Deferred to its own wave.

**D1. The output-off state is configured, not inherited.** This is the
2635B's equivalent of B1, and it is subtler. Nothing self-energises -
`source.output` resets to OFF and stays there. But `offmode` resets to
`OUTPUT_NORMAL`, `offfunc` to `OUTPUT_DCVOLTS` and `offlimiti` to 1 mA,
so an output that is "off" is still **actively sourcing 0 V into the
sample with a milliamp of compliance available**. A driven low-impedance
path, not an open circuit.

The suite's Stop-de-energises guarantee is therefore true in letter and
misleading in spirit. It matters more on this model than on the 2611A
next door: this is the instrument bought for high-resistance samples,
and a 1 mA path across one between runs is six to nine orders of
magnitude above anything the measurement cares about. The temperature
stage sharpens it - a Peltier cycling under a shorted sample is exactly
when a thermoelectric EMF has somewhere to go.

All three attributes are now written on every reset. A cross-driver grep
found that no driver in the suite sets an off-state *function* or
*limit*; only the 2611A and B2901A set the *mode*. **The 2611A very
likely carries the same latent gap**, and that is a separate wave and a
separate manual - flagged here rather than fixed alongside a new
instrument.

**D2. The off-state compliance stays at 1 mA.** Kept deliberately rather
than lowered. The alternative off-state function, `OUTPUT_DCAMPS`,
sources 0 A and lets the terminals float to the 40 V `offlimitv`
default, which on a high-impedance sample is worse than a short - 0 V
with a limit at least holds the sample at a known potential. The manual
also warns that limits below 1 mA interfere with contact check. Exposed
as `OFF_STATE_CURRENT_LIMIT_A` so it is one constant to change, and
written up in INSTRUMENTS.md so the operator knows what "off" means.

**D3. High-Z stays routed through `offmode`.** The manual offers a
second route - assigning `OUTPUT_HIGH_Z` directly to `source.output`,
which reaches high-Z without touching `offmode`. Deliberately unused, so
the suite expresses the idea one way rather than two. Recorded because
it has a trap in it: reading `source.output` back after that assignment
returns `0`, not `2`, so a future read-back verification must not expect
the value it just wrote.

**D4. All four autorange flags are set explicitly.** `source.rangeY`
documents the 2635B's source current range default as a fixed 1 nA,
which read alone suggests a reset instrument is pinned five decades
below a typical Van der Pauw level. `measure.rangeY` settles it -
autoranging is enabled for all four functions by default, and the range
attribute reports where autorange currently sits. Set explicitly anyway:
the cost is four writes and the failure it guards against is every run
being wrong from the first point.

**D5. Autozero left on AUTO, and written.** The manual describes exactly
the behaviour the 2611A's bench commissioning measured as a
three-aperture first reading: reference and zero conversions inserted
when they expire. Accuracy over timing, and the deviation-39 note on the
2611A now has a documented cause rather than an inferred one.

**D6. `set_source_delay(0)` is honoured as asked, and the consequence is
documented.** On this model that replaces a `DELAY_AUTO` the instrument
would otherwise apply - a current-range-dependent settle inserted before
every current measurement, which on the low ranges is the box protecting
the operator from unsettled readings. Every experiment sets the delay
explicitly, so behaviour is deterministic either way; the point is that
zero means something stronger here than on the 2611A.

**D7. Sense mode is restated on every reset.** It resets to
`SENSE_LOCAL`, i.e. 2-wire, which measures the leads as well as the
sample. The write is a no-op against current firmware and is kept
anyway: a default that is never sent is a default nobody chose, and
firmware revisions move them.

**D8. Power compliance explicitly disabled.** `limitp` resets to 0, and
when non-zero the SMU overrides whichever of the V and I limits it needs
to in order to hold the power ceiling - so an inherited non-zero value
would quietly override a compliance the experiment set on purpose.

**D9. The error queue is split on tabs.** `errorqueue.next()` returns
four values and `print()` separates multiple arguments with a tab
character. The 2611A splits on whitespace, so its `message` field
swallows the severity and node onto the end of the text and breaks any
multi-word message across fields. Cosmetic there; not carried forward.

**D10. Line frequency is read before it is written.**
`localnode.linefreq` is nonvolatile and its page says "Affected by: Not
applicable" - reset does not touch it. So writing 50 Hz on every connect
would be a pointless flash write every session, and would silently clear
an `autolinefreq` somebody set deliberately. Read, compare, write only
on disagreement. A failure to read is reported and does not fail the
connection: being unable to ask is not evidence of a fault, and NPLC
still works, it just rejects mains hum less well.

**D11. `measure.lowrangei` kept at 100 pA, and now written.**
Originally "left at its reset default", on the reasoning that it is the
one place this instrument's low-current capability is genuinely
reachable, and that it costs settling time but no correctness.

Both halves held up, and the bench put a number on the settling time.
At NPLC 0.001 with a 10 ms delay, 20 readings per figure:

    100 pA floor (the default)    86.7 ms per reading
    1 nA floor                    30.2 ms
    1 uA floor                    30.2 ms
    autorange off, fixed range    30.2 ms
    autozero off                  30.2 ms
    no measurement delay          20.2 ms

Unusually clean for a timing measurement. The entire ranging cost is in
the decades below 1 nA - raising the floor there recovers all of it,
raising it further recovers nothing - and autozero costs nothing at this
integration, which rules D5 out as a factor. The 10 ms in section 6 is
exactly the delay that was requested, confirming D6. Roughly 20 ms is
fixed front-end overhead no setting reaches.

For comparison the 2611A, same dialect and same driver structure,
measures 15.9 ms per reading including the same 10 ms delay. Its
`lowrangei` resets to 100 nA - three decades higher.

**The value is unchanged; what changed is that it is now sent.** A
number worth two thirds of the reading time should be a decision in the
driver with the evidence attached, not whatever reset happened to leave
(fault 17). Raising it is a one-line edit for a bench that only measures
above a nanoamp, and it trades measurement capability rather than only
speed - so it belongs to whoever knows the sample. Recorded in
INSTRUMENTS.md in those terms.

**D12. The hardware sweep is not wired up.** The TSP sweep factories are
the same family the 2611A drives successfully and would very likely
work. "Very likely" is how the GSM's staircase earned three bench-found
deviations. Same reasoning as B4. The software fallback reads back every
level it sources, so the measurement is sound and only the timing is
host-dependent.

**D13. No channel alias.** The 2611A sends `smu = smua` once per
connection and writes `smu.` thereafter, because its original scripts
did. There is no original here, so this driver addresses `smua.`
directly. It removes a piece of per-connection state that has to land
before any other command means anything, and it makes each command
self-contained - which is what lets the tests assert strings that read
exactly like the manual page. The failure it prevents is quiet: `smu.`
with no alias defined indexes a nil value in Lua, so the level never
changes and the run continues at whatever was set before.

**D14. ASCII precision raised to 16 on every reset.** The find that
justifies the whole exercise. `print()` *is* governed by
`format.asciiprecision` - the print() page says so - and that attribute
resets to **6 significant figures**. The Hall experiment pins
`VOLTAGE_FIGURES = 9` precisely because V_H sits under a resistive
offset 100-1000x larger and is recovered by subtracting nearly-equal
numbers; six figures put a ~0.1% floor on V_H before any physics, with
no error and no warning.

**Nothing in this codebase sets that attribute anywhere**, which means
the 2611A has been reading at six significant figures for its entire
life here. Same shape as the sentinel discovery below: a new driver
surfacing something the existing ones were quietly doing. Not fixed in
this patch - it is a different instrument and a different manual, and a
one-line change to a bench-verified driver deserves its own wave and its
own bench check. **Open item.**

**D15. Source and measure current ranges are different sets, and
`LIMITS` declares the sourceable one.** The 100 pA range is
measurement-only; the lowest range the 2635B can source is 1 nA.
`SMULimits.current_ranges` is consumed by Van der Pauw and Hall as the
*sourced level* dropdown and by IV sweep as the *compliance* dropdown,
never as a measurement range - so it holds source ranges only.

Listing 100 pA would offer an operator a Van der Pauw current the
instrument cannot produce. It would clamp to its lowest source range and
the sheet resistance would be computed from a current that was never
sourced: no error, plausible number, wrong by the clamp ratio. Fault 4.

The cost is that the 100 pA measure range is unreachable from this app.
That is recorded in INSTRUMENTS.md rather than worked around, because
the fix is a `measure_current_ranges` field on `SMULimits` and a
dropdown to feed from it - a shared-layer change that does not belong in
the same patch as an unverified instrument. **This is the first
instrument in the suite where the two sets differ**, which is why the
conflation went unnoticed for seven drivers.

**D16. `compliance_tripped()` implemented, after the page was read.**
It was deliberately left unwired in the first pass: `smuX.source.compliance`
is *named* in the limit-attribute page, but guessing how a Lua boolean
renders through `print()` would have produced a query that silently
always answered "fine" - and `compliance_tripped()` returning False
means "everything was fine" where None means "this instrument cannot
say". A wrong False is worse than an honest None.

The attribute's own page settled it, including a worked example whose
output is the bare word `true`. Two things it records that the driver
now documents: reading the attribute updates the status model and the
front-panel indicator as a side effect, and the flag covers the
voltage, current **and power** limits alike, so True means "a
configured ceiling is in control of the output" rather than "the
compliance this experiment set was hit". Unparseable and failed replies
both return None.

**D17. `MODEL_IDS` claims `2635B` only.** Not `263`, not `2600B`. The
2636B is dual-channel and would be driven on one channel with the other
silently ignored; the 2634B lacks the 100 pA measurement range
altogether. **The IDN string is the one unconfirmed fact in this
driver** - it is written from the family convention rather than read off
the unit, and is flagged in INSTRUMENTS.md. If auto-detection fails at
the bench the app offers a manual dropdown, so the failure is an
inconvenience rather than a dead end.

### Two faults checked and found absent

Worth recording as examined rather than unexamined, since both bit other
drivers in this suite:

- **Fault 15 does not apply.** `smuX.source.limitY` states that the SMU
  always autoranges for the limit setting, so a compliance cannot be
  silently clamped by whatever range happens to be active - which is
  exactly what happened on the U2722A. The same page does impose an
  ordering rule that the suite already follows: set the limit before
  turning the source on.
- **Fault 11 does not apply to ranging.** `smuX.measure.rangeY` states
  that explicitly setting a measure range disables autoranging for that
  function, so no `AUTORANGE_OFF` is needed first. The B2901A needs the
  opposite treatment, and the driver test asserts the absence of that
  dance so nobody copies the SCPI assumption across.

---

## The no-reading sentinel - found while adding the fifth driver

Fault 3 in the checklist below says an instrument reports "no reading"
as a *number*: +9.91e37 for not-a-number, +9.9e37 for over-range, and
TSP uses the same values. The GSM driver handled it from the start,
which turned out to be the whole of the protection.

Adding the B2901A made it the second driver to need the same constant,
which is the point the capability ledger exists to catch. Rather than
copy it, a diagnostic ran every registered driver against a transport
that answers every reading with a sentinel. The results were facts, not
a reading of the code:

| Driver | Returned the sentinel as data |
|---|---|
| Keithley 2450 | yes, both values, both columns |
| Keithley 2401 | yes, both values, both columns |
| Keithley 2611A | yes, both values, both columns |
| Keysight U2722A | yes, both values, both columns |
| GW Instek GSM-20H10 | no |
| Keysight B2901A | no |

Four of six. `NAN_THRESHOLD` and a `drop_sentinel()` helper moved to
`BaseSMU`; the two drivers that had their own copy now inherit it, and
the four that had nothing now apply it. `tests/test_sentinel_handling.py`
discovers drivers from the registry rather than from a list kept in the
test, so a driver added later fails until it handles the sentinel
whether or not its author has heard of +9.91e37.

**Sentinels are replaced in place, never filtered out.** Dropping a
voltage by omission shifts every later column left and the current is
silently promoted into the voltage's position - a number of the right
shape, wrong by a factor of the resistance, and indistinguishable from a
real reading afterwards. That is worse than the sentinel it replaces,
because a sentinel is at least obviously absurd. The test asserts the
sentinel column is None *and* the other column still holds its own
value; checking only that one of them is None would pass an
implementation that shifted.

**Two drivers are exempt**, and the test guards the exemption list
itself. The miniSMU is driven through `minismu_py` rather than a text
protocol, so it hands back Python floats and there is no reply to parse.
The DummySMU computes its readings.

**Writing the test found a second thing worth knowing.** The first
version assumed every driver returns voltage first. The 2611A does not -
TSP's `measure.iv()` gives current then voltage - so the test reported
correct behaviour as a fault, which is how a bad test teaches somebody
to "fix" working code. The reply order is now a small table in the test
file, which pins the 2611A's reversal a second time.

**What this does not tell you.** Nothing here has met a real instrument
sending a real sentinel. The diagnostic proves the parsing, not that any
of these four instruments produce the value in the circumstances the
manuals describe. `tools/smu_checkup.py` is where that would be
answered.

---

## The 2611A corrections - found by writing a driver for its sibling

The 2635B was written from the 2600B manual with no original script. Two
of the decisions forced by that exercise turned out to be faults the
2611A had been carrying since it was ported, and a third was a habit
worth not keeping. None showed up as a departure from working code,
because the original scripts had them too.

This is the third time the pattern has repeated: the GSM's sentinel
handling, then the B2901A's promotion of it to `BaseSMU`, now this. **A
new driver written carefully is the most reliable audit of the existing
ones this project has.**

**A1. Replies were truncated to six significant figures.** The 2600A
manual lists `format.asciiprecision` as governing `print`, `printnumber`
*and* `printbuffer`, with a reset default of 6. Nothing in this codebase
had ever set it.

So every reading this driver has taken came back at six figures - both
through `measure()` and, because the hardware sweep reads back with
`printbuffer`, through every sweep point as well. The Hall experiment
pins `VOLTAGE_FIGURES = 9` precisely because V_H sits under a resistive
offset 100-1000x larger and is recovered by subtracting nearly-equal
numbers; six figures put a ~0.1% floor on V_H before any physics.

It arrived as slightly-wrong data, never as an error, and the display
truncation that caused the `test_hall_handoff` flake documented in
HANDOFF was a *different* six-figure problem in the same measurement -
which is how this one stayed hidden behind it. Now 16 on every reset.

**Any Hall or high-resistance result taken with this driver before this
change carries that floor.** Nothing here can tell you which runs those
were; that is a lab-records question, not a code one.

**A2. "Output off" was a driven 0 V source.** `offmode` resets to
`OUTPUT_NORMAL`, which on a 2611A sources 0 V into the sample with
`offlimiti` (1 mA) available - a low-impedance path across the sample
rather than an open circuit. `set_output_off_mode()` existed and was
correct, but nothing stated the mode or the limit at reset, so the
off-state was whatever reset had left. Both now sent explicitly.

**The family shape differs, which is the vindication of keeping the two
drivers as separate files.** The 2600B adds an `offfunc` attribute
selecting between a 0 V and a 0 A off-state; **the 2600A has none** -
normal-off is always 0 V. So `keithley_2611a.py` states two attributes
where `keithley_2635b.py` states three, and a subclass would have sent
the 2635B's third one into a Lua interpreter that has no such field.

**A3. Line frequency is read before it is written.** Never set at all
before. Reading first matters more here than on the 2635B: the 2600A
manual states that explicitly setting `linefreq` sets `autolinefreq` to
false, permanently and in nonvolatile memory. A driver writing 50 Hz on
every connect would silently disable automatic detection on an
instrument somebody had deliberately left detecting, and nothing would
ever turn it back on.

**A4. `compliance_tripped()` implemented.** `smu.source.compliance`,
read-only, a Lua boolean. The 2600A page describes it per source
function - the voltage limit reached when sourcing current, or the
current limit when sourcing voltage - and unlike the 2600B wording does
not mention a power limit, so nothing is claimed about `limitp`.
Unparseable and failed replies return None rather than False, because
False means "everything was fine" and a wrong reassurance is worse than
an honest silence.

**A5. The error queue is split on tabs.** `print()` separates multiple
arguments with a tab and `errorqueue.next()` returns four of them, so
splitting on whitespace put the severity and node on the end of the
message and broke multi-word messages across fields. Cosmetic, and
fixed while the file was open.

### Two faults checked and found absent

- **Fault 11 does not apply to ranging.** The 2600A `measure.rangeY`
  page states that explicitly setting a source or measurement range
  disables autoranging for that function, and that autoranging is
  enabled for all four functions by default. The existing fixed-range
  writes were correct.
- **Fault 16 does not apply.** The Model 2611/2612 range table gives a
  *source* and a *measure* column for every range, and they agree from
  100 nA up - unlike the 2635B, where the 100 pA range is measure-only.
  One list is honest here. The 10 A range is pulse-mode only and was
  already correctly absent from LIMITS.

### The 200 V interlock - declared, not handled

Footnote 1 on the range table: the 200 V source range is available only
when the interlock is enabled. The interlock section names **2611, 2612,
2635 and 2636**, so this applies to both TSP drivers - the 2600B range
table does not footnote it for the 2635B, but the section text does.

The condition is that the output can only be turned on when the
interlock line is pulled high, and that if a fixture lid opens the
output goes off and **stays** off until the line is set high again.
There is no command that overrides this: it is a physical line on the
Digital I/O port.

So software cannot help, and pretending otherwise would be worse than
saying nothing. What the drivers do instead is *declare* the condition -
`INTERLOCK_ABOVE_V = 20.2` - and `begin_run()` prints one line the first
time a run starts on such an instrument. The 200 V range is used here
for highly resistive samples, and the failure it prevents is an operator
watching a high-voltage run refuse to source and going looking for a
driver fault.

Three properties of that note, each pinned by a test:

- **Printed from `begin_run()`**, the seam every experiment passes
  through. The pre-existing connect-time `sweep_note()` hook is wired
  into IV sweep only, so a fact printed there reaches one experiment out
  of four.
- **Once per session, not once per run.** A warning repeated on every
  run is one operators learn to skip, and that decay is invisible - the
  line is still there, still correct, and no longer read.
- **It cannot fail a run.** A console convenience must never stop a
  measurement starting, so the seam swallows its own errors.

**This bench keeps the interlock line shorted with a wire.** Recorded
because it changes what the hardware does, not to argue with it: with
the line jumpered the lid-open cutout does not exist, so 200 V at up to
100 mA can remain live on an open fixture. Anyone reading a 200 V run
off this bench should know that the protection the manual assumes is not
in circuit. The manual also cautions that the interlock line degrades
after about 10,000 operations, which a permanent jumper does not
exercise.

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

**16. One range list standing in for two.** A driver declares
`current_ranges` and everything assumes source ranges and measure ranges
are the same set. On the 2635B they are not: it measures to 100 pA and
sources only to 1 nA. Offering a measure-only range as a sourced level
gets it clamped to the nearest sourceable one, and the derived
resistance is then computed from a current that was never sourced - no
error, plausible number. Check both directions in the manual before
declaring LIMITS. Deviation D15.

**17. A default that is never sent is a default nobody chose.** Distinct
from fault 6, which is about state inherited *from a previous run*. This
is state inherited from the factory: `format.asciiprecision` resets to 6
significant figures on every 2600B, which is below what the Hall
measurement needs, and no driver in this suite had ever set it. It
arrives as slightly-wrong data rather than as an error. Where a reset
default is load-bearing, send it explicitly even when it already has the
value you want - firmware revisions move them. Deviation D14.

**18. An accuracy that is an implementation detail, not a guarantee.**
The maths modules averaged with the built-in `sum()`. On CPython 3.12
and later that is Neumaier compensated summation and is very accurate;
on 3.11 it is not, and the difference moved a fitted intercept enough to
turn an exact-comparison golden red on a bench machine that had picked
the older interpreter. The accuracy was real but accidental - it is a
property of one interpreter version, not of the language. `math.fsum` is
documented to return the correctly rounded sum. Where a number ends up
in saved data, prefer the guarantee over the accident, and keep the
built-in only for integer counts where it is exact and `fsum` would
wrongly return a float. Guarded by `tests/test_no_bare_sum.py`.

**19. A probe asked where the answer is already known.** Distinct from
the non-discriminating probe (fault 12) but the same family. The
commissioning checkup called `compliance_tripped()` at tier 2, with the
output **off** - where False is the honest answer, and where a method
that always returns False, or always returns None, passes exactly as
well as a correct one. Thirty lines later the same instrument was riding
its voltage limit into an open circuit and nothing asked it again. Ask
at the moment the answer is known *and known to be the interesting one*;
an assertion made where the boring answer is correct proves nothing.
Fixed by `_check_compliance_reported()` in `core/checkup.py`, and by
making the fakes compute compliance from state - two of them returned a
hardcoded `"false"`, so the new probe passed against fakes that could
not have said otherwise.

**20. A diagnostic tool with the fault it diagnoses.**
`tools/scpi_console.py` decided which lines produce a reply by looking
for `?`. TSP has no query punctuation - a 2600B answers when the script
calls `print()` and stays silent otherwise - so every `print(...)` was
sent as a write. The instrument still generates the reply, so it sits in
the output buffer and the next real query reads the *previous* line's
answer: every result after it off by one, silently, each looking
plausible. The console had therefore never been usable against the TSP
instruments, and the fault was found only because a TSP probe script was
written for the first time. Tools that produce evidence need the same
scrutiny as the code they produce evidence about.

**21. Asking about the wrong quantity.** The B2901A's
`compliance_tripped()` read `:SENS:CURR:PROT:TRIP?` unconditionally.
Compliance is always on the quantity you are *not* sourcing - source
current and a voltage limit clamps you - so that question is right only
when sourcing voltage. Sourcing current, the current protection is
genuinely untripped and the instrument answered `0` **honestly, to the
wrong question**. Van der Pauw and Hall both source current, so on those
two experiments the flag was False whatever the instrument was doing:
not a silence, a wrong reassurance.

Nothing could have caught it from the outside. The tests set a
`tripped` flag the fake returned regardless of mode, so a driver asking
either question passed; and the checkup only asked with the output off.
It took the clamping probe on a real instrument riding a 1 V limit into
an open circuit - `:MEAS?` reporting +1.000077 V while the driver said
False.

The fix reads `:SOUR:FUNC:MODE?` and asks about the matching
protection, rather than tracking the mode locally: a remembered copy is
one reset or one front-panel press from being wrong, and being wrong
here produces a confident False. Called once per sweep, so the extra
query costs nothing.

Two fake defects fell out of it, both worth more than the bug:

* The fake answered the current trip in either mode, so it could not
  distinguish a correct driver from this one. It now computes
  compliance from state - level, resistance and the limit that was set.
* `_write` matched `:SOUR:FUNC:MODE` including the query form, so
  **asking** what was being sourced silently rewrote the answer to
  voltage. A fake that mistakes a question for a command corrupts the
  state the test then asserts against.

The `resistance` a fake models was a module constant, which is why the
clamping probe could never be reached for this driver in tests. It is a
constructor argument now, and the B2901A is covered alongside the two
TSP drivers.

---

## The Van der Pauw → Hall handoff — an interface deleted (Wave 5c)

Not a deviation from an original. There *was* no original: the two
notebooks were separate programs and the sheet resistance moved between
them by being read off a screen and typed into a box. What follows is
recorded here because it changes what a saved Hall file means, which is
the first reason this document exists.

### What changed

Van der Pauw wrote `<sample>_vanderpauw.csv`; Hall's **Load from
VdP...** button opened that file, parsed the `# Rs_ohm_per_sq:` header
line, and recorded the file path as `# Rs_source:` in its own saved
data. `core/vdp_result.py` was the parser.

That file is now the *record* of a measurement and not an interface
between two parts of the software. The sheet resistance crosses in
memory as the `DerivedResult` that produced it, and a saved Hall file
says instead:

```
# input_sheet_resistance_from: res-20260813-a1b2c3d4 (vdp_sheet_resistance:1,
#     runs: vanderpauw-0001-... vanderpauw-0002-... ...)
```

**What this buys.** A file path is not provenance. It names a location,
and locations get renamed, moved, copied into a folder called `old`, and
overwritten by the next session's save. The result id and the run ids
name the measurement itself, and they stay true whatever happens to the
filesystem.

**What it costs, stated plainly.** A Van der Pauw run measured last week
can no longer supply a Hall run today. That was decided rather than
overlooked: the two are one session on one mounted sample with the same
contacts, and there is never a Monday Van der Pauw and a Tuesday Hall.
Keeping the CSV path as a fallback would have left two routes to one
number, which is the failure this codebase is built around — they drift,
and the one that drifts is the one nobody is watching.

**Reading old files.** Nothing reads `# Rs_source:` any more, but old
files still carry it and it still means what it meant. A Hall file with
`Rs_source` came from before Wave 5c; one with
`input_sheet_resistance_from` came after. Neither spelling appears in
both.

### Two things found while building it

**The sample-name mismatch warning could never fire.** The plan was a
warning at the transfer and a refusal at the calculation. The warning
turned out to be unreachable: Van der Pauw's staleness signature
includes the sample name, so renaming the session strip makes its result
stale, and a stale result is refused at the transfer before any mismatch
check runs. The behaviour is therefore *stricter* than designed — a
refusal, not a warning — and the dead check was deleted rather than left
in. A check that cannot fire is worse than no check: it teaches whoever
reads the code that the case is handled by *it*, and nobody looks there
again when the rule that actually handles it changes.

**A test that would have passed either way.** The first version of the
mixed-sample guard measured Hall's own runs before renaming the sample,
so the pre-existing source-run check refused the calculation on its own
and the new upstream check was never exercised. Confirmed by deleting
the new check and watching the test stay green. The voltages are typed
rather than copied now, so the carried-over sheet resistance is the only
thing that can carry the old sample into the refusal. Third time this
project has shipped an assertion that was true whether or not the code
worked; the pattern each time was a test written from the *intent* of a
change rather than from what would distinguish it.

### A third thing found, after CI

**The reminder under the sample box cost 20 vertical pixels, and there
were only 10 to spend.** Written as its own row on the session strip, it
passed every test on the development machine and failed Ubuntu CI on
`test_layout.py` — 1010 px against a 1000 px budget, and 864 against
860 folded. The runner's font metrics are larger, so the combined window
was already within 10 px of the tripwire before this wave touched
anything.

Two things worth keeping from it.

The reminder now sits *beside* the sample box rather than under it, and
costs nothing: the window is back to the base commit's 914 × 1456 open
and 800 folded, measured, not assumed.

More usefully, `test_layout.py` could only ever have caught this on a
machine whose fonts were big enough — it reported a real regression as a
difference between machines, and on a slightly smaller font it would
have reported nothing at all while the window grew. So the specific
failure has a structural guard of its own now
(`test_the_session_strip_stays_one_row_tall`): whatever goes on the
strip goes beside what is there, not underneath it. That one fails
identically everywhere. The pixel budget stays as the tripwire for
"this got a lot bigger"; it is not a good guard for "this got slightly
bigger on some machines".

**The headroom itself is an open question, not something this wave
fixed.** Ten pixels under a budget described in its own docstring as
"deliberately loose" means the next addition to any panel fails CI
whatever it is. Either vertical space gets reclaimed or the budget gets
revisited, and both are their own patch.

### Open, and deliberately not fixed

**One sample label covering two physical coupons defeats §16 entirely.**
The label typed on the session strip is what `core/identity.py` mints a
sample identifier from. Two different coupons measured under one name
are one `sample_id`, so nothing is ever mixed as far as every check in
the suite is concerned — and a Van der Pauw sheet resistance from the
first would carry silently onto the second, with every number looking
right.

`SampleRegistry.new(label)` exists precisely for this. It mints a
distinct identifier under an unchanged label, and nothing calls it.

Wave 5c decided a line of text under the sample box was the
proportionate answer, on the stated grounds that bench labelling
practice is disciplined. That is a judgement about people, not about
software, and it is the kind that stops being true quietly. If a result
is ever suspected of belonging to the wrong coupon, the fix is a "New
sample" button on the session strip calling `samples.new()` — not more
wording.

---

## The sample summary — a file that may replace itself (Wave 5c-ii)

The first file in the suite that can overwrite a previous version of
itself. Recorded here because that breaks a rule the rest of the
codebase holds to without exception, and because a summary can go
*backwards* without looking damaged — which is exactly the plausible-but-
wrong-artefact failure this project exists to avoid, one level up from a
plausible-but-wrong number.

### Why it is allowed to overwrite at all

Every data CSV goes through `unique_filename` and auto-suffixes, so no
measurement can ever be lost. The summary is derived: every number in it
is also in the CSV headers. Delete every summary in a folder and nothing
is lost but the convenience of not reading headers. That is a genuinely
different category from a data file, and it is the whole justification —
it would not be defensible for anything that held a reading.

### The failure it could still cause, and the guard

VdP and Hall both measured, summary complete. A week later, one quick
VdP re-run under the same name saves, and the summary is regenerated with
Hall marked "not calculated". It now looks identical to a sample that was
never Hall-measured.

Two things stop this being silent. The explicit `not calculated` row
means a part-finished summary is visibly part-finished rather than
looking whole. And the pre-flight asks, once, at the first run under a
name that already has files, whether this session's summary may replace
the old one — so the overwrite is a decision, not an accident. The
question is really an early "you already have data under this name here"
warning: caught at the first run it costs one dialog, caught after the
runs it is a tangle of two groups sharing a name, because a committed run
carries the identity it was measured under and renaming the box does not
change that.

### What was nearly wrong

**The re-arm trace wiped valid decisions.** The shared sample-name
variable's trace fires on *every* write, including a programmatic re-set
to the value already there — which panels and refreshes do incidentally.
The first version re-armed on all of them, so an incidental write between
the run (which chose "overwrite") and the save turned the decision back
into a suffix, and the save quietly wrote `_summary_1` instead of
replacing the file the operator meant to replace. The re-arm now compares
against the last `(sample, folder)` it acted on and ignores no-op writes.
Found by mutation; it is the kind of bug that produces a wrong file with
no error and no wrong number.

**The all-empty guard was untested.** `save_runs` only calls the summary
writer when its own tab has a calculated result, so the writer's "write
nothing when nothing is calculated" branch was never reached by the save
path and a mutation deleting it survived. The writer is called per sample
and has to defend itself regardless of who calls it, so it has its own
direct test now.

### The prompt hung the test suite

Worth recording because the rule it broke was already written down.

The first version of the collision question was a hand-rolled `Toplevel`
with `grab_set()` and `wait_window()` - three buttons saying what they
actually do, rather than Yes/No/Cancel. It was also unstubbable. Every
GUI test in this suite neutralises dialogs by monkeypatching the
`messagebox` module inside the module under test, and a window built by
hand goes round that seam entirely.

The consequence was not a failure but a *hang*: any headless test that
pressed Run while the save folder happened to contain a file matching the
sample name blocked forever, with the previous test's output already
printed and looking like a pass. `HANDOFF.md` has had "modal dialogs
block headless tests forever" in it since Wave 4.

It survived review here because the container's home directory was empty,
so the prompt never fired. It surfaced on a real machine, where it had a
`sample_*.csv` sitting in home.

Two changes, because either alone leaves a hole:

- The question now goes through `messagebox.askyesnocancel`, so every
  existing stub intercepts it. The button labels are the price; the
  message text carries the meaning instead. `askyesnocancel` was added to
  the four test files that spell their recorder's methods out by hand
  rather than using `__getattr__`.
- `tests/conftest.py` points `expanduser("~")` at a throwaway directory
  for the whole suite. `LabApp` defaults its save folder to the user's
  home, which is right in production and wrong in a test - the suite was
  reading, and could in principle have written to, a directory it does
  not own. Latent until this wave gave the run path a reason to look at
  the folder.

The structural guard is `test_the_collision_prompt_uses_the_messagebox_seam`,
which reads the method's source and fails if it builds a window or waits
on one. Asserted that way rather than by trying to detect a hang, because
a hanging test reports nothing - which is what made the original so
unpleasant to find.

### Old files

Nothing about existing CSVs changes. Summary files simply did not exist
before this wave; a folder either has them or does not.

## Wave 6a — the IV standby/sweep contract, and sweep ownership

No original script to port here: the sequencing decisions below were taken from
the review (§8, §19, §20) and from the instrument manuals, and each was signed
off before the code was written. Recorded in the same deviation-ledger form as
the B2901A's B1–B7 and the 2635B's D1–D13.

| # | Decision | Status |
|---|---|---|
| W6-1 | Stop discards the whole run, completed cycles included. IV was the only experiment where the sweep in flight was kept. | signed off |
| W6-2 | The OFF button is removed from IV. Stop is the only de-energise path, and the worker de-energises on the thread that owns the session. | signed off |
| W6-3 | A standby whose source function differs from the sweep's is **allowed**, with a dialog explaining that the sample will be de-energised at every cycle boundary. Not refused: it is a legitimate thing to want. | signed off |
| W6-4 | The pre-sweep settle runs through `run.sleep()` and is cancellable. | signed off |
| W6-5 | The 2450 range finding is recorded in `HANDOFF.md` and the driver is left untouched — no bench access. No console warning. | signed off |
| W6-6 | Where the standby and sweep functions match, no source-function command is sent at the boundary and the bias is continuous. Where they differ, the output is taken down deliberately for the change. | signed off |
| W6-7 | All configuration precedes every output-on transition, in every experiment. Written up as house rule 12. | signed off |

Withdrawn: **W6-1a** proposed a `cycles_completed` column so a stopped periodic
run could not be mistaken for a short completed one. W6-1 makes partial files
impossible, so the column would have been constant. Dropped rather than kept as
decoration.

### What the manuals would not answer

Three command references were read looking for one fact — whether a
source-function change drops the output — and none of them states it:

* Keithley 2450, `:SOURce[1]:FUNCtion[:MODE]` (reset default `VOLT`)
* Keysight B2901A, `[:SOURce]:FUNCtion:MODE` (reset default `VOLT`)
* Keysight B2901A, `:OUTPut[:STATe]` (default `OFF`) — parameter and query only

The design therefore does not depend on the answer; see house rule 12. An
oscilloscope check of the actual output transitions is an open item for a bench
session.

Useful facts that *were* settled:

* B2901A compliance defaults: `:SENS:CURR:PROT` **100 µA**, `:SENS:VOLT:PROT`
  **2 V**. These are the `DEFault` parameter values; the manual does not state
  outright that `*RST` lands on them. **Unverified against hardware** — two
  bench queries (`*RST`, then each `?`) would settle it, and it is the number
  protecting a biased sample when nothing sets it.
* B2901A measurement autorange resets **ON** for both current and voltage, so
  the driver's explicit `:SENS:...:RANG:AUTO OFF` before a manual range is
  consistent with the reset state, and `set_*_range(None)` restores it.
* B2901A source level, if the output is on, is applied immediately — which is
  why re-asserting a standby bias mid-run needs no output cycle.
* A manual source range caps the level that can be set (2450 and B2901A both).
  This is the same shape as deviation 15/21 on the U2722A. Watch item, not yet
  acted on.

### Sweep ownership — review §20

`BaseSMU`'s software sweep kept its state in attributes on the driver, and
`start_linear_sweep()` rebound all of them without joining the previous worker.
The worker resolved those attributes *at append time*, so a sweep still running
when the next one started appended its points into the new sweep's lists and
kept stepping the source underneath it. Demonstrated in
`tests/test_sweep_ownership.py`: against the old code the first sweep's buffer
comes back as `[100.0, 1.0, 2.0, 3.0, 4.0]` — the second sweep's opening level
inside the first sweep's data. It fits a line without complaint.

Each sweep now owns a `_SoftwareSweep` record: private storage, stop event,
terminal event, thread, and an id that is never reused. The worker closes over
its own record, so cross-contamination is impossible by construction rather than
by discipline.

**Contract change, and it caught four drivers.** `abort_sweep()` used to return
nothing; it now returns whether anything can still source. `None` is falsy, so
an un-updated driver would have made every sweep record a spurious "the worker
did not stop" error. The dummy, 2611A, GSM-20H10 and miniSMU overrides were all
updated, and `test_sweep_ownership.py` now checks the whole registry so the
fifth cannot be missed.

## Bench answers, 2026-08-14 — 2611A, 2635B, GSM-20H10

Run with `tools/bench_probes.py` against a 10 kΩ load. Every probe carried a
control step; the controls are quoted below because a result without its
control is an opinion.

### D14 is closed: `print()` and `printnumber()` do not differ

Both instruments, at reset:

```
print(format.asciiprecision)   ->  6.00000e+00
print(1/3)                     ->  3.33333e-01
printnumber(1/3)               ->  3.33333e-01
```

and after `format.asciiprecision = 16` (control: the attribute read back as
`1.600000000000000e+01`, so the write took):

```
print(1/3)                     ->  3.333333333333333e-01
printnumber(1/3)               ->  3.333333333333333e-01
```

**They are identical.** The open question of whether `asciiprecision` governs
`print()` as well as `printnumber()` is answered: it governs both. D14 needs no
further work and the driver's `ASCII_PRECISION = 16` is confirmed necessary and
sufficient.

On a real reading through 10 kΩ at 1 V:

| | at reset precision | at 16 |
|---|---|---|
| 2611A | `1.00393e-04` | `1.003929428406991e-04` |
| 2635B | `1.00411e-04` | `1.004091536742635e-04` |

### Which stored data this affects — narrower than it first looks

Both drivers already write `format.asciiprecision = 16` in their reset
sequence (`keithley_2611a.py`, `keithley_2635b.py`). The probe measured the
instrument straight after `*RST`, i.e. *before* a driver had configured it — so
what it confirms is that the existing correction was necessary and works, not
that live data is truncated.

The correction landed in `18a36a2` (Wave 5, 2026-08-11). **2611A data taken
before that date was truncated to six significant figures.** Later data was
not, and the 2635B has no data older than its driver.

Six figures is about 5 ppm — irrelevant to an IV resistance fit. It is not
irrelevant to Hall: at a raw reading near 1 V, six figures quantises at 10 µV,
which can exceed V_H itself when V_H is recovered by subtracting nearly-equal
numbers. **The population worth revisiting is pre-2026-08-11 Hall runs on the
2611A, and nothing else.**

### The GSM-20H10 does not accept `:ABORt`

```
:NOSUCHCOMMAND   ->  -113: Undefined header      (control: the queue reports)
:ABOR            ->  -113: Undefined header      <- rejected
:TRIG:CLE        ->  []                          (control: the queue drains)
```

Settled, not "genuinely unclear" as the driver docstring had it. `:TRIG:CLE` is
the correct and only documented way to stop a sweep on this model. The control
matters here: an empty queue after `:ABOR` would have been ambiguous on its own,
because a queue that never reports looks the same as acceptance.

### A source-function change does NOT drop the output on TSP

2611A and 2635B, both:

```
print(smua.source.output)   ->  1.00000e+00     (control: before the change)
smua.source.func = smua.OUTPUT_DCAMPS
print(smua.source.output)   ->  1.00000e+00     <- survives
```

So the 2400 family's behaviour (deviation 48) does **not** generalise. This does
not change the Wave 6 design and should not: the deliberate output-down/up
sequence is what makes the transition identical across the fleet, and the
B2901A and 2450 remain unanswered. What it does change is the honesty of the
note — a `bias_gap_s` on a 2611A or 2635B is a cost being chosen, not one the
instrument forces.

### 2635B ranging, all three confirmed

```
print(smua.measure.autorangei)  ->  1.00000e+00     at reset
smua.measure.rangei = 1e-6
print(smua.measure.autorangei)  ->  0.00000e+00     assignment disabled it
print(smua.measure.rangei)      ->  1.00000e-06
```

Assigning `measure.rangeY` disables autoranging by itself — **no explicit
`AUTORANGE_OFF` needed, the opposite of the B2901A**, where one was required.

And the overrange, 100 µA read on a 1 µA range:

```
print(smua.measure.i())         ->  9.91000e+37     error queue empty
```

The sentinel, with no error raised. A measure range set too small is now a
**documented** route to a sentinel rather than a hypothetical one — which makes
the sentinel handling load-bearing on this model rather than defensive.

## The range/limit ordering split — closed

Four experiments held two different orders for the same pair of calls, and
nobody had chosen either:

| Experiment | Was |
|---|---|
| Van der Pauw | range, then limit |
| Hall | range, then limit |
| Ossila 4PP | limit, then range |
| IV sweep | limit, then range |

Standardised on **range first**, which is not a preference - fault 15 /
deviation 21 already recorded the reason from the bench: on the U2722A a
compliance is clamped to the range active when it arrives, and `*RST` leaves
the smallest range selected. A limit sent before the range that has to hold it
is accepted, silently reduced, and the run proceeds against a compliance far
below the one on screen. No error, plausible numbers, wrong by the clamp ratio.

4PP and IV sweep were changed; Van der Pauw and Hall were already correct.
Both changed sites carry a comment naming the deviation, so reordering them
means arguing with the reason rather than guessing at it.

Pinned by `tests/test_range_before_limit.py`, which drives each changed
experiment through a recording proxy and inspects the resulting command order.
Ordering is not a property of any single driver method - every call can be
individually correct and the sequence still wrong - so the experiment is run
rather than its methods inspected.

Van der Pauw and Hall are not driven in that file. Their sequencing runs
through a run context and a polarity block, which needs a harness rather than
a test; Wave 6b builds that harness for the command-trace work and covers both.

**Open, and independent of this:** whether the B2901A also couples compliance
to the measurement range is still unanswered - see the outstanding B2901A
questions in `HANDOFF.md`. The ordering above is correct regardless, because
it is already proven necessary on the U2722A. A negative answer on the B2901A
would not reopen it.

## Wave 6b — command traces

Review §33. Three new test files, and one change to Van der Pauw and Hall that
the tests found.

### What was found

`test_house_rule_12.py` was written to extend the IV rule to the other three
experiments, on the expectation that they already complied — a hand-check
during Wave 6a had said so. That hand-check was wrong. It read each
`_configure` block, saw configuration followed by `output_on()`, and never
looked at what happened *after* the output went on.

Van der Pauw and Hall both re-sent `set_source_delay()` and
`set_current_range(None)` at the top of each polarity block, with the sample
live. See `HANDOFF.md`, house rule 12, for the fix and the electrical reason.

The general lesson is the one the file's own docstring makes: ordering is not a
property of any single method, so it cannot be established by reading methods.

### The two halves, and why both

**Ordering invariants** (`test_house_rule_12.py`, `test_range_before_limit.py`)
drive the real experiments through a recording proxy and inspect the resulting
command order. These are the discriminating ones — every mutation tried against
them went red, naming the offending call.

**Exact spellings** (`test_transition_traces.py`, `test_dialect_hygiene.py`)
pin what each driver actually says. An instrument sent a command from the wrong
dialect does not error usefully: it logs, ignores, and leaves the previous
setting in force. So "the output-off went out" is a weaker claim than "the
output-off went out in this instrument's dialect".

### A scope limit worth stating

`test_transition_traces.py`'s compliance-before-output-on check is **not** a
caller-ordering test, despite reading like one. The test calls the methods in
order itself, so the trace follows automatically. A mutation round showed this
and the docstring now says it outright.

What it does catch is a driver that *defers* configuration — batching writes
and flushing them after the output-on. Proven by mutating the B2901A to hold
its compliance write until `output_on()`, which turns it red. Caller ordering
is `test_house_rule_12.py`'s job.

### Dialect hygiene

Matching SCPI mnemonics as substrings was the first attempt and was wrong: TSP's
`smua.source.func` contains "sour", so every TSP driver was flagged as speaking
SCPI. Mnemonics are now anchored at the start of the command, with the leading
colon optional — the B2901A sends `:SOUR:VOLT` and the GSM-20H10 and U2722A
send `SOUR:VOLT`, both valid and both in use here.

Confirmed to fail in both directions: a SCPI line planted in the 2611A and a
TSP line planted in the B2901A are each caught and named. A coverage check
fires if a driver has no declared dialect — without it, removing a driver's
entry moved it from checked to silently skipped.

## Wave 6d-i — the ranging contract

### The fault

Two different things were both called "range", and one method name did for both.

The **source range** is the size of the container being poured from: it caps the
level that can be set, and one too small clamps the level — fault 4, no error,
a plausible number wrong by the clamp ratio. The **measure range** is the size
of the measuring jug: one too small overranges into a sentinel, one too large
throws away resolution.

`set_current_range()` meant:

| Driver | What it sent |
|---|---|
| 2450, U2722A | source range |
| 2401, 2611A, 2635B, GSM-20H10, B2901A | measure range |
| miniSMU | one knob serving both |

Two source, five measure, one combined — and `SMULimits.current_ranges` has been
describing *source* capability all along, confirmed against the B2901A source
output range tables. One range list standing in for two: fault 16, in a form
nobody had spotted on this instrument.

### Why nothing had gone wrong yet

Van der Pauw, Hall and 4PP all source current and measure that same current, so
`abs(level_a)` is the correct argument under both readings. The sourced and
measured quantities are the same number and both interpretations give the right
answer.

That is a coincidence, not a design, and it holds only while every experiment
pours and measures the same litre. **An experiment letting the operator choose
to source voltage and measure voltage breaks it silently** — which is exactly
the experiment planned next, and the reason this wave exists rather than a note
recording the coincidence.

IV sweep is already the odd one out: it sources voltage and measures current, so
its `compliance`-sized argument is a measure range. Right on the five
measure-drivers, wrong on the 2450 and U2722A.

### The shape

`core/ranges.py` defines `RangePlan`, with all four axes required — no partial
plans. `AUTO` is a legal, explicit choice; saying nothing is not, because an
unstated range is one inherited from the previous run (fault 6).

The plan is declared once, before energising, which is what makes it compatible
with house rule 12. Four independent setters could be interleaved with an
output-on; a plan cannot.

Numbers are magnitudes, not range names — drivers pick the smallest range that
fits, so no experiment needs to know any instrument's range table. Numeric
strings are refused: `float("1e-3")` succeeds, so a Tk `StringVar` would flow
straight in and be coerced, which is the fault class Wave 2 existed to remove.
`bool` is refused too, being a subclass of `int` — `source_current=True` would
otherwise arrive as 1 amp.

### One-knob instruments (decision W6d-2)

The U2722A has one range per quantity serving source and measure; the miniSMU's
vendor library is the same. A plan asking for two different values is reconciled
by taking the **wider**, with a console message and a note in the returned
summary.

Wider always fails safe: a range broader than needed never clamps a source level
and never overranges a reading. The cost is resolution — a worse measurement
rather than a wrong one, and this project would rather lose a digit than gain a
plausible number that is wrong. `AUTO` beats any fixed value, since autoranging
covers everything a fixed range would.

The U2722A has no autorange at all, so an `AUTO` plan is refused there rather
than accepted and ignored — accepting it would leave the range wherever it was,
most likely the 1 µA it resets to, and clamp every level above that.

### Ledger

`INDEPENDENT_SOURCE_RANGE` and `HAS_MEASURE_RANGE` default to **True** on
`BaseSMU`, so a driver that says nothing silently claims independent ranging.
Both are therefore ledger rows, and the contract test fails on disagreement in
either direction — confirmed by claiming the U2722A had independent ranges and
watching it go red.

### Confirmed at reset

Source autorange is **ON after reset** on the B2901A, GSM-20H10 and 2401, from
the command summary tables. That removes the fault-4 risk from this wave: an
unset source range cannot silently clamp.

The 2450's hooks are written from its command reference and are **unverified
against hardware** — there is no 2450 in this lab.

### Scope

Capability only. Nothing calls `apply_ranges()` except its own tests, so every
pre-existing test stayed green and green means something: 789 passing, up from
759, with no wire change anywhere. Adoption and the deletion of the old pair are
6d-ii, where behaviour legitimately changes and a red test unambiguously means
the adoption rather than a fault in this layer.

## Wave 6d-ii — adopting the ranging contract

`set_current_range()` and `set_voltage_range()` are gone from `BaseSMU` and all
nine drivers. All four experiments and `core/checkup.py` build a `RangePlan` and
call `apply_ranges()`.

### What error 823 was actually telling us

Deviation 41 recorded that the 2401 and GSM-20H10 reject "a source-range change"
with error 823, *Invalid with source read-back on*. That wording described the
symptom from the caller's side and is misleading. The command that produced it
was `:SENS:VOLT:RANG` — a **measurement** range — sent while sourcing voltage.

The rule is:

> **You cannot set a measurement range for the quantity you are sourcing.**

On the 2400 family the measured value of the sourced quantity is read back from
the source, so it has no independent measurement range. It is meaningless on
every SMU; those two models are simply the ones honest enough to refuse.

The old design never hit it because nothing ever set a source range and the
checkup's Tier 2 was made mode-aware specifically to avoid the combination.
Adopting the four-axis plan walked straight back into it — **every one of the
four experiments had it wrong on first attempt**, including the wave written to
get ranging right. Caught by the negative assertion in `test_checkup.py` that
existed to protect deviation 41.

### `RangePlan.for_sourcing()`

Plans are now built through a constructor that takes the sourced quantity, the
magnitude being sourced, and the magnitude expected of the *other* quantity. It
fills the remaining axes, and in particular sets the measurement range of the
sourced quantity to `AUTO`, where it cannot be reached.

Unrepresentable rather than merely detectable. A validation check would have
required every caller to be tested against every instrument that enforces the
rule; a constructor that cannot express the mistake needs none.

`tests/test_range_plan.py` pins both halves: the axis rule itself, and — by
scanning `experiments/` for direct `RangePlan(` construction — that no
experiment goes around the constructor. Both confirmed to fail by mutation.

### The U2722A and AUTO

Refusing `AUTO` on a model with no autorange, as Wave 6d-i did, was wrong. It
aborted callers that are model-agnostic by design (the checkup asks every
instrument for an all-AUTO plan) and it contradicted decision W6d-2's own
reasoning. `AUTO` now selects the **widest** range the model has, with a console
note. Widest never clamps a level and never overranges a reading; the cost is
resolution, which is a worse measurement rather than a false one.

Doing nothing would still have been wrong — that leaves the range wherever it
was, most likely the 1 µA it resets to, clamping almost everything.

### The contract test

`MANDATORY` no longer names the deleted pair. It names the four per-axis hooks
instead, which is a stronger requirement: a driver can no longer satisfy the
contract while leaving an axis unreachable. `apply_ranges` is deliberately *not*
in that list — it is one shared implementation on `BaseSMU` dispatching to the
hooks, and requiring every driver to override it would put the one-knob
reconciliation logic into nine copies.

Which measure hooks a driver must implement follows its `has_measure_range`
ledger row, so a shared-knob instrument implements the two source hooks and
inherits base hooks that refuse out loud.

### A bug shipped in 6d-i, fixed here

The per-axis hooks on the 2611A and 2635B were generated with doubled braces and
emitted the literal text `{ch}.source.rangei = {amps:.6e}` instead of a command.
Nothing called them on `main`, so no measurement was affected — but it was live.
Found by `test_dialect_hygiene.py`, which is not what that test was written for
and is the second time it has caught something outside its stated remit.

### `None` is not a range

`None` is not accepted anywhere in a plan. Van der Pauw and Hall convert their
form's `None` to `AUTO` at the call site, which is where `RangePlan` insists
such conversions happen: a plan that accepted `None` would be treating the
shape of an unset variable as a deliberate choice.
