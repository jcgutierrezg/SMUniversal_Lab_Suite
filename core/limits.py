"""
Instrument capability limits.

Every driver declares its hardware envelope here, so the absolute-maximum
ratings ship with the driver instead of living in whoever-wrote-the-script's
head. Two things use it:

  1. The GUI, to populate range dropdowns with values this instrument can
     actually reach.
  2. A hard gate before any run, so a setting valid on a 2611A can't be
     sent to a 2401 that would refuse or clip it.
"""
from dataclasses import dataclass, field


class LimitError(ValueError):
    """Raised when a requested source point is outside the instrument's
    capability. Caught by the app and shown to the user - it means 'this
    instrument can't do that', not 'the code is broken'."""


@dataclass
class SMULimits:
    """Capability envelope for one SMU model.

    `max_voltage` / `max_current` are the headline numbers. `power_envelope`
    covers the fact that most SMUs can't do both at once: a 2450 does 200 V
    at ~105 mA *or* 20 V at 1 A, not 200 V at 1 A. Each entry is a
    (max_volts, max_amps) corner of the operating region; a request passes
    if it fits inside at least one corner.

    Leave `power_envelope` empty for instruments where the flat maxima are
    the whole story.
    """
    max_voltage: float
    max_current: float
    voltage_ranges: list = field(default_factory=list)   # volts
    current_ranges: list = field(default_factory=list)   # amps
    power_envelope: list = field(default_factory=list)   # [(volts, amps), ...]

    def validate_source_point(self, current=None, voltage=None):
        """Check a requested operating point. Pass whichever of
        `current` (A) and `voltage` (V) apply; magnitudes are used, so
        sign/polarity doesn't matter.

        Raises LimitError with a message meant for the user.
        """
        if current is not None:
            i = abs(current)
            if i > self.max_current:
                raise LimitError(
                    f"Requested current {i:.6g} A exceeds this instrument's "
                    f"maximum of {self.max_current:.6g} A."
                )
        if voltage is not None:
            v = abs(voltage)
            if v > self.max_voltage:
                raise LimitError(
                    f"Requested voltage {v:.6g} V exceeds this instrument's "
                    f"maximum of {self.max_voltage:.6g} V."
                )

        # both given and an envelope is declared: check they fit together
        if current is not None and voltage is not None and self.power_envelope:
            i, v = abs(current), abs(voltage)
            if not any(v <= ev and i <= ei for ev, ei in self.power_envelope):
                corners = ", ".join(
                    f"{ev:.6g} V @ {ei:.6g} A" for ev, ei in self.power_envelope
                )
                raise LimitError(
                    f"{v:.6g} V at {i:.6g} A is outside this instrument's "
                    f"power envelope (usable corners: {corners})."
                )

    def nearest_current_range(self, amps):
        """Smallest declared current range that still fits `amps`, or
        None if it doesn't fit any."""
        fits = [r for r in sorted(self.current_ranges) if r >= abs(amps)]
        return fits[0] if fits else None

    def nearest_voltage_range(self, volts):
        """Smallest declared voltage range that still fits `volts`, or
        None if it doesn't fit any."""
        fits = [r for r in sorted(self.voltage_ranges) if r >= abs(volts)]
        return fits[0] if fits else None


def format_amps(a):
    """Turn 1e-4 into '100 µA' for dropdown labels."""
    return _format_si(a, "A")


def format_volts(v):
    """Turn 0.3 into '300 mV' for dropdown labels."""
    return _format_si(v, "V")


def _format_si(value, unit):
    """Shared SI-prefix formatter. Keeps dropdown labels readable
    instead of showing raw floats like 1e-07."""
    a = abs(value)
    for scale, prefix in ((1.0, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n")):
        if a >= scale:
            scaled = value / scale
            # drop the trailing .0 on whole numbers
            text = f"{scaled:g}"
            return f"{text} {prefix}{unit}"
    return f"{value:g} {unit}"


def parse_si(text):
    """Parse '100 µA', '300 mV', '100u', '0.3', '1e-4' into a float in
    base units.

    Shared by every experiment that lets the user type a level rather
    than pick one, so that '100u' means the same thing everywhere. The
    trailing unit letter is optional - a bare prefix ('100u') is read as
    micro, which is what people actually type.
    """
    s = str(text).strip().replace("\u03bc", "\u00b5")
    for prefix, scale in (("m", 1e-3), ("\u00b5", 1e-6), ("u", 1e-6), ("n", 1e-9)):
        for unit in ("A", "V"):
            token = prefix + unit
            if s.endswith(token):
                return float(s[:-len(token)].strip()) * scale
    for unit in ("A", "V"):
        if s.endswith(unit):
            return float(s[:-1].strip())
    # bare prefix with no unit letter: '100u', '5m'
    for prefix, scale in (("m", 1e-3), ("\u00b5", 1e-6), ("u", 1e-6), ("n", 1e-9)):
        if s.endswith(prefix):
            return float(s[:-len(prefix)].strip()) * scale
    return float(s)
