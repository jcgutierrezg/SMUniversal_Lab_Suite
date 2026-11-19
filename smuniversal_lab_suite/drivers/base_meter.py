"""
The meter contract - a fourth sibling of `BaseSMU`, `BaseLoad` and
`BaseSupply`.

A bench multimeter or a picoammeter reads a quantity and sets nothing.
By the test in `docs/architecture/devices.md` - *does it carry the
measurement?* - it
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
    meter, and fills only the quantity the meter is set to read -
    `MEASURE_FUNCTIONS`, one entry: voltage on the 34401A, current on
    the Keithley 6485 picoammeter.
  * **Its input is part of the circuit.** A voltmeter's input resistance
    is in parallel with whatever it is measuring, and an ammeter's
    input can be shunted to low inside the instrument (the 6485's zero
    check). Either is a setting that changes the reading, and it is
    read back like one.

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
The role a meter is *for* - a voltmeter beside an SMU in the
four-contact tabs, or a picoammeter in series with a source - arrives
as a role of its own, not as an invitation into `source`.

Two quantities, one checkup
---------------------------
The range methods come in a pair, one per quantity (`set_voltage_range`
and `set_current_range`, each with its readback), because the two are
different settings on any meter that has both. The checkup, and
anything else that does not care which quantity a meter reads, goes
through the neutral layer instead - `measured_quantity()`,
`measure_ranges()`, `set_measure_range()` and `verify_measure_range()` -
which picks the pair `MEASURE_FUNCTIONS` names.
"""
from smuniversal_lab_suite.core import readback as _readback
from smuniversal_lab_suite.core.limits import LimitError

from .base_instrument import BaseInstrument


class BaseMeter(BaseInstrument):
    """What every meter in this suite implements."""

    DISPLAY_NAME = "Unknown meter"

    # ---- what a meter does not have ----
    CAN_SOURCE = False
    #: Nothing `set_source_function()` would accept.
    SOURCE_FUNCTIONS = ()
    #: What `measure()` returns a number for, as the driver configures
    #: the instrument - exactly one quantity. Voltage unless a model
    #: says otherwise: the 34401A has current ranges, but none below
    #: 10 mA, so it reads volts; the 6485 can read nothing but current.
    MEASURE_FUNCTIONS = ("voltage",)
    HAS_COMPLIANCE = False
    #: A meter reads across one input pair; there is no sense pair to
    #: switch. 4-wire is a resistance *function* on a meter, not a mode.
    REMOTE_SENSE_CONTROL = False
    FIXED_SENSE = "2-wire (a meter has one input pair)"

    # ---- by invitation ----
    ROLE_CAVEATS = {
        "measures_only": (
            "It is a meter: it reads one quantity and sets nothing. "
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
        self._current_range = None      # None = autorange
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
        return (f"{self.DISPLAY_NAME} is a meter and sets nothing, so "
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
        """Accept 2-wire, which is the only thing a meter has, and
        refuse 4-wire rather than record a mode nothing switched to."""
        if on:
            raise NotImplementedError(
                f"{self.DISPLAY_NAME} reads across one input pair; there "
                f"is no sense line to switch.")

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
            f"{self.DISPLAY_NAME} does not read voltage.")

    def set_current_range(self, amps=None):
        """Select the current range, in amps, or autorange on `None`.

        A value between two ranges takes the next one up, as for
        voltage. Implemented by a meter whose `MEASURE_FUNCTIONS` is
        current.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} does not read current.")

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

    def set_input_shunt(self, on=True):
        """Shunt the input to low inside the meter (on), or connect it
        to the circuit (off) - the 6485's zero check. Implemented with
        `read_input_connected`, by a model that has one."""
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no input shunt.")

    @classmethod
    def supports_high_impedance(cls):
        """True when the input resistance can be chosen from software."""
        return cls.HIGH_IMPEDANCE_MAX_RANGE_V is not None

    @classmethod
    def supports_input_shunt(cls):
        """True when the input can be shunted to low inside the meter
        (the 6485's zero check) and the driver can ask whether it is.

        A shunted input still answers every reading - with the meter's
        own offset, a plausible small number - so it is a state the
        checkup has to read back, not one it can see in the data.
        """
        return cls.read_input_connected is not BaseMeter.read_input_connected

    @classmethod
    def has_terminal_switch(cls):
        """True when the driver can read a front/rear terminal switch.
        A meter with one input connector has none to read."""
        return cls.read_terminals is not BaseMeter.read_terminals

    # ---- the measured quantity, whichever it is ----
    #
    # One layer that does not care whether the meter reads volts or
    # amps, for the checkup and for metadata. Each picks the pair of
    # methods `MEASURE_FUNCTIONS` names.

    #: Quantity -> (unit, the `LIMITS` attribute holding its ranges).
    _QUANTITY = {"voltage": ("V", "voltage_ranges"),
                 "current": ("A", "current_ranges")}

    @classmethod
    def measured_quantity(cls):
        """'voltage' or 'current': the one thing `measure()` reports."""
        quantity = tuple(cls.MEASURE_FUNCTIONS)[0]
        if quantity not in cls._QUANTITY:
            raise ValueError(f"{cls.DISPLAY_NAME}: a meter reading "
                             f"{quantity!r} is not supported")
        return quantity

    @classmethod
    def measured_unit(cls):
        """'V' or 'A'."""
        return cls._QUANTITY[cls.measured_quantity()][0]

    @classmethod
    def measure_ranges(cls):
        """The ranges of the measured quantity, ascending."""
        attribute = cls._QUANTITY[cls.measured_quantity()][1]
        return sorted(getattr(cls.LIMITS, attribute))

    def set_measure_range(self, value=None):
        """`set_voltage_range` or `set_current_range`, whichever the
        meter reads."""
        if self.measured_quantity() == "current":
            return self.set_current_range(value)
        return self.set_voltage_range(value)

    def read_measure_range(self):
        """The range in force for the measured quantity."""
        if self.measured_quantity() == "current":
            return self.read_current_range()
        return self.read_voltage_range()

    def verify_measure_range(self, expected):
        """Is the meter on the range of its quantity that was asked for?"""
        if self.measured_quantity() == "current":
            return self.verify_current_range(expected)
        return self.verify_voltage_range(expected)

    @classmethod
    def reading_of(cls, volts, amps):
        """`(reading, other)`: the measured quantity out of a
        `measure()` pair, and the other column, which a meter leaves
        None."""
        if cls.measured_quantity() == "current":
            return amps, volts
        return volts, amps

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

    def read_current_range(self):
        """The current range in force, in amps."""
        return None

    def read_input_connected(self):
        """False when the input is shunted to low inside the meter (zero
        check on), True when it is measuring the circuit. Only a model
        with such a shunt implements it - see `supports_input_shunt`."""
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

    def verify_current_range(self, expected):
        """Is the meter on the current range that was asked for?"""
        return self._config_readback("current range", float(expected),
                                     self.read_current_range, "A")

    def describe_configuration(self):
        """What the meter reports about how it is reading, as a dict.

        For run metadata, once a role records it: a voltmeter reading
        is only interpretable beside its range, integration time,
        autozero and input resistance, an ammeter reading beside its
        range and whether its input was shunted, and the terminal switch
        is the one setting software cannot make. Each value is read
        back, not remembered - `None` where it could not be asked.
        """
        out = {}
        for key, reader in (("function", self.read_function),
                            ("voltage_range_v", self.read_voltage_range),
                            ("current_range_a", self.read_current_range),
                            ("input_connected", self.read_input_connected),
                            ("autorange", self.read_autorange),
                            ("nplc", self.read_nplc),
                            ("autozero", self.read_autozero),
                            ("high_impedance", self.read_high_impedance),
                            ("terminals", self.read_terminals)):
            out[key] = reader()
        return out
