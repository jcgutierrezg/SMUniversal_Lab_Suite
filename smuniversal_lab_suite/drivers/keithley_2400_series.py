"""
The Keithley 2400-series SourceMeter dialect, shared by the models that
speak it.

Two SMUs in this fleet are 2400-series instruments: the Keithley 2401
(the 20 V member) and the Keithley 2400 (the 200 V one). One manual
covers both - the Model 2400 Series SourceMeter User's Manual,
2400S-900-01 - and its SCPI command reference is one reference for the
whole family. So the code that speaks it lives here once, and each
model file declares only what is its own: its identity, its envelope,
and the numbers measured on *its* unit.

**Why the measured numbers stay in the model files.** The readback
trust flags and the sub-count floor are claims about one instrument on
one bench, earned by `tools/bench_readback.py` and
`tools/bench_envelope.py`. Kept here, a model joining the family would
inherit another unit's measurements and report them as its own - fault
42 by construction. So this class holds none of them, and a model is
`unverified` and `unmeasured` until a session on that model says
otherwise.

**What membership rests on.** For the 2401, a commissioned driver: this
code ran as `drivers/keithley_2401.py` until 2026-11-18, when it was
lifted out unchanged so the 2400 could share it. For the 2400, the
shared command reference only, until its first checkup.

Same family idea as the 2450, but a different generation, and the
spelling differs in ways that matter. The 2450 says `:SOUR:CURR:VLIM`
for compliance; the 2400 series says `:SENS:VOLT:PROT` - a *sense*
keyword for a *source* concept, which reads oddly until you know the
history. Sending 2450 syntax to a 2400-series instrument does not
raise: the instrument logs an error, ignores the command, and carries
on with the previous compliance. That is exactly the failure this
driver layer exists to prevent, and the reason the 2450 has a file of
its own rather than a branch in this one.

Command set taken from the working parts of
`IV_Meas_2611A_2401_-_Long_bias_Dual_SMU.py`.

**No sweep methods here, deliberately.** The family can sweep in
hardware, but the original script's attempt at it is commented out
above a working point-by-point loop, so it was evidently abandoned
rather than finished. `BaseSMU` provides the software sweep - the same
step/settle/measure loop the script ended up using - so these drivers
inherit a working sweep for free. If someone later needs the
instrument's own sweep for tighter timing, add the three sweep methods
here and set `SWEEP_KIND = "hardware"`; nothing in experiments/ changes.
"""
from smuniversal_lab_suite.core.ranges import AUTO
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

from .base_smu import BaseSMU


class Keithley2400Series(BaseSMU):
    """The dialect. Not registered: it has no identity of its own, so
    `MODEL_IDS` stays empty and no `*IDN?` reply can resolve to it."""

    def __init__(self, transport):
        super().__init__(transport)
        # The fixed measurement range each axis was last asked for, or
        # None. Re-sent when that axis's compliance arrives - see
        # `_resend_measure_range()`.
        self._measure_ranges = {"current": None, "voltage": None}

    # ---- source configuration ----
    def set_source_function(self, mode):
        """Select the sourced quantity.

        **Changing the source function drops the output**, and this
        driver disables auto output-off below - so the caller must send
        `output_on()` afterwards or the next `:READ?` will hang. The
        2400 series' own documentation: "if auto output-off is disabled
        (:SOURce1:CLEar:AUTO OFF), then the output must be turned on
        before you can perform a :READ?".

        The hang is total and silent. `:READ?` is `:INITiate` followed
        by `:FETCh?`, and `:FETCh?` only runs once the instrument
        returns to idle after completing its source-measure operations.
        With the output off those operations never happen, so the query
        blocks until the VISA timeout and surfaces as a comms error -
        which is where two rounds of bench diagnosis went on the 2401
        before the command reference explained it.
        """
        if mode == "current":
            self.transport.write(":SOUR:FUNC CURR")
            self.transport.write(':SENS:FUNC "VOLT"')
        elif mode == "voltage":
            self.transport.write(":SOUR:FUNC VOLT")
            self.transport.write(':SENS:FUNC "CURR"')
        else:
            raise ValueError(f"Unknown source mode: {mode!r}")

        # Auto-clear pulses the output off between readings. The original
        # turns it off explicitly for both directions, which is what a
        # sweep wants: the source should hold its level between points,
        # not drop to zero and settle again.
        self.transport.write(":SOUR:CLE:AUTO 0")
        # A range remembered under the other function must not follow a
        # limit into this one: a plan for the new function says which
        # ranges it wants.
        self._measure_ranges = {"current": None, "voltage": None}

    def set_current_level(self, amps):
        self.guard_source_level("current", amps, "A")
        self.transport.write(f":SOUR:CURR:LEV {amps:.6e}")

    def set_voltage_level(self, volts):
        # The original rounded every level to 4 decimals
        # (`round(Vo + i*step, 4)`) before sending it. Not reproduced -
        # see the note at the bottom of this file.
        self.transport.write(f":SOUR:VOLT:LEV {volts:.6e}")

    def set_current_limit(self, amps):
        """Current compliance while sourcing voltage.

        2400-series spelling. `:SOUR:VOLT:ILIM` (the 2450 form) is
        silently ignored here.
        """
        self.transport.write(f":SENS:CURR:PROT {amps:.6e}")
        self._resend_measure_range("current")

    def set_voltage_limit(self, volts):
        """Voltage compliance while sourcing current."""
        self.transport.write(f":SENS:VOLT:PROT {volts:.6e}")
        self._resend_measure_range("voltage")

    #: Error codes this family logs that an output-off command cannot
    #: raise, with why - read by `confirm_output_off()`, which notes them
    #: instead of calling the shutdown uncertain. The same `824` as the
    #: GSM-20H10's, from the same re-send below: the first send of a
    #: range wider than the compliance in force is refused by design.
    #: Every other code still makes the shutdown uncertain. Seen on the
    #: 2401 (fault 48); a property of the re-send, so it holds for every
    #: model that runs it.
    ERRORS_NOT_FROM_OUTPUT_OFF = {
        824: "a measure range refused against the compliance in force, "
             "the expected first half of this driver's range re-send",
    }

    def _resend_measure_range(self, quantity):
        """Send the remembered measurement range again, now its limit is in.

        A range wider than the compliance already in force is refused
        with `824 Cannot exceed compliance range`, and the narrower range
        stays. Every experiment ranges before it limits (fault 15), so
        any run whose compliance is higher than the one already set -
        the 105 uA *RST leaves, or the last run's - measured on the old
        compliance's range. Seen 2026-09-16 on both axes of the 2401:
        1 mA asked against 100 uA read back 105 uA, and 20 V against 1 V
        read back 2.1 V.

        The same fix, for the same refusal, as the GSM-20H10's - kept
        here rather than in BaseSMU so that the instruments that do not
        refuse (the 2611A, 2635B and B2901A all accepted the wider range
        outright on the same day) keep the commissioning records taken
        against the base code they ran.

        If the new compliance is narrower than the range, the second send
        is refused too and the narrower range stands, which is right: the
        compliance is the protection. The first refusal stays in the
        error queue as a true record. Only fixed ranges are remembered,
        and source axes are never touched.
        """
        remembered = self._measure_ranges.get(quantity)
        if remembered is None:
            return
        axis = "CURR" if quantity == "current" else "VOLT"
        self.transport.write(f":SENS:{axis}:RANG {remembered:.6e}")

    # ---- ranging ----
    # ---- ranging: per-axis (wave 6d) ----
    def _apply_source_current_range(self, amps):
        """Source ranging confirmed present on the 2401; autorange ON at
        reset."""
        if amps is AUTO:
            self.transport.write(":SOUR:CURR:RANG:AUTO ON")
        else:
            self.transport.write(":SOUR:CURR:RANG:AUTO OFF")
            self.transport.write(f":SOUR:CURR:RANG {amps:.6e}")

    def _apply_source_voltage_range(self, volts):
        if volts is AUTO:
            self.transport.write(":SOUR:VOLT:RANG:AUTO ON")
        else:
            self.transport.write(":SOUR:VOLT:RANG:AUTO OFF")
            self.transport.write(f":SOUR:VOLT:RANG {volts:.6e}")

    def _apply_measure_current_range(self, amps):
        if amps is AUTO:
            self._measure_ranges["current"] = None
            self.transport.write(":SENS:CURR:RANG:AUTO ON")
        else:
            # Remembered before it is sent: it may be refused against
            # the compliance in force. See _resend_measure_range().
            self._measure_ranges["current"] = amps
            self.transport.write(f":SENS:CURR:RANG {amps:.6e}")

    def _apply_measure_voltage_range(self, volts):
        if volts is AUTO:
            self._measure_ranges["voltage"] = None
            self.transport.write(":SENS:VOLT:RANG:AUTO ON")
        else:
            self._measure_ranges["voltage"] = volts
            self.transport.write(f":SENS:VOLT:RANG {volts:.6e}")

    # ---- reading state back ----
    #
    # Every header below is the query form of a header this driver
    # already *writes*, four lines up or thirty. That is the whole
    # argument for sending them: SCPI requires a settable numeric
    # command to have a query form, and the risk this file has been
    # avoiding is a header the instrument does not have at all - an
    # unanswered query times out and latches the transport, which costs
    # a run rather than a line in a report.
    #
    # Implementing the query moved each axis from `unsupported` (a skip,
    # "nobody can ask") to `unverified` (a warn, "it answered and agreed,
    # unchecked"). Promoting one to `confirmed` takes a bench session on
    # the model in question, so the trust flags are declared in each
    # model's file, never here; see core/readback.py.
    #
    # Note what a correct range answer looks like on this family: a
    # range is reported by its **full scale**, and the 2400 series puts
    # full scale 5% above the nominal decade - `1.050000E-04` for the
    # 100 uA range. `BaseSMU.RANGE_READBACK_HEADROOM` is what stops that
    # reading as a mismatch.

    def read_current_limit(self):
        return self._read_setting(":SENS:CURR:PROT?")

    def read_voltage_limit(self):
        return self._read_setting(":SENS:VOLT:PROT?")

    def read_source_current_range(self):
        return self._read_setting(":SOUR:CURR:RANG?")

    def read_source_voltage_range(self):
        return self._read_setting(":SOUR:VOLT:RANG?")

    def read_measure_current_range(self):
        return self._read_setting(":SENS:CURR:RANG?")

    def read_measure_voltage_range(self):
        return self._read_setting(":SENS:VOLT:RANG?")

    def _read_setting(self, query):
        """One float from a settings query, or `None`.

        Not `drop_sentinel`: a *setting* coming back as the no-reading
        sentinel would be a fault to report rather than a value to
        discard. Same shape as the GSM-20H10's reader, and deliberately
        not shared with it - these are different dialects whose queries
        were confirmed at different times, and one reader would let one
        instrument's verification be read as another's.
        """
        try:
            reply = self.transport.query(query, timeout_s=3.0)
        except TransportDesynchronised:
            raise
        except Exception:
            return None
        try:
            return float(str(reply).strip().split(",")[0])
        except (ValueError, IndexError):
            return None

    #: Which protection trip reports compliance, per sourced quantity.
    #: The limit is always on the quantity you are NOT setting. The
    #: GSM-20H10 driver quotes this table out of *this* family's manual,
    #: word for word, which is why it is not a guess here.
    _TRIP_QUERY = {"VOLT": ":SENS:CURR:PROT:TRIP?",
                   "CURR": ":SENS:VOLT:PROT:TRIP?"}

    def compliance_tripped(self):
        """Whether the source is riding its compliance limit.

        Worth having because a sweep in compliance still draws a neat
        line with a convincing R-squared: the instrument was clamping,
        so the fit describes the limit rather than the sample.

        The sourced function is read from the instrument rather than
        remembered, for the reason the B2901A gives at length: a local
        copy is one `reset()` or one front-panel change away from being
        wrong, and being wrong here means a confident answer to the
        wrong question.

        `None` when the instrument cannot be asked. Silence is not a
        reassurance, and `False` would be one.

        NOT the `:READ?` status word. That reply's fifth field carries a
        Compliance bit, and across this project's whole archive it is
        set in exactly six readings - which are also the only
        current-sourcing readings in the archive. Mode and compliance
        are perfectly confounded there, so the data cannot show the bit
        means compliance rather than "sourcing current". Reading it
        would be fault 19 in its purest form: a probe that cannot
        produce a value on the wrong side of the question. The
        discriminating measurement is one current-sourcing reading into
        a load that is NOT clamping, checking bit 3 is clear, and it has
        not been made.
        """
        try:
            mode = self.transport.query(":SOUR:FUNC?", timeout_s=3.0)
            query = self._TRIP_QUERY.get(str(mode).strip().upper()[:4])
            if query is None:
                return None
            reply = self.transport.query(query, timeout_s=3.0)
            return bool(int(float(str(reply).strip())))
        except TransportDesynchronised:
            raise
        except Exception:
            return None

    # ---- sensing ----
    def set_remote_sense(self, on=True):
        """4-wire (remote) or 2-wire (local) sensing.

        The original enabled this at connect and left it there, which
        matches how the rigs are wired.
        """
        self.transport.write(f":SYST:RSEN {1 if on else 0}")

    # ---- timing ----
    HIGH_Z_OFF = True

    def set_output_off_mode(self, high_z=False):
        """HIMPedance opens the output relay; NORMal sources 0 V.

        This driver used to pin HIMPedance in reset() unconditionally.
        It is now a per-run choice from the panel, defaulting to NORMal.
        See docs/instruments/keithley-2401.md, deviation 18 - a change in
        behaviour for the 2401, not just an added control.
        """
        self.transport.write(
            f":OUTP:SMOD {'HIMP' if high_z else 'NORM'}")

    def set_source_delay(self, seconds):
        """:SOUR:DEL takes seconds on this family, as on the 2450."""
        self.transport.write(f":SOUR:DEL {seconds:.6f}")

    NPLC_RANGE = (0.01, 10.0)

    def set_nplc(self, nplc):
        """Integration time. Same spelling as the 2450 here - NPLC is
        one of the places the two generations agree."""
        value = self.clamp_nplc(nplc)
        self.transport.write(f":SENS:CURR:NPLC {value:.4f}")
        self.transport.write(f":SENS:VOLT:NPLC {value:.4f}")

    # ---- output ----
    def output_on(self):
        self.transport.write(":OUTP ON")

    def output_off(self):
        self.transport.write(":OUTP OFF")

    def reset(self):
        """Put the instrument in a known state.

        Called after connect. The original did this inline in its
        connect handler.

        Named reset() rather than configure(): the 2401 was the only
        driver in the suite spelling it differently, so the app had no
        single name it could call and ended up calling neither.

        Note that `OUTP:SMOD HIMP` used to be sent here, pinning the
        output-off mode to high-impedance for every run. It is now a
        per-run choice from the panel and defaults to NORMal - see
        docs/instruments/keithley-2401.md, deviation 18.
        """
        self.transport.write("*RST")
        self.transport.write("*CLS")
        self.transport.write(":OUTP:ENAB 0")     # disable the interlock line
        self.transport.write(":SYST:RSEN 1")     # 4-wire, as the rigs are wired
        self.transport.write(":SOUR:CLE:AUTO 0")
        # *RST discarded the ranges; re-sending a remembered one after
        # it would configure a setting nobody asked for since (fault 6).
        self._measure_ranges = {"current": None, "voltage": None}

    # ---- measurement ----
    def read_error(self):
        """Pop one entry off the instrument's error queue.

        Returns (code, message); code 0 means the queue was empty. A
        failed read reports 0 as well - see BaseSMU.read_error for why.
        """
        try:
            reply = self.transport.query(":SYST:ERR?", timeout_s=3.0)
        except TransportDesynchronised:
            raise
        except Exception:
            return (0, "")
        if not reply:
            return (0, "")
        head, _, tail = str(reply).partition(",")
        try:
            return (int(float(head.strip())), tail.strip().strip('"'))
        except ValueError:
            return (0, str(reply).strip())

    def measure(self, timeout_s=3.0):
        """Trigger a reading and parse it into (volts, amps).

        `:READ?` on a 2400 returns a five-field group per reading:

            voltage, current, resistance, timestamp, status

        The original used `MEAS?` and took fields 0 and 1, which is the
        same thing - `MEAS?` is `:CONF` followed by `:READ?`, so it
        reconfigures the instrument on every single point and undoes the
        ranging and compliance set beforehand. `:READ?` triggers a
        reading against the configuration already in place, which is
        what a sweep wants.
        """
        reply = self.transport.query(":READ?", timeout_s=timeout_s)
        return self._parse_reading(reply)

    @staticmethod
    def _parse_reading(reply):
        """Take voltage and current out of a 2400-series reply.

        Fields beyond the first two are ignored: resistance is derived,
        and timestamp and status belong to the instrument's own buffer
        bookkeeping rather than to the measurement.

        A reading in compliance still parses - the numbers are real, the
        instrument simply couldn't reach the requested level. Detecting
        that is the caller's job via the status field if it ever matters.
        """
        if not reply:
            return (None, None)
        parts = reply.split(",") if "," in reply else reply.split()
        nums = []
        for part in parts:
            try:
                nums.append(float(part))
            except ValueError:
                stripped = "".join(ch for ch in part
                                   if ch.isdigit() or ch in ".-+eE")
                try:
                    nums.append(float(stripped))
                except ValueError:
                    pass
        # No-reading sentinels become None in place. See
        # BaseSMU.drop_sentinel.
        nums = [Keithley2400Series.drop_sentinel(n) for n in nums]
        if len(nums) >= 2:
            return (nums[0], nums[1])
        if len(nums) == 1:
            return (nums[0], None)
        return (None, None)


# ---------------------------------------------------------------------
# Two things the original did that are deliberately not reproduced.
# Both are disclosed in docs/instruments/keithley-2401.md.
#
# 1. Source levels were rounded to 4 decimal places before sending:
#
#        voltage_i = round(Vo + i * step, 4)
#
#    That quantises the source to 100 µV. Harmless over ±1 V, but it
#    silently destroys a low-bias sweep: ±100 µV over 21 points asks for
#    10 µV steps and gets 3 distinct levels instead of 21, with the
#    remaining 18 points landing on duplicates. The x-axis in the saved
#    file still claims 21 evenly spaced values, so the collapse is
#    invisible after the fact. Levels are now sent at full float
#    precision.
#
# 2. `MEAS?` was used per point instead of `:READ?`. `MEAS?` is
#    shorthand for "configure, then read", so it reset the ranging and
#    compliance that had just been set up, on every point of the sweep.
#    `:READ?` respects the existing configuration.
# ---------------------------------------------------------------------
