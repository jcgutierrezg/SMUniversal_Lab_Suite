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


#: A quantity this instrument can produce either way round.
EITHER = "either"
#: A quantity this instrument can only ever produce positive.
POSITIVE = "positive"
#: ...and only ever negative. In this suite's sign convention that is
#: what sinking looks like: see `polarity is in the suite's convention`
#: below.
NEGATIVE = "negative"

POLARITIES = (EITHER, POSITIVE, NEGATIVE)


@dataclass
class SMULimits:
    """Capability envelope for one instrument model.

    Named for the fleet it was written for and kept that way rather than
    renamed, because two names for one class is how two descriptions of
    one thing start disagreeing. An electronic load declares its
    envelope here too; what differs between the fleets is which of the
    optional fields below carry anything.

    `max_voltage` / `max_current` are the headline numbers. `power_envelope`
    covers the fact that most SMUs can't do both at once: a 2450 does 200 V
    at ~105 mA *or* 20 V at 1 A, not 200 V at 1 A. Each entry is a
    (max_volts, max_amps) corner of the operating region; a request passes
    if it fits inside at least one corner.

    Leave `power_envelope` empty for instruments where the flat maxima are
    the whole story.

    `max_power` is a *continuous* ceiling, not a set of corners: the
    product V x I must stay under it everywhere, which is a hyperbola
    and not a rectangle. Corners cannot express one - approximating a
    150 W limit with rectangles either forbids points the instrument can
    hold or permits points it cannot. `None` on any model where the
    corners are the whole story, which is every SMU here.

    Polarity is in the suite's convention, not the instrument's
    ------------------------------------------------------------
    `current_polarity` and `voltage_polarity` say which signs this model
    can actually produce. `EITHER` - the default - is every SMU in this
    fleet and preserves the behaviour every one of them was commissioned
    with: magnitudes are compared and the sign is not looked at.

    A one-quadrant instrument is the reason the fields exist. An
    electronic load cannot reverse its terminals and cannot source, so
    its voltage is `POSITIVE` and - because this suite reports a sink as
    a **negative** current, so that a cell measured by a load overlays
    the same cell measured by an SMU - its current is `NEGATIVE`.

    Without this, `validate_source_point` takes `abs()` of everything
    and a -0.2 V to 0.8 V sweep passes the gate on an instrument that
    physically cannot reach the first half of it. Nothing then fails:
    the load sits at its floor returning readings of the right shape,
    and the curve is wrong in the region where it was asked to do the
    impossible.
    """
    max_voltage: float
    max_current: float
    voltage_ranges: list = field(default_factory=list)   # volts
    current_ranges: list = field(default_factory=list)   # amps
    power_envelope: list = field(default_factory=list)   # [(volts, amps), ...]
    max_power: float | None = None                       # watts, or None
    current_polarity: str = EITHER
    voltage_polarity: str = EITHER

    def __post_init__(self):
        for name in ("current_polarity", "voltage_polarity"):
            value = getattr(self, name)
            if value not in POLARITIES:
                raise ValueError(
                    f"{name} must be one of {POLARITIES}, got {value!r}. "
                    f"An unrecognised value would otherwise read as "
                    f"'no constraint' and pass everything.")

    def _check_polarity(self, value, polarity, quantity, unit):
        """Refuse a sign this instrument cannot produce.

        Silent on `EITHER`, which is every SMU here, and silent on zero -
        zero has no sign, it is where every settle-to-zero path goes,
        and refusing it would stop a sweep at the one level that is
        always reachable.
        """
        if polarity == EITHER or value == 0:
            return
        if polarity == POSITIVE and value < 0:
            raise LimitError(
                f"Requested {quantity} {value:.6g} {unit} is negative, and "
                f"this instrument can only produce positive {quantity}. An "
                f"electronic load cannot reverse its terminals and cannot "
                f"source: below zero there is nothing for it to sink, and "
                f"it would sit at its floor returning readings of the right "
                f"shape for a region it never reached. Use an SMU for that "
                f"half of the sweep."
            )
        if polarity == NEGATIVE and value > 0:
            raise LimitError(
                f"Requested {quantity} {value:.6g} {unit} is positive, which "
                f"in this suite's convention means current flowing *out* of "
                f"the instrument. This one can only sink, which is recorded "
                f"as a negative current so that a sample measured here "
                f"overlays the same sample measured on an SMU. Ask for "
                f"{-abs(value):.6g} {unit} if you meant to sink that much."
            )

    def validate_source_point(self, current=None, voltage=None,
                              sourcing=None):
        """Check a requested operating point. Pass whichever of
        `current` (A) and `voltage` (V) apply.

        Magnitudes are used for the maxima, so on an instrument that can
        produce either sign - every SMU in this fleet - the sign is not
        looked at.

        `sourcing` names which of the two is being **commanded**, and
        only that one has its polarity checked. The two arguments do not
        mean the same kind of thing at a single call site: every
        experiment here passes the swept level for one and the
        *compliance* for the other, and a compliance is a bound on
        magnitude with no sign of its own.

        Getting that wrong was a real refusal, at the bench, on a
        perfectly legal run. A voltage sweep to 0.7 V with the current
        range set to 30 A refused with "Requested current 30 A is
        positive" - the polarity rule applied to a dropdown value that
        was never a request for +30 A in the first place.

        `None` checks no polarity at all. That is the conservative
        default for a caller that has not said which axis it is driving:
        the maxima and the envelope still apply, and a one-quadrant
        instrument's own level setters refuse the wrong sign anyway.

        Raises LimitError with a message meant for the user.
        """
        if current is not None:
            if sourcing == "current":
                self._check_polarity(current, self.current_polarity,
                                     "current", "A")
            i = abs(current)
            if i > self.max_current:
                raise LimitError(
                    f"Requested current {i:.6g} A exceeds this instrument's "
                    f"maximum of {self.max_current:.6g} A."
                )
        if voltage is not None:
            if sourcing == "voltage":
                self._check_polarity(voltage, self.voltage_polarity,
                                     "voltage", "V")
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

        # A continuous ceiling, checked last because it is the one that
        # bites in the middle of the operating region rather than at its
        # edges. On a solar cell that middle is the maximum power point,
        # so a run that passes every other check here can still be the
        # one that trips the instrument exactly where the measurement
        # mattered most.
        if (current is not None and voltage is not None
                and self.max_power is not None):
            watts = abs(current) * abs(voltage)
            if watts > self.max_power:
                raise LimitError(
                    f"{abs(voltage):.6g} V at {abs(current):.6g} A is "
                    f"{watts:.6g} W, over this instrument's continuous "
                    f"ceiling of {self.max_power:.6g} W."
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


#: Length suffixes as powers of ten, not as float factors. Converting
#: between two of them divides or multiplies by a whole power of ten,
#: which is the arithmetic `core.units` measured as leaving the least
#: residue: '0.18 µm' becomes 180 nm, not 180.00000000000003.
_LENGTH_EXPONENTS = {
    "nm": -9,
    "µm": -6,
    "um": -6,
    "mm": -3,
    "cm": -2,
    "m": 0,
}


def parse_length(text, unit="nm"):
    """Parse '100 nm', '1.5µm', '2 mm', '180' into a float in `unit`.

    A bare number is already in `unit`. Returns the value in `unit`
    rather than in metres because the thickness box is read in
    nanometres by the people typing into it and written back out in
    them; the conversion to SI happens once, at the caller, through
    `core.units`.

    Longest suffix first, so '5 nm' is not read as five metres with an
    'n' left over.
    """
    s = str(text).strip().replace("μ", "µ")
    target = _LENGTH_EXPONENTS[unit]
    for suffix in sorted(_LENGTH_EXPONENTS, key=len, reverse=True):
        if s.endswith(suffix):
            number = float(s[:-len(suffix)].strip())
            shift = _LENGTH_EXPONENTS[suffix] - target
            break
    else:
        number = float(s)
        shift = 0
    if shift >= 0:
        return number * 10 ** shift
    return number / 10 ** -shift


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
