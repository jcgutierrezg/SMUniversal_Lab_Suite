"""The Keysight B2901A driver: dialect, reset defaults, and the sentinel.

Written from the manual with no original script to port, so there is no
"does it still do what the lab's code did" check available. Every test
here instead guards a specific documented behaviour that would fail
*silently* if the driver got it wrong.

Four groups, in order of how much damage the failure does:

A. **The dialect is really this instrument's.** Sending 2400-family
   syntax to a B2901A does not raise - the B2900 has a compatibility
   mode it is not in, so a Keithley spelling is logged, ignored, and the
   previous setting stays in force. So these assert the exact strings
   *and* the absence of the other drivers' spellings. Compliance is the
   sharp case: `:SENS:CURR:PROT` here versus `:SOUR:CURR:ILIM` on a
   2450, and a sweep run with the compliance silently left at its reset
   value of 100 µA would clamp and still draw a convincing line.

B. **Three reset defaults get overridden.** `*RST` is mandatory on
   connect, so each of these is correct only because it is re-sent
   afterwards. Auto-output-on is the serious one: left enabled, the
   instrument energises its own output on `:INIT` or `:READ`, and the
   Stop-de-energises guarantee stops being true for reasons no command
   log would explain.

C. **The +9.91e37 sentinel is dropped, and dropped positionally.** It
   parses as an ordinary float. One in a sweep drags a least-squares fit
   to a meaningless slope while the R-squared still looks healthy.

D. **The sense-function spelling is resolved by asking.** The manual
   contradicts itself; the driver probes rather than guesses, and has to
   cope with either spelling being the one that works.

The instrument is faked; the driver under test is the one that would run
on the bench.
"""
import math

import pytest

from core.limits import LimitError
from core.ranges import AUTO
from core.transports.base import Transport, TransportDesynchronised
from drivers.keysight_b2901a import KeysightB2901A
from drivers.registry import driver_for_idn

SAMPLE_OHM = 220.0
IDN = "Keysight Technologies,B2901A,MY51141631,3.4.2011.1234"


class B2901ATransport(Transport):
    """A fake B2901A with a resistor across its terminals.

    `sense_func_style` decides which spelling of the `:SENS:FUNC:ON`
    argument this instrument accepts, so the probe can be exercised
    against both halves of the manual's contradiction.
    """

    def __init__(self, sense_func_style="quoted", resistance=SAMPLE_OHM):
        super().__init__()
        # Parameterised so the fake can be driven as an open circuit,
        # which is the only state where compliance behaviour can be
        # exercised. It was a module constant, so the checkup's clamping
        # probe could never be reached for this driver - and this is the
        # driver the probe caught a real bug in.
        self.resistance = resistance
        self.sent = []
        self.connected = True
        self.sense_func_style = sense_func_style
        self.enabled_functions = 6      # the reset default: all six
        self.elements = "VOLT,CURR,RES,TIME,STAT,SOUR"
        self.auto_output_on = True      # the reset default
        self.output = False
        self.remote_sense = False       # the reset default
        self.mode = "voltage"
        self.level = 0.0
        self.voltage_limit = 20.0
        self.current_limit = 1e-4
        # None means "work it out from state"; True/False force it, for
        # the tests that need a specific answer.
        self.tripped = None
        self.nan_columns = set()        # 0 = volts, 1 = amps
        self.errors = []

    def connect(self, address, **kw):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)
        upper = text.upper()

        if upper == "*RST":
            # Everything this instrument forgets on reset.
            self.auto_output_on = True
            self.remote_sense = False
            self.enabled_functions = 6
            self.elements = "VOLT,CURR,RES,TIME,STAT,SOUR"
            self.output = False
        elif upper.startswith(":OUTP:ON:AUTO"):
            self.auto_output_on = upper.split()[-1] in ("1", "ON")
        elif upper.startswith(":OUTP:OFF:MODE"):
            self.off_mode = upper.split()[-1]
        elif upper.startswith(":OUTP"):
            self.output = upper.split()[-1] in ("1", "ON")
        elif upper.startswith(":SENS:REM"):
            self.remote_sense = upper.split()[-1] in ("1", "ON")
        elif upper.startswith(":SENS:FUNC:OFF:ALL"):
            self.enabled_functions = 0
        elif upper.startswith(":SENS:FUNC:ON") and not upper.endswith("?"):
            arg = text.split(None, 1)[1] if " " in text else ""
            quoted = '"' in arg
            if self.sense_func_style == "quoted":
                matches = quoted
            elif self.sense_func_style == "bare":
                matches = not quoted
            else:
                matches = False        # an instrument that takes neither
            if matches:
                self.enabled_functions = len(arg.split(","))
            else:
                # What a SCPI instrument does with an argument it
                # doesn't accept: queue an error, change nothing.
                self.errors.append((-104, "Data type error"))
        elif upper.startswith(":FORM:ELEM:SENS"):
            self.elements = upper.split(None, 1)[1]
        elif upper.startswith(":SOUR:FUNC:MODE") and not upper.endswith("?"):
            # The `?` guard matters: `:SOUR:FUNC:MODE?` reaches here too,
            # and without it the *question* rewrote the answer - asking
            # what was being sourced set the mode to voltage, because
            # the query string contains no "CURR".
            self.mode = "current" if "CURR" in upper else "voltage"
        elif upper.startswith(":SOUR:VOLT ") or upper.startswith(":SOUR:CURR "):
            self.level = float(text.split()[-1])
        elif upper.startswith(":SENS:VOLT:PROT "):
            self.voltage_limit = float(text.split()[-1])
        elif upper.startswith(":SENS:CURR:PROT "):
            self.current_limit = float(text.split()[-1])
        elif upper.startswith(":OUTP ON"):
            self.output = True
        elif upper.startswith(":OUTP OFF"):
            self.output = False

    def _read(self, timeout_s=3.0):
        last = self.sent[-1] if self.sent else ""
        upper = last.upper()

        if "IDN" in upper:
            return IDN
        if upper.startswith(":SENS:FUNC:ON:COUN"):
            return str(self.enabled_functions)
        if upper.startswith(":FORM:ELEM:SENS?"):
            return self.elements
        if upper.startswith(":SOUR:FUNC:MODE?"):
            return "CURR" if self.mode == "current" else "VOLT"

        # Compliance lives on the quantity you are NOT sourcing: source
        # current and the VOLTAGE protection is what trips. Modelling
        # that is the whole point - the fake used to answer the current
        # trip regardless of mode, so a driver asking the wrong question
        # got a plausible "0" and looked correct.
        if upper.startswith(":SENS:VOLT:PROT:TRIP"):
            return "1" if self._clamping() and self.mode == "current" else "0"
        if upper.startswith(":SENS:CURR:PROT:TRIP"):
            return "1" if self._clamping() and self.mode == "voltage" else "0"
        if upper.startswith(":SYST:ERR"):
            if self.errors:
                code, message = self.errors.pop(0)
                return f'{code},"{message}"'
            return '0,"No error"'
        if upper.startswith(":MEAS"):
            return self._reading()
        return ""

    def _clamping(self):
        """Whether the instrument cannot deliver what was asked.

        Computed from state rather than answered with a constant: a fake
        that always says one thing cannot tell a working driver from a
        broken one.
        """
        if self.tripped is not None:
            return self.tripped
        if not self.output:
            return False
        if self.mode == "current":
            return abs(self.level) * self.resistance >= self.voltage_limit
        return abs(self.level) / self.resistance >= self.current_limit

    def _reading(self):
        """Volts and amps across the resistor, clamped, honouring the
        sentinel.

        The clamp models what `_in_compliance()` above already claims:
        an instrument riding its voltage limit holds that limit rather
        than reporting the voltage an unclamped source would have
        produced. Without it this returned 1e6 V against a 1 V limit
        into the open circuit the compliance probe uses, while the trip
        query on the same fake said the output was in compliance.
        """
        if self.mode == "voltage":
            volts, amps = self.level, self.level / self.resistance
        else:
            volts, amps = self.level * self.resistance, self.level
            if abs(volts) > self.voltage_limit:
                volts = math.copysign(self.voltage_limit, volts)
                amps = volts / self.resistance
        columns = [volts, amps]
        for index in self.nan_columns:
            columns[index] = 9.91e37
        return ",".join(f"{value:.6E}" for value in columns)


def fresh(style="quoted"):
    transport = B2901ATransport(sense_func_style=style)
    return transport, KeysightB2901A(transport)


def sent_matching(transport, fragment):
    return [line for line in transport.sent if fragment in line.upper()]


# --- A. the dialect is this instrument's ------------------------------

def test_compliance_is_sense_side_not_source_side(check):
    """The sharpest dialect difference in the whole driver.

    A 2450 sets compliance as a source limit. Send that spelling here
    and nothing raises - the command is logged and ignored, and the
    compliance stays at its 100 µA reset value. A sweep then clamps and
    still draws a clean line.
    """
    transport, smu = fresh()
    smu.set_current_limit(0.05)
    smu.set_voltage_limit(2.0)

    check("current compliance is sense-side",
          any(":SENS:CURR:PROT" in line for line in transport.sent),
          f"sent: {transport.sent}")
    check("voltage compliance is sense-side",
          any(":SENS:VOLT:PROT" in line for line in transport.sent))
    check("no 2450 source-limit spelling",
          not sent_matching(transport, "ILIM"),
          f"found: {sent_matching(transport, 'ILIM')}")
    check("no 2400 :SOUR:CURR:PROT spelling",
          not [l for l in transport.sent if ":SOUR" in l and "PROT" in l])


def test_no_licensed_compliance_keywords(check):
    """`:BOTH`, `:NEGative` and `:POSitive` need licence "SWS" and
    firmware 3.1+. A driver using them works on some B2901As and not
    others, and the failure arrives at run time on an untested unit."""
    transport, smu = fresh()
    smu.set_current_limit(0.05)
    smu.set_voltage_limit(2.0)
    for keyword in (":BOTH", ":NEG", ":POS"):
        check(f"no {keyword} keyword", not sent_matching(transport, keyword),
              f"found: {sent_matching(transport, keyword)}")


def test_source_and_range_spellings(check):
    transport, smu = fresh()
    smu.set_source_function("current")
    smu.set_current_level(1e-3)
    smu._apply_measure_voltage_range(2.0)
    smu._apply_measure_current_range(AUTO)

    check("source function via :SOUR:FUNC:MODE",
          any(line.startswith(":SOUR:FUNC:MODE CURR")
              for line in transport.sent))
    check("level via :SOUR:CURR",
          any(line.startswith(":SOUR:CURR ") for line in transport.sent))
    check("a fixed range switches auto off first",
          transport.sent.index(":SENS:VOLT:RANG:AUTO OFF")
          < [i for i, l in enumerate(transport.sent)
             if l.startswith(":SENS:VOLT:RANG ")][0],
          "auto must be off before a fixed range means anything")
    check("None asks for auto",
          ":SENS:CURR:RANG:AUTO ON" in transport.sent)


def test_levels_are_not_quantised(check):
    """Two ported originals rounded levels before sending. Invisible at
    ±1 V; at ±100 µV it collapses 21 requested points onto 3 distinct
    levels while the saved x-axis still claims 21."""
    transport, smu = fresh()
    smu.set_voltage_level(1.2345e-4)
    line = [l for l in transport.sent if l.startswith(":SOUR:VOLT ")][-1]
    check("full precision reaches the instrument",
          abs(float(line.split()[-1]) - 1.2345e-4) < 1e-12,
          f"sent {line!r}")


# --- B. reset overrides its own defaults ------------------------------

def test_reset_disables_automatic_output_on(check):
    """The instrument energises its own output on :INIT or :READ unless
    told not to. Stop de-energising is load-bearing across this suite,
    and an output that comes back on by itself leaves no command to
    trace it to."""
    transport, smu = fresh()
    smu.reset()
    check("auto output-on is off", transport.auto_output_on is False)
    check("and it is sent after the reset that re-enabled it",
          transport.sent.index(":OUTP:ON:AUTO 0") > transport.sent.index("*RST"))
    check("before anything that could energise the output",
          transport.sent.index(":OUTP:ON:AUTO 0")
          < min(i for i, l in enumerate(transport.sent)
                if l.startswith(":SENS") or l.startswith(":FORM")),
          f"order: {transport.sent}")


def test_reset_pins_the_element_list(check):
    """Reset leaves all six elements enabled. Two are wanted, and the
    reply order is the instrument's fixed one, not the order asked."""
    transport, smu = fresh()
    smu.reset()
    check("two elements requested", transport.elements == "VOLT,CURR",
          f"elements are {transport.elements!r}")
    check("ASCII format set", ":FORM:DATA ASC" in transport.sent)


def test_reset_sets_the_line_frequency(check):
    """NPLC only cancels mains hum if the instrument knows the period,
    so integration time set without this is worth less than it looks."""
    transport, smu = fresh()
    smu.reset()
    check("line frequency sent", ":SYST:LFR 50" in transport.sent,
          f"sent: {[l for l in transport.sent if 'LFR' in l]}")


def test_remote_sense_is_reasserted_not_assumed(check):
    """`:SENS:REM` resets to OFF, and the IV sweep defaults to 4-wire.
    Left alone, a Kelvin-wired rig returns 2-wire numbers that look
    entirely reasonable."""
    transport, smu = fresh()
    smu.reset()
    check("4-wire really is off after a reset", transport.remote_sense is False)
    smu.set_remote_sense(True)
    check("and the driver can turn it on", transport.remote_sense is True)
    check("with this instrument's spelling",
          ":SENS:REM ON" in transport.sent)
    check("not the Keithley :SYST:RSEN spelling",
          not sent_matching(transport, "RSEN"))


# --- C. the sentinel --------------------------------------------------

def test_sentinel_is_dropped_not_measured(check):
    """+9.91e37 parses as an ordinary float and nothing raises."""
    transport, smu = fresh()
    smu.set_source_function("voltage")
    smu.set_voltage_level(1.0)

    volts, amps = smu.measure()
    check("a normal reading survives", volts is not None and amps is not None)
    check("and is right", abs(amps - 1.0 / SAMPLE_OHM) < 1e-9)

    transport.nan_columns = {1}
    volts, amps = smu.measure()
    check("the sentinel column is dropped", amps is None,
          f"got {amps!r}")
    check("and the other column survives", volts is not None)


def test_sentinel_drops_positionally(check):
    """Losing the voltage must not promote the current into its place.

    An omitted column would shift everything left and the reading would
    come back as (current, None) - a number in the right shape, wrong by
    a factor of the resistance, and impossible to spot afterwards.
    """
    transport, smu = fresh()
    smu.set_source_function("voltage")
    smu.set_voltage_level(1.0)
    transport.nan_columns = {0}

    volts, amps = smu.measure()
    check("voltage is the dropped one", volts is None)
    check("current keeps its own value", amps is not None
          and abs(amps - 1.0 / SAMPLE_OHM) < 1e-9,
          f"got amps={amps!r}, expected {1.0 / SAMPLE_OHM}")


def test_threshold_catches_both_sentinels(check):
    """+9.91e37 is "not a number"; over-range values sit near it. The
    threshold is below both, and a real reading is never near it."""
    check("NAN sentinel", KeysightB2901A._parse_reading("9.910000E+37") == [None])
    check("over-range sentinel",
          KeysightB2901A._parse_reading("9.900000E+37") == [None])
    check("a 3 A reading is untouched",
          KeysightB2901A._parse_reading("3.000000E+00") == [3.0])
    check("a 10 fA reading is untouched",
          KeysightB2901A._parse_reading("1.000000E-14") == [1e-14])


# --- D. the sense-function probe --------------------------------------

def test_probe_resolves_either_spelling(check):
    """The manual uses both quoted and bare arguments across its
    examples. The driver asks which one this instrument acted on rather
    than sending both and being unable to say."""
    for style in ("quoted", "bare"):
        transport, smu = fresh(style)
        smu.reset()
        check(f"{style}: exactly two functions enabled",
              transport.enabled_functions == 2,
              f"got {transport.enabled_functions}")
        check(f"{style}: the driver recorded which spelling worked",
              smu._sense_func_style == style,
              f"recorded {smu._sense_func_style!r}")
        check(f"{style}: and says so on the console",
              style in smu.sweep_note())


def test_probe_confirms_by_counting(check):
    """`:SENS:FUNC:ON:COUN?` is asked, not assumed. An instrument that
    accepts the command and enables nothing is the case that matters."""
    transport, smu = fresh()
    smu.reset()
    check("the count was actually queried",
          any(":SENS:FUNC:ON:COUN" in line for line in transport.sent),
          "the probe must ask, not assume")
    check("the functions are cleared before being set",
          transport.sent.index(":SENS:FUNC:OFF:ALL")
          < min(i for i, l in enumerate(transport.sent)
                if l.startswith(":SENS:FUNC:ON ")),
          "reset leaves all six enabled, so a count taken without "
          "clearing first is true whether or not the command worked")
    check("and the count asked for is exact",
          transport.enabled_functions == 2,
          f"got {transport.enabled_functions}")


def test_probe_reports_failure_rather_than_pretending(check):
    """If neither spelling works the driver says so. With a function
    disabled every reading in that column is the sentinel, which
    `measure()` drops - so it fails as missing data, not wrong data."""
    transport, smu = fresh(style="neither")
    smu.reset()
    check("no spelling was recorded", smu._sense_func_style is None)
    check("and the console is told",
          "could not confirm" in smu.sweep_note().lower(),
          f"note was {smu.sweep_note()!r}")


# --- capability and limit declarations --------------------------------

def test_registry_resolves_the_idn(check):
    check("this driver claims a B2901A", driver_for_idn(IDN) is KeysightB2901A)
    check("but not the two-channel sibling",
          driver_for_idn("Keysight Technologies,B2902A,MY5,3.4")
          is not KeysightB2901A,
          "B2902A has two channels and must not silently get this driver")
    check("nor the 10 nA precision model",
          driver_for_idn("Keysight Technologies,B2911A,MY5,3.4")
          is not KeysightB2901A,
          "B2911A has a range this table does not list")


def test_limits_match_the_datasheet(check):
    limits = KeysightB2901A.LIMITS
    check("3 A DC", limits.max_current == 3.03)
    check("210 V", limits.max_voltage == 210.0)
    check("no pulse-only 10 A range offered",
          all(r <= 3.0 for r in limits.current_ranges),
          f"ranges: {limits.current_ranges}")
    check("no 10 nA range - that is the B2911A",
          1e-8 not in limits.current_ranges)


def test_power_envelope_has_all_three_corners(check):
    """Two corners would let 210 V at 3 A through, which is 630 W from a
    31.8 W instrument."""
    smu = KeysightB2901A(B2901ATransport())
    smu.validate_source_point(voltage=6.0, current=3.0)
    smu.validate_source_point(voltage=21.0, current=1.5)
    smu.validate_source_point(voltage=200.0, current=0.1)
    for volts, amps in ((210.0, 3.0), (21.0, 3.0), (200.0, 1.0)):
        with pytest.raises(LimitError):
            smu.validate_source_point(voltage=volts, current=amps)
        check(f"{volts} V at {amps} A refused", True)


def test_nplc_clamps_into_the_declared_window(check):
    transport, smu = fresh()
    smu.set_nplc(1000.0)
    check("clamped to the maximum",
          any("100" in line for line in sent_matching(transport, "NPLC")))
    check("set on both functions",
          len(sent_matching(transport, "NPLC")) == 2,
          "voltage and current must integrate over the same window")


def test_high_z_off_mode(check):
    transport, smu = fresh()
    smu.set_output_off_mode(high_z=True)
    check("HIZ opens the relay", ":OUTP:OFF:MODE HIZ" in transport.sent)
    smu.set_output_off_mode(high_z=False)
    check("NORM is the default sense", ":OUTP:OFF:MODE NORM" in transport.sent)


def test_compliance_trip_reports_none_when_unaskable(check):
    """None rather than False: an instrument that cannot be asked has
    not reported that everything was fine."""
    transport, smu = fresh()
    transport.tripped = True
    check("trip is seen", smu.compliance_tripped() is True)
    transport.tripped = False
    check("and cleared", smu.compliance_tripped() is False)

    class Unparseable(B2901ATransport):
        def _read(self, timeout_s=3.0):
            return "yes please"

    check("an unparseable reply is not a reassurance",
          KeysightB2901A(Unparseable()).compliance_tripped() is None)

    class Mute(B2901ATransport):
        def _read(self, timeout_s=3.0):
            raise OSError("no reply")

    # An instrument that stops answering is a stronger statement than an
    # unparseable one, and gets a stronger response. Returning None here
    # would let a sweep carry on past a link that has stopped answering,
    # which is the failure the transport latch exists to stop.
    with pytest.raises(TransportDesynchronised):
        KeysightB2901A(Mute()).compliance_tripped()


def test_read_error_never_invents_a_failure(check):
    """Being unable to ask about errors is not evidence a command
    failed; treating it as one would abort runs over a dropped reply."""
    transport, smu = fresh()
    check("empty queue reads as 0", smu.read_error()[0] == 0)
    transport.errors.append((-113, "Undefined header"))
    check("a real error is reported", smu.read_error()[0] == -113)

    class Garbled(B2901ATransport):
        def _read(self, timeout_s=3.0):
            return "not a code"

    check("an unparseable queue reply still reads as 0",
          KeysightB2901A(Garbled()).read_error()[0] == 0,
          "being unable to PARSE the answer is not evidence of a fault")

    class Mute(B2901ATransport):
        def _read(self, timeout_s=3.0):
            raise OSError("no reply")

    # The rule in the docstring above holds for a dropped reply, not for
    # a link that stopped answering: read_error() re-raises that rather
    # than reporting a clean queue on a session nobody can vouch for.
    with pytest.raises(TransportDesynchronised):
        KeysightB2901A(Mute()).read_error()


def test_measure_uses_meas_not_read(check):
    """`:READ` and `:INIT` are the two commands that trigger automatic
    output-on. Choosing a path never exposed to it means the output
    state does not depend on one setup line having succeeded."""
    transport, smu = fresh()
    smu.measure()
    check("spot measurement via :MEAS?",
          any(line.startswith(":MEAS") for line in transport.sent))
    check("no :READ? on the measurement path",
          not [l for l in transport.sent if l.upper().startswith(":READ")])
    check("no bare :INIT either",
          not [l for l in transport.sent if l.upper().startswith(":INIT")])


# --- compliance is on the quantity you are not sourcing --------------

def test_compliance_is_read_from_the_right_protection(check):
    """Sourcing current, the limit is a VOLTAGE compliance.

    The driver asked `:SENS:CURR:PROT:TRIP?` unconditionally, which is
    the right question only when sourcing voltage. Sourcing current, the
    current protection is not tripped at all, so the instrument answered
    0 honestly to the wrong question - and Van der Pauw and Hall both
    source current, so on those two experiments the flag was False no
    matter what the instrument was doing.

    Caught by the checkup's clamping probe on a real B2901A riding a 1 V
    limit into an open circuit: `:MEAS?` reported +1.000077 V and this
    still said False.
    """
    for mode, expected_query in (("current", ":SENS:VOLT:PROT:TRIP?"),
                                 ("voltage", ":SENS:CURR:PROT:TRIP?")):
        transport = B2901ATransport()
        smu = KeysightB2901A(transport)
        smu.set_source_function(mode)
        transport.tripped = True

        check(f"sourcing {mode}: compliance is noticed",
              smu.compliance_tripped() is True,
              f"asked: {[l for l in transport.sent if 'TRIP' in l]}")
        check(f"sourcing {mode}: it asked {expected_query}",
              expected_query in transport.sent,
              f"asked: {[l for l in transport.sent if 'TRIP' in l]}")


def test_the_sourced_function_is_read_not_remembered(check):
    """A local copy of the source mode is one reset - or one front-panel
    press - away from being wrong, and being wrong here means a
    confident False."""
    transport = B2901ATransport()
    smu = KeysightB2901A(transport)
    smu.set_source_function("current")
    transport.tripped = True
    smu.compliance_tripped()
    check("the instrument was asked what it is sourcing",
          ":SOUR:FUNC:MODE?" in transport.sent,
          f"sent: {[l for l in transport.sent if 'MODE' in l]}")


def test_not_clamping_still_reads_false(check):
    """The probe must distinguish clamping from not, in both modes -
    a method that always said True would pass the test above."""
    for mode in ("current", "voltage"):
        transport = B2901ATransport()
        smu = KeysightB2901A(transport)
        smu.set_source_function(mode)
        transport.tripped = False
        check(f"sourcing {mode}: not clamping reads False",
              smu.compliance_tripped() is False)


def test_an_unrecognised_source_mode_is_not_reassurance(check):
    """If the instrument answers `:SOUR:FUNC:MODE?` with something
    neither CURR nor VOLT, we do not know which protection to ask about
    - and "I don't know" must read as None, not False.

    Mutation-found: returning False there passed everything else,
    because no test drove the instrument into a mode it could not name.
    False means "everything was fine"; None means "cannot say", and the
    IV sweep only warns on a truthy answer.
    """
    class Confused(B2901ATransport):
        def _read(self, timeout_s=3.0):
            last = (self.sent[-1] if self.sent else "").upper()
            if last.startswith(":SOUR:FUNC:MODE?"):
                return "RES"        # not a sourcing mode we know
            return super()._read(timeout_s)

    transport = Confused()
    smu = KeysightB2901A(transport)
    smu.set_source_function("current")
    transport.tripped = True
    check("an unknown mode reads as None",
          smu.compliance_tripped() is None,
          f"got {smu.compliance_tripped()!r}")
