"""No driver returns the "no reading" sentinel as a measurement.

SCPI instruments report "there is no reading here" as a *number*:
+9.91e37 for not-a-number, +9.9e37 for over-range. TSP uses the same
values. Nothing raises and nothing is logged - the value parses as a
perfectly ordinary float and enters the data as a point 37 orders of
magnitude out. One of them in a sweep drags the least-squares fit to a
meaningless slope while still reporting a healthy R-squared, because the
fit describes the sentinel and the R-squared describes how well.

**This file exists because the code was wrong.** The handling lived on
the GSM driver alone. When the B2901A became the second instrument to
need it, a diagnostic across every registered driver found the 2450,
2401, 2611A and U2722A all returning both sentinels straight through, in
both columns. Reading the code had suggested as much; running it settled
it. The constant then moved to `BaseSMU`.

So the test is written the way it is on purpose - **discovered from the
registry, not from a list maintained here**. A hand-kept list of drivers
would be one more thing to forget to update, and the sixth driver would
inherit the fix silently while inheriting no proof of it. A driver added
next year fails this file until it handles the sentinel, whether or not
its author has ever heard of +9.91e37.

Two drivers are exempt and each says why below.
"""
import pytest

from core.transports.base import Transport
from drivers.base_smu import BaseSMU
from drivers.dummy_smu import DummySMU
from drivers.registry import KNOWN_DRIVERS
from drivers.undalogic_minismu import UndalogicMiniSMU

#: The two values, exactly as an instrument sends them.
SENTINELS = {
    "not-a-number": "9.910000E+37",
    "over-range": "9.900000E+37",
}

#: Not text-protocol drivers, and each for a different reason.
EXEMPT = {
    # Driven through the minismu_py library rather than a text
    # protocol - it hands back Python floats, so there is no reply to
    # parse and no sentinel to meet. If that library ever grows one,
    # this exemption is where to start.
    UndalogicMiniSMU,
    # Simulated. It computes its readings, so it can only produce a
    # sentinel if someone writes one deliberately.
    DummySMU,
}

#: *IDN? replies, so each driver resolves and configures normally.
IDNS = {
    "Keithley2450": "KEITHLEY INSTRUMENTS,MODEL 2450,04412345,1.7.12b",
    "Keithley2401": "KEITHLEY INSTRUMENTS,MODEL 2401,01234567,C32",
    "Keithley2611A": "Keithley Instruments,MODEL 2611A,1398687,1.4.2",
    "GWInstekGSM20H10": "GW INSTEK,GSM-20H10,GEW852313,V1.10",
    "KeysightU2722A": "Agilent Technologies,U2722A,MY12345678,1.05",
    "KeysightB2901A": "Keysight Technologies,B2901A,MY51141631,3.4.2011",
}


class SentinelTransport(Transport):
    """An instrument whose every reading is the sentinel.

    Setup queries answer plausibly so each driver reaches its measure
    path; only the reading itself is the sentinel.
    """

    def __init__(self, payload, idn):
        super().__init__()
        self.payload = payload
        self.idn = idn
        self.connected = True
        self.last = ""

    def connect(self, address, **kw):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.last = text

    def _read(self, timeout_s=3.0):
        upper = self.last.upper()
        if "IDN" in upper:
            return self.idn
        if "ERR" in upper:
            return '0,"No error"'
        if "TRIP" in upper:
            return "0"
        if "COUN" in upper:
            return "2"
        return f"{self.payload},{self.payload}"


#: Which quantity comes first in a driver's combined reply.
#:
#: The 2611A is the odd one: TSP's `measure.iv()` gives current first,
#: then voltage - the opposite of everything else here, and a fact its
#: own tests already pin because getting it wrong transposes every
#: reading in every experiment while still producing plausible numbers.
#: A test that assumed one order for everybody would report that
#: correct behaviour as a fault, which is how a good test teaches
#: someone to "fix" working code.
REPLY_ORDER = {
    "Keithley2611A": ("amps", "volts"),
}
DEFAULT_ORDER = ("volts", "amps")

#: Drivers that measure with one query per quantity rather than parsing
#: a combined reply. There is no column to shift, so the check is that
#: one sentinel does not take the other reading down with it.
SPLIT_QUERY = {"KeysightU2722A"}

REAL_AMPS = 4.545455e-03


class SplitQueryTransport(SentinelTransport):
    """For drivers that ask for voltage and current separately.

    Voltage answers with the sentinel, current with a real reading, so
    the test can tell whether one bad quantity takes the other down
    with it.
    """

    def __init__(self, idn):
        super().__init__("9.910000E+37", idn)

    def _read(self, timeout_s=3.0):
        upper = self.last.upper()
        if "IDN" in upper:
            return self.idn
        if "ERR" in upper:
            return '0,"No error"'
        if "TRIP" in upper:
            return "0"
        if "COUN" in upper:
            return "2"
        if "CURR" in upper:
            return f"{REAL_AMPS:.6E}"
        return "9.910000E+37"


def text_protocol_drivers():
    return [cls for cls in KNOWN_DRIVERS if cls not in EXEMPT]


def test_the_exemptions_are_still_the_only_ones(check):
    """Guards the exemption list itself.

    An exemption is a claim about how a driver talks to its instrument.
    If a driver is removed from the registry this list goes stale
    silently, and a stale exemption is how a real driver ends up
    quietly excused from the check.
    """
    for cls in EXEMPT:
        check(f"{cls.__name__} is still registered", cls in KNOWN_DRIVERS)
    check("and there are drivers left to test",
          len(text_protocol_drivers()) >= 4,
          f"only {len(text_protocol_drivers())} would be checked")


@pytest.mark.parametrize("driver", text_protocol_drivers(),
                         ids=lambda c: c.__name__)
@pytest.mark.parametrize("label,payload", sorted(SENTINELS.items()),
                         ids=lambda v: v if isinstance(v, str) else "")
def test_no_driver_returns_a_sentinel_as_data(driver, label, payload, check):
    """Every text-protocol driver turns both sentinels into None."""
    smu = driver(SentinelTransport(payload, IDNS.get(driver.__name__, "x")))
    volts, amps = smu.measure()
    for name, value in (("volts", volts), ("amps", amps)):
        check(f"{driver.__name__} {label} {name} is not data",
              value is None,
              f"returned {value!r} - a reading 37 orders of magnitude out")


def test_a_real_reading_is_never_mistaken_for_one(check):
    """The threshold has to be above everything an SMU can produce.

    The largest quantity any instrument in this suite sources is 210 V,
    and the smallest current it measures is around 10 fA. Neither is
    within thirty orders of magnitude of the threshold, which is what
    makes a blanket magnitude test safe here.
    """
    for value in (210.0, -210.0, 3.03, 1e-14, 0.0, -1e-14, 1e30):
        check(f"{value:g} survives", BaseSMU.drop_sentinel(value) == value)
    for value in (9.91e37, -9.91e37, 9.9e37, 1e38):
        check(f"{value:g} is dropped", BaseSMU.drop_sentinel(value) is None)


def test_dropping_is_positional_not_by_omission(check):
    """A dropped voltage must not promote the current into its place.

    Filtering sentinels out of a list rather than replacing them shifts
    every later column left. The reading then comes back the right
    shape, wrong by a factor of the resistance, and indistinguishable
    from a real one afterwards - which is worse than the sentinel it
    was meant to fix, because a sentinel is at least obviously absurd.

    So the assertion is specific: the sentinel column is None *and* the
    other column still holds its own value. Checking only that one of
    them is None would pass an implementation that shifted.
    """
    for driver in text_protocol_drivers():
        name = driver.__name__
        idn = IDNS.get(name, "x")

        if name in SPLIT_QUERY:
            transport = SplitQueryTransport(idn)
        else:
            first, second = REPLY_ORDER.get(name, DEFAULT_ORDER)
            # The sentinel always sits in the voltage position,
            # whatever order this driver sends the pair in.
            values = {"volts": "9.910000E+37",
                      "amps": f"{REAL_AMPS:.6E}"}
            transport = SentinelTransport(
                f"{values[first]},{values[second]}", idn)
            transport.combined = True

        volts, amps = driver(transport).measure()
        check(f"{name}: the sentinel column is None", volts is None,
              f"got volts={volts!r}")
        check(f"{name}: the real column keeps its own value",
              amps is not None and abs(amps - REAL_AMPS) < 1e-9,
              f"got amps={amps!r} - the current may have shifted into "
              f"the voltage's place")


def test_no_driver_redeclares_the_threshold(check):
    """One definition, on BaseSMU.

    Two drivers had their own copy before the promotion. A driver that
    redeclares it can drift from the rest without anything noticing,
    which is the whole failure mode this file was written after.
    """
    for cls in KNOWN_DRIVERS:
        own = [k for k in cls.__mro__ if k is not BaseSMU
               and "NAN_THRESHOLD" in k.__dict__]
        check(f"{cls.__name__} inherits the threshold", not own,
              f"redeclared in {[k.__name__ for k in own]}")
