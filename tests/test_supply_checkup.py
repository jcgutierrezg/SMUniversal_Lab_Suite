"""The supply checkup, and whether its checks can fail.

A checkup that passes a working driver proves little. What makes one
worth running at a bench is that it **fails a broken one** - so most of
this file breaks the driver or the instrument on purpose and requires
the report to notice. Each of those is a mutation kept as a test.

The one that matters most is the error path. A supply here has no error
queue, only registers its driver decodes into one, and a decoder that
reads nothing reports "no error" as confidently as an instrument with
nothing to say. Every clean-register row in a report rests on the
checkup having first seen that register complain.
"""
import pytest
from test_tsx_p import SupplyTransport

from smuniversal_lab_suite.core.checkup import (
    Checkup,
    LoadCheckup,
    SupplyCheckup,
    build_report,
    checkup_for,
)
from smuniversal_lab_suite.core.transports.null_transport import NullTransport
from smuniversal_lab_suite.drivers.aimtti_tsx_p import (
    AimTTiTSX1820P,
    AimTTiTSX3510P,
)
from smuniversal_lab_suite.drivers.dummy_smu import DummySMU
from smuniversal_lab_suite.drivers.registry import KNOWN_SUPPLIES

#: Every registered supply, with the transport that plays it.
CASES = [(cls, cls.MODEL_IDS[0]) for cls in (AimTTiTSX3510P, AimTTiTSX1820P)]


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    """The checkup waits for the meters to catch up with a level it has
    just set - a second, on the real instrument. The fake has no meters
    to wait for."""
    from smuniversal_lab_suite.core.checkup import supply as supply_checkup

    for cls in KNOWN_SUPPLIES:
        monkeypatch.setattr(cls, "READBACK_SETTLE_S", 0.0)
    monkeypatch.setattr(supply_checkup, "QUIET_BUS_PAUSE_S", 0.0)


def build(cls=AimTTiTSX3510P, **kwargs):
    kwargs.setdefault("model", cls.MODEL_IDS[0])
    transport = SupplyTransport(**kwargs)
    return cls(transport), transport


def by_name(results):
    return {r.name: r for r in results}


def severity(results, name):
    result = by_name(results).get(name)
    return None if result is None else result.severity


# ---------------------------------------------------------------
# A working instrument
# ---------------------------------------------------------------


@pytest.mark.parametrize("cls,model", CASES, ids=[c[1] for c in CASES])
def test_a_working_supply_has_no_failures(cls, model, check):
    supply, wire = build(cls)
    checkup = SupplyCheckup(supply)
    results = checkup.run()
    failures = [f"{r.name}: {r.detail}" for r in results
                if r.severity == "fail"]
    check(f"{model}: no failures", not failures, failures)
    check(f"{model}: it ran all three tiers",
          {r.tier for r in results} == {1, 2, 3},
          sorted({r.tier for r in results}))
    check(f"{model}: it finished", not checkup._stopped_early)
    check(f"{model}: the instrument understood everything it was sent "
          f"on purpose", wire.esr == 0, f"esr left at {wire.esr}")


def test_every_registered_supply_has_a_checkup_case(check):
    """The rule the other two fleets have: a driver cannot quietly opt
    out of being run through its checkup offline."""
    covered = {cls for cls, _ in CASES}
    missing = [c.__name__ for c in KNOWN_SUPPLIES if c not in covered]
    check("every registered supply is exercised here", not missing,
          f"no case for: {missing}")


def test_the_output_is_never_left_on_or_left_armed(check):
    """Off, and with the voltage setting back at zero - because the
    setting is what the front-panel output key energises next."""
    # With and without the burst check, which ends by zeroing the
    # setting itself and so hides a live tier that forgot to.
    for load_ohms in (None, 10.0):
        for burst in (True, False):
            supply, wire = build(load_ohms=load_ohms)
            SupplyCheckup(supply,
                          open_circuit=load_ohms is None).run(burst=burst)
            case = f"load {load_ohms}, burst {burst}"
            check(f"{case}: output off", wire.output is False)
            check(f"{case}: voltage setting at zero",
                  wire.v_set == 0.0, f"left at {wire.v_set} V")
            check(f"{case}: trip restored to its widest",
                  wire.ovp == wire.ovp_high, f"left at {wire.ovp} V")


@pytest.mark.parametrize("cls,model", CASES, ids=[c[1] for c in CASES])
def test_the_setpoint_readbacks_pass_and_the_trip_still_warns(cls, model,
                                                              check):
    """The setpoint rows are a pass on both units: each one's readback
    was checked against values set at its front panel. The trip rows
    still warn - nobody has set a trip by hand."""
    supply, _ = build(cls)
    results = SupplyCheckup(supply).run(tiers=(2,), burst=False)
    rows = {name: [r.severity for r in results if r.name == name]
            for name in ("voltage setting read back",
                         "current setting read back",
                         "over-voltage trip read back")}
    check(f"{model}: voltage confirmed",
          rows["voltage setting read back"] == ["pass"], rows)
    check(f"{model}: current confirmed",
          rows["current setting read back"] == ["pass"], rows)
    check(f"{model}: the trip is still unverified",
          rows["over-voltage trip read back"] == ["warn", "warn"], rows)


# ---------------------------------------------------------------
# The quiet bus
# ---------------------------------------------------------------

QUIET = "a pause after a reading leaves no error"


def test_a_quiet_bus_is_recognised_and_the_report_says_it_happened(check):
    """An instrument that flags the pause, as both units do. The row
    passes, and says the flag was raised and set aside - which is not
    the same statement as nothing having been raised."""
    supply, _ = build(quiet_after=("IO?",))
    results = SupplyCheckup(supply).run(burst=False)
    row = by_name(results)[QUIET]
    check("it passes", row.severity == "pass", f"{row.severity}: "
          f"{row.detail}")
    check("and records that the instrument raised it",
          "set it aside" in row.detail and "0 time" not in row.detail,
          row.detail)
    check("no error-queue row failed because of it",
          not [r.name for r in results if r.severity == "fail"],
          [f"{r.name}: {r.detail}" for r in results
           if r.severity == "fail"])

    silent, _ = build()
    row = by_name(SupplyCheckup(silent).run(burst=False))[QUIET]
    check("a link that never raises it passes with that said instead",
          row.severity == "pass" and "did not report" in row.detail,
          row.detail)


def test_a_driver_that_reports_the_quiet_bus_fails_the_pause(check,
                                                             monkeypatch):
    """The mutation: the driver as it was before it recognised this.
    Every run that waits between samples would end uncertain."""
    from smuniversal_lab_suite.drivers import aimtti_tsx_p

    monkeypatch.setattr(aimtti_tsx_p, "QER_UNTERMINATED", 99)
    supply, _ = build(quiet_after=("IO?",))
    results = SupplyCheckup(supply).run(burst=False)
    row = by_name(results)[QUIET]
    check("the pause row fails", row.severity == "fail", row.severity)
    check("and says what it would cost",
          "uncertain shutdown" in row.detail, row.detail)


def test_it_renders_a_report(check):
    supply, _ = build()
    checkup = SupplyCheckup(supply)
    results = checkup.run()
    report = build_report(supply, results, address="GPIB0::11::INSTR")
    check("names the instrument", "Aim-TTi TSX3510P" in report)
    check("and the driver", "AimTTiTSX3510P" in report)
    check("it timed a reading",
          checkup._seconds_per_reading is not None
          and severity(results, "seconds per reading") == "pass")


# ---------------------------------------------------------------
# The error path has to be seen complaining
# ---------------------------------------------------------------


def test_the_error_path_is_proved_before_its_silence_is_trusted(check):
    supply, wire = build()
    results = SupplyCheckup(supply).run(tiers=(2,), burst=False)
    name = "the error path reports a rejected command"
    check("the probe was sent past the driver's guard", "I 0" in wire.sent,
          wire.sent[:12])
    check("and the complaint was required", severity(results, name) == "pass",
          by_name(results)[name].detail)
    order = [r.name for r in results]
    check("before any later row leaned on a clean register",
          order.index(name) < order.index("error queue after the two "
                                          "settings"), order)


def test_a_driver_that_cannot_read_its_errors_fails_the_probe(check):
    """The mutation this check exists for. `read_error()` stuck at "no
    error" passes every other row in the report."""
    supply, _ = build()
    supply.read_error = lambda: (0, "No error")
    results = SupplyCheckup(supply).run(tiers=(2,), burst=False)
    name = "the error path reports a rejected command"
    check("the probe fails", severity(results, name) == "fail",
          severity(results, name))
    check("and says what that undermines",
          "no clean error register" in by_name(results)[name].detail)
    others = [r for r in results if r.name.startswith("error queue after")]
    check("while every ordinary queue row still passes",
          others and all(r.severity == "pass" for r in others),
          [f"{r.name}={r.severity}" for r in others])


def test_an_instrument_that_numbers_the_error_differently_is_a_warning(
        check):
    supply, wire = build()
    reject = wire._reject
    wire._reject = lambda number: reject(119 if number == 103 else number)
    results = SupplyCheckup(supply).run(tiers=(2,), burst=False)
    name = "the error path reports a rejected command"
    check("rejected under another number: warn",
          severity(results, name) == "warn", severity(results, name))


def test_a_driver_with_no_probe_declared_says_what_is_unproven(check):
    supply, _ = build()
    type(supply).ERROR_PROBE, kept = None, type(supply).ERROR_PROBE
    try:
        results = SupplyCheckup(supply).run(tiers=(2,), burst=False)
    finally:
        type(supply).ERROR_PROBE = kept
    name = "the error path reports a rejected command"
    check("a skip, not a pass", severity(results, name) == "skip")


def test_a_setting_the_instrument_rejected_fails_the_queue(check):
    """An instrument that refuses the probe voltage - here, one whose
    range is narrower than the driver believes."""
    supply, wire = build()
    wire.vmax = 0.5
    results = SupplyCheckup(supply).run(tiers=(2,), burst=False)
    row = by_name(results)["error queue after the two settings"]
    check("the rejection is reported", row.severity == "fail", row.severity)
    check("under the instrument's own number", "100" in row.detail,
          row.detail)
    check("and the readback disagrees too",
          severity(results, "voltage setting read back") == "fail")


# ---------------------------------------------------------------
# The live checks can fail
# ---------------------------------------------------------------


def test_a_voltmeter_that_is_wrong_fails(check):
    supply, _ = build(volts_error=0.5)
    results = SupplyCheckup(supply).run(burst=False)
    check("a 0.5 V error is not within tolerance",
          severity(results, "voltmeter tracks the commanded voltage")
          == "fail")


def test_a_driver_returning_nothing_fails(check):
    supply, _ = build()
    supply.measure = lambda timeout_s=3.0: (None, None)
    results = SupplyCheckup(supply).run(burst=False)
    check("no reading is a failure", severity(results, "measure()") == "fail")


def test_a_driver_returning_the_current_as_the_voltage_fails(check):
    """Fault 21, as a mutation: the two quantities swapped."""
    supply, _ = build()
    real = supply.measure
    supply.measure = lambda timeout_s=3.0: tuple(reversed(real()))
    results = SupplyCheckup(supply).run(burst=False)
    check("swapped readings fail the voltmeter check",
          severity(results, "voltmeter tracks the commanded voltage")
          == "fail")


def test_open_circuit_never_passes_the_check_it_cannot_run(check):
    """Whether the current setting clamps needs a load. With nothing
    attached the supply is in constant voltage whatever the driver
    does, so that row must be a skip - fault 19 otherwise."""
    supply, _ = build()
    results = SupplyCheckup(supply).run(burst=False)
    name = "the current setting clamps, and the driver notices"
    check("skipped", severity(results, name) == "skip")
    check("and the sign of zero current is not graded either",
          severity(results, "a sourced current reads positive") == "skip")
    check("constant voltage is what it reports",
          severity(results, "regulation() once settled") == "pass",
          by_name(results)["regulation() once settled"].detail)
    check("and not clamped",
          severity(results, "compliance_tripped() open-circuit") == "pass")


def test_a_driver_claiming_to_be_clamped_open_circuit_fails(check):
    supply, _ = build()
    supply.compliance_tripped = lambda: True
    results = SupplyCheckup(supply).run(burst=False)
    check("clamped with nothing attached is a failure",
          severity(results, "compliance_tripped() open-circuit") == "fail")


def test_a_supply_whose_limit_register_says_nothing_is_a_warning(check):
    """Not what the 1820 does - it reports its mode on every read - but
    a unit that reported nothing must not be passed. The compliance
    column would be blank, and the report has to say so."""
    supply, wire = build(reasserts=False)
    wire._note_mode = lambda: None
    results = SupplyCheckup(supply).run(burst=False)
    check("unknown regulation warns",
          severity(results, "regulation() once settled") == "warn")
    check("and cannot-say is a warning, not a pass",
          severity(results, "compliance_tripped() open-circuit") == "warn")


def test_something_attached_is_recorded_and_not_graded(check):
    """1 V into 2 ohms against a 50 mA setting: current limit, 0.1 V at
    the terminals. Correct behaviour, and a failure if graded as an
    open circuit."""
    supply, _ = build(load_ohms=2.0)
    results = SupplyCheckup(supply, open_circuit=False).run(burst=False)
    check("the voltmeter check is skipped",
          severity(results, "voltmeter tracks the commanded voltage")
          == "skip")
    check("the sign is graded now that current flows",
          severity(results, "a sourced current reads positive") == "pass")
    check("nothing failed",
          not [r.name for r in results if r.severity == "fail"],
          [f"{r.name}: {r.detail}" for r in results
           if r.severity == "fail"])

    told_nothing, _ = build(load_ohms=2.0)
    results = SupplyCheckup(told_nothing).run(burst=False)
    check("left to assume an open circuit, it warns that current flows",
          severity(results, "open-circuit current is near zero") == "warn")


def test_a_sourced_current_of_the_wrong_sign_fails(check):
    supply, _ = build(load_ohms=2.0)
    real = supply.measure

    def inverted(timeout_s=3.0):
        volts, amps = real()
        return volts, -amps
    supply.measure = inverted
    results = SupplyCheckup(supply, open_circuit=False).run(burst=False)
    check("a negative sourced current fails",
          severity(results, "a sourced current reads positive") == "fail")


# ---------------------------------------------------------------
# The guards are graded by asking them to refuse
# ---------------------------------------------------------------

REFUSALS = (
    "refuses a negative voltage",
    "refuses to sink",
    "refuses a current setting below the floor",
    "refuses a current setting of zero",
    "the gate refuses a compliance below the floor",
    "refuses a voltage above the maximum",
    "refuses an over-voltage trip outside its range",
    "refuses a remote-sense request it cannot honour",
)


def test_the_refusals_are_asked_for_not_read(check):
    supply, wire = build()
    results = SupplyCheckup(supply).run(tiers=(2,), burst=False)
    for name in REFUSALS:
        check(f"{name}: passed", severity(results, name) == "pass",
              severity(results, name))
    check("and none of them reached the instrument",
          severity(results, "error queue after the refusals") == "pass")


@pytest.mark.parametrize("method,broken,names", [
    ("_checked_voltage", lambda volts: float(volts),
     ["refuses a negative voltage", "refuses a voltage above the maximum"]),
    ("_checked_current", lambda amps: float(amps),
     ["refuses to sink", "refuses a current setting below the floor",
      "refuses a current setting of zero"]),
    ("validate_source_point", lambda **kwargs: None,
     ["the gate refuses a compliance below the floor"]),
    ("set_remote_sense", lambda on=True: None,
     ["refuses a remote-sense request it cannot honour"]),
])
def test_a_guard_that_stopped_refusing_fails(method, broken, names, check):
    """Mutation, in a test rather than by hand."""
    supply, _ = build()
    setattr(supply, method, broken)
    results = SupplyCheckup(supply).run(tiers=(2,), burst=False)
    for name in names:
        check(f"without {method}: {name} fails",
              severity(results, name) == "fail", severity(results, name))


def test_a_guard_that_let_a_bad_setting_through_shows_in_the_queue(check):
    """The second line: with the driver's guard gone, the instrument's
    own rejection has to surface rather than vanish."""
    supply, _ = build()
    supply._checked_voltage = lambda volts: float(volts)
    results = SupplyCheckup(supply).run(tiers=(2,), burst=False)
    row = by_name(results)["error queue after the refusals"]
    check("the instrument's complaint is reported", row.severity == "fail",
          row.detail)


# ---------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------


def test_the_dispatcher_sends_each_fleet_to_its_own_checkup(check):
    from test_72_13200 import LoadTransport

    from smuniversal_lab_suite.drivers.multicomp_72_13200 import (
        MulticompPro7213200,
    )

    supply, _ = build()
    demo = NullTransport()
    demo.connect("demo")
    load = MulticompPro7213200(LoadTransport())
    check("a supply gets the supply checkup",
          type(checkup_for(supply)) is SupplyCheckup)
    check("a load still gets the load checkup",
          type(checkup_for(load)) is LoadCheckup)
    check("an SMU still gets the SMU checkup",
          type(checkup_for(DummySMU(demo))) is Checkup)
    check("and the supply checkup takes the open-circuit flag",
          checkup_for(supply, open_circuit=False).open_circuit is False)


def test_the_burst_check_runs_on_a_supply(check):
    supply, wire = build()
    results = SupplyCheckup(supply).run(tiers=(2,))
    row = by_name(results)[SupplyCheckup.BURST_NAME]
    check("it formed a burst and every query answered",
          row.severity == "pass", f"{row.severity}: {row.detail}")
    check("and left the voltage setting at zero afterwards",
          wire.v_set == 0.0, f"{wire.v_set}")
