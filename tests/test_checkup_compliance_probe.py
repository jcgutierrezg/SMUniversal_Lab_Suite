"""The checkup's "is it actually clamping?" probe.

Why this file exists
--------------------
`compliance_tripped()` was already exercised at tier 2 - but with the
output **off**, where the honest answer is False. A method that always
returned False, or always returned None, passed that check just as well
as a correct one. The bench reports for the 2635B and the B2901A both
show it: `compliance_tripped()` answered `False` at tier 2, and thirty
lines later the same instrument was riding a 10 V limit into an open
circuit with nothing asking it again.

That is the shape the B2901A's first sense-function probe had - counting
enabled measurement functions after a reset that had already enabled
them all - and the shape this project keeps having to relearn: **an
observation that would be identical whether or not the thing worked is
not evidence.**

The new probe asks at the one moment the answer is known in advance:
sourcing a current into an open circuit, immediately after the measured
voltage has been confirmed at the limit. True is the only correct answer
there.

What made this test necessary rather than optional
--------------------------------------------------
The existing checkup fakes model a 1 kohm resistor, so they never enter
compliance and the new branch was never reached by any of them. The
first version of this work would have shipped a probe that nothing ran.
So these tests drive the fakes as genuine open circuits, and assert all
four outcomes - True, False, None, and raising - are told apart.
"""
import pytest

from core.checkup import Checkup, PROBE_COMPLIANCE_V
from drivers.keithley_2611a import Keithley2611A
from drivers.keithley_2635b import Keithley2635B
from drivers.keysight_b2901a import KeysightB2901A

from test_checkup_all_drivers import TSPTransport
from test_2635b import Keithley2635BTransport
from test_b2901a import B2901ATransport

#: Large enough that the probe current cannot be delivered - an open
#: circuit is a resistor of some enormous value, and the instrument
#: must ride into the voltage limit trying to push current through it.
OPEN_CIRCUIT_OHMS = 1e12

PROBE_NAME = "compliance_tripped() while clamping"


def _run(driver):
    report = Checkup(driver, open_circuit=True).run()
    results = (report["results"] if isinstance(report, dict)
               else [r.as_dict() for r in report])
    return [r for r in results if PROBE_NAME in r["name"]]


def test_the_probe_is_reached_at_all(check):
    """Guards the mistake this file was written to catch.

    If the checkup stops entering compliance - a changed probe current,
    a reordered tier 3 - every assertion below would pass vacuously by
    finding nothing to assert on.
    """
    driver = Keithley2635B(Keithley2635BTransport(resistance=OPEN_CIRCUIT_OHMS))
    hits = _run(driver)
    check("the probe ran", len(hits) == 1,
          f"found {len(hits)} results named {PROBE_NAME!r} - if zero, the "
          f"checkup never reached compliance and the probe is dead code")


@pytest.mark.parametrize("cls,transport_cls", [
    (Keithley2611A, TSPTransport),
    (Keithley2635B, Keithley2635BTransport),
    (KeysightB2901A, B2901ATransport),
], ids=lambda o: getattr(o, "__name__", str(o)))
def test_a_working_driver_reports_clamping(cls, transport_cls, check):
    """Every driver that claims to report compliance must say True
    while the output rides the limit.

    The B2901A is here because it is the one this probe caught: it read
    `:SENS:CURR:PROT:TRIP?` regardless of what was being sourced, so
    sourcing current - which Van der Pauw and Hall both do - it asked
    about a protection that was not tripped and got an honest "0" to the
    wrong question.
    """
    transport = transport_cls(resistance=OPEN_CIRCUIT_OHMS)
    hits = _run(cls(transport))
    check(f"{cls.__name__}: the probe ran", len(hits) == 1)
    if hits:
        check(f"{cls.__name__}: reported clamping",
              hits[0]["severity"] == "pass",
              f"{hits[0]['severity']}: {hits[0]['detail']}")


def test_a_driver_that_says_fine_while_clamping_fails(check):
    """The failure worth catching.

    A sweep in compliance still draws a neat straight line with a
    convincing R-squared - the fit describes the limit rather than the
    sample - so a compliance flag stuck at False is worse than none at
    all. None means "cannot say"; False means "everything was fine".
    """
    class AlwaysFine(Keithley2635B):
        def compliance_tripped(self):
            return False

    hits = _run(AlwaysFine(Keithley2635BTransport(
        resistance=OPEN_CIRCUIT_OHMS)))
    check("the probe ran", len(hits) == 1)
    if hits:
        check("a stuck-False driver is a failure",
              hits[0]["severity"] == "fail",
              f"{hits[0]['severity']}: {hits[0]['detail']}")
        check("and the report says why it matters",
              "straight line" in hits[0]["detail"],
              hits[0]["detail"])


def test_a_driver_that_cannot_say_is_skipped_not_failed(check):
    """Most instruments here genuinely cannot report compliance.

    Recording that as a failure would put a permanent red mark on five
    drivers for a capability they do not have, and a report with
    permanent expected failures is one nobody reads.
    """
    class CannotSay(Keithley2635B):
        def compliance_tripped(self):
            return None

    hits = _run(CannotSay(Keithley2635BTransport(
        resistance=OPEN_CIRCUIT_OHMS)))
    check("the probe ran", len(hits) == 1)
    if hits:
        check("not reporting is a skip, not a failure",
              hits[0]["severity"] == "skip",
              f"{hits[0]['severity']}: {hits[0]['detail']}")


def test_a_raising_driver_is_reported_not_propagated(check):
    """A broken query must not take the whole checkup down - the run
    that would have diagnosed it is the one that dies."""
    class Broken(Keithley2635B):
        def compliance_tripped(self):
            raise RuntimeError("bus fell over")

    hits = _run(Broken(Keithley2635BTransport(resistance=OPEN_CIRCUIT_OHMS)))
    check("the probe ran and the checkup survived", len(hits) == 1)
    if hits:
        check("recorded as a failure", hits[0]["severity"] == "fail")
        check("naming the exception", "bus fell over" in hits[0]["detail"],
              hits[0]["detail"])


def test_the_fake_itself_can_answer_both_ways(check):
    """The fakes must compute compliance from state rather than return
    a constant.

    The checkup's TSP fake answered `"false"` unconditionally until this
    wave. Against that, a correct driver and a broken one are
    indistinguishable - the probe would have been non-discriminating in
    exactly the way it exists to prevent.
    """
    transport = Keithley2635BTransport(resistance=OPEN_CIRCUIT_OHMS)
    driver = Keithley2635B(transport)
    driver.reset()

    driver.set_source_function("current")
    driver.set_voltage_limit(PROBE_COMPLIANCE_V)
    driver.set_current_level(1e-6)
    driver.output_on()
    check("clamping into an open circuit reads True",
          driver.compliance_tripped() is True)

    driver.output_off()
    check("and not clamping with the output off reads False",
          driver.compliance_tripped() is False)


# ---------------------------------------------------------------------------
# What "at compliance" means: the settle, and both edges of the window
#
# Added 2026-08-21. The probe above asks `compliance_tripped()` at a
# moment it calls "demonstrably clamping", and until this wave it
# established that moment by testing a single lower bound on one
# reading. Two instruments showed what that misses, in opposite
# directions, and the fakes could show neither because they never
# clamped at all.
# ---------------------------------------------------------------------------

REACHED_NAME = "compliance reached on open circuit"


class RampingTransport(Keithley2635BTransport):
    """A fake whose output climbs to the limit over several readings.

    The GSM-20H10 on 2026-08-21: sourcing 1 uA into an open circuit, the
    measured voltage rose -0.1561, +0.1577, +0.4500, +0.6796, +0.9151 V
    against a 1 V limit - still climbing 0.23 V per reading when the
    checkup stopped looking, because the settle loop exited the instant
    a reading passed 80% of the limit. It then asked whether the output
    was clamping, was correctly told no, and recorded that as a failure.

    Roughly 1 uF being charged at 1 uA. Nothing was wrong with the
    instrument.
    """

    def __init__(self, *args, steps=5, **kwargs):
        super().__init__(*args, **kwargs)
        self._steps = steps
        self._reads = 0
        self._ramped_volts = 0.0

    def _reading_pair(self):
        amps, volts = super()._reading_pair()
        if self.source_func == "current" and self.output:
            self._reads += 1
            # Ramp linearly to whatever the clamp settled on, then stay.
            fraction = min(1.0, self._reads / float(self._steps))
            volts = volts * fraction
            amps = volts / self.resistance
            self._ramped_volts = volts
        return amps, volts

    def _read(self, timeout_s=3.0):
        """Report compliance from where the output *is*, not where it
        is heading.

        Without this the fake answered "clamping" from the first
        reading of the ramp - which is what a real instrument does not
        do, and it left this whole file unable to catch the fault it
        was written for. A mutation reintroducing the 80% early exit
        passed every test here, because the fake said True at 80%
        whether or not the probe had waited.

        The GSM-20H10 returned `0` from both trip queries at 0.9151 V of
        a 1 V limit, correctly: it was not clamping yet.
        """
        last = self.sent[-1] if self.sent else ""
        if ("source.compliance" in last
                and self.source_func == "current" and self.output):
            self.timeouts.append(timeout_s)
            return ("true" if abs(self._ramped_volts) >= self._voltage_limit()
                    else "false")
        return super()._read(timeout_s)


class UnclampedTransport(Keithley2635BTransport):
    """A fake whose limit is not in force: it holds a wider one.

    The U2722A on 2026-08-21. Its 1 V compliance was refused for being
    below 10% of the range the shared knob had been forced onto, so the
    range rail bounded the output instead and it settled at -2.0 V - and
    the probe recorded a pass, because -2.0 V clears a 0.8 V floor.
    """

    RAIL_V = 2.0

    def _reading_pair(self):
        if self.source_func == "current" and self.output:
            volts = -self.RAIL_V
            return volts / self.resistance, volts
        return super()._reading_pair()


def _all_results(driver):
    """Every result from ONE run.

    One run, because these fakes are stateful: `RampingTransport`
    consumes its ramp as it is read, so a second `Checkup` against the
    same transport starts already settled and proves nothing. That cost
    a mutation round - reintroducing the early exit passed, because the
    assertion that would have caught it was reading a second run whose
    output was no longer ramping.
    """
    report = Checkup(driver, open_circuit=True).run()
    return (report["results"] if isinstance(report, dict)
            else [r.as_dict() for r in report])


def _reached(driver):
    return [r for r in _all_results(driver) if r["name"] == REACHED_NAME]


def test_a_still_ramping_output_is_not_judged(check):
    """The GSM-20H10 case: keep looking until it stops moving.

    The interesting answer is the one this asks for. Under the previous
    loop the probe stopped at the first reading past 80%, called it
    compliance, and failed the driver for honestly saying it was not
    clamping yet. Here the ramp is slow enough that an 80% exit lands
    mid-climb, and the requirement is that the probe waits.
    """
    transport = RampingTransport(resistance=OPEN_CIRCUIT_OHMS, steps=5)
    results = _all_results(Keithley2635B(transport))
    reached = [r for r in results if r["name"] == REACHED_NAME]
    hits = [r for r in results if PROBE_NAME in r["name"]]

    check("the reached-compliance check ran", len(reached) == 1,
          f"found {len(reached)}")
    if reached:
        check("a settled output at the limit is a pass, not a skip",
              reached[0]["severity"] == "pass", reached[0]["detail"])

    # The one that catches the regression. An early exit lands mid-ramp,
    # where the instrument correctly says it is not clamping - so the
    # probe either skips without asking, or asks and blames the driver.
    check("the driver was asked whether it was clamping", len(hits) == 1,
          f"found {len(hits)} - the probe stopped before the output "
          f"settled, so it never asked")
    if hits:
        check("and the driver is not blamed for a ramp",
              hits[0]["severity"] == "pass", hits[0]["detail"])


def test_an_output_beyond_its_limit_fails(check):
    """The U2722A case, and the reason this is a failure and not a warn.

    An output sitting past its own compliance means the compliance is
    not being enforced at the value that was set. A compliance is the
    bound on what reaches the sample and the person at the fixture, so
    the one reading that proves it is not working must be the loudest
    result the probe can give.
    """
    driver = Keithley2635B(UnclampedTransport(resistance=OPEN_CIRCUIT_OHMS))
    reached = _reached(driver)
    check("the reached-compliance check ran", len(reached) == 1,
          f"found {len(reached)}")
    if reached:
        check("an output beyond its limit is a failure",
              reached[0]["severity"] == "fail", reached[0]["detail"])
        check("and the detail says the limit is not the one that was set",
              "not the one that was set" in reached[0]["detail"],
              reached[0]["detail"])


def test_a_healthy_clamp_may_sit_slightly_over_the_limit(check):
    """The miniSMU measured -1.023 V against a 1 V limit, working.

    So the ceiling cannot be the limit itself. This pins the decision:
    normal overshoot passes, and the failing case above is a factor of
    two away from it, not a few percent.
    """
    class OvershootTransport(Keithley2635BTransport):
        def _reading_pair(self):
            if self.source_func == "current" and self.output:
                volts = -1.023 * PROBE_COMPLIANCE_V
                return volts / self.resistance, volts
            return super()._reading_pair()

    reached = _reached(
        Keithley2635B(OvershootTransport(resistance=OPEN_CIRCUIT_OHMS)))
    check("the reached-compliance check ran", len(reached) == 1)
    if reached:
        check("2.3% of overshoot is still a healthy clamp",
              reached[0]["severity"] == "pass", reached[0]["detail"])


def test_an_output_that_never_arrives_warns_about_a_load(check):
    """The lower edge still has to work: settled, and nowhere near the
    limit, means something is drawing the current away."""
    class LoadedTransport(Keithley2635BTransport):
        def _reading_pair(self):
            if self.source_func == "current" and self.output:
                volts = 0.05 * PROBE_COMPLIANCE_V
                return volts / self.resistance, volts
            return super()._reading_pair()

    reached = _reached(
        Keithley2635B(LoadedTransport(resistance=OPEN_CIRCUIT_OHMS)))
    check("the reached-compliance check ran", len(reached) == 1)
    if reached:
        check("settled far below the limit warns",
              reached[0]["severity"] == "warn", reached[0]["detail"])
