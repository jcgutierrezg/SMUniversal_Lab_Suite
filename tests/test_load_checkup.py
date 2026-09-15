"""The load checkup, and the one property that justifies its existence.

`Checkup` assumes nothing is connected, because for a source-measure
unit an open circuit is a *known* DUT. For a load it is the opposite: an
open circuit is the condition under which every reading is zero whether
the driver works or not, so an SMU checkup pointed at a load would run
to completion, report a clean sheet and prove nothing.

So the test that matters here is not "does it pass" - it is **does it
refuse to pass when it has learned nothing**. A skip is a gap in a
report; a pass earned against an open circuit is a false statement about
a driver, and it is the one this project has made most often.
"""
import pytest
from test_72_13200 import LoadTransport

from smuniversal_lab_suite.core.checkup import (
    Checkup,
    LoadCheckup,
    build_report,
    checkup_for,
)
from smuniversal_lab_suite.core.checkup.load import SOURCE_PRESENT_V
from smuniversal_lab_suite.drivers.dummy_smu import DummySMU
from smuniversal_lab_suite.core.transports.null_transport import NullTransport
from smuniversal_lab_suite.drivers.multicomp_72_13200 import (
    MulticompPro7213200,
)


def build(volts=0.0, amps=0.0, **kwargs):
    """A load with `volts` across its terminals. Zero means nothing
    attached, which is the case this file is really about."""
    transport = LoadTransport(volts=volts, amps=amps,
                              current_ceiling=30.0, voltage_ceiling=120.0,
                              **kwargs)
    return MulticompPro7213200(transport), transport


def severities(results, *names):
    by_name = {r.name: r.severity for r in results}
    return [by_name.get(n) for n in names]


# ---------------------------------------------------------------
# The property that justifies the file
# ---------------------------------------------------------------


def test_an_open_circuit_produces_skips_and_never_a_pass(check):
    """The whole reason a load needs its own checkup.

    With nothing attached the load sinks nothing, so a driver returning
    zeros from every method would satisfy any check written the way the
    SMU ones are. Tier 3 has to notice, and say so.
    """
    load, _ = build(volts=0.0, amps=0.0)
    results = LoadCheckup(load).run()

    tier3 = [r for r in results if r.tier == 3]
    check("tier 3 ran at all", tier3, "no tier 3 results")
    check("and passed nothing it could not have learned",
          not any(r.severity == "pass" for r in tier3
                  if "source is attached" not in r.name),
          [f"{r.name}={r.severity}" for r in tier3])

    attached = [r for r in tier3 if r.name == "a source is attached"]
    check("the absent source is reported as a skip", attached
          and attached[0].severity == "skip",
          [r.severity for r in attached])
    check("and the reason says why zeros prove nothing",
          attached and "whether this driver works or not"
          in attached[0].detail,
          attached[0].detail if attached else "")


def test_a_source_present_turns_the_live_checks_on(check):
    """With something attached the same checks become real."""
    load, transport = build(volts=5.0, amps=0.2)
    results = LoadCheckup(load).run()

    tracked, signed = severities(
        results,
        "ammeter tracks the commanded current",
        "a sink reads negative")
    check("the ammeter check ran", tracked == "pass", f"{tracked}")
    check("the sign check ran", signed == "pass", f"{signed}")


def test_the_sign_check_is_discriminating(check):
    """A driver that forgot the flip must fail it.

    Asked separately from the magnitude on purpose: a forgotten flip is
    out by exactly twice the current, which at a small probe level can
    still look close.
    """
    load, transport = build(volts=5.0, amps=0.2)

    # The instrument reporting a sink as positive, and the driver
    # passing it straight through - which is the bug.
    load.measure = lambda timeout_s=3.0: (5.0, +0.2)
    results = LoadCheckup(load).run()
    signed, = severities(results, "a sink reads negative")
    check("an inverted reading fails", signed == "fail", f"{signed}")


def test_the_threshold_is_what_decides_present(check):
    """Just under and just over `SOURCE_PRESENT_V`."""
    quiet, _ = build(volts=SOURCE_PRESENT_V * 0.5)
    loud, _ = build(volts=SOURCE_PRESENT_V * 2.0, amps=0.2)
    under, = severities(LoadCheckup(quiet).run(), "a source is attached")
    over, = severities(LoadCheckup(loud).run(), "a source is attached")
    check("below the threshold is a skip", under == "skip", f"{under}")
    check("above it is a pass", over == "pass", f"{over}")


# ---------------------------------------------------------------
# The error queue that is not there
# ---------------------------------------------------------------


def test_the_missing_error_queue_is_stated_once(check):
    """Not silently skipped, and not repeated after every group.

    A row reading "no errors" would be exactly the false reassurance
    this instrument cannot give; a row per group would bury the report
    in the same nothing.
    """
    load, _ = build(volts=5.0, amps=0.2)
    results = LoadCheckup(load).run()
    rows = [r for r in results if r.name == "error queue"]
    check("said exactly once", len(rows) == 1, f"{len(rows)} rows")
    check("as a warning, not a pass", rows and rows[0].severity == "warn",
          [r.severity for r in rows])
    check("and it says what that costs",
          rows and "ignored in silence" in rows[0].detail,
          rows[0].detail if rows else "")


# ---------------------------------------------------------------
# The guards are graded by asking them to refuse
# ---------------------------------------------------------------


def test_the_refusals_are_asked_for_not_read(check):
    """A guard is only worth having if it fires."""
    load, _ = build(volts=5.0, amps=0.2)
    results = LoadCheckup(load).run()
    for name in ("refuses to source",
                 "refuses a negative voltage",
                 "refuses a CV setpoint below the commanding floor",
                 "the headroom guard refuses below the floor"):
        got, = severities(results, name)
        check(f"{name}: passed", got == "pass", f"{got}")


def test_a_guard_that_stopped_refusing_fails(check):
    """Mutation, in a test rather than by hand.

    The refusal checks would be worthless if they graded anything other
    than the guard actually firing.
    """
    load, _ = build(volts=5.0, amps=0.2)
    load.set_current_level = lambda amps: None      # accepts anything
    results = LoadCheckup(load).run()
    got, = severities(results, "refuses to source")
    check("a guard that accepts is a failure", got == "fail", f"{got}")


# ---------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------


def test_the_input_is_never_left_on(check):
    for volts in (0.0, 5.0):
        load, transport = build(volts=volts, amps=0.2)
        LoadCheckup(load).run()
        check(f"{volts} V: input off afterwards", not transport.input_on,
              "the checkup left the load sinking")


def test_it_completes_and_renders(check):
    load, _ = build(volts=5.0, amps=0.2)
    checkup = LoadCheckup(load)
    results = checkup.run()
    check("it produced results", len(results) > 10, f"{len(results)}")
    report = build_report(load, results, address="COM6", open_circuit=False)
    check("the report renders", "Multicomp Pro 72-13200" in report)
    check("and names the driver", "MulticompPro7213200" in report)


def test_the_dispatcher_sends_each_fleet_to_its_own_checkup(check):
    """A load put through the SMU checkup would run to completion and
    prove nothing, which is the failure this dispatcher prevents."""
    load, _ = build()
    demo = NullTransport(); demo.connect("demo")
    check("a load gets the load checkup",
          isinstance(checkup_for(load), LoadCheckup))
    check("an SMU gets the SMU checkup",
          isinstance(checkup_for(DummySMU(demo)), Checkup)
          and not isinstance(checkup_for(DummySMU(demo)), LoadCheckup))


def test_every_registered_load_has_a_checkup_case(check):
    """The same rule the SMU fleet has: a driver cannot quietly opt out.

    `tests/test_checkup_all_drivers.py` enforces this for `KNOWN_SMUS`;
    this is the other half, and it is here rather than there because
    the two checkups take different arguments and grade different
    things.
    """
    from smuniversal_lab_suite.drivers.registry import KNOWN_LOADS

    covered = {MulticompPro7213200}
    missing = [c.__name__ for c in KNOWN_LOADS if c not in covered]
    check("every registered load is exercised here", not missing,
          f"no case for: {missing}")
