"""
Keithley 2401 SourceMeter - older 2400-series SCPI dialect.

Same family idea as the 2450 next door, but a different generation, and
the spelling differs in ways that matter. The 2450 says
`:SOUR:CURR:VLIM` for compliance; the 2400 series says
`:SENS:VOLT:PROT` - a *sense* keyword for a *source* concept, which
reads oddly until you know the history. Sending 2450 syntax to a 2401
does not raise: the instrument logs an error, ignores the command, and
carries on with the previous compliance. That is exactly the failure
this driver layer exists to prevent, and the reason the two models get
separate files rather than a shared class with `if model ==` branches.

Command set taken from the working parts of
`IV_Meas_2611A_2401_-_Long_bias_Dual_SMU.py`.

**No sweep methods here, deliberately.** The 2401 can sweep in hardware,
but the original script's attempt at it is commented out above a
working point-by-point loop, so it was evidently abandoned rather than
finished. `BaseSMU` provides the software sweep - the same
step/settle/measure loop the script ended up using - so this driver
inherits a working sweep for free. If someone later needs the
instrument's own sweep for tighter timing, add the three sweep methods
here and set `SWEEP_KIND = "hardware"`; nothing in experiments/ changes.
"""
from core.limits import SMULimits
from core.ranges import AUTO
from .base_smu import BaseSMU


class Keithley2401(BaseSMU):
    # "MODEL 2401" is what the instrument actually reports. Bare "2401"
    # is a fallback for reply strings that omit the MODEL keyword; the
    # registry prefers the longer match when both are present.
    MODEL_IDS = ["MODEL 2401", "2401"]
    DISPLAY_NAME = "Keithley 2401"

    LIMITS = SMULimits(
        max_voltage=21.0,
        max_current=1.05,
        voltage_ranges=[0.2, 2.0, 20.0],
        current_ranges=[1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0],
        # The 2401 is the 20 V member of the 2400 family - it does not
        # have the 200 V range its 2400/2410 siblings do. Declaring the
        # flat maxima is enough: unlike the 2450 there is no high-voltage
        # corner to trade against current, so a single rectangle
        # describes the whole operating region.
        power_envelope=[],
    )

    # ---- source configuration ----
    def set_source_function(self, mode):
        """Select the sourced quantity.

        **Changing the source function drops the output**, and this
        driver disables auto output-off below - so the caller must send
        `output_on()` afterwards or the next `:READ?` will hang. The
        2401's own documentation: "if auto output-off is disabled
        (:SOURce1:CLEar:AUTO OFF), then the output must be turned on
        before you can perform a :READ?".

        The hang is total and silent. `:READ?` is `:INITiate` followed
        by `:FETCh?`, and `:FETCh?` only runs once the instrument
        returns to idle after completing its source-measure operations.
        With the output off those operations never happen, so the query
        blocks until the VISA timeout and surfaces as a comms error -
        which is where two rounds of bench diagnosis went before the
        command reference explained it.
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

    def set_current_level(self, amps):
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

    def set_voltage_limit(self, volts):
        """Voltage compliance while sourcing current."""
        self.transport.write(f":SENS:VOLT:PROT {volts:.6e}")

    # ---- ranging ----
    # ---- ranging: per-axis (wave 6d) ----
    def _apply_source_current_range(self, amps):
        """Source ranging confirmed present; autorange ON at reset."""
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
            self.transport.write(":SENS:CURR:RANG:AUTO ON")
        else:
            self.transport.write(f":SENS:CURR:RANG {amps:.6e}")

    def _apply_measure_voltage_range(self, volts):
        if volts is AUTO:
            self.transport.write(":SENS:VOLT:RANG:AUTO ON")
        else:
            self.transport.write(f":SENS:VOLT:RANG {volts:.6e}")


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
        See PORTING_NOTES deviation 18 - this is a change in behaviour
        for the 2401, not just an added control.
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

        Named reset() rather than configure(): this was the only driver
        in the suite spelling it differently, so the app had no single
        name it could call and ended up calling neither.

        Note that `OUTP:SMOD HIMP` used to be sent here, pinning the
        output-off mode to high-impedance for every run. It is now a
        per-run choice from the panel and defaults to NORMal - see
        PORTING_NOTES deviation 18.
        """
        self.transport.write("*RST")
        self.transport.write("*CLS")
        self.transport.write(":OUTP:ENAB 0")     # disable the interlock line
        self.transport.write(":SYST:RSEN 1")     # 4-wire, as the rigs are wired
        self.transport.write(":SOUR:CLE:AUTO 0")

    # ---- measurement ----
    def read_error(self):
        """Pop one entry off the instrument's error queue.

        Returns (code, message); code 0 means the queue was empty. A
        failed read reports 0 as well - see BaseSMU.read_error for why.
        """
        try:
            reply = self.transport.query(":SYST:ERR?", timeout_s=3.0)
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
        nums = [Keithley2401.drop_sentinel(n) for n in nums]
        if len(nums) >= 2:
            return (nums[0], nums[1])
        if len(nums) == 1:
            return (nums[0], None)
        return (None, None)


# ---------------------------------------------------------------------
# Two things the original did that are deliberately not reproduced.
# Both are disclosed in HANDOFF.md.
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
