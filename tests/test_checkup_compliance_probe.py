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

from test_checkup_all_drivers import TSPTransport
from test_2635b import Keithley2635BTransport

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
], ids=lambda o: getattr(o, "__name__", str(o)))
def test_a_working_driver_reports_clamping(cls, transport_cls, check):
    """Both TSP drivers read `smuX.source.compliance`, and both should
    say True while the output rides the limit."""
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
