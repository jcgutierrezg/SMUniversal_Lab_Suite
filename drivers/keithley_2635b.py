"""
Keithley 2635B SourceMeter - TSP dialect, low-current member of the
Series 2600B family.

Written from the Series 2600B Reference Manual (2600BS-901-01 Rev. F)
with **no original lab script to port**. Nothing here is inherited from
a working routine, so every default is a decision rather than a
convention, and each one is flagged in PORTING_NOTES under "Keithley
2635B" with a D-number the user signed off individually.

Why this file is standalone
---------------------------
The 2611A next door speaks the same TSP dialect and roughly 80% of the
command text is identical, so subclassing it was on the table. It was
rejected deliberately: the two are different instruments with different
envelopes, and the family differences are not where you would look for
them. `smuX.measure.delay` is the proof - same attribute, same spelling,
and it resets to DELAY_OFF on a 2611B but to DELAY_AUTO on a 2635B. A
subclass would have inherited the 2611A's assumptions silently.

The shared-TSP-base extraction is a real refactor worth doing, but not
in the same patch as an instrument that has never been on a bench.

What this instrument is for
---------------------------
200 V, 1.5 A DC, and current *measurement* ranges down to 100 pA. It is
the high-resistance-sample box: 1 fA-class resolution is the reason to
reach for it over the 2611A, which stops at 100 nA.

**Source and measure ranges are not the same set on this model, and
this is the first instrument in the suite where that is true.** The
100 pA range is measurement-only; the lowest range it can *source* is
1 nA. `SMULimits.current_ranges` is consumed by Van der Pauw and Hall as
the sourced-level dropdown and by IV sweep as the compliance dropdown -
never as a measurement range - so it is declared as the **sourceable**
list. Putting 100 pA in it would offer an operator a Van der Pauw source
current the instrument cannot produce; it would clamp to its lowest
source range and the sheet resistance would be computed from a current
that was never sourced. No error, plausible number, wrong by the clamp
ratio.

The consequence is that the 100 pA measure range is unreachable from
this app. That is recorded in INSTRUMENTS.md rather than worked around,
because the fix is a `measure_current_ranges` field on SMULimits and
that belongs in its own wave.

Reset defaults this driver overrides
------------------------------------
TSP `reset()` is mandatory on connect, so each of these is correct only
because it is re-sent afterwards. This is where fault 6 gets paid for.

1. **The output-off state is a driven 0 V source, not a disconnection.**
   `offmode` resets to OUTPUT_NORMAL, `offfunc` to OUTPUT_DCVOLTS and
   `offlimiti` to 1 mA - so "output off" means the SMU actively sources
   0 V into the sample with 1 mA of compliance available. A
   low-impedance path, not an open circuit.

   This is the 2635B's equivalent of the B2901A's `:OUTP:ON:AUTO` trap,
   and it is worse on this model than on the 2611A: a box whose purpose
   is measuring high-resistance samples should not leave 1 mA available
   across one between runs, and a Peltier stage cycling under a shorted
   sample is exactly the case where a thermoelectric EMF has somewhere
   to go. All three are now written explicitly (D1, D2) so they are a
   recorded choice rather than whatever reset left behind.

   0 V with 1 mA is kept as the value, not changed. The alternative,
   `OUTPUT_DCAMPS`, sources 0 A and lets the terminals float to the 40 V
   `offlimitv` - worse on a high-impedance sample than a short. True
   isolation is `set_output_off_mode(high_z=True)`, which opens the
   relay.

2. **ASCII precision resets to 6 significant figures.** `print()` is
   governed by `format.asciiprecision` (confirmed in the print() page),
   and that attribute resets to 6. The Hall experiment pins
   VOLTAGE_FIGURES = 9 precisely because V_H sits under a resistive
   offset 100-1000x larger and the eight-term average recovers it by
   subtracting nearly-equal numbers; six figures put a ~0.1% floor on
   V_H before any physics. Set to 16 - the documented maximum, and a
   match for the double the instrument holds internally (D14).

   Nothing in this codebase sets this attribute anywhere else, which
   means the 2611A has been reading at 6 figures all along. That is a
   separate wave and a separate manual; it is flagged in PORTING_NOTES
   rather than fixed here.

3. **`measure.delay` resets to DELAY_AUTO on this model** (-1), where
   the 2611B/2612B/2614B reset to DELAY_OFF (0). DELAY_AUTO inserts a
   current-range-dependent settle before every current measurement,
   which on a pA-capable instrument is the box protecting the operator
   from unsettled readings. Every experiment sets the delay explicitly
   so behaviour is deterministic either way, but `set_source_delay(0)`
   is a more consequential request here than on the 2611A (D6).

4. **`measure.lowrangei` is written, not inherited.** The value is
   unchanged - 100 pA, the instrument's own default - but it is now a
   number in the driver rather than whatever reset left behind, because
   it turned out to be the single biggest lever on reading time. The
   bench measured 86.7 ms per reading with the 100 pA floor against
   30.2 ms with a 1 nA floor, and every millisecond of the difference
   is in the decades below 1 nA. Kept at 100 pA because that range is
   why this instrument is on the bench; see the constant's own comment
   for the trade and the numbers.

5. `autozero` (D5), `highc`, `limitp` (D8), the four autorange flags
   (D4), `sense` (D7) and `format.data` are all written explicitly.
   Several restate the documented default on purpose: a default that is
   never sent is a default nobody chose, and firmware revisions move
   them.

Two documented facts that removed guesswork
-------------------------------------------
**Ranging.** `smuX.measure.rangeY` says outright that explicitly setting
a measure range disables autoranging for that function. So a fixed range
needs no separate `AUTORANGE_OFF` first - unlike the B2901A, where
`:SENS:x:RANG:AUTO OFF` has to precede the range or the setting is
accepted and ignored (fault 11).

**Compliance.** `smuX.source.limitY` says the SMU always autoranges for
the limit setting. That is fault 15 - the U2722A's compliance silently
clamped by the active range - explicitly absent here. The same page does
impose an ordering rule: set the limit *before* turning the source on.

Line frequency is read, not written
------------------------------------
`localnode.linefreq` is nonvolatile and its page says "Affected by: Not
applicable" - reset does not touch it. So it is read once at reset and
written only if it disagrees (D10), which avoids a needless nonvolatile
write on every connect and avoids silently clearing an `autolinefreq`
somebody set deliberately.

No channel alias
----------------
The 2611A driver sends `smu = smua` once per connection and writes
`smu.` thereafter. This one writes `smua.` directly (D13). It removes a
piece of per-connection state that has to land before any other command
means anything, and it makes every command self-contained - so the tests
assert strings that read exactly like the manual page.
"""
from core.limits import SMULimits
from core.ranges import AUTO
from .base_smu import BaseSMU


class Keithley2635B(BaseSMU):
    # Confirmed on the bench 2026-08-12:
    #     Keithley Instruments Inc., Model 2635B, 4126721, 3.2.2
    # Note "Model", not "MODEL" as the 2611A sends, and a space after
    # each comma. Matching is case-insensitive so this resolves without
    # a MODEL_IDS change - recorded here because the difference is the
    # kind of thing that gets "fixed" by someone normalising the list.
    MODEL_IDS = ["MODEL 2635B", "2635B"]
    DISPLAY_NAME = "Keithley 2635B"

    # Software sweep. The TSP sweep factories almost certainly work here
    # - they are the same family the 2611A uses - but "almost certainly"
    # is how the GSM earned three bench-found deviations. Not wired
    # until this instrument has been through tools/smu_checkup.py (D12).
    SWEEP_KIND = "software"

    HIGH_Z_OFF = True               # smua.source.offmode = OUTPUT_HIGH_Z
    # 200 V is the range this bites on: the manual states the output can
    # only be turned on when the interlock line is pulled high, and that
    # after a fixture lid opens the output stays off until it goes high
    # again. Nothing in software can override it.
    INTERLOCK_ABOVE_V = 20.2

    NPLC_RANGE = (0.001, 25.0)      # manual: 0.001 to 25
    REMOTE_SENSE_CONTROL = True     # smua.sense = SENSE_REMOTE/SENSE_LOCAL

    #: Mains frequency this bench runs on. Nonvolatile on the
    #: instrument, so reset() reads it and only writes on disagreement.
    LINE_FREQUENCY_HZ = 50

    #: Significant figures for every number the instrument prints.
    #: Resets to 6, which is below what the Hall experiment needs.
    ASCII_PRECISION = 16

    #: Lowest current range autoranging may select.
    #:
    #: 100 pA is the instrument's own reset default and is kept
    #: deliberately - this is the range that makes a 2635B worth owning.
    #: It is now *written* rather than inherited, so it is a decision
    #: with a number attached instead of whatever reset happened to
    #: leave (fault 17).
    #:
    #: **It costs about two thirds of the reading time.** Measured on
    #: the bench at NPLC 0.001 with a 10 ms delay, 20 readings per
    #: figure:
    #:
    #:     100 pA floor (this default)   86.7 ms per reading
    #:     1 nA floor                    30.2 ms
    #:     1 uA floor                    30.2 ms
    #:     autorange off, fixed range    30.2 ms
    #:
    #: The entire cost is in the decades below 1 nA: raising the floor
    #: to 1 nA recovers all of it, and raising it further recovers
    #: nothing. About 20 ms of what remains is fixed front-end overhead
    #: no setting reaches. For a 200-point IV sweep that is roughly 27 s
    #: against 15 s.
    #:
    #: Raising it does **not** stop sub-nanoamp currents being read - a
    #: 10 pA current still resolves on the 1 nA range - it stops
    #: autoranging onto the 100 pA range, where the noise floor and
    #: accuracy are better below about 100 pA. Whether that matters is a
    #: property of the sample, not of the driver: at 200 V a 1 Gohm
    #: sample draws 200 nA and the floor is irrelevant, while a 1 Tohm
    #: sample draws 200 pA and it is not. Left at 100 pA because the
    #: instrument was bought for the second case; see INSTRUMENTS.md.
    MEASURE_LOW_RANGE_FLOOR_A = 100e-12

    #: Compliance available while the output is "off" in normal mode.
    #: The instrument's own default, kept deliberately and sent
    #: explicitly. Below 1 mA interferes with contact check, which this
    #: suite does not use, so it can be lowered if a sample ever needs
    #: it - see INSTRUMENTS.md.
    OFF_STATE_CURRENT_LIMIT_A = 1e-3

    LIMITS = SMULimits(
        max_voltage=200.0,
        max_current=1.5,
        voltage_ranges=[0.2, 2.0, 20.0, 200.0],
        # SOURCE ranges. The 100 pA range is measurement-only and is
        # deliberately absent - see the module docstring. Do not "fix"
        # this by pasting the manual's range table back in: that table
        # covers both directions and this list is only one of them.
        current_ranges=[1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4,
                        1e-3, 1e-2, 1e-1, 1.0, 1.5],
        # 200 V at 100 mA, or 20 V at 1.5 A - DC, not pulsed. The
        # manual's operating-boundary figures give 202 V and 20.2 V,
        # the absolute limits; the nominal figures are used here so the
        # gate refuses points the published specification does not
        # cover.
        power_envelope=[(20.0, 1.5), (200.0, 0.1)],
    )

    def __init__(self, transport, channel="smua"):
        """`channel` selects the SMU channel. The 2635B is
        single-channel ('smua'); the dual-channel 2636B adds 'smub'."""
        super().__init__(transport)
        self.channel = channel
        self._line_freq_note = ""

    # ---- reset ----
    def reset(self):
        """TSP `reset()`, then re-assert everything it clobbers.

        Order is deliberate. The output-off state goes first, so that
        the sample is never sitting under an inherited off-state while
        the rest of the configuration is sent.
        """
        ch = self.channel
        self.transport.write("reset()")

        # 1. What "output off" physically means. See docstring point 1.
        self.transport.write(f"{ch}.source.offmode = {ch}.OUTPUT_NORMAL")
        self.transport.write(f"{ch}.source.offfunc = {ch}.OUTPUT_DCVOLTS")
        self.transport.write(
            f"{ch}.source.offlimiti = {self.OFF_STATE_CURRENT_LIMIT_A:.6e}")

        # 2. Reply precision, before anything is read back.
        self.transport.write("format.data = format.ASCII")
        self.transport.write(
            f"format.asciiprecision = {self.ASCII_PRECISION}")

        # 3. Ranging and measurement configuration.
        self.transport.write(f"{ch}.source.autorangev = {ch}.AUTORANGE_ON")
        self.transport.write(f"{ch}.source.autorangei = {ch}.AUTORANGE_ON")
        self.transport.write(f"{ch}.measure.autorangev = {ch}.AUTORANGE_ON")
        self.transport.write(f"{ch}.measure.autorangei = {ch}.AUTORANGE_ON")
        self.transport.write(f"{ch}.measure.autozero = {ch}.AUTOZERO_AUTO")
        self.transport.write(
            f"{ch}.measure.lowrangei = "
            f"{self.MEASURE_LOW_RANGE_FLOOR_A:.6e}")

        # 4. Things that must be off. High-capacitance mode forces
        #    current autorange to FOLLOW_LIMIT and locks out every range
        #    below 1 uA, which would quietly cap this instrument's
        #    entire reason for existing. Power compliance overrides the
        #    V and I limits when enabled.
        self.transport.write(f"{ch}.source.highc = {ch}.DISABLE")
        self.transport.write(f"{ch}.source.limitp = 0")

        # 5. Sense mode. Restates the documented default on purpose:
        #    2-wire measures the leads as well as the sample, and a
        #    default nobody sent is a default nobody chose. Callers
        #    wanting 4-wire call set_remote_sense(True) after this.
        self.transport.write(f"{ch}.sense = {ch}.SENSE_LOCAL")

        self._sync_line_frequency()

    def _sync_line_frequency(self):
        """Read `localnode.linefreq`; write it only if it disagrees.

        Nonvolatile and untouched by reset, so writing it every connect
        would be a pointless flash write. Reading first also means a
        bench that has `autolinefreq` set deliberately is left alone
        unless it is actually wrong.

        A failure to read is not a failure to configure: NPLC still
        works, it just rejects mains hum less well. So this reports and
        moves on rather than taking the connection down.
        """
        try:
            reply = self.transport.query("print(localnode.linefreq)",
                                         timeout_s=3.0)
            present = int(float(str(reply).strip().split()[0]))
        except Exception:
            self._line_freq_note = (
                "could not read the line frequency setting")
            return
        if present == self.LINE_FREQUENCY_HZ:
            self._line_freq_note = f"line frequency already {present} Hz"
            return
        self.transport.write(
            f"localnode.linefreq = {self.LINE_FREQUENCY_HZ}")
        self._line_freq_note = (
            f"line frequency changed from {present} Hz to "
            f"{self.LINE_FREQUENCY_HZ} Hz")

    # ---- source configuration ----
    def set_source_function(self, mode):
        ch = self.channel
        if mode == "current":
            self.transport.write(f"{ch}.source.func = {ch}.OUTPUT_DCAMPS")
        elif mode == "voltage":
            self.transport.write(f"{ch}.source.func = {ch}.OUTPUT_DCVOLTS")
        else:
            raise ValueError(f"Unknown source mode: {mode!r}")

    def set_current_level(self, amps):
        self.transport.write(
            f"{self.channel}.source.leveli = {amps:.6e}")

    def set_voltage_level(self, volts):
        self.transport.write(
            f"{self.channel}.source.levelv = {volts:.6e}")

    def set_current_limit(self, amps):
        """Current compliance, used when sourcing voltage.

        The manual is explicit that the SMU autoranges for the limit
        setting, so unlike the U2722A (fault 15) this cannot be silently
        clamped by whatever range happens to be active. It also says to
        set the limit before turning the source on, which is the order
        every experiment in this suite already uses.
        """
        self.transport.write(
            f"{self.channel}.source.limiti = {amps:.6e}")

    def set_voltage_limit(self, volts):
        """Voltage compliance, used when sourcing current."""
        self.transport.write(
            f"{self.channel}.source.limitv = {volts:.6e}")

    # ---- ranging ----
    # ---- ranging: per-axis (wave 6d) ----
    def _apply_source_current_range(self, amps):
        ch = self.channel
        if amps is AUTO:
            self.transport.write(f"{ch}.source.autorangei = {ch}.AUTORANGE_ON")
        else:
            self.transport.write(f"{ch}.source.rangei = {amps:.6e}")

    def _apply_source_voltage_range(self, volts):
        ch = self.channel
        if volts is AUTO:
            self.transport.write(f"{ch}.source.autorangev = {ch}.AUTORANGE_ON")
        else:
            self.transport.write(f"{ch}.source.rangev = {volts:.6e}")

    def _apply_measure_current_range(self, amps):
        """Assigning a range disables autoranging by itself on this
        family - confirmed on the bench 2026-08-14, and the opposite of
        the B2901A, which needs an explicit OFF first."""
        ch = self.channel
        if amps is AUTO:
            self.transport.write(f"{ch}.measure.autorangei = {ch}.AUTORANGE_ON")
        else:
            self.transport.write(f"{ch}.measure.rangei = {amps:.6e}")

    def _apply_measure_voltage_range(self, volts):
        ch = self.channel
        if volts is AUTO:
            self.transport.write(f"{ch}.measure.autorangev = {ch}.AUTORANGE_ON")
        else:
            self.transport.write(f"{ch}.measure.rangev = {volts:.6e}")


    # ---- sensing ----
    def set_remote_sense(self, on=True):
        ch = self.channel
        mode = f"{ch}.SENSE_REMOTE" if on else f"{ch}.SENSE_LOCAL"
        self.transport.write(f"{ch}.sense = {mode}")

    # ---- timing ----
    def set_source_delay(self, seconds):
        """Settle time before a measurement, in seconds.

        Note that 0 means something stronger here than on the 2611A. On
        this model `measure.delay` resets to DELAY_AUTO (-1), a
        current-range-dependent settle the instrument inserts before
        every current measurement; sending 0 replaces it with no delay
        at all. That is the caller's request and it is honoured, but on
        the low current ranges it is the setting most likely to produce
        unsettled readings that still look like data.
        """
        self.transport.write(
            f"{self.channel}.measure.delay = {seconds:.6f}")

    def set_nplc(self, nplc):
        """One attribute covers both measure functions on TSP."""
        value = self.clamp_nplc(nplc)
        self.transport.write(
            f"{self.channel}.measure.nplc = {value:.4f}")

    # ---- output ----
    def output_on(self):
        ch = self.channel
        self.transport.write(f"{ch}.source.output = {ch}.OUTPUT_ON")

    def output_off(self):
        ch = self.channel
        self.transport.write(f"{ch}.source.output = {ch}.OUTPUT_OFF")

    def set_output_off_mode(self, high_z=False):
        """Choose what "off" physically means.

        Normal off is a driven 0 V source with the compliance set in
        reset(); high-Z opens the output relay and disconnects the
        sample entirely.

        The manual offers a second route to high-Z - assigning
        `OUTPUT_HIGH_Z` straight to `source.output`, which goes there
        without touching `offmode`. It is deliberately not used, so this
        suite has one way to express the idea rather than two. Worth
        knowing if it is ever wired up: reading `source.output` back
        after that assignment returns 0, not 2.
        """
        ch = self.channel
        mode = f"{ch}.OUTPUT_HIGH_Z" if high_z else f"{ch}.OUTPUT_NORMAL"
        self.transport.write(f"{ch}.source.offmode = {mode}")

    # ---- measurement ----
    def read_error(self):
        """Pop one entry off the error queue.

        `errorqueue.next()` returns four values - code, message,
        severity, node - and print() separates multiple arguments with a
        **tab**. So the reply is split on tabs, not on whitespace: the
        2611A splits on whitespace and its message field therefore
        swallows the severity and node onto the end of the text.
        Cosmetic there, and not worth carrying forward.

        Falls back to whitespace only when there is no tab at all, so an
        instrument that answers unexpectedly still gets shown to a
        human rather than guessed at.
        """
        try:
            reply = self.transport.query(
                "print(errorqueue.next())", timeout_s=3.0)
        except Exception:
            return (0, "")
        text = str(reply or "").strip()
        if not text:
            return (0, "")

        fields = [f.strip() for f in text.split("\t")] if "\t" in text \
            else text.split(None, 1)
        try:
            code = int(float(fields[0]))
        except (ValueError, IndexError):
            return (0, text)
        message = fields[1].strip().strip('"') if len(fields) > 1 else ""
        return (code, message)

    def measure(self, timeout_s=3.0):
        """One reading as (volts, amps), via TSP's matched-pair call.

        `smua.measure.iv()` takes both quantities from one conversion,
        so the V and I of a point describe the same moment. Two separate
        `measure.v()` / `measure.i()` calls would cost two apertures and
        describe two moments - which the Hall measurement cares about
        more than the IV sweep does. The 2611A wore that exact bug and
        the bench found it as a 1034 ms reading at NPLC 25.

        **The return order is current first, then voltage** - the
        manual's own wording, "returns the last actual current
        measurement and voltage measurement as iReading and vReading
        respectively". This contract is (volts, amps), so the pair is
        swapped here. Getting it wrong transposes every reading in every
        experiment while still producing plausible numbers, which is why
        it is pinned by a test with deliberately asymmetric values and
        again in tests/test_sentinel_handling.py's REPLY_ORDER.

        print() separates the two with a tab; commas are tolerated so
        that a fake or a firmware revision using them still parses.
        """
        reply = self.transport.query(
            f"print({self.channel}.measure.iv())", timeout_s=timeout_s)
        parts = str(reply or "").replace(",", " ").replace("\t", " ").split()
        nums = []
        for token in parts:
            try:
                nums.append(float(token))
            except ValueError:
                pass

        # Positionally, never by omission: dropping a value out of the
        # list would promote the current into the voltage's place.
        nums = [self.drop_sentinel(n) for n in nums]
        if len(nums) >= 2:
            return (nums[1], nums[0])
        # A lone number cannot be assigned to a quantity with any
        # confidence, so neither is claimed.
        return (None, None)

    def compliance_tripped(self):
        """Whether a configured limit is currently in control of the
        source.

        `true` means the limit function is driving the output rather
        than the source function - i.e. the instrument is clamping. The
        attribute does not say *which* limit, and the manual is explicit
        that it covers voltage, current and power alike, so a True here
        means "one of the three ceilings was reached", not necessarily
        the compliance the experiment set.

        Worth having because a sweep in compliance still produces a neat
        straight line and a convincing R-squared: the fit describes the
        limit rather than the sample.

        **An unparseable or missing reply returns None, not False.** The
        base contract draws that distinction deliberately - None is
        "this instrument cannot say", False is "everything was fine" -
        and collapsing the two would turn a silence into a reassurance.
        That is the whole reason this was left unwired until the
        attribute page was read: guessing how a Lua boolean renders
        would have produced a query that always answered "fine".

        Reading the attribute has a documented side effect - it updates
        the status model and the front-panel compliance indicator. That
        is benign here, but it is why this is a query and not something
        to poll in a tight loop.
        """
        try:
            reply = self.transport.query(
                f"print({self.channel}.source.compliance)", timeout_s=3.0)
        except Exception:
            return None
        text = str(reply or "").strip().lower()
        if text.startswith("true"):
            return True
        if text.startswith("false"):
            return False
        return None

    # ---- console note ----
    def sweep_note(self):
        """What the console says about this instrument at connect.

        Four facts an operator cannot see from the front panel, each of
        which changes how a result should be read.
        """
        parts = [
            "2635B: 200 V / 1.5 A DC, and the only SMU here that "
            "measures below 100 nA.",
            "Sources down to 1 nA; the 100 pA range is measure-only and "
            "is not reachable from this app.",
            "Software sweep (the TSP sweep factories are not wired up "
            "on this model yet).",
            "The 200 V source range needs the interlock line held high.",
            "Readings take ~87 ms: autoranging reaches the 100 pA range. "
            "Raising MEASURE_LOW_RANGE_FLOOR_A to 1 nA gives ~30 ms if "
            "the sample never draws that little.",
            'Output "off" sources 0 V with a '
            f"{self.OFF_STATE_CURRENT_LIMIT_A * 1e3:g} mA limit - tick "
            "high-Z to disconnect the sample instead.",
        ]
        if self._line_freq_note:
            parts.append(self._line_freq_note.capitalize() + ".")
        return " ".join(parts)
