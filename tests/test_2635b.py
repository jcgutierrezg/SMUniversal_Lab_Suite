"""The Keithley 2635B driver: dialect, reset defaults, and the sentinel.

Written from the Series 2600B Reference Manual with **no original script
to port**, so there is no "does it still do what the lab's code did"
check available anywhere. Every test here instead guards a specific
documented behaviour that would fail *silently* if the driver got it
wrong.

Why the string assertions are so literal
----------------------------------------
This instrument speaks TSP, which is Lua. Send it SCPI and it does not
answer with a helpful error - `:SOUR:CURR:LEV 1e-4` is a syntax error in
a scripting language, and what comes back is a parser complaint on the
error queue that nothing in a measurement loop reads. Worse, send it
*nearly right* TSP - the 2611A's `smu.source.leveli` without the alias
that defines `smu` - and Lua indexes a nil value, which is again an
error queue entry and again silent from Python's point of view. The
previous setting simply stays in force and the run continues with
plausible numbers.

So these assert the exact strings **and** the absence of the other
drivers' dialects, including the sibling TSP driver's.

Five groups, in order of how much damage the failure does:

A. **The output-off state.** Reset leaves this instrument sourcing 0 V
   into the sample with 1 mA available - a driven low-impedance path,
   not a disconnection. On a box whose purpose is high-resistance
   samples that matters more than it does on the 2611A.

B. **Reply precision.** `print()` is governed by
   `format.asciiprecision`, which resets to 6 significant figures. The
   Hall experiment needs 9. Six would put a ~0.1% floor on V_H before
   any physics, silently, in every reading.

C. **The dialect is really this instrument's**, and is not the 2611A's.

D. **The return order of `measure.iv()` is current first.** Getting it
   wrong transposes every reading in every experiment while still
   producing plausible-looking numbers.

E. **The limits describe what can be sourced**, not everything the
   manual's range table lists.

The instrument is faked; the driver under test is the one that would run
on the bench.
"""
import math
import pytest

from core.ranges import AUTO

from core.limits import LimitError
from core.transports.base import (Transport,
                                  TransportDesynchronised)
from drivers.keithley_2635b import Keithley2635B
from drivers.registry import driver_for_idn

IDN = "Keithley Instruments Inc.,MODEL 2635B,4001234,4.0.2"
SAMPLE_OHM = 47000.0        # a high-resistance sample, as befits this box


class Keithley2635BTransport(Transport):
    """A fake 2635B with a resistor across its terminals.

    Models instrument-side *state*, not just the wire, so a test can ask
    "what would the instrument be set to now" rather than only "what
    string went out". `line_freq` starts at the factory 60 Hz so the
    read-then-write-only-if-wrong path is exercised by default.
    """

    def __init__(self, resistance=SAMPLE_OHM, line_freq=60,
                 line_freq_readable=True, sentinel_column=None,
                 compliance="auto"):
        super().__init__()
        self.sent = []
        self.timeouts = []
        self.connected = True
        self.resistance = resistance
        self.line_freq = line_freq
        self.line_freq_readable = line_freq_readable
        # 0 = the current column, 1 = the voltage column, as they appear
        # in the reply (iv() sends current first).
        self.sentinel_column = sentinel_column
        # What `print(smua.source.compliance)` answers - a Lua boolean,
        # as the manual's own worked example shows.
        #
        # "auto" COMPUTES it from state rather than returning a
        # constant. That distinction matters: a fake that always says
        # False cannot tell a working driver from a broken one, so any
        # test asking "does it notice compliance?" would pass either
        # way. An explicit True/False/None still overrides, for the
        # tests that need a specific reply.
        self.compliance = compliance

        # Instrument state, keyed by the attribute path as written.
        self.attrs = {}
        self.source_func = "voltage"        # smua.source.func resets to volts
        self.level = 0.0
        self.output = False

    def connect(self, address, **kw):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)

        if text == "reset()":
            # Factory defaults, exactly as the manual's per-attribute
            # tables give them for a 2635B. The point of modelling these
            # is that a driver which *fails* to override one leaves the
            # real default visible here.
            self.attrs = {
                "smua.source.offmode": "smua.OUTPUT_NORMAL",
                "smua.source.offfunc": "smua.OUTPUT_DCVOLTS",
                "smua.source.offlimiti": "1e-3",
                "smua.source.func": "smua.OUTPUT_DCVOLTS",
                "smua.source.highc": "smua.DISABLE",
                "smua.measure.autozero": "smua.AUTOZERO_AUTO",
                "smua.measure.delay": "-1",        # DELAY_AUTO on this model
                "smua.measure.nplc": "1.0",
                "smua.sense": "smua.SENSE_LOCAL",
                "format.asciiprecision": "6",      # below what Hall needs
                "format.data": "format.ASCII",
            }
            self.source_func = "voltage"
            self.level = 0.0
            self.output = False
            return

        if "=" in text:
            key, _, value = text.partition("=")
            key, value = key.strip(), value.strip()
            if key.endswith(("source.rangev", "source.rangei",
                             "measure.rangev", "measure.rangei")):
                # A range assignment does not stay where it was put. The
                # instrument selects the range that *contains* the value
                # and reports that range back, so writing 0.1 V and
                # reading 0.2 V is the correct answer rather than a
                # discrepancy - which is exactly what the range readback
                # has to be able to tell apart from a range that was
                # silently narrowed. A fake that echoed the written
                # value could not distinguish the two, so no test above
                # it could either.
                value = self._snap_range(key, value)
            self.attrs[key] = value
            if key == "smua.source.func":
                self.source_func = ("current" if "DCAMPS" in value
                                    else "voltage")
            elif key in ("smua.source.levelv", "smua.source.leveli"):
                try:
                    self.level = float(value)
                except ValueError:
                    pass
            elif key == "smua.source.output":
                self.output = "OUTPUT_ON" in value
            elif key == "localnode.linefreq":
                try:
                    self.line_freq = int(float(value))
                except ValueError:
                    pass

    #: The declared ranges, smallest first, as the driver's own LIMITS
    #: gives them. Kept here rather than imported so the fake states its
    #: own model of the instrument instead of agreeing with the code
    #: under test by construction.
    VOLTAGE_RANGES = (0.2, 2.0, 20.0, 200.0)
    CURRENT_RANGES = (1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4,
                      1e-3, 1e-2, 1e-1, 1.0, 1.5)

    def _snap_range(self, key, value):
        """The range this instrument would select for a written value."""
        try:
            wanted = abs(float(value))
        except ValueError:
            return value
        table = (self.CURRENT_RANGES if key.endswith("i")
                 else self.VOLTAGE_RANGES)
        for ceiling in table:
            if wanted <= ceiling:
                return f"{ceiling:.6e}"
        return f"{table[-1]:.6e}"

    def _reading_pair(self):
        """(amps, volts) - the order iv() returns them in, clamped.

        The clamp is not decoration. Without it, sourcing 1 uA into the
        1e12 ohm open circuit the compliance probe uses reported 1e6 V
        against a 1 V limit, while `source.compliance` next door
        reported the same output as tripped. Both cannot be true, and
        the checkup tested only that the reading was above a floor, so
        nothing noticed.

        An instrument in compliance holds the limit and delivers
        whatever current that produces - essentially none into an open
        circuit.
        """
        if self.source_func == "current":
            amps = self.level
            volts = amps * self.resistance
            limit = self._voltage_limit()
            if abs(volts) > limit:
                volts = math.copysign(limit, volts)
                amps = volts / self.resistance
        else:
            volts = self.level
            amps = volts / self.resistance
        return amps, volts

    def _voltage_limit(self):
        try:
            return float(self.attrs.get("smua.source.limitv", "20"))
        except ValueError:
            return 20.0

    def _read(self, timeout_s=3.0):
        self.timeouts.append(timeout_s)
        last = self.sent[-1] if self.sent else ""

        if "IDN" in last.upper():
            return IDN
        if "localnode.linefreq" in last:
            if not self.line_freq_readable:
                raise RuntimeError("instrument did not answer")
            return str(self.line_freq)
        if "errorqueue.next()" in last:
            # code, message, severity, node - tab separated, as print()
            # renders multiple arguments.
            return "0\tQueue is empty\t0\t1"
        if "source.compliance" in last:
            if self.compliance == "auto":
                # True exactly when the instrument cannot deliver what
                # was asked: sourcing a current whose Ohm's-law voltage
                # would exceed the limit, which an open circuit
                # guarantees.
                if self.output and self.source_func == "current":
                    wanted = abs(self.level) * self.resistance
                    return ("true" if wanted >= self._voltage_limit()
                            else "false")
                return "false"
            if self.compliance is None:      # an instrument that
                return "unexpected"          # answers oddly
            return "true" if self.compliance else "false"
        if "measure.iv()" in last:
            amps, volts = self._reading_pair()
            columns = [amps, volts]
            if self.sentinel_column is not None:
                columns[self.sentinel_column] = 9.91e37
            precision = int(float(self.attrs.get(
                "format.asciiprecision", "6")))
            return "\t".join(f"{v:.{max(precision - 1, 1)}e}"
                             for v in columns)

        # Any other `print(<attribute>)` answers from the modelled
        # state. This is what makes the range and power-limit readbacks
        # discriminating: an attribute the driver never wrote answers
        # `nil`, exactly as TSP does, so a readback contract that
        # confused "no answer" with "agreed" would go red here rather
        # than at a bench.
        if last.startswith("print(") and last.endswith(")"):
            attribute = last[len("print("):-1].strip()
            if attribute in self.attrs:
                return self.attrs[attribute]
            return "nil"
        return "0"


def fresh(**kw):
    transport = Keithley2635BTransport(**kw)
    return transport, Keithley2635B(transport)


def configured(**kw):
    """A driver that has been through reset(), as it is on connect."""
    transport, smu = fresh(**kw)
    smu.reset()
    return transport, smu


def index_of(transport, fragment):
    for i, line in enumerate(transport.sent):
        if fragment in line:
            return i
    return -1


# --- A. the output-off state -----------------------------------------

def test_reset_pins_what_output_off_physically_means(check):
    """Reset leaves "off" meaning a driven 0 V source, not an open.

    `offmode` resets to OUTPUT_NORMAL, `offfunc` to OUTPUT_DCVOLTS and
    `offlimiti` to 1 mA, so an "off" output is still connected and will
    supply up to a milliamp into any EMF present. The suite's
    Stop-de-energises guarantee is true in letter and misleading in
    spirit unless all three are stated deliberately.
    """
    transport, smu = configured()

    # Mutation-found: without this, every ordering assertion below is
    # satisfied by index_of() returning -1 for a reset that never
    # happened, and the whole group passes against a driver that only
    # ever sends overrides.
    check("the channel is actually reset", "reset()" in transport.sent,
          f"sent: {transport.sent}")
    check("off-mode is stated, not inherited",
          "smua.source.offmode = smua.OUTPUT_NORMAL" in transport.sent,
          f"sent: {transport.sent}")
    check("the off-state source function is stated",
          "smua.source.offfunc = smua.OUTPUT_DCVOLTS" in transport.sent)
    check("the off-state compliance is stated",
          any(l.startswith("smua.source.offlimiti =")
              for l in transport.sent))
    check("and it is the 1 mA the notes signed off",
          abs(float(transport.attrs["smua.source.offlimiti"]) - 1e-3) < 1e-12,
          f"offlimiti is {transport.attrs.get('smua.source.offlimiti')!r}")


def test_the_off_state_is_settled_before_anything_else(check):
    """Order matters: the sample should never sit under an inherited
    off-state while the rest of the configuration goes out."""
    transport, smu = configured()
    reset_at = index_of(transport, "reset()")
    offmode_at = index_of(transport, "smua.source.offmode")
    offlimit_at = index_of(transport, "smua.source.offlimiti")

    check("there is a reset to be ordered against", reset_at >= 0,
          "index_of() returns -1 when absent, which would satisfy every "
          "'came after' check below for free")
    check("the off-state is configured after the reset that clobbered it",
          offmode_at > reset_at, f"reset at {reset_at}, offmode at {offmode_at}")

    later = [i for i, l in enumerate(transport.sent)
             if "autorange" in l or "autozero" in l or "sense" in l]
    check("and before the rest of the configuration",
          offlimit_at < min(later), f"order: {transport.sent}")


def test_high_z_is_available_and_spelled_as_an_off_mode(check):
    """High-Z is the only true disconnection this instrument offers."""
    transport, smu = configured()
    smu.set_output_off_mode(high_z=True)
    check("high-Z via offmode",
          "smua.source.offmode = smua.OUTPUT_HIGH_Z" in transport.sent)

    smu.set_output_off_mode(high_z=False)
    check("and back to normal",
          transport.attrs["smua.source.offmode"] == "smua.OUTPUT_NORMAL")

    check("the driver declares the capability",
          Keithley2635B.supports_high_z_off())
    check("the one-shot source.output route is not used as well",
          not any("source.output = smua.OUTPUT_HIGH_Z" in l
                  for l in transport.sent),
          "two ways to express one idea is how they drift apart")


# --- B. reply precision ----------------------------------------------

def test_reset_raises_ascii_precision_above_the_hall_requirement(check):
    """`print()` is governed by `format.asciiprecision`, which resets to
    six significant figures.

    The Hall experiment pins VOLTAGE_FIGURES = 9 because V_H sits under
    a resistive offset 100-1000x larger and is recovered by subtracting
    nearly-equal numbers. Six figures put a ~0.1% floor on V_H before
    any physics - and it would arrive as slightly-wrong data, never as
    an error.
    """
    transport, smu = configured()
    check("precision is set explicitly",
          any(l.startswith("format.asciiprecision =")
              for l in transport.sent), f"sent: {transport.sent}")
    precision = int(float(transport.attrs["format.asciiprecision"]))
    check("and it clears the 9 figures Hall needs", precision >= 9,
          f"asciiprecision is {precision}; the reset default of 6 would "
          f"truncate every reading")
    # Mutation-found, and the same trap the B2901A's first probe fell
    # into: reset() already leaves format.data as ASCII, so asserting
    # the *state* is true whether or not the driver sent anything. The
    # assertion has to be that the command went out.
    check("the ASCII format is sent, not merely inherited",
          "format.data = format.ASCII" in transport.sent,
          f"sent: {transport.sent}")


def test_precision_is_set_before_anything_is_read_back(check):
    """A precision raised after the first query would leave that
    reading truncated, which is the one nobody re-checks."""
    transport, smu = configured()
    precision_at = index_of(transport, "format.asciiprecision")
    queries = [i for i, l in enumerate(transport.sent)
               if l.startswith("print(")]
    if not check("something is read back at all", bool(queries),
                 f"sent: {transport.sent}"):
        return
    first_query = queries[0]
    check("precision precedes the first print()",
          precision_at < first_query,
          f"precision at {precision_at}, first query at {first_query}")


def test_readings_carry_the_extra_digits(check):
    """End to end: the reading that comes back is not truncated to six.

    Asserting the attribute alone would pass a driver that set the
    precision and then read through some other path.

    The sourced current is a value `%.6e` represents exactly, so this
    tests the *reply* precision rather than the setpoint formatting -
    the first version of this test conflated the two and failed for the
    wrong reason. The sample resistance is deliberately awkward, so the
    measured voltage needs eleven significant figures to survive.
    """
    awkward = 47123.456789
    transport, smu = configured(resistance=awkward)
    smu.set_source_function("current")
    smu.set_current_level(1e-6)
    volts, amps = smu.measure()
    check("the measured voltage keeps its digits",
          volts is not None and abs(volts - 1e-6 * awkward) < 1e-15,
          f"got {volts!r}, expected {1e-6 * awkward!r} - the reset "
          f"default of 6 figures would give 4.71235e-02")


# --- C. the dialect is this instrument's ------------------------------

def test_no_scpi_reaches_a_lua_interpreter(check):
    """TSP is Lua. SCPI sent here is a syntax error that lands on the
    error queue and stops nothing."""
    transport, smu = configured()
    smu.set_source_function("current")
    smu.set_current_level(1e-6)
    smu.set_voltage_limit(2.0)
    smu.set_current_limit(1e-3)
    smu._apply_measure_voltage_range(2.0)
    smu._apply_measure_current_range(1e-6)
    smu.set_remote_sense(True)
    smu.set_nplc(1.0)
    smu.set_source_delay(0.1)
    smu.output_on()
    smu.output_off()
    smu.measure()
    smu.read_error()

    # *IDN? is legitimate on a 2600B and is the one exception.
    wire = [l for l in transport.sent if l != "*IDN?"]
    colons = [l for l in wire if ":" in l]
    stars = [l for l in wire if "*" in l]
    check("no colon-delimited SCPI headers", not colons, f"found: {colons}")
    check("no SCPI common commands", not stars, f"found: {stars}")

    for spelling in (":SOUR", ":SENS", ":OUTP", ":FORM", ":SYST",
                     "ILIM", "RSEN", ":READ", ":INIT"):
        hits = [l for l in wire if spelling in l.upper()]
        check(f"no {spelling} spelling", not hits, f"found: {hits}")


def test_no_2611a_channel_alias(check):
    """The sibling TSP driver aliases `smu = smua` and writes `smu.`
    thereafter. This one addresses the channel directly.

    Mixing them is the quiet failure: `smu.source.leveli = 1e-4` with no
    alias defined indexes a nil value in Lua. The error queue gets an
    entry, the level never changes, and the run carries on at whatever
    was set before.
    """
    transport, smu = configured()
    smu.set_current_level(1e-4)

    check("the alias is never sent",
          not any(l.strip().startswith("smu =") for l in transport.sent),
          f"sent: {transport.sent}")
    check("and no command depends on it",
          not any("smu." in l for l in transport.sent),
          f"found bare-alias commands: "
          f"{[l for l in transport.sent if 'smu.' in l]}")
    check("every channel reference is explicit",
          all("smua." in l or l in ("reset()", "*IDN?")
              or l.startswith("format.") or l.startswith("localnode.")
              or l.startswith("print(")
              for l in transport.sent),
          f"sent: {transport.sent}")


def test_source_and_compliance_spellings(check):
    transport, smu = configured()
    smu.set_source_function("current")
    smu.set_current_level(1e-6)
    smu.set_voltage_limit(2.0)

    check("source function", "smua.source.func = smua.OUTPUT_DCAMPS"
          in transport.sent)
    check("level via source.leveli",
          any(l.startswith("smua.source.leveli =") for l in transport.sent))
    smu.set_current_limit(3e-3)

    # Both directions, with distinguishable values. Mutation-found:
    # asserting only that `limitv` appears passes a driver where
    # set_current_limit also writes `limitv` - the current compliance
    # then silently stays at its 100 mA reset value, and a sweep that
    # clamps still draws a convincing straight line.
    for attribute, expected in (("smua.source.limitv", 2.0),
                                ("smua.source.limiti", 3e-3)):
        actual = transport.attrs.get(attribute)
        check(f"compliance via {attribute.split('.')[-1]}",
              actual is not None
              and abs(float(actual) - expected) < abs(expected) * 1e-9,
              f"{attribute} is {actual!r}, expected {expected!r} - "
              f"the two compliance setters may be crossed")
    check("compliance is not spelled as a measure-side protection",
          not any("prot" in l.lower() for l in transport.sent))

    smu.set_source_function("voltage")
    check("voltage source function",
          "smua.source.func = smua.OUTPUT_DCVOLTS" in transport.sent)
    with pytest.raises(ValueError):
        smu.set_source_function("resistance")


def test_a_fixed_range_needs_no_autorange_off_first(check):
    """The manual states that assigning a measure range disables
    autoranging for that function.

    The B2901A needs the opposite - `:RANG:AUTO OFF` must precede the
    range or the range is accepted and ignored (fault 11). Sending an
    AUTORANGE_OFF here would be harmless but would mean somebody had
    copied the SCPI driver's assumption across, so its absence is
    asserted rather than left to chance.
    """
    transport, smu = configured()
    before = len(transport.sent)
    smu._apply_measure_current_range(1e-6)
    smu._apply_measure_voltage_range(2.0)
    new = transport.sent[before:]

    check("the range is one write", len(new) == 2, f"sent: {new}")
    check("current range assigned directly",
          any(l.startswith("smua.measure.rangei =") for l in new))
    check("voltage range assigned directly",
          any(l.startswith("smua.measure.rangev =") for l in new))
    check("no AUTORANGE_OFF dance",
          not any("AUTORANGE_OFF" in l for l in new), f"sent: {new}")


def test_auto_asks_for_autorange_on_the_right_axis(check):
    """AUTO on the measure axis touches only the measure autorange.

    Was `test_none_asks_for_autorange`, where `None` meant autorange on
    a method that did not say which axis it was ranging. Wave 6d-ii
    replaced it with four named hooks, so the axis is now part of the
    question rather than something the driver decided for you.
    """
    transport, smu = configured()
    before = len(transport.sent)
    smu._apply_measure_current_range(AUTO)
    smu._apply_measure_voltage_range(AUTO)
    new = transport.sent[before:]
    check("current autorange",
          "smua.measure.autorangei = smua.AUTORANGE_ON" in new, f"{new}")
    check("voltage autorange",
          "smua.measure.autorangev = smua.AUTORANGE_ON" in new, f"{new}")
    check("and the source axis is untouched",
          not any("source.autorange" in t or "source.range" in t
                  for t in new), f"{new}")

    before = len(transport.sent)
    smu._apply_source_current_range(AUTO)
    new = transport.sent[before:]
    check("the source axis has its own autorange",
          "smua.source.autorangei = smua.AUTORANGE_ON" in new, f"{new}")


def test_reset_clears_the_settings_that_would_cap_this_instrument(check):
    """High-capacitance mode locks out every current range below 1 µA
    and forces current autorange to FOLLOW_LIMIT. On the one SMU here
    bought for low-current work, inheriting it enabled would remove the
    reason it is on the bench."""
    transport, smu = configured()
    check("high-C mode is explicitly disabled",
          "smua.source.highc = smua.DISABLE" in transport.sent)
    check("power compliance is explicitly disabled",
          "smua.source.limitp = 0" in transport.sent,
          "left enabled it overrides both the V and I limits")
    check("autozero is stated",
          "smua.measure.autozero = smua.AUTOZERO_AUTO" in transport.sent)
    check("sense mode is stated, not inherited",
          "smua.sense = smua.SENSE_LOCAL" in transport.sent)
    for attribute in ("source.autorangev", "source.autorangei",
                      "measure.autorangev", "measure.autorangei"):
        check(f"{attribute} is set on",
              f"smua.{attribute} = smua.AUTORANGE_ON" in transport.sent)


def test_remote_sense_switches_both_ways(check):
    transport, smu = configured()
    smu.set_remote_sense(True)
    check("4-wire", transport.attrs["smua.sense"] == "smua.SENSE_REMOTE")
    smu.set_remote_sense(False)
    check("2-wire", transport.attrs["smua.sense"] == "smua.SENSE_LOCAL")


def test_levels_are_not_quantised(check):
    """Two ported originals rounded levels before sending. Invisible at
    1 V; at 100 µV it collapses distinct points onto one level while the
    saved x-axis still claims they differed."""
    transport, smu = configured()
    smu.set_voltage_level(1.2345e-4)
    lines = [l for l in transport.sent
             if l.startswith("smua.source.levelv =")]
    if not check("a voltage level was set at all", bool(lines),
                 f"sent: {transport.sent}"):
        return
    check("full precision reaches the instrument",
          abs(float(lines[-1].split("=")[-1]) - 1.2345e-4) < 1e-12,
          f"sent {lines[-1]!r}")


# --- C2. line frequency ----------------------------------------------

def test_line_frequency_is_written_only_when_it_disagrees(check):
    """Nonvolatile and untouched by reset, so writing it every connect
    would be a pointless flash write on every single session."""
    transport, smu = configured(line_freq=60)
    check("a wrong line frequency is corrected",
          "localnode.linefreq = 50" in transport.sent, f"{transport.sent}")
    check("and the instrument now agrees", transport.line_freq == 50)

    transport, smu = configured(line_freq=50)
    check("a correct one is left alone",
          not any("localnode.linefreq =" in l for l in transport.sent),
          f"sent: {transport.sent}")
    check("but it was still checked",
          any("print(localnode.linefreq)" in l for l in transport.sent))


def test_an_unparseable_line_frequency_does_not_break_the_connection(check):
    """Being unable to ask is not evidence of a fault. NPLC still works;
    it just rejects mains hum less well.

    This is the case the rule was written for: the instrument answered,
    the answer was no use. Distinct from the one below, where it did not
    answer at all.
    """
    transport, smu = fresh()
    transport.line_freq = "not a number"
    smu.reset()
    check("reset completed", "smua.sense = smua.SENSE_LOCAL"
          in transport.sent)
    check("and the note says what happened",
          "line frequency" in smu.sweep_note().lower(),
          smu.sweep_note())


def test_an_unanswered_line_frequency_ends_the_session():
    """No answer is a different claim from a useless answer.

    If the reply to `localnode.linefreq` never arrives, it may still be
    on its way - and the next question would collect it. Carrying on
    with a note would mean every reading afterwards belonging to the
    wrong question, with a note about mains hum as the only clue.

    The app turns this into a blocked instrument at connect time rather
    than a crash: base_app._initialise_driver() catches a failed reset
    and refuses runs until a clean reconnect.
    """
    transport, smu = fresh(line_freq_readable=False)
    with pytest.raises(TransportDesynchronised):
        smu.reset()


# --- D. measure(): order, and the sentinel ---------------------------

def test_measure_returns_volts_first_from_a_current_first_reply(check):
    """`measure.iv()` returns current then voltage; this contract is
    (volts, amps).

    The values are deliberately asymmetric and not reciprocal, so a
    transposition cannot coincidentally satisfy the assertion.
    """
    transport, smu = configured()
    smu.set_source_function("current")
    smu.set_current_level(1e-6)
    volts, amps = smu.measure()

    check("volts came back as volts",
          abs(volts - 1e-6 * SAMPLE_OHM) < 1e-9,
          f"got volts={volts!r}, amps={amps!r} - transposed?")
    check("amps came back as amps", abs(amps - 1e-6) < 1e-15)
    check("and they are not interchangeable here", volts != amps)


def test_measure_is_one_matched_pair_not_two_reads(check):
    """Two separate `measure.v()` / `measure.i()` calls cost two
    apertures and describe two different moments. The 2611A wore that
    bug and the bench found it as a 1034 ms reading at NPLC 25."""
    transport, smu = configured()
    before = len(transport.sent)
    smu.measure()
    new = transport.sent[before:]
    check("exactly one query", len(new) == 1, f"sent: {new}")
    check("and it is the matched pair",
          new[0] == "print(smua.measure.iv())", f"sent: {new}")


def test_measure_honours_the_callers_timeout(check):
    """A reading at NPLC 25 takes over half a second, and the 2611A's
    bench data shows the first one after a configuration change costs
    three apertures. A driver that hardcodes its own timeout instead of
    passing the caller's through turns that into a bus timeout that
    looks like a dead instrument."""
    transport, smu = configured()
    smu.measure(timeout_s=12.0)
    check("the timeout reached the transport",
          transport.timeouts[-1] == 12.0,
          f"transport was asked for {transport.timeouts[-1]!r} s")


@pytest.mark.parametrize("column,label", [(0, "current"), (1, "voltage")])
def test_a_sentinel_never_shifts_the_other_column(column, label, check):
    """Dropping by omission would promote the surviving value into the
    missing one's place - the right shape, wrong by a factor of the
    resistance, and indistinguishable from a real reading afterwards."""
    transport, smu = configured(sentinel_column=column)
    smu.set_source_function("current")
    smu.set_current_level(1e-6)
    volts, amps = smu.measure()

    if column == 0:
        check(f"the {label} column is None", amps is None, f"got {amps!r}")
        check("the voltage keeps its own value",
              volts is not None and abs(volts - 1e-6 * SAMPLE_OHM) < 1e-9,
              f"got volts={volts!r}")
    else:
        check(f"the {label} column is None", volts is None, f"got {volts!r}")
        check("the current keeps its own value",
              amps is not None and abs(amps - 1e-6) < 1e-15,
              f"got amps={amps!r}")


def test_error_queue_is_split_on_tabs(check):
    """`errorqueue.next()` returns four values and print() separates
    them with tabs. Splitting on whitespace instead puts the severity
    and node on the end of the message, and splits multi-word messages
    across fields."""
    transport, smu = configured()
    code, message = smu.read_error()
    check("code parsed", code == 0, f"got {code!r}")
    check("the message is only the message", message == "Queue is empty",
          f"got {message!r} - severity and node should not be in here")
    check("asked in TSP", "print(errorqueue.next())" in transport.sent)


# --- E. limits describe what can be sourced --------------------------

def test_source_ranges_exclude_the_measure_only_range(check):
    """`current_ranges` feeds the Van der Pauw and Hall *source level*
    dropdowns and the IV sweep *compliance* dropdown - never a
    measurement range.

    The 100 pA range is measurement-only on this model. Offering it as a
    source level would let an operator request a Van der Pauw current
    the instrument cannot produce; it clamps to its lowest source range
    and the sheet resistance is computed from a current that was never
    sourced. Do not "fix" this by pasting the manual's range table back
    in - that table covers both directions.
    """
    ranges = Keithley2635B.LIMITS.current_ranges
    check("the measure-only 100 pA range is absent", 1e-10 not in ranges,
          f"ranges: {ranges}")
    check("nothing below the 1 nA source floor is offered",
          min(ranges) >= 1e-9, f"lowest is {min(ranges):g}")
    check("the 1 nA source range is offered", 1e-9 in ranges)
    check("and the full-scale ranges are there",
          1.5 in ranges and 1.0 in ranges)


def test_limits_gate_the_power_envelope(check):
    """200 V and 1.5 A are both reachable, but not together."""
    smu = Keithley2635B(Keithley2635BTransport())
    smu.validate_source_point(voltage=20.0, current=1.5)
    smu.validate_source_point(voltage=200.0, current=0.1)
    with pytest.raises(LimitError):
        smu.validate_source_point(voltage=200.0, current=1.5)
    with pytest.raises(LimitError):
        smu.validate_source_point(voltage=250.0)
    with pytest.raises(LimitError):
        smu.validate_source_point(current=2.0)
    check("the envelope is declared",
          Keithley2635B.LIMITS.power_envelope == [(20.0, 1.5), (200.0, 0.1)])
    check("voltage ranges reach 200 V",
          Keithley2635B.LIMITS.voltage_ranges[-1] == 200.0)


def test_the_registry_resolves_this_instrument(check):
    """A driver whose own IDN resolves elsewhere is undetectable at the
    bench, and the failure looks like a broken instrument."""
    check("the full reply resolves", driver_for_idn(IDN) is Keithley2635B,
          f"resolved to {driver_for_idn(IDN)}")
    check("and it does not poach the 2611A",
          driver_for_idn("Keithley Instruments,MODEL 2611A,1398687,1.4.2")
          is not Keithley2635B)
    check("nor answer for a 2636B it is not",
          driver_for_idn("Keithley Instruments Inc.,MODEL 2636B,4001234,4.0.2")
          is not Keithley2635B,
          "the 2636B is dual-channel; claiming it would drive one channel "
          "and silently ignore the other")


def test_the_sweep_is_software_and_says_so(check):
    """No bench, no confirmed factory-script page, so the TSP sweep
    factories are not wired up. The software fallback reads back every
    level it sources."""
    check("declared as software", Keithley2635B.sweep_kind() == "software")
    check("and it can still sweep", Keithley2635B.supports_sweep())

    transport, smu = configured()
    note = smu.sweep_note()
    for fragment in ("100 pA", "1 nA", "Software sweep", "high-Z"):
        check(f"the console note mentions {fragment!r}", fragment in note,
              f"note: {note}")


def test_nplc_is_clamped_to_this_model_s_window(check):
    """TSP goes both finer and coarser than the SCPI boxes: 0.001 to 25,
    where the 2400 family stops at 0.01 and 10."""
    transport, smu = configured()
    smu.set_nplc(100.0)
    check("clamped at the top",
          abs(float(transport.attrs["smua.measure.nplc"]) - 25.0) < 1e-9,
          f"got {transport.attrs.get('smua.measure.nplc')!r}")
    smu.set_nplc(1e-6)
    check("clamped at the bottom",
          abs(float(transport.attrs["smua.measure.nplc"]) - 0.001) < 1e-9)


def test_source_delay_reaches_the_instrument_in_seconds(check):
    """The base contract is seconds. The original VdP script sent
    microseconds to a command that takes seconds and was out by 10^6."""
    transport, smu = configured()
    smu.set_source_delay(0.25)
    check("delay in seconds",
          abs(float(transport.attrs["smua.measure.delay"]) - 0.25) < 1e-9,
          f"got {transport.attrs.get('smua.measure.delay')!r}")


def test_output_control(check):
    transport, smu = configured()
    smu.output_on()
    check("on", transport.output is True)
    check("spelling", "smua.source.output = smua.OUTPUT_ON" in transport.sent)
    smu.output_off()
    check("off", transport.output is False)
    check("spelling", "smua.source.output = smua.OUTPUT_OFF" in transport.sent)


# --- F. compliance ----------------------------------------------------

def test_compliance_is_reported_both_ways(check):
    """A sweep in compliance still draws a neat line with a convincing
    R-squared - the fit describes the limit rather than the sample - so
    an instrument that can say it is clamping is worth asking."""
    transport, smu = configured()
    check("not clamping reads as False", smu.compliance_tripped() is False,
          f"got {smu.compliance_tripped()!r}")
    check("asked in TSP",
          "print(smua.source.compliance)" in transport.sent,
          f"sent: {transport.sent}")

    transport.compliance = True
    check("clamping reads as True", smu.compliance_tripped() is True)


def test_an_unclear_compliance_reply_is_not_reassurance(check):
    """None means "this instrument cannot say"; False means "everything
    was fine". Collapsing the two turns a silence into a reassurance,
    which is exactly what the base contract warns about - and it is why
    this stayed unwired until the attribute page was read rather than
    guessing how a Lua boolean prints.
    """
    transport, smu = configured()
    transport.compliance = None          # answers something unparseable
    check("an unparseable reply is None", smu.compliance_tripped() is None,
          f"got {smu.compliance_tripped()!r}")

    class Mute(Keithley2635BTransport):
        def _read(self, timeout_s=3.0):
            if "source.compliance" in (self.sent[-1] if self.sent else ""):
                raise RuntimeError("no answer")
            return super()._read(timeout_s)

    # A silent instrument is not "cannot say" - it is "cannot be
    # trusted to say anything after this". None would be a quieter
    # answer than the situation deserves.
    with pytest.raises(TransportDesynchronised):
        Keithley2635B(Mute()).compliance_tripped()


def test_the_interlock_threshold_is_declared(check):
    """The 2600B interlock section names the 2635 alongside the 2611,
    so this model carries the same 200 V condition even though its
    range table does not footnote it."""
    check("the 2635B declares an interlock",
          Keithley2635B.INTERLOCK_ABOVE_V == 20.2,
          f"got {Keithley2635B.INTERLOCK_ABOVE_V!r}")
    note = Keithley2635B.interlock_note()
    check("and names the threshold", note and "20.2" in note, f"{note!r}")
    check("the console note mentions it too",
          "interlock" in configured()[1].sweep_note().lower(),
          configured()[1].sweep_note())


# --- G. the current range floor --------------------------------------

def test_the_range_floor_is_written_not_inherited(check):
    """`measure.lowrangei` decides how far autoranging may search, and
    on this instrument that is the single biggest lever on reading time:
    86.7 ms per reading with the 100 pA floor against 30.2 ms with a
    1 nA floor, measured on the bench at NPLC 0.001.

    The value is the instrument's own reset default, so writing it
    changes nothing today. That is the point - a number this
    consequential should be a decision in the driver rather than
    whatever reset happened to leave (fault 17), so that changing it is
    a one-line edit rather than an archaeology exercise.
    """
    transport, smu = configured()
    check("the floor is sent",
          any(l.startswith("smua.measure.lowrangei =") for l in transport.sent),
          f"sent: {transport.sent}")
    check("and it is the 100 pA the notes signed off",
          abs(float(transport.attrs["smua.measure.lowrangei"]) - 100e-12)
          < 1e-15,
          f"lowrangei is {transport.attrs.get('smua.measure.lowrangei')!r}")


def test_the_floor_is_actually_a_knob(check):
    """A constant that the driver ignores is documentation, not
    configuration. Changing it must change what reaches the
    instrument."""
    class Faster(Keithley2635B):
        MEASURE_LOW_RANGE_FLOOR_A = 1e-9

    transport = Keithley2635BTransport()
    Faster(transport).reset()
    check("the subclass's floor is what gets sent",
          abs(float(transport.attrs["smua.measure.lowrangei"]) - 1e-9) < 1e-18,
          f"lowrangei is {transport.attrs.get('smua.measure.lowrangei')!r}")


def test_the_floor_does_not_disturb_autoranging(check):
    """A floor is a bound on autoranging, not a replacement for it.
    Sending AUTORANGE_OFF alongside would fix the range instead, which
    is a different instrument configuration entirely."""
    transport, smu = configured()
    check("current autorange is still on",
          "smua.measure.autorangei = smua.AUTORANGE_ON" in transport.sent)
    check("nothing turned autoranging off",
          not any("AUTORANGE_OFF" in l for l in transport.sent),
          f"sent: {[l for l in transport.sent if 'AUTORANGE' in l]}")
