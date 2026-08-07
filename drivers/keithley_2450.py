"""
Keithley 2450 SourceMeter - SCPI dialect.

This is the model the Van der Pauw script was written against: its use of
`:SOUR:CURR:VLIM` is specific to the 2450/2460/2470 graphical series
(the older 2400 spells the same idea `:SENS:CURR:PROT`), which is why
that script's commands map onto this driver one-for-one.

If your VdP instrument turns out to be a different model, the fix is a
new file here plus a registry line - no experiment code changes.
"""
from core.limits import SMULimits
from .base_smu import BaseSMU


class Keithley2450(BaseSMU):
    MODEL_IDS = ["MODEL 2450", "2450"]
    DISPLAY_NAME = "Keithley 2450"

    LIMITS = SMULimits(
        max_voltage=210.0,
        max_current=1.05,
        voltage_ranges=[0.02, 0.2, 2.0, 20.0, 200.0],
        current_ranges=[1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0],
        # 2450 does 210 V at 105 mA, or 21 V at 1.05 A - not both maxima at once
        power_envelope=[(21.0, 1.05), (210.0, 0.105)],
    )

    # ---- source configuration ----
    def set_source_function(self, mode):
        if mode == "current":
            self.transport.write(":SOUR:FUNC CURR")
        elif mode == "voltage":
            self.transport.write(":SOUR:FUNC VOLT")
        else:
            raise ValueError(f"Unknown source mode: {mode!r}")

    def set_current_level(self, amps):
        self.transport.write(f":SOUR:CURR:LEV {amps:.6e}")

    def set_voltage_level(self, volts):
        self.transport.write(f":SOUR:VOLT:LEV {volts:.6e}")

    def set_current_limit(self, amps):
        """Current compliance while sourcing voltage."""
        self.transport.write(f":SOUR:VOLT:ILIM {amps:.6e}")

    def set_voltage_limit(self, volts):
        """Voltage compliance while sourcing current - the VLIM the VdP
        setup panel exposes."""
        self.transport.write(f":SOUR:CURR:VLIM {volts:.6e}")

    # ---- ranging ----
    def set_current_range(self, amps=None):
        if amps is None:
            self.transport.write(":SOUR:CURR:RANG:AUTO ON")
        else:
            self.transport.write(f":SOUR:CURR:RANG {amps:.6e}")

    def set_voltage_range(self, volts=None):
        if volts is None:
            self.transport.write(":SENS:VOLT:RANG:AUTO ON")
        else:
            self.transport.write(f":SENS:VOLT:RANG {volts:.6e}")

    # ---- sensing ----
    def set_remote_sense(self, on=True):
        self.transport.write(f":SYST:RSEN {'ON' if on else 'OFF'}")

    def set_terminals(self, which="front"):
        """2450-specific: choose front or rear terminals. Not part of
        BaseSMU because plenty of SMUs have no such switch."""
        self.transport.write(f":ROUT:TERM {'FRON' if which == 'front' else 'REAR'}")

    # ---- timing ----
    def set_source_delay(self, seconds):
        """:SOUR:DEL takes SECONDS on this family (0 to 10000 s)."""
        self.transport.write(f":SOUR:DEL {seconds:.6f}")

    HIGH_Z_OFF = True

    def set_output_off_mode(self, high_z=False):
        """HIMPedance opens the output relay; NORMal sources 0 V."""
        self.transport.write(
            f":OUTP:SMOD {'HIMP' if high_z else 'NORM'}")

    NPLC_RANGE = (0.01, 10.0)

    def set_nplc(self, nplc):
        """Integration time, set on both sense functions.

        NPLC is per measure function on this family, so setting only
        the one the current sweep mode happens to use would leave the
        other on whatever it was - and the next sweep in the other
        direction would silently integrate for a different time.
        """
        value = self.clamp_nplc(nplc)
        self.transport.write(f":SENS:CURR:NPLC {value:.4f}")
        self.transport.write(f":SENS:VOLT:NPLC {value:.4f}")

    # ---- output ----
    def output_on(self):
        self.transport.write(":OUTP ON")

    def output_off(self):
        self.transport.write(":OUTP OFF")

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

        The reply format depends on what's in the instrument's read-back
        list; the VdP setup returns voltage and current, so this parses
        the first two numbers it finds and treats them in that order.
        Returns (None, None) if the reply can't be parsed.
        """
        reply = self.transport.query(":READ?", timeout_s=timeout_s)
        return self._parse_reading(reply)

    @staticmethod
    def _parse_reading(reply):
        """Pull the leading numbers out of a :READ? reply.

        Kept identical to the original VdP parsing: split on comma (or
        whitespace), coerce each field to float, strip stray characters
        on anything that won't convert cleanly, then take the first two
        numbers as (voltage, current).
        """
        if not reply:
            return (None, None)
        sep = "," if "," in reply else None
        parts = reply.split(sep) if sep else reply.split()
        nums = []
        for p in parts:
            try:
                nums.append(float(p))
            except ValueError:
                stripped = "".join(ch for ch in p if (ch.isdigit() or ch in ".-+eE"))
                try:
                    nums.append(float(stripped))
                except ValueError:
                    pass
        if len(nums) >= 2:
            return (nums[0], nums[1])
        if len(nums) == 1:
            return (nums[0], None)
        return (None, None)
