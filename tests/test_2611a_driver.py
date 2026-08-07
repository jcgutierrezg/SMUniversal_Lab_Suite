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
    def __init__(self, current=2e-3, voltage=7.0):
        super().__init__()
        self.sent = []
        self.connected = True
        self.current = current
        self.voltage = voltage

    def connect(self, address, **kw):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)

    def _read(self, timeout_s):
        last = self.sent[-1] if self.sent else ""
        if "measure.iv()" in last:
            # TSP prints a returned tuple tab-separated, current first.
            return f"{self.current:.6e}\t{self.voltage:.6e}"
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
