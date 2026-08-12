import pytest

pytestmark = [pytest.mark.slow]

import sys, os

"""The checkup runs against every registered driver, not just some.

`tools/smu_checkup.py` is written entirely against the BaseSMU contract
and the capability declarations, so in principle it works on anything in
the registry. "In principle" is not good enough for a bench tool: if it
crashes halfway through on the 2611A because TSP replies parse
differently, the operator finds out with the instrument powered up and
the report half-written.

So this drives the real checkup through the real drivers on each one's
existing fake transport - the same fakes the per-driver tests use, which
know each instrument's own dialect and quirks. What is being proved is
narrow but important:

  - the checkup completes on every registered driver, no crashes
  - it never leaves the output on
  - every declared capability gets exercised or explicitly skipped
  - the differences between instruments show up as skips, not failures

It is deliberately NOT asserting that every check passes. Some fakes do
not model everything - that is fine, and a fake reporting a fault is the
checkup working. What matters is that it runs to completion and reports
rather than falling over.
"""
from core.checkup import Checkup, build_report
from drivers.registry import KNOWN_DRIVERS
from core.transports.null_transport import NullTransport

from drivers.keithley_2450 import Keithley2450
from drivers.keithley_2401 import Keithley2401
from drivers.keithley_2611a import Keithley2611A
from drivers.keithley_2635b import Keithley2635B
from drivers.gwinstek_gsm20h10 import GWInstekGSM20H10
from drivers.keysight_u2722a import KeysightU2722A
from drivers.keysight_b2901a import KeysightB2901A
from drivers.undalogic_minismu import UndalogicMiniSMU
from drivers.dummy_smu import DummySMU

# Each driver's own fake, reused from the test that already models that
# instrument's dialect properly. Rebuilding them here would mean two
# fakes per instrument drifting apart.
from test_sweep_fallback import OhmicTransport
from test_2401_driver import Fake2401
from test_gsm20h10 import GSMTransport
from test_u2722a import U2722ATransport
from test_minismu import FakeTransport as MiniSMUFake
from test_b2901a import B2901ATransport
from test_2635b import Keithley2635BTransport


def minismu_transport():
    t = MiniSMUFake("1.5.0")
    t.connect("COM3")
    return t


def null_transport():
    t = NullTransport()
    t.connect("demo")
    return t


# The 2611A speaks TSP, and no existing fake models it - the 2450's
# ohmic fake answers SCPI. Rather than skip the one driver whose reply
# format is most unlike the others, it gets a minimal TSP fake here.
from core.transports.base import Transport


class TSPTransport(Transport):
    """A fake 2611A: TSP in, print()ed values out."""

    def __init__(self, resistance=1000.0):
        super().__init__()
        self.sent = []
        self.connected = True
        self.resistance = resistance
        self.level = 0.0
        self.mode = "voltage"
        self.output = False
        # The compliance limit, so `source.compliance` can be COMPUTED
        # from state rather than answered with a constant. It used to
        # return "false" unconditionally, which meant the checkup's new
        # "is it clamping?" probe passed against a fake that could not
        # have said otherwise - exactly the non-discriminating check
        # that probe exists to catch.
        self.voltage_limit = 20.0
        # The 2611A's sweep is a TSP library call that fills nvbuffer1,
        # and the driver polls `nvbuffer1.n` for progress. Without
        # modelling the buffer the checkup would sit through its full
        # 30 s sweep deadline here, proving nothing.
        self.buffer_n = 0
        self.sweep_points = 0

    def connect(self, address, **kw):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)
        if "smu.source.func" in text:
            self.mode = "current" if "OUTPUT_DCAMPS" in text else "voltage"
        if "smu.source.output" in text:
            self.output = "OUTPUT_ON" in text
        if "smu.source.limitv" in text:
            try:
                self.voltage_limit = float(text.split("=")[-1].strip())
            except ValueError:
                pass
        for key in ("smu.source.levelv", "smu.source.leveli"):
            if key in text:
                try:
                    self.level = float(text.split("=")[-1].strip())
                except ValueError:
                    pass
        if "nvbuffer1.clear" in text:
            self.buffer_n = 0
        if "SweepVLinMeasureI" in text or "SweepILinMeasureV" in text:
            # SweepVLinMeasureI(smu, start, stop, delay, points)
            try:
                args = text[text.index("(") + 1:text.rindex(")")].split(",")
                self.sweep_points = int(float(args[-1].strip()))
            except (ValueError, IndexError):
                self.sweep_points = 5
            self.buffer_n = self.sweep_points

    def _read(self, timeout_s):
        last = self.sent[-1] if self.sent else ""
        if "errorqueue.next()" in last:
            return "0\tQueue is empty\t0\t0"
        if "localnode.linefreq" in last:
            return "50"
        if "source.compliance" in last:
            # True exactly when the instrument cannot deliver what was
            # asked: sourcing a current whose Ohm's-law voltage exceeds
            # the limit, which is what an open circuit guarantees.
            if self.output and self.mode == "current":
                wanted = abs(self.level) * self.resistance
                return "true" if wanted >= self.voltage_limit else "false"
            return "false"
        if "localnode.model" in last or "*IDN" in last:
            return "Keithley Instruments Inc., Model 2611A, 1234567, 1.0"
        if "measure.iv()" in last:
            if self.mode == "voltage":
                volts = self.level
                amps = volts / self.resistance
            else:
                amps = self.level
                volts = amps * self.resistance
            # iv() returns CURRENT first, then voltage.
            return f"{amps:.6e}\t{volts:.6e}"
        if "nvbuffer1.n" in last:
            return str(self.buffer_n)
        if "printbuffer" in last:
            # sourcevalues then readings, comma separated, as the driver
            # asks for them.
            points = max(self.sweep_points, 1)
            step = 0.1 / max(points - 1, 1)
            values = []
            for i in range(points):
                volts = step * i
                values.append(volts if "sourcevalues" in last
                              else volts / self.resistance)
            return ", ".join(f"{v:.6e}" for v in values)
        return "0"


CASES = [
    ("Keithley2450", Keithley2450, OhmicTransport),
    ("Keithley2401", Keithley2401, Fake2401),
    ("Keithley2611A", Keithley2611A, TSPTransport),
    ("Keithley2635B", Keithley2635B, Keithley2635BTransport),
    ("GWInstekGSM20H10", GWInstekGSM20H10, GSMTransport),
    ("KeysightU2722A", KeysightU2722A, U2722ATransport),
    ("KeysightB2901A", KeysightB2901A, B2901ATransport),
    ("UndalogicMiniSMU", UndalogicMiniSMU, minismu_transport),
    ("DummySMU", DummySMU, null_transport),
]

# ---------------------------------------------------------------
# A. coverage: nothing in the registry is left untested
# ---------------------------------------------------------------


def test_every_driver_is_covered(check):
    covered = {name for name, _, _ in CASES}
    registered = {cls.__name__ for cls in KNOWN_DRIVERS}
    missing = sorted(registered - covered)
    check("every registered driver has a checkup case", not missing,
          f"no case for: {missing}" if missing else f"{len(covered)} drivers")

    # ---------------------------------------------------------------
    # B. the checkup completes on each one
    # ---------------------------------------------------------------


def test_checkup_runs_on_every_driver(check):
    global outcomes
    outcomes = {}
    for name, driver_cls, transport_factory in CASES:
        transport = transport_factory()
        if not getattr(transport, "connected", False):
            transport.connect("fake")
        driver = driver_cls(transport)

        try:
            c = Checkup(driver, open_circuit=False)
            c.run()
            crashed = None
        except Exception as exc:
            c = None
            crashed = f"{type(exc).__name__}: {exc}"

        check(f"{name}: the checkup runs to completion", crashed is None,
              crashed or "")
        if c is None:
            continue

        counts = c.counts()
        outcomes[name] = (c, counts)
        print(f"          {counts['pass']} pass, {counts['warn']} warn, "
              f"{counts['fail']} fail, {counts['skip']} skip")

        check(f"{name}: all three tiers ran",
              {r.tier for r in c.results} == {1, 2, 3},
              f"tiers seen: {sorted({r.tier for r in c.results})}")
        check(f"{name}: a meaningful number of checks ran",
              counts["pass"] + counts["fail"] >= 20,
              f"{counts['pass'] + counts['fail']} conclusive checks")

    # ---------------------------------------------------------------
    # C. the output is never left on
    # ---------------------------------------------------------------


def test_output_is_left_off_everywhere(check):
    for name, driver_cls, transport_factory in CASES:
        transport = transport_factory()
        if not getattr(transport, "connected", False):
            transport.connect("fake")
        driver = driver_cls(transport)
        Checkup(driver, open_circuit=False).run()

        # Each fake tracks the output differently; find whichever it has.
        state = None
        for attr in ("output", "_output_on", "output_enabled"):
            if hasattr(transport, attr):
                state = getattr(transport, attr)
                break
            if hasattr(driver, attr):
                state = getattr(driver, attr)
                break
        client = getattr(transport, "client", None)
        if client is not None and hasattr(client, "output"):
            state = client.output

        if state is None:
            print(f"  ....  {name}: fake does not track output state")
            continue
        check(f"{name}: output is off when the checkup ends", not state)

    # ---------------------------------------------------------------
    # D. capability differences show up as skips, not failures
    # ---------------------------------------------------------------


def test_capabilities_are_reported_not_failed(check):
    for name, (c, counts) in outcomes.items():
        cls = type(c.driver)
        skipped = " ".join(r.name + r.detail for r in c.results
                           if r.severity == "skip")

        if not cls.supports_ovp():
            check(f"{name}: no OVP is a skip", "OVP" in skipped)
        if not cls.supports_high_z_off():
            check(f"{name}: no high-Z is a skip", "high-Z" in skipped)
        if not cls.supports_nplc():
            check(f"{name}: no NPLC is a skip", "NPLC" in skipped)

    # The two instruments that cannot be forced to 2-wire must say so,
    # because it changes how the measurement checks should be read.
    for name in ("KeysightU2722A",):
        if name in outcomes:
            c, _ = outcomes[name]
            check(f"{name}: fixed sensing is noted in the report",
                  c._sensing_note is not None and "fixed" in c._sensing_note,
                  f"{c._sensing_note}")

    # ---------------------------------------------------------------
    # E. every driver produces a readable report
    # ---------------------------------------------------------------


def test_report_renders_for_every_driver(check):
    for name, (c, counts) in outcomes.items():
        report = build_report(c.driver, c.results, "fake", c._sensing_note,
                              open_circuit=False)
        check(f"{name}: the report names the instrument",
              type(c.driver).DISPLAY_NAME in report)
        check(f"{name}: and carries every result",
              all(f"| {r.name} |" in report for r in c.results))
