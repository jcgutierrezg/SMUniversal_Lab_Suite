import re
import pytest

pytestmark = [pytest.mark.slow]

import sys, os

"""The instrument checkup.

A diagnostic that reports "all clear" on a broken instrument is worse
than no diagnostic, so most of this file is fault injection: take a
working driver, break one specific thing, and confirm the checkup
notices and says which thing.

The faults injected are the ones that have actually happened in this
project or were caught in review:

  - a command spelling the instrument rejects (the error queue is the
    only way to see this; it is why read_error was promoted to the
    contract)
  - measure() returning a single number instead of a (V, I) pair
  - a sweep that starts, reports complete, and returns nothing
  - a source that never moves because its range clamped it
  - MODEL_IDS that no longer matches what the instrument replies
  - a declared capability the hardware rejects
"""
import core.checkup as checkup_module
from core.checkup import (Checkup, build_report, PROBE_VOLTAGE,
                          PROBE_COMPLIANCE_V, SWEEP_POINTS)
from core.transports.null_transport import NullTransport
from drivers.dummy_smu import DummySMU
from drivers.base_smu import BaseSMU


def make(cls=DummySMU, **kwargs):
    """A driver on a demo transport.

    Note that every fault-injection subclass below inherits DummySMU's
    identity, so the registry resolves it to DummySMU and the "identity
    resolves to this driver" check fails for all of them. That is the
    check working correctly - a driver whose identity belongs to a
    different class really would be auto-detected wrongly - so the
    assertions here look for specific failures by name rather than
    counting them.
    """
    transport = NullTransport()
    transport.connect("demo")
    return cls(transport, **kwargs)


def run(driver, tiers=(1, 2, 3), open_circuit=False):
    c = Checkup(driver, open_circuit=open_circuit)
    c.run(tiers=tiers)
    return c


def names_of(results, severity):
    return [r.name for r in results if r.severity == severity]


def failed_containing(c, fragment):
    return [r for r in c.results
            if r.severity == "fail" and fragment.lower() in r.name.lower()]


# ---------------------------------------------------------------
# A. a healthy instrument passes
# ---------------------------------------------------------------


class ReturnsOneNumber(DummySMU):
    """measure() that returns a bare float - a parse that lost a column."""

    def measure(self, timeout_s=3.0):
        return 0.1


def test_healthy_instrument(check):
    c = run(make())
    counts = c.counts()
    check("nothing fails on a working driver", counts["fail"] == 0,
          f"failed: {names_of(c.results, 'fail')}")
    check("and a useful number of checks actually ran", counts["pass"] > 30,
          f"{counts['pass']} passed")
    check("all three tiers are represented",
          {r.tier for r in c.results} == {1, 2, 3})

    # The simulated instrument models a resistor, so the open-circuit
    # checks must be skipped rather than warned about - otherwise a demo
    # run looks broken and nobody trusts the tool.
    check("open-circuit checks are skipped when a sample is connected",
          any(r.severity == "skip" and "not checked" in r.detail
              for r in c.results))

    c_open = run(make(), open_circuit=True)
    check("and they warn when an open circuit was promised but not found",
          any(r.severity == "warn" for r in c_open.results),
          "the dummy always has a resistor across it")

    # ---------------------------------------------------------------
    # B. the error queue is what catches a bad command spelling
    # ---------------------------------------------------------------


def test_rejected_command_is_caught(check):
    class RejectsOneCommand(DummySMU):
        """An instrument that quietly does not understand set_current_limit.

    This is the failure mode SCPI instruments actually have: the command
    is logged to the error queue and ignored, the write returns
    normally, and nothing downstream can tell. Before read_error was in
    the contract, a checkup could not have seen this at all.
    """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._queue = []

        def set_current_limit(self, amps):
            self._queue.append((-113, "Undefined header"))

        def read_error(self):
            return self._queue.pop(0) if self._queue else (0, "")


    # Each setter is exercised in the source mode the experiments use it
    # in, so the check names carry a "[sourcing voltage]" suffix.
    c = run(make(RejectsOneCommand))
    bad = failed_containing(c, "error queue after set_current_limit")
    check("a rejected command is caught by the error-queue check", bool(bad),
          f"failures were {names_of(c.results, 'fail')}")
    if bad:
        check("and the instrument's own message is reported",
              "Undefined header" in bad[0].detail, bad[0].detail)
    check("the method call itself still looked fine",
          any(r.name.startswith("set_current_limit()") and r.severity == "pass"
              for r in c.results),
          "which is exactly why the queue check has to exist")

    # ---------------------------------------------------------------
    # C. measurement faults
    # ---------------------------------------------------------------


def test_measurement_faults(check):
    c = run(make(ReturnsOneNumber))
    check("measure() returning a single number is caught",
          bool(failed_containing(c, "measure()")),
          f"{names_of(c.results, 'fail')}")


    class ReturnsNone(DummySMU):
        """measure() whose reply could not be parsed at all."""

        def measure(self, timeout_s=3.0):
            return (None, None)


    c = run(make(ReturnsNone))
    bad = failed_containing(c, "measure()")
    check("an unparseable reading is caught", bool(bad))
    if bad:
        check("and the report explains what None means",
              "could not be parsed" in bad[0].detail, bad[0].detail)

    # ---------------------------------------------------------------
    # D. sweep faults
    # ---------------------------------------------------------------


def test_sweep_faults(check):
    class SweepReturnsNothing(DummySMU):
        """Reports complete, hands back an empty result.

    minismu_py 0.4.0 fixed a real bug of exactly this shape - CSV sweep
    retrieval returning only the first point - so it is worth proving
    the checkup would see it.
    """

        def read_sweep(self, points):
            return [], []


    c = run(make(SweepReturnsNothing))
    check("a sweep returning no data is caught",
          bool(failed_containing(c, "read_sweep")),
          f"{names_of(c.results, 'fail')}")


    class SweepNeverFinishes(DummySMU):
        """Reports zero points forever - a hardware sweep that never armed."""

        def sweep_points_ready(self):
            return 0


    # The real deadline is 30 s, which is right on a bench and far too long
    # in a test, so it is shortened for this one case. What is being proved
    # is that a stalled sweep ends as a reported failure rather than hanging
    # the tool.
    import core.checkup as cm
    original_wait = cm.Checkup._tier3_sweep


    def short_deadline(self):
        import time as _time
        real_monotonic = _time.monotonic
        start = real_monotonic()
        _time.monotonic = lambda: real_monotonic() + (
            60.0 if real_monotonic() - start > 0.3 else 0.0)
        try:
            return original_wait(self)
        finally:
            _time.monotonic = real_monotonic


    cm.Checkup._tier3_sweep = short_deadline
    try:
        c = run(make(SweepNeverFinishes))
    finally:
        cm.Checkup._tier3_sweep = original_wait

    bad = failed_containing(c, "sweep completes")
    check("a stalled sweep is reported as a failure, not a hang", bool(bad),
          f"{names_of(c.results, 'fail')}")
    if bad:
        check("and the report says how far it got",
              "0 of" in bad[0].detail, bad[0].detail)


    class SourceNeverMoves(DummySMU):
        """A source clamped by its range - the U2722A's R2V trap in miniature.

    The sweep completes, returns the right number of points, and every
    sourced value is the same. Point count alone would call this a pass.

    The measured currents are zeroed too, which is what separates this
    from a sweep the compliance limited: a source that is not stepping
    draws nothing, while one stopped by compliance is sitting at the
    limit. The checkup has to tell them apart or it cries wolf on every
    low-resistance sample.
    """

        def read_sweep(self, points):
            sourced, measured = super().read_sweep(points)
            return [0.0] * len(sourced), [0.0] * len(measured)


    class ComplianceStopsTheSweep(DummySMU):
        """A short span because the current hit the limit - not a fault."""

        def read_sweep(self, points):
            sourced, measured = super().read_sweep(points)
            from core.checkup import PROBE_COMPLIANCE_I
            return ([0.001] * len(sourced),
                    [PROBE_COMPLIANCE_I] * len(measured))


    c = run(make(SourceNeverMoves))
    bad = failed_containing(c, "actually moved")
    check("a sweep whose source never moves is caught", bool(bad),
          f"{names_of(c.results, 'fail')}")
    if bad:
        check("and the report suggests a clamp or a range",
              "clamped" in bad[0].detail or "range" in bad[0].detail,
              bad[0].detail)

    # The same short span, but at compliance, is the instrument working.
    c = run(make(ComplianceStopsTheSweep), open_circuit=False)
    check("a sweep stopped by compliance is not called a fault",
          not failed_containing(c, "actually moved"),
          f"{names_of(c.results, 'fail')}")
    check("it is recorded as expected with a sample connected",
          any(r.name == "the sweep actually moved" and r.severity == "skip"
              for r in c.results))

    c = run(make(ComplianceStopsTheSweep), open_circuit=True)
    check("but on a promised open circuit it warns that something is "
          "connected",
          any(r.name == "the sweep actually moved" and r.severity == "warn"
              for r in c.results),
          "an open circuit drawing compliance current is itself the finding")

    # ---------------------------------------------------------------
    # E. identity and auto-detection
    # ---------------------------------------------------------------


def test_identity_faults(check):
    class WrongModelIds(DummySMU):
        MODEL_IDS = ["NOTHING-LIKE-THIS"]


    c = run(make(WrongModelIds), tiers=(1,))
    bad = failed_containing(c, "resolves to this driver")
    check("MODEL_IDS that no longer match the reply is caught", bool(bad),
          "two drivers currently carry provisional MODEL_IDS, so this is "
          "the check that will fire first on the bench")
    if bad:
        check("and the report says auto-detect would pick wrongly",
              "auto-detect" in bad[0].detail, bad[0].detail)

    # ---------------------------------------------------------------
    # F. a declared capability the hardware rejects
    # ---------------------------------------------------------------


def test_declared_capability_rejected(check):
    class NplcDeclaredButRejected(DummySMU):
        """The ledger says it has NPLC; the instrument disagrees.

    Declining a capability that was never declared is correct behaviour
    and records as a skip. Declining one that WAS declared is a fault,
    and the checkup has to tell them apart.
    """

        def set_nplc(self, nplc):
            raise NotImplementedError("this unit has no integration control")


    c = run(make(NplcDeclaredButRejected), tiers=(1, 2))
    bad = failed_containing(c, "set_nplc")
    check("a declared capability the hardware rejects is a failure, not a skip",
          bool(bad), f"{names_of(c.results, 'fail')}")
    if bad:
        check("and it is reported as unexpected",
              "unexpectedly unsupported" in bad[0].detail, bad[0].detail)


    class NoMeasureRange(DummySMU):
        """No fixed measurement range - a real shape, and correct
        behaviour rather than a fault.

        Wave 6d-ii: the U2722A no longer refuses AUTO (it widens to its
        largest range instead), so this stands in for any model whose
        ledger says it has no measure-range axis at all. The base hook
        refuses out loud, and the checkup has to record that as a
        declined capability rather than a failure.
        """

        HAS_MEASURE_RANGE = False

        def _apply_measure_current_range(self, amps):
            raise NotImplementedError("no measurement range on this model")

        def _apply_measure_voltage_range(self, volts):
            raise NotImplementedError("no measurement range on this model")


    c = run(make(NoMeasureRange), tiers=(1, 2))
    check("an undeclared capability declining is a skip, not a failure",
          not failed_containing(c, "apply_ranges"),
          f"{names_of(c.results, 'fail')}")
    check("and it is recorded rather than passed over silently",
          any("apply_ranges" in r.name and r.severity == "skip"
              for r in c.results),
          f"{[(r.name, r.severity) for r in c.results if 'range' in r.name.lower()]}")

    # ---------------------------------------------------------------
    # G. the output is left off, whatever happens
    # ---------------------------------------------------------------


def test_output_is_left_off(check):
    class BlowsUpMidMeasurement(DummySMU):
        def read_sweep(self, points):
            raise RuntimeError("instrument fell over")


    driver = make(BlowsUpMidMeasurement)
    c = run(driver)
    check("a crash mid-checkup still fails loudly",
          bool(failed_containing(c, "read_sweep")),
          f"{names_of(c.results, 'fail')}")
    check("but the output is turned off afterwards",
          not driver._output_on,
          "a checkup that aborts with the terminals live is worse than none")
    check("and the cleanup is recorded",
          any("cleanup" in r.name for r in c.results))

    # tier 3 refuses to run at all if the output could not be turned off
    class CannotTurnOutputOff(DummySMU):
        def output_off(self):
            raise RuntimeError("relay stuck")


    c = run(make(CannotTurnOutputOff))
    check("tier 3 is skipped when the output cannot be turned off",
          any(r.tier == 3 and r.severity == "skip" and "not safe" in r.detail
              for r in c.results),
          "sourcing into an unknown state is not worth the information")

    # ---------------------------------------------------------------
    # H. sensing is forced to 2-wire where possible
    # ---------------------------------------------------------------


def test_sensing(check):
    driver = make()
    c = run(driver)
    check("2-wire is selected for the checkup",
          any(r.name.startswith("set_remote_sense(False)")
              and r.severity == "pass" for r in c.results),
          "open sense leads on an unconnected instrument can slew the "
          "output to compliance")


    class FixedFourWire(DummySMU):
        REMOTE_SENSE_CONTROL = False
        FIXED_SENSE = "4-wire (hardwired)"


    c = run(make(FixedFourWire))
    check("an instrument that cannot be switched is noted, not worked around",
          c._sensing_note is not None and "4-wire" in c._sensing_note,
          f"{c._sensing_note}")
    check("and it does not fail the checkup",
          not failed_containing(c, "remote_sense"))

    # ---------------------------------------------------------------
    # I. the report
    # ---------------------------------------------------------------
    # ---------------------------------------------------------------
    # J. setters are exercised in the mode the experiments use them in
    # ---------------------------------------------------------------


def test_setters_are_mode_aware(check):
    # A real instrument rejects the wrong combination and is right to:
    # setting a current level while sourcing voltage is a settings
    # conflict, and on the GSM-20H10 setting the source range while source
    # read-back is on is error 823. Both were reported as driver faults by
    # an earlier version of this checkup, and neither call is one the
    # application ever makes.
    c = run(make())
    names = [r.name for r in c.results if r.tier == 2]


    def exercised(setter, mode):
        return any(setter in n and f"sourcing {mode}" in n for n in names)


    check("current limit is set while sourcing voltage",
          exercised("set_current_limit", "voltage"))
    check("and the ranges, in one plan",
          exercised("apply_ranges", "voltage"))
    check("and the voltage level, which is the sourced quantity",
          exercised("set_voltage_level", "voltage"))
    check("voltage limit is set while sourcing current",
          exercised("set_voltage_limit", "current"))
    check("and the ranges, in one plan",
          exercised("apply_ranges", "current"))
    check("and the current level", exercised("set_current_level", "current"))

    check("the current level is NOT set while sourcing voltage",
          not exercised("set_current_level", "voltage"),
          "that combination is a settings conflict on real hardware")
    # Wave 6d-ii changed the premise of this one, so it changed with it.
    #
    # It used to assert that the checkup never sets a source range,
    # because error 823 ("invalid with source read-back on", seen on
    # both the 2401 and the GSM-20H10) is a combination the application
    # could not produce - `_one_sweep` only ever ranged the measured
    # quantity. That is no longer true: every experiment now fixes the
    # range of the quantity it sources, which is the whole point of the
    # ranging contract, and a sweep that autoranges its source walks
    # across range boundaries and leaves a step in the data.
    #
    # So the checkup must make the call, because the application makes
    # it. If 823 comes back on those two models it is a real finding
    # about a real code path rather than an artefact of the tool - which
    # is the only kind of failure a commissioning tool should report.
    check("the ranges of the sourced quantity are set, in one plan",
          exercised("apply_ranges", "voltage")
          and exercised("apply_ranges", "current"),
          "the checkup must exercise what the experiments now do")

    # ---------------------------------------------------------------
    # K. the driver's own post-sweep note is captured
    # ---------------------------------------------------------------


def test_post_sweep_note_is_captured(check):
    class DropsSweepPoints(DummySMU):
        """Returns fewer points than asked, and says why - as the GSM does
    when readings come back NAN or over-range."""

        def read_sweep(self, points):
            sourced, measured = super().read_sweep(points)
            self._note = "2 of 5 sweep points came back as NAN and were dropped"
            return sourced[:3], measured[:3]

        def sweep_note(self):
            return getattr(self, "_note", "")


    c = run(make(DropsSweepPoints))
    check("a short sweep is still reported as a failure",
          bool(failed_containing(c, "read_sweep")))
    check("but the driver's explanation is captured alongside it",
          any(r.name == "driver note after the sweep"
              and "NAN" in r.detail for r in c.results),
          "without this the shortfall looks unexplained when the driver "
          "already knows exactly why")

    # ---------------------------------------------------------------
    # L. integration time is restored before anything is measured
    # ---------------------------------------------------------------


def test_nplc_is_restored_before_measuring(check):
    # Found on a U2722A: its declared ceiling is 255 PLC, a 5.1 s aperture,
    # and with two queries per reading that is 10.5 s per point. Leaving it
    # there after the capability check made a 5-point sweep time out and
    # look broken, on an instrument doing exactly what it was told.
    driver = make()
    c = run(driver)
    nplc_calls = [r.name for r in c.results if "set_nplc" in r.name]
    check("both declared limits are exercised",
          sum(1 for n in nplc_calls if "declared limit" in n) == 2, nplc_calls)
    check("and the fast end is restored afterwards",
          any("restored for measuring" in n for n in nplc_calls), nplc_calls)
    check("the restore is the last NPLC call",
          "restored" in nplc_calls[-1], nplc_calls)
    check("the timing result names the NPLC it was measured at",
          any(r.name.startswith("time per reading at NPLC")
              for r in c.results),
          "an unqualified figure is one somebody will quote later")


    class SlowReadings(DummySMU):
        """A reading that takes long enough to blow a fixed deadline."""

        def measure(self, timeout_s=3.0):
            import time as _t
            _t.sleep(0.05)
            return super().measure(timeout_s)


    c = run(make(SlowReadings))
    check("a slow instrument still completes its sweep",
          not failed_containing(c, "sweep completes"),
          f"{names_of(c.results, 'fail')}")
    timing = [r for r in c.results if "time per reading" in r.name]
    check("and the measured cost per reading is recorded",
          timing and timing[0].elapsed_s >= 0.05,
          f"{timing[0].elapsed_s if timing else None}")

    # ---------------------------------------------------------------
    # M. one timeout must not look like three faults
    # ---------------------------------------------------------------


def test_timeout_recovery(check):
    # A 2401 on the bench produced one slow reading, then two more
    # failures and a warning - all from the same root cause. A timed-out
    # read leaves the reply in the output buffer, so the next query
    # collects the previous command's answer and the session runs one step
    # out of phase. Read as four findings, it sends you looking for three
    # faults that do not exist.


    class TimesOutOnce(DummySMU):
        """One slow reading, then fine again - if the session is cleared."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.failed = False
            self.cleared = False

        def measure(self, timeout_s=3.0):
            if not self.failed:
                self.failed = True
                raise TimeoutError("VI_ERROR_TMO (-1073807339): Timeout expired")
            return super().measure(timeout_s)


    class ClearingTransport(NullTransport):
        def __init__(self):
            super().__init__()
            self.cleared = 0

        def clear(self):
            self.cleared += 1
            return True


    transport = ClearingTransport()
    transport.connect("demo")
    driver = TimesOutOnce(transport)
    c = Checkup(driver, open_circuit=False)
    c.run()

    check("the timeout itself is reported", bool(failed_containing(c, "measure")))
    check("a device clear was sent to resynchronise", transport.cleared >= 1,
          f"cleared {transport.cleared} times")
    timeout_rows = [r for r in c.results if "not answering" in r.detail]
    check("and the failure says so", bool(timeout_rows),
          f"{[r.detail for r in c.results if r.severity == 'fail']}")
    check("recovery means later checks are not blamed on it",
          "should be independent" in timeout_rows[0].detail
          if timeout_rows else False)
    check("the rest of the checkup still ran",
          any(r.tier == 3 and "sweep" in r.name for r in c.results),
          "one bad reading should not end the run")


    class TransportThatCannotClear(NullTransport):
        def clear(self):
            return False


    transport = TransportThatCannotClear()
    transport.connect("demo")
    c = Checkup(TimesOutOnce(transport), open_circuit=False)
    c.run()
    suspect = [r for r in c.results if "MAY BE" in r.detail]
    check("an unrecoverable timeout warns that later failures may be "
          "consequences", bool(suspect),
          "otherwise one root cause reads as several independent faults")

    report = build_report(c.driver, c.results, "demo", None, open_circuit=False)
    check("and the report says so up front", "out of step" in report)

    check("the base transport declines to clear rather than pretending",
          NullTransport().clear() is False,
          "a clear that silently did nothing would be worse than none")

    # The two messages must not be interchangeable: one says later results
    # can be trusted, the other says they cannot, and that is the whole
    # value of the distinction.
    transport = ClearingTransport()
    transport.connect("demo")
    c = Checkup(TimesOutOnce(transport), open_circuit=False)
    c.run()
    recovered = [r for r in c.results if "not answering" in r.detail]
    check("a recovered timeout does NOT warn about later failures",
          recovered and "MAY BE" not in recovered[0].detail,
          f"{recovered[0].detail if recovered else None}")

    # ---------------------------------------------------------------
    # N. read timeouts scale with the integration time
    # ---------------------------------------------------------------


def test_read_timeout_scales_with_nplc(check):
    # A 2401 at NPLC 10 that has to autorange on the way takes longer than
    # measure()'s 3 s default, and the timeout it produces looks like a
    # broken instrument rather than a slow one.


    class RecordsTimeout(DummySMU):
        NPLC_RANGE = (5.0, 50.0)      # a slow instrument

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.timeouts_seen = []

        def measure(self, timeout_s=3.0):
            self.timeouts_seen.append(timeout_s)
            return super().measure(timeout_s)


    driver = make(RecordsTimeout)
    run(driver)
    check("measure() is given a timeout, not left at its default",
          driver.timeouts_seen and all(t > 3.0 for t in driver.timeouts_seen),
          f"{sorted(set(driver.timeouts_seen))}")
    check("and it allows for the aperture in use",
          max(driver.timeouts_seen) >= 5.0 / 50.0 * 4,
          f"{max(driver.timeouts_seen)} s for a {5.0 / 50.0:.2g} s aperture")

    # ---------------------------------------------------------------
    # O. compliance is judged by magnitude, not sign
    # ---------------------------------------------------------------


def test_compliance_sign_is_not_judged(check):
    # A miniSMU reported -1.02 V while sourcing +1 uA into an open circuit,
    # and an earlier version of this checkup warned that its polarity was
    # inverted. It is not: a 10 kohm resistor gave R = +9.95 kohm with
    # positive current producing positive voltage.
    #
    # The mistake was judging polarity where the instrument was not
    # regulating. It measured -1.2e-10 A against a requested +1 uA - it was
    # railed, and which rail a saturated loop picks is implementation-
    # defined. A false alarm on a commissioning tool is expensive: it sends
    # someone to the bench after a fault that is not there.


    class RailsToCompliance(DummySMU):
        """Reaches its voltage limit when sourcing current, as a real SMU
    does into an open circuit."""

        SIGN = 1.0

        def set_source_function(self, mode):
            self._mode = mode
            return super().set_source_function(mode)

        def measure(self, timeout_s=3.0):
            if getattr(self, "_mode", "voltage") == "current":
                return (self.SIGN * PROBE_COMPLIANCE_V, 1e-11)
            return super().measure(timeout_s)


    class RailsNegative(RailsToCompliance):
        SIGN = -1.0


    for label, cls in (("positive", RailsToCompliance),
                       ("negative", RailsNegative)):
        c = run(make(cls), open_circuit=True)
        rows = [r for r in c.results
                if r.name == "compliance reached on open circuit"]
        check(f"railing {label} passes - the magnitude is what matters",
              rows and rows[0].severity == "pass",
              f"{rows[0].severity if rows else 'no row'}")

    check("and the report says why the sign was not judged",
          "sign not checked" in rows[0].detail, rows[0].detail)


    class NeverReachesCompliance(RailsToCompliance):
        """Settles low and stays there - what a real load looks like."""
        SIGN = 0.001


    c = run(make(NeverReachesCompliance), open_circuit=True)
    rows = [r for r in c.results
            if r.name == "compliance reached on open circuit"]
    check("an output that settles low IS flagged",
          rows and rows[0].severity == "warn",
          f"{rows[0].severity if rows else 'no row'} - with nothing "
          f"connected the output should ride up to compliance")
    if rows:
        check("and the wording says it stopped rising",
              "stopped rising" in rows[0].detail, rows[0].detail[:70])


    class StillRamping(DummySMU):
        """Climbs steadily without reaching the limit inside the budget.

    This is what a U2722A does: sourcing 1 uA into an open circuit
    charges roughly 1.2 uF of its own output capacitance, about 1 V/s,
    so a 1 V limit takes over a second. Read once after 50 ms it looks
    like a 41 mV clamp, and an earlier version of this checkup told the
    operator to go and check the terminals.
    """

        def set_source_function(self, mode):
            self._mode = mode
            return super().set_source_function(mode)

        def measure(self, timeout_s=3.0):
            if getattr(self, "_mode", "voltage") == "current":
                self._v = getattr(self, "_v", 0.0) + 0.02
                return (self._v, 1e-11)
            return super().measure(timeout_s)


    c = run(make(StillRamping), open_circuit=True)
    rows = [r for r in c.results
            if r.name == "compliance reached on open circuit"]
    check("an output still climbing is NOT called a load",
          rows and rows[0].severity == "skip",
          f"{rows[0].severity if rows else 'no row'}")
    if rows:
        check("and the report explains it is charging its own capacitance",
              "charging its own capacitance" in rows[0].detail
              and "Not a load" in rows[0].detail, rows[0].detail[:80])


    class SlowButArrives(DummySMU):
        """Ramps, and does reach compliance within the budget."""

        def set_source_function(self, mode):
            self._mode = mode
            return super().set_source_function(mode)

        def measure(self, timeout_s=3.0):
            if getattr(self, "_mode", "voltage") == "current":
                self._v = min(getattr(self, "_v", 0.0) + 0.35,
                              PROBE_COMPLIANCE_V)
                return (self._v, 1e-11)
            return super().measure(timeout_s)


    c = run(make(SlowButArrives), open_circuit=True)
    rows = [r for r in c.results
            if r.name == "compliance reached on open circuit"]
    check("polling lets a slow output arrive and pass",
          rows and rows[0].severity == "pass",
          f"{rows[0].severity if rows else 'no row'} - a single read after "
          f"50 ms would have missed it")

    # ---------------------------------------------------------------
    # P. the integration time can be set deliberately
    # ---------------------------------------------------------------


def test_requested_nplc(check):
    # Two open questions need the same measurement: whether the 2611A's
    # measure.iv() costs one aperture or two, and whether the miniSMU's OSR
    # really runs at 1000 S/s. Both are answered by timing a reading at a
    # LONG integration time and comparing with the fast one - so the
    # checkup has to be able to measure at a chosen NPLC rather than always
    # at the fast end.
    driver = make()
    c = Checkup(driver, open_circuit=False, nplc=10)
    c.run(tiers=(1, 2, 3))
    names = [r.name for r in c.results if "set_nplc" in r.name]
    check("the requested value is used, not the fast end",
          any("requested" in n for n in names), names)
    check("and it is what the timing is reported against",
          any(r.name == f"time per reading at NPLC {DummySMU.clamp_nplc(10):g}"
              for r in c.results),
          [r.name for r in c.results if "time per reading" in r.name])
    check("the declared limits are still both exercised first",
          sum(1 for n in names if "declared limit" in n) == 2, names)

    c = Checkup(make(), open_circuit=False)
    c.run(tiers=(1, 2))
    check("without the flag it still restores the fast end",
          any("restored for measuring" in r.name for r in c.results))

    # ---------------------------------------------------------------
    # Q. the command trace
    # ---------------------------------------------------------------


def test_command_trace(check):
    # A result row names the CHECK that failed. When the failure is a
    # timeout that says nothing about which command caused it - the 2401's
    # current-source reading times out somewhere among six commands and the
    # report cannot say which. The trace can.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "smu_checkup",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "tools", "smu_checkup.py"))
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    transport = NullTransport()
    transport.connect("demo")
    trace = []
    cli.install_trace(transport, trace)
    transport.query("*IDN?")
    transport.write("SOMETHING")
    check("queries are recorded with their replies",
          any("*IDN?" in sent and reply for _, sent, reply in trace), trace)
    check("writes are recorded too",
          any("SOMETHING" in sent for _, sent, _ in trace))
    check("and each carries an elapsed time",
          all(isinstance(e, float) for e, _, _ in trace))


    class ExplodingTransport(NullTransport):
        def _read(self, timeout_s):
            raise TimeoutError("VI_ERROR_TMO")


    transport = ExplodingTransport()
    transport.connect("demo")
    trace = []
    cli.install_trace(transport, trace)
    try:
        transport.query(":READ?")
    except TimeoutError:
        pass
    check("a failing command is recorded, not lost",
          any(":READ?" in sent and "!!" in reply for _, sent, reply in trace),
          trace)
    check("which is the whole point - the failure names the command",
          any("TimeoutError" in reply for _, _, reply in trace))

    # ---------------------------------------------------------------
    # R. apertures per reading, measured rather than assumed
    # ---------------------------------------------------------------


def test_apertures_per_reading(check):
    # "Does measure() cost one integration or two?" has come up for three
    # instruments now, and a single timing figure cannot answer it - the
    # aperture is buried under bus overhead at the fast end and dominates
    # at the slow end. Two points on the SAME instrument give the slope.
    # Comparing across separate runs does not work: per-reading overhead
    # varied eightfold between two machines here.


    class TwoAperturesPerReading(DummySMU):
        """Integrates voltage and current separately, like the U2722A."""

        APERTURES = 2.0
        OVERHEAD_S = 0.01

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._nplc_now = 1.0

        def set_nplc(self, nplc):
            self._nplc_now = self.clamp_nplc(nplc)
            return super().set_nplc(nplc)

        def measure(self, timeout_s=3.0):
            import time as _t
            _t.sleep(self.OVERHEAD_S
                     + self.APERTURES * self._nplc_now / 50.0)
            return super().measure(timeout_s)


    class OneAperturePerReading(TwoAperturesPerReading):
        APERTURES = 1.0


    for label, cls, expected in (("two", TwoAperturesPerReading, 2.0),
                                 ("one", OneAperturePerReading, 1.0)):
        c = Checkup(make(cls), open_circuit=False, nplc=10)
        c.run(tiers=(1, 2, 3))
        rows = [r for r in c.results if r.name == "apertures per reading"]
        check(f"{label} apertures is measured as {expected:g}",
              rows and abs(rows[0].elapsed_s - expected) < 0.35,
              f"{rows[0].elapsed_s if rows else 'no row'}")

    check("the report explains what the number means",
          rows and "integrated separately" in rows[0].detail)


    class MostlyOverhead(TwoAperturesPerReading):
        """Integration is a small part of each reading.

    The slope is then weakly determined: a few ms of drift moves it a
    long way. This is exactly why the miniSMU's cross-session estimate
    was wrong by a factor of five while the U2722A's survived - 5 ms of
    integration against 6-29 ms of overhead, versus 500 ms against
    35 ms.
    """

        APERTURES = 2.0
        OVERHEAD_S = 2.0


    c = Checkup(make(MostlyOverhead), open_circuit=False, nplc=1)
    c.run(tiers=(1, 2, 3))
    rows = [r for r in c.results if r.name == "apertures per reading"]
    check("an overhead-dominated reading says its slope is weak",
          rows and "weakly determined" in rows[0].detail,
          rows[0].detail[-90:] if rows else "no row")
    check("and suggests what to do about it",
          rows and "slower NPLC" in rows[0].detail)

    c = Checkup(make(TwoAperturesPerReading), open_circuit=False, nplc=10)
    c.run(tiers=(1, 2, 3))
    rows = [r for r in c.results if r.name == "apertures per reading"]
    check("while an integration-dominated one does not",
          rows and "weakly determined" not in rows[0].detail,
          rows[0].detail[-70:] if rows else "no row")


    class ClaimsTooLongAnAperture(TwoAperturesPerReading):
        """Reads far quicker than its declared NPLC implies.

    Impossible in reality: a reading cannot be shorter than the
    integration it claims. It means the driver's aperture model is
    wrong, and the NPLC going into every CSV with it. The miniSMU was
    out by a factor of eighteen this way.
    """

        APERTURES = 0.05


    c = Checkup(make(ClaimsTooLongAnAperture), open_circuit=False, nplc=10)
    c.run(tiers=(1, 2, 3))
    rows = [r for r in c.results if r.name == "apertures per reading"]
    check("an impossible sub-one figure is flagged",
          rows and rows[0].severity == "warn",
          f"{rows[0].severity if rows else 'no row'}")
    if rows:
        # The multiplier is a measured quantity, so it is checked as one.
        # Asserting the literal string "20x" made this test depend on
        # clock resolution: on Windows time.monotonic() ticks every
        # 15.6 ms, and the 10 ms interval this scenario builds came out
        # as 33x there while reading 20x on Linux. The band below is
        # wide enough for timing jitter and still tight enough to catch
        # a real change in the aperture model.
        stated = re.search(r"about (\d+)x too long", rows[0].detail)
        check("and the report says the recorded NPLC is overstated",
              "overstated" in rows[0].detail and stated is not None
              and 10 <= int(stated.group(1)) <= 40,
              rows[0].detail[-90:])

    c = Checkup(make(TwoAperturesPerReading), open_circuit=False)
    c.run(tiers=(1, 2, 3))
    check("without --nplc there is no second point, so it is not reported",
          not any(r.name == "apertures per reading" for r in c.results),
          "one timing figure cannot give a slope")

    # ---------------------------------------------------------------
    # S. the output must be re-enabled after a source-function change
    # ---------------------------------------------------------------


def test_output_reenabled_after_mode_change(check):
    # The 2401 spent two rounds of bench diagnosis looking like a broken
    # instrument. Its documentation explains it: changing the source
    # function drops the output, and with auto output-off disabled "the
    # output must be turned on before you can perform a :READ?". `:READ?`
    # is :INITiate then :FETCh?, and :FETCh? only runs once the
    # source-measure operations complete - which, with the output off, they
    # never do. So the query blocks until the VISA timeout and reports a
    # comms failure for a configuration mistake.
    #
    # Every experiment already calls output_on() after
    # set_source_function(). The checkup did not.


    class DropsOutputOnModeChange(DummySMU):
        """Behaves like the 2400 family: the output goes off when the
    source function changes, and a reading with it off hangs."""

        def set_source_function(self, mode):
            result = super().set_source_function(mode)
            self._output_on = False
            return result

        def measure(self, timeout_s=3.0):
            if not self._output_on:
                raise TimeoutError(
                    "VI_ERROR_TMO: Timeout expired before operation completed")
            return super().measure(timeout_s)


    driver = make(DropsOutputOnModeChange)
    c = run(driver)
    check("no reading times out",
          not any(r.severity == "fail" and "measure" in r.name
                  for r in c.results),
          f"{names_of(c.results, 'fail')}")
    check("the output is re-enabled after the mode change",
          any("after the mode change" in r.name and r.severity == "pass"
              for r in c.results),
          [r.name for r in c.results if "output_on" in r.name])
    check("and the sweep still runs afterwards",
          not failed_containing(c, "sweep"),
          f"{names_of(c.results, 'fail')}")
    check("the output is still off at the end",
          not driver._output_on)

    check("the contract says the output state is undefined afterwards",
          "undefined" in (BaseSMU.set_source_function.__doc__ or "").lower(),
          "an instrument-specific trap that callers have to know about")


def test_report(check):
    c = run(make())
    report = build_report(c.driver, c.results, "demo", c._sensing_note,
                          open_circuit=False)
    check("names the instrument", DummySMU.DISPLAY_NAME in report)
    check("leads with a verdict", "**Result:**" in report)
    check("says something is connected when that was declared",
          "something is connected" in report)
    check("has a section per tier",
          report.count("## Tier") == 3, f"{report.count('## Tier')}")
    check("every result appears as a row",
          all(f"| {r.name} |" in report for r in c.results))

    c = run(make(ReturnsOneNumber))
    report = build_report(c.driver, c.results, "demo", None)
    check("a failing checkup says FAIL at the top",
          "**Result:** FAIL" in report)
    check("and lists the failures before the detail tables",
          report.index("## Failures") < report.index("## Tier 1"))

    c = run(make(), open_circuit=True)
    report = build_report(c.driver, c.results, "demo", None, open_circuit=True)
    check("warnings get their own section", "## Warnings" in report)
    check("and the verdict distinguishes them from failures",
          "PASS WITH WARNINGS" in report)
