
"""The Keithley 2611A driver - TSP, not SCPI.

The 2611A is the odd one out: everything else here speaks SCPI, and a
TSP command that looks wrong is not rejected the way an unknown SCPI
header is. `smu.measure.v` without the parentheses is a valid
expression that returns a function object, and printing it gives you a
string that parses to nothing. So the failure modes are quieter than
elsewhere and worth pinning explicitly.

The specific trap this file exists for: `smu.measure.iv()` returns
**current first, then voltage**, which is the opposite order from the
`print(smu.measure.v(), smu.measure.i())` it replaced. Getting it wrong
transposes every reading in every experiment while still producing
numbers that look entirely plausible.
"""
import pytest

from core.transports.base import Transport, TransportDesynchronised
from drivers.keithley_2611a import Keithley2611A


class TSPTransport(Transport):
    def __init__(self, current=2e-3, voltage=7.0, line_freq=60,
                 line_freq_readable=True, compliance=False):
        super().__init__()
        self.sent = []
        self.connected = True
        self.current = current
        self.voltage = voltage
        self.line_freq = line_freq
        self.line_freq_readable = line_freq_readable
        self.compliance = compliance
        self.attrs = {}

    def connect(self, address, **kw):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)
        if text == "reset()":
            # Factory defaults for a 2611A, as the 2600A manual gives
            # them. Modelling these is the point: a driver that fails to
            # override one leaves the real default visible here.
            self.attrs = {
                "smu.source.offmode": "smu.OUTPUT_NORMAL",
                "smu.source.offlimiti": "1e-3",
                "format.asciiprecision": "6",   # below what Hall needs
                "format.data": "format.ASCII",
            }
            return
        if "=" in text:
            key, _, value = text.partition("=")
            self.attrs[key.strip()] = value.strip()
            if key.strip() == "localnode.linefreq":
                try:
                    self.line_freq = int(float(value.strip()))
                except ValueError:
                    pass

    def _read(self, timeout_s):
        last = self.sent[-1] if self.sent else ""
        if "localnode.linefreq" in last:
            if not self.line_freq_readable:
                raise RuntimeError("instrument did not answer")
            return str(self.line_freq)
        if "source.compliance" in last:
            if self.compliance is None:
                return "unexpected"
            return "true" if self.compliance else "false"
        if "measure.iv()" in last:
            # TSP prints a returned tuple tab-separated, current first,
            # at whatever format.asciiprecision is currently set to.
            digits = int(float(self.attrs.get("format.asciiprecision", "6")))
            fmt = f".{max(digits - 1, 1)}e"
            return f"{self.current:{fmt}}\t{self.voltage:{fmt}}"
        if "errorqueue.next()" in last:
            return "0\tQueue is empty\t0\t0"
        if "localnode.model" in last or "IDN" in last:
            return "Keithley Instruments Inc., Model 2611A, 1314733, 2.2.2"

        # Any other `print(<attribute>)` answers from the modelled
        # state, and an attribute nothing wrote answers `nil` - exactly
        # as TSP does. That is what makes the compliance and range
        # readbacks discriminating: the fallback below returns "0",
        # which parses as a perfectly plausible float, so a driver
        # reading an attribute nobody set would have looked correct
        # while reporting a limit of zero.
        if last.startswith("print(") and last.endswith(")"):
            attribute = last[len("print("):-1].strip()
            if attribute in self.attrs:
                return self.attrs[attribute]
            return "nil"
        return "0"


# ---------------------------------------------------------------


def test_measure_pair_order(check):
    # Deliberately asymmetric values: 2 mA and 7 V cannot be transposed by
    # coincidence the way 1 and 1 could.
    t = TSPTransport(current=2e-3, voltage=7.0)
    smu = Keithley2611A(t)
    volts, amps = smu.measure()

    check("the matched-pair call is used",
          any("measure.iv()" in x for x in t.sent), f"{t.sent}")
    check("the two-measurement form is gone",
          not any("measure.v()" in x for x in t.sent),
          "it integrated V over one aperture and I over the NEXT one - "
          "1034 ms per reading at NPLC 25 on the bench, which is two "
          "0.5 s apertures")
    check("voltage comes back as voltage", abs(volts - 7.0) < 1e-9,
          f"got {volts} - measure.iv() returns CURRENT first")
    check("and current as current", abs(amps - 2e-3) < 1e-12, f"got {amps}")

    # Sign matters too: a transposition can survive a magnitude check when
    # both happen to be small.
    t = TSPTransport(current=-1.5e-6, voltage=0.25)
    volts, amps = Keithley2611A(t).measure()
    check("signs are preserved", volts > 0 and amps < 0, f"{volts}, {amps}")


def test_unparseable_replies(check):
    t = TSPTransport()
    t.current = t.voltage = 0.0


    class OneNumber(TSPTransport):
        def _read(self, timeout_s):
            last = self.sent[-1] if self.sent else ""
            if "measure.iv()" in last:
                return "2.000000e-03"
            return super()._read(timeout_s)


    volts, amps = Keithley2611A(OneNumber()).measure()
    check("a single number claims neither quantity",
          volts is None and amps is None,
          f"got {volts}, {amps} - guessing which one it is would put a "
          f"current in a voltage column")


    class Garbage(TSPTransport):
        def _read(self, timeout_s):
            last = self.sent[-1] if self.sent else ""
            if "measure.iv()" in last:
                return "TSP error at line 1"
            return super()._read(timeout_s)


    volts, amps = Keithley2611A(Garbage()).measure()
    check("an error string parses to None, not 1.0",
          volts is None and amps is None, f"{volts}, {amps}")


def test_error_queue(check):
    smu = Keithley2611A(TSPTransport())
    code, message = smu.read_error()
    check("an empty queue reads as code 0", code == 0, f"{code}: {message}")
    check("and uses the TSP spelling, not :SYST:ERR?",
          any("errorqueue.next()" in x for x in smu.transport.sent),
          "the SCPI form would be swallowed by the TSP parser as an "
          "unknown identifier")


# ---------------------------------------------------------------
# Corrections found while writing the 2635B from the 2600B manual
# ---------------------------------------------------------------


def configured(**kw):
    t = TSPTransport(**kw)
    smu = Keithley2611A(t)
    smu.reset()
    return t, smu


def test_reset_raises_ascii_precision_above_the_hall_requirement(check):
    """`format.asciiprecision` governs `print`, `printnumber` AND
    `printbuffer`, and resets to six significant figures.

    Nothing in this codebase set it for the whole life of this driver,
    so every reading came back truncated - through measure() and,
    because the hardware sweep reads back with printbuffer, through
    every sweep point too. The Hall experiment needs nine: V_H sits
    under a resistive offset 100-1000x larger and is recovered by
    subtracting nearly-equal numbers.
    """
    t, smu = configured()
    check("precision is set explicitly",
          any(x.startswith("format.asciiprecision =") for x in t.sent),
          f"sent: {t.sent}")
    check("and it clears the nine figures Hall needs",
          int(float(t.attrs["format.asciiprecision"])) >= 9,
          f"asciiprecision is {t.attrs.get('format.asciiprecision')!r}")
    check("the ASCII format is sent, not merely inherited",
          "format.data = format.ASCII" in t.sent,
          "reset already leaves it ASCII, so asserting the state alone "
          "would be true whether or not the driver sent anything")


def test_precision_is_set_before_anything_is_read_back(check):
    t, smu = configured()
    precision_at = [i for i, x in enumerate(t.sent)
                    if x.startswith("format.asciiprecision =")][0]
    queries = [i for i, x in enumerate(t.sent)
               if x.startswith("print(")]
    if not check("something is read back at all", bool(queries),
                 f"sent: {t.sent}"):
        return
    first_query = queries[0]
    check("precision precedes the first print()", precision_at < first_query,
          f"precision at {precision_at}, first query at {first_query}")


def test_readings_are_no_longer_truncated(check):
    """End to end, through the fake's own precision handling.

    The awkward voltage needs eleven significant figures to survive; at
    the reset default of six it comes back as 7.12346e+00.
    """
    t, smu = configured(voltage=7.123456789, current=2e-3)
    volts, amps = smu.measure()
    check("the measured voltage keeps its digits",
          volts is not None and abs(volts - 7.123456789) < 1e-9,
          f"got {volts!r} - six significant figures would give 7.12346")


def test_reset_states_what_output_off_means(check):
    """Reset leaves "off" meaning a driven 0 V source with 1 mA
    available, not an open circuit.

    Note there is no `offfunc` on this family - normal-off is always a
    0 V source - so there are two attributes here where the 2635B has
    three.
    """
    t, smu = configured()
    check("the channel is actually reset", "reset()" in t.sent)
    check("off-mode is stated, not inherited",
          "smu.source.offmode = smu.OUTPUT_NORMAL" in t.sent, f"sent: {t.sent}")
    check("the off-state compliance is stated",
          any(x.startswith("smu.source.offlimiti =") for x in t.sent))
    check("and it is 1 mA",
          abs(float(t.attrs["smu.source.offlimiti"]) - 1e-3) < 1e-12,
          f"offlimiti is {t.attrs.get('smu.source.offlimiti')!r}")
    check("no offfunc is sent - this family has none",
          not any("offfunc" in x for x in t.sent),
          "the 2600A has no such attribute; sending it is a Lua error")


def test_line_frequency_is_read_before_it_is_written(check):
    """Writing `linefreq` sets `autolinefreq` false permanently, so a
    driver that writes it every connect silently disables automatic
    detection on a box somebody left detecting on purpose."""
    t, smu = configured(line_freq=60)
    check("a wrong line frequency is corrected",
          "localnode.linefreq = 50" in t.sent, f"sent: {t.sent}")
    check("and the instrument now agrees", t.line_freq == 50)

    t, smu = configured(line_freq=50)
    check("a correct one is left alone",
          not any("localnode.linefreq =" in x for x in t.sent),
          f"sent: {t.sent}")
    check("but it was still checked",
          "print(localnode.linefreq)" in t.sent)


def test_an_unparseable_line_frequency_does_not_break_the_connection(check):
    """The instrument answered; the answer was no use. Tolerated."""
    t = TSPTransport()
    t.line_freq = "not a number"
    smu = Keithley2611A(t)
    smu.reset()
    check("reset completed",
          "smu.measure.autorangei = smu.AUTORANGE_ON" in t.sent)
    check("and the note says what happened",
          "line frequency" in smu.sweep_note().lower(), smu.sweep_note())


def test_an_unanswered_line_frequency_ends_the_session():
    """It did not answer at all, which is the stronger claim.

    A reply that never arrived may still be in flight, so the next
    question would collect it. See the 2635B's copy of this test - the
    rule is the transport's, not any one driver's.
    """
    with pytest.raises(TransportDesynchronised):
        Keithley2611A(TSPTransport(line_freq_readable=False)).reset()


def test_compliance_is_reported_both_ways(check):
    t, smu = configured()
    check("not clamping reads as False", smu.compliance_tripped() is False,
          f"got {smu.compliance_tripped()!r}")
    check("asked in TSP", "print(smu.source.compliance)" in t.sent)
    t.compliance = True
    check("clamping reads as True", smu.compliance_tripped() is True)


def test_an_unclear_compliance_reply_is_not_reassurance(check):
    """None means "cannot say"; False means "everything was fine"."""
    t, smu = configured(compliance=None)
    check("an unparseable reply is None", smu.compliance_tripped() is None,
          f"got {smu.compliance_tripped()!r}")


def test_error_queue_is_split_on_tabs(check):
    """print() separates multiple arguments with a tab, and
    errorqueue.next() returns four of them. Splitting on whitespace put
    the severity and node on the end of the message and broke multi-word
    messages across fields."""
    t, smu = configured()
    code, message = smu.read_error()
    check("code parsed", code == 0, f"got {code!r}")
    check("the message is only the message", message == "Queue is empty",
          f"got {message!r} - severity and node should not be in here")


def test_a_fixed_range_needs_no_autorange_off_first(check):
    """The manual states that explicitly setting a range disables
    autoranging for that function."""
    t, smu = configured()
    before = len(t.sent)
    smu._apply_measure_current_range(1e-6)
    smu._apply_measure_voltage_range(2.0)
    new = t.sent[before:]
    check("the range is one write each", len(new) == 2, f"sent: {new}")
    check("no AUTORANGE_OFF dance",
          not any("AUTORANGE_OFF" in x for x in new), f"sent: {new}")


def test_source_and_measure_ranges_are_the_same_set_here(check):
    """Fault 16 does not apply to this model.

    The 2635B measures to 100 pA and sources only to 1 nA, so its
    LIMITS declares the sourceable list alone. The 2611A's range table
    gives both a source and a measure column for every range from
    100 nA up, so one list is honest here. The 10 A range is pulse-mode
    only and is correctly absent.
    """
    ranges = Keithley2611A.LIMITS.current_ranges
    check("the floor is the 100 nA both columns share",
          min(ranges) == 1e-7, f"lowest is {min(ranges):g}")
    check("the pulse-only 10 A range is absent", 10.0 not in ranges,
          f"ranges: {ranges}")
    check("the DC ceiling is 1.5 A", max(ranges) == 1.5)


# ---------------------------------------------------------------
# The 200 V interlock
# ---------------------------------------------------------------


def test_the_interlock_threshold_is_declared(check):
    """The manual states the output can only be turned on above the
    200 V range's threshold when the interlock line is pulled high, and
    that after a fixture lid opens it stays off until the line goes high
    again. No command overrides it, so the driver declares the condition
    rather than trying to handle it.
    """
    check("the 2611A declares an interlock",
          Keithley2611A.INTERLOCK_ABOVE_V == 20.2,
          f"got {Keithley2611A.INTERLOCK_ABOVE_V!r}")

    note = Keithley2611A.interlock_note()
    check("and has something to say about it", bool(note))
    check("naming the threshold", "20.2" in note, note)
    check("and pointing away from the driver as the suspect",
          "interlock" in note.lower(), note)


def test_instruments_without_an_interlock_say_nothing(check):
    """Declared per model, not inferred from the dialect - the note has
    to be absent on instruments that have no such line, or it becomes
    noise everybody learns to skip."""
    from drivers.keithley_2450 import Keithley2450
    from drivers.keysight_u2722a import KeysightU2722A
    for cls in (Keithley2450, KeysightU2722A):
        check(f"{cls.__name__} declares none",
              cls.INTERLOCK_ABOVE_V is None)
        check(f"{cls.__name__} prints nothing",
              cls.interlock_note() is None)


# ---------------------------------------------------------------
# Reading the compliance VALUE back (2026-09-04)
# ---------------------------------------------------------------


def test_the_compliance_value_reads_back_not_just_the_flag(check):
    """`source.compliance` was here; `source.limit{i,v}` was not.

    So the checkup reported "Keithley 2611A does not report its
    compliance - a collapse here would be invisible" about an instrument
    whose flag passes both of its probes, including the one taken while
    riding the limit.

    They are different questions. A flag says a limit was reached. It
    cannot say *which* limit, so it cannot see a compliance that moved:
    on the U2722A the bench watched a 100 uA limit become 12 mA across a
    range change with a clean error queue, and a trip flag would have
    reported False throughout.
    """
    t = TSPTransport()
    smu = Keithley2611A(t)

    smu.set_current_limit(1e-3)
    smu.set_voltage_limit(7.0)
    check("current compliance reads back", smu.read_current_limit() == 1e-3,
          f"{smu.read_current_limit()}")
    check("voltage compliance reads back", smu.read_voltage_limit() == 7.0,
          f"{smu.read_voltage_limit()}")
    check("read over print(), the mechanism this driver already uses",
          any(x == "print(smu.source.limiti)" for x in t.sent), f"{t.sent}")

    # The control leg. The instrument's held limit is moved behind the
    # driver's back and the readback has to follow the instrument, not a
    # value the driver remembers sending.
    t.attrs["smu.source.limiti"] = "1.2e-2"
    check("the readback follows the instrument", smu.read_current_limit()
          == 1.2e-2, f"{smu.read_current_limit()}")

    answer = smu.verify_compliance("voltage", 1e-3)
    check("a 12x widening is a mismatch, not a warn",
          answer.state == "mismatched", f"{answer.state}: {answer.detail}")

    # A limit nobody set answers `nil`, which is no usable answer rather
    # than a plausible zero.
    check("an unset compliance is None, not 0.0",
          Keithley2611A(TSPTransport()).read_current_limit() is None)

    # Implemented and still not trusted: no bench session has compared
    # either against a compliance this instrument was known to hold.
    check("compliance readback is not trusted",
          Keithley2611A.COMPLIANCE_READBACK_TRUSTED is False)


def test_a_sub_count_current_level_is_refused(check):
    """MEASURED 2026-09-01, and the coarsest converter of the five.

    `tools/bench_envelope.py` pinned the source current range to 1e-4 A
    and halved down; the sign stopped being followed below 1.221e-08 A,
    and 1e-4 / 8192 is 1.2207e-08 - one count of the range the sweep was
    on. Four bits behind the 2635B on the same family's command set,
    which the readings bear out: the two legs were already lopsided
    (+4.43e-09 against -4.19e-08) at the last level that followed.

    Both sides of the boundary, because a guard tested only from below
    passes against a driver that refuses everything.
    """
    from core.ranges import AUTO, RangeError, RangePlan

    counts = Keithley2611A.SOURCE_COUNTS_PER_RANGE["current"]
    check("the declared count reproduces the measured floor",
          abs(1e-4 / counts - 1.2207e-8) < 1e-12, f"{1e-4 / counts}")

    t = TSPTransport()
    smu = Keithley2611A(t)
    smu.apply_ranges(RangePlan.for_sourcing(
        "current", source_range=1e-4, measure_range=2.0))

    floor = smu.source_level_floor("current")
    check("the floor is ten counts of the range in force",
          abs(floor - 1e-4 / counts * 10) < 1e-18, f"{floor}")

    before = len(t.sent)
    try:
        smu.set_current_level(floor / 10.0)
        check("a sub-count level is refused", False, "it was written")
    except RangeError:
        check("a sub-count level is refused", True)
        check("and nothing reached the instrument first",
              len(t.sent) == before, f"{t.sent[before:]}")

    smu.set_current_level(floor)
    check("the floor itself goes out",
          any("source.leveli" in x for x in t.sent[before:]),
          f"{t.sent[before:]}")

    # Under autoranging the driver does not know which range is in
    # force, so the floor drops to the bound that holds on every range -
    # ten counts of this model's narrowest source range, 100 nA.
    auto = Keithley2611A(TSPTransport())
    auto.apply_ranges(RangePlan.for_sourcing(
        "current", source_range=AUTO, measure_range=2.0))
    check("autorange falls back to the narrowest range's floor",
          abs(auto.source_level_floor("current") - 1e-7 / counts * 10) < 1e-20,
          f"{auto.source_level_floor('current')}")

    # And the voltage axis is untouched: the bench procedure sources
    # current and only current, so nothing has measured that converter.
    check("the voltage axis is still unmeasured",
          Keithley2611A.sub_count_state("voltage") == "unmeasured")
    check("so no voltage floor is offered",
          smu.source_level_floor("voltage") is None)
