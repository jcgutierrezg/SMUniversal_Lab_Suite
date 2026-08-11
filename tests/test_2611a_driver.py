import sys, os

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
from core.transports.base import Transport
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


def test_an_unreadable_line_frequency_does_not_break_the_connection(check):
    t = TSPTransport(line_freq_readable=False)
    smu = Keithley2611A(t)
    smu.reset()
    check("reset completed",
          "smu.measure.autorangei = smu.AUTORANGE_ON" in t.sent)
    check("and the note says what happened",
          "line frequency" in smu.sweep_note().lower(), smu.sweep_note())


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
    smu.set_current_range(1e-6)
    smu.set_voltage_range(2.0)
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
