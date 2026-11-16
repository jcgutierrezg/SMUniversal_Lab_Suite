"""
The multimeter contract - a fourth sibling of `BaseSMU`, `BaseLoad` and
`BaseSupply`.

A bench multimeter reads a quantity and sets nothing. By the test in
`docs/architecture/devices.md` - *does it carry the measurement?* - it
is a driver whenever its reading is the measurement, as a voltmeter
across the sense corners of a film is. But it has no operating point at
all, and that decides what it may be used for:

  * **Nothing to source, nothing to switch on.** There is no level, no
    compliance, no output relay. A shutdown is a write that has nothing
    to do, so it always succeeds - which is the opposite of every other
    fleet, where a shutdown is the one thing that must not fail open.
  * **One function at a time.** A meter reads DC volts *or* current *or*
    resistance, as configured. `measure()` keeps the shared `(volts,
    amps)` shape so nothing above `drivers/` learns it is holding a
    meter, and fills only the quantity the meter is set to read.
  * **Its input is part of the circuit.** A voltmeter's input resistance
    is in parallel with whatever it is measuring, so it is a setting
    that changes the reading, and it is read back like one.

Why it is not a `BaseSMU`, a load or a supply
---------------------------------------------
Every one of those contracts is mostly about setting an operating point,
and a meter answers none of those questions. The Keithley 487 joined
the SMU fleet because it answers every question of the voltage half;
this answers no half, so a fleet of its own is the honest shape - the
same reason a load was not filed as an SMU (see
`drivers/base_instrument.py`).

`base_instrument.py` is deliberately not touched by this file. The
source methods it declares abstract are implemented here as refusals,
so the shared base - and the commissioning record of every other
instrument - stays as it was.

By invitation, and nobody has invited it yet
--------------------------------------------
Every experiment in the suite has one role, `source`, and reads both
quantities off the instrument in it. A meter cannot fill that role, but
two experiments would accept one on declarations alone: IV sweep and
Fixed Source state no `ROLE_REQUIRES`, because an electronic load has
to pass them. So a meter declares `ROLE_CAVEATS`, and no experiment's
`ROLE_ACCEPTS` lists it: every window refuses it at Connect, with the
caveat's text as the reason.

Strictly that is a capability ("cannot set an operating point") rather
than a caveat ("can, but badly"), and it would be one if declaring it
did not mean editing `BaseInstrument`. It moves there at the next round
that touches the shared base anyway - see `docs/open/technical-debt.md`.
The role a meter is *for* - most likely a voltmeter beside an SMU in
the four-contact tabs - arrives as a role of its own, not as an
invitation into `source`.
"""
from smuniversal_lab_suite.core import readback as _readback
from smuniversal_lab_suite.core.limits import LimitError

from .base_instrument import BaseInstrument


class BaseMeter(BaseInstrument):
    """What every multimeter in this suite implements."""

    DISPLAY_NAME = "Unknown meter"

    # ---- what a meter does not have ----
    CAN_SOURCE = False
    #: Nothing `set_source_function()` would accept.
    SOURCE_FUNCTIONS = ()
    #: What `measure()` returns a number for, as the driver configures
    #: the instrument. Voltage only until a role asks for more: the
    #: first meter here has current ranges, but none below 10 mA.
    MEASURE_FUNCTIONS = ("voltage",)
    HAS_COMPLIANCE = False
    #: DC volts is read across two terminals; there is no sense pair to
    #: switch. 4-wire is a resistance *function* on a meter, not a mode.
    REMOTE_SENSE_CONTROL = False
    FIXED_SENSE = "2-wire (a voltmeter has one input pair)"

    # ---- by invitation ----
    ROLE_CAVEATS = {
        "measures_only": (
            "It is a multimeter: it reads a voltage and sets nothing. "
            "It cannot source, so it cannot be the instrument an "
            "experiment sweeps or holds a level with."),
    }

    # ---- the integration menu ----
    #: The integration times this model accepts, in power-line cycles,
    #: ascending - or empty on a model where the setting is continuous
    #: inside `NPLC_RANGE`. A meter's integration time is usually a
    #: menu, and a value between two entries is snapped here rather than
    #: sent for the instrument to round (see `snap_nplc`).
    NPLC_CHOICES: tuple[float, ...] = ()

    #: The highest range on which the high-impedance input mode applies,
    #: in volts, or `None` on a model without one. Above it the input
    #: is the fixed divider whatever the mode says.
    HIGH_IMPEDANCE_MAX_RANGE_V = None

    #: Has the configuration readback been checked at the bench against
    #: a value the instrument was known to hold? The rule every readback
    #: in this suite follows: a query answering the number it was just
    #: handed is not evidence until something independent agrees.
    CONFIG_READBACK_TRUSTED = False

    #: `(command, code)`: something the instrument must reject, and the
    #: error it must reject it with. Read by the checkup, which sends it
    #: past the driver and requires the complaint - a clean error queue
    #: is only evidence once it has been seen to say otherwise.
    ERROR_PROBE = None

    def __init__(self, transport):
        super().__init__(transport)
        #: What this driver last sent, for the readbacks to be graded
        #: against. Not a readback itself - a front-panel press changes
        #: the truth without changing these.
        self._voltage_range = None      # None = autorange
        self._nplc = None
        self._autozero = None
        self._high_impedance = None

    # ---- sweeps: none ----
    @classmethod
    def supports_sweep(cls):
        """False: there is no level to step."""
        return False

    def start_linear_sweep(self, mode, start, stop, points, delay_s):
        raise NotImplementedError(self._sets_nothing("sweep"))

    # ---- the source half of the contract, refused ----
    def _sets_nothing(self, what):
        return (f"{self.DISPLAY_NAME} is a multimeter and sets nothing, so "
                f"it cannot {what}. Use a source-measure unit for that.")

    def set_source_function(self, mode):
        raise NotImplementedError(self._sets_nothing(
            f"be told to source {mode!r}"))

    def set_voltage_level(self, volts):
        raise NotImplementedError(self._sets_nothing("source a voltage"))

    def set_current_level(self, amps):
        raise NotImplementedError(self._sets_nothing("source a current"))

    def set_source_delay(self, seconds):
        raise NotImplementedError(self._sets_nothing(
            "wait after a source step"))

    def validate_source_point(self, current=None, voltage=None,
                              sourcing=None):
        """Refuse every operating point: there is none to reach.

        A `LimitError`, so a caller that reaches this gate gets the same
        dialog-before-anything-moves it would get for an out-of-range
        level on any other instrument.
        """
        raise LimitError(self._sets_nothing("hold an operating point"))

    def set_remote_sense(self, on=True):
        """Accept 2-wire, which is the only thing a voltmeter has, and
        refuse 4-wire rather than record a mode nothing switched to."""
        if on:
            raise NotImplementedError(
                f"{self.DISPLAY_NAME} reads DC volts across one input "
                f"pair; there is no sense line to switch.")

    # ---- output: there is none ----
    def output_on(self):
        raise NotImplementedError(self._sets_nothing("switch an output on"))

    def output_off(self):
        """Nothing to do, and nothing sent.

        Every exit path in the suite calls this on every instrument it
        holds, so it must succeed rather than refuse. Sending nothing is
        the honest implementation: a meter has no output to switch, and
        a write here would only be a command for the error queue to
        complain about at the end of the session.
        """
        return None

    # ---- configuration, implemented per model ----
    def set_voltage_range(self, volts=None):
        """Select the DC voltage range, in volts, or autorange on `None`.

        A value between two ranges takes the next one up, so the reading
        is never clipped by a range below it.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} must implement set_voltage_range().")

    def set_autozero(self, on=True):
        """Interleave a zero measurement with every reading (on), or not.

        On halves the reading rate and removes the input's offset drift;
        off is faster and drifts. A setting that changes what a reading
        means, so it is recorded with the data.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no autozero setting.")

    def set_high_impedance(self, on=True):
        """Choose the input resistance on the low voltage ranges.

        Off is the meter's fixed divider (10 MOhm on most), which loads
        the circuit by that much. On lifts it to the amplifier's own
        input on the ranges up to `HIGH_IMPEDANCE_MAX_RANGE_V`; above
        those the divider is in circuit regardless.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no input-impedance setting.")

    @classmethod
    def supports_high_impedance(cls):
        """True when the input resistance can be chosen from software."""
        return cls.HIGH_IMPEDANCE_MAX_RANGE_V is not None

    @classmethod
    def snap_nplc(cls, nplc):
        """The integration time this model will actually use for `nplc`.

        Clamped into `NPLC_RANGE` first (an out-of-range request is a
        speed preference, not a safety matter), then moved **up** to the
        next menu entry. Up rather than nearest, because the cost of the
        two errors is not the same: more integration than asked is a
        slower reading, less is a noisier one that nobody asked for.

        `None` on a model with no setting.
        """
        clamped = cls.clamp_nplc(nplc)
        if clamped is None or not cls.NPLC_CHOICES:
            return clamped
        for choice in cls.NPLC_CHOICES:
            # A hair of tolerance, so 0.2 typed as 0.2000000001 by a
            # float conversion is not pushed up a whole decade.
            if choice >= clamped * (1 - 1e-9):
                return float(choice)
        return float(cls.NPLC_CHOICES[-1])

    # ---- reading the configuration back ----
    #
    # Each returns `None` where the driver has no confirmed spelling for
    # the query - the rule every readback here follows, because an
    # unrecognised query is never answered and latches the transport.

    def read_function(self):
        """What the meter is set to measure, in its own spelling."""
        return None

    def read_voltage_range(self):
        """The DC voltage range in force, in volts."""
        return None

    def read_autorange(self):
        """True when the meter is choosing its own range."""
        return None

    def read_nplc(self):
        """The integration time in force, in power-line cycles."""
        return None

    def read_autozero(self):
        """True when autozero is on."""
        return None

    def read_high_impedance(self):
        """True when the high-impedance input mode is selected."""
        return None

    def read_terminals(self):
        """'front' or 'rear', on a model with a terminal switch."""
        return None

    def _config_readback(self, subject, expected, reader, unit,
                         matcher=None):
        supported = (getattr(type(self), reader.__name__)
                     is not getattr(BaseMeter, reader.__name__))
        return self._read_and_compare(
            subject, expected, reader, supported=supported,
            trusted=bool(self.CONFIG_READBACK_TRUSTED), unit=unit,
            tolerance=_readback.DEFAULT_TOLERANCE, matcher=matcher,
            unsupported_detail=f"{self.DISPLAY_NAME} has no confirmed "
                               f"query for its {subject}")

    def verify_nplc(self, expected):
        """Is the meter integrating for what was asked?"""
        return self._config_readback("integration time", float(expected),
                                     self.read_nplc, "PLC")

    def verify_voltage_range(self, expected):
        """Is the meter on the range that was asked for?"""
        return self._config_readback("DC voltage range", float(expected),
                                     self.read_voltage_range, "V")

    def describe_configuration(self):
        """What the meter reports about how it is reading, as a dict.

        For run metadata, once a role records it: a voltmeter reading
        is only interpretable beside its range, integration time,
        autozero and input resistance, and the terminal switch is the
        one setting software cannot make. Each value is read back, not
        remembered - `None` where it could not be asked.
        """
        out = {}
        for key, reader in (("function", self.read_function),
                            ("voltage_range_v", self.read_voltage_range),
                            ("autorange", self.read_autorange),
                            ("nplc", self.read_nplc),
                            ("autozero", self.read_autozero),
                            ("high_impedance", self.read_high_impedance),
                            ("terminals", self.read_terminals)):
            out[key] = reader()
        return out
