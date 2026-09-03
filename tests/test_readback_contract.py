import pytest

pytestmark = [pytest.mark.slow]


"""The readback contract, the instrument-aware probe, and the two guards.

Everything the software sends an instrument is a *request*. Until
something reads it back, the only evidence that the instrument is in the
state the software believes it is in is that the write did not raise -
and a wrong header does not raise, it is logged and ignored while the
previous setting stays in force.

This file holds three things that were open until the readback contract
landed, and the reason each mattered is a measurement rather than an
argument:

  1. **The probe was a module-wide constant.** `PROBE_CURRENT = 1e-6`
     went to every instrument in the registry. On the U2722A the
     shared-knob reconciliation puts the current axis on R120mA, where
     one count is 7.32 uA, so 1 uA is a seventh of a count - and below a
     count the output is offset residue whose *sign is not the one
     commanded*. The driver refuses it, correctly, which made the
     checkup **structurally unable to pass** on a working instrument.

  2. **`apply_ranges()` reported what it sent.** On the GSM-20H10,
     asking for a 100 uA measurement range with a 10 uA compliance in
     force gives `+824` and leaves `SENS:CURR:DC:RANG?` reading
     `1.050000E-05`. No exception, and every reading afterwards taken on
     a range the operator did not choose.

  3. **`limitp` on the 2635B was a ceiling nothing watched.** Power
     compliance applies whichever of the three limits is lower, and
     `limitv` reads back the programmed value rather than the effective
     one - so the readback that already existed could not see it.

What is asserted here is narrow and deliberate. Not that any instrument
is in a good state: these are fakes, and a fake proves nothing about
hardware. What is proved is that **every outcome is told apart**, that
the one outcome rendering as a pass cannot be reached without a bench
session behind it, and that the two guards fire.

Every check has a control leg, because this project's most repeated
fault is a probe asked where the answer is already known.
"""
import math

from test_2635b import Keithley2635BTransport
from test_gsm20h10 import GSMTransport
from test_u2722a import U2722ATransport

from core import readback as readback_states
from core.checkup import (
    PROBE_COMPLIANCE_I,
    PROBE_COMPLIANCE_V,
    PROBE_CURRENT,
    PROBE_VOLTAGE,
    Checkup,
    probe_levels_for,
)
from core.ranges import RangeError
from core.transports.null_transport import NullTransport
from drivers.base_smu import BaseSMU
from drivers.gwinstek_gsm20h10 import GWInstekGSM20H10
from drivers.keithley_2635b import Keithley2635B
from drivers.keysight_u2722a import KeysightU2722A
from drivers.registry import KNOWN_DRIVERS


class AnyTransport(NullTransport):
    """A NullTransport with a `client`, so every driver accepts it.

    The miniSMU refuses a transport without one - it is driven through a
    library rather than a text protocol - and the alternative to this is
    exempting the one driver in the registry that checks. Nothing here
    calls the client.
    """
    client = object()


def any_driver(cls):
    transport = AnyTransport()
    transport.connect("demo")
    return cls(transport)


def rows(results, fragment):
    """`(name, severity, detail)` for every result whose name matches.

    A soft-assertion detail that says only "this check failed" sends the
    reader back to a debugger, and every check in this file is about
    telling outcomes apart - so a failure quotes the rows it was looking
    at.
    """
    return [(r.name, r.severity, r.detail)
            for r in results if fragment in r.name]


# ---------------------------------------------------------------
# A. the probe lands inside each driver's own declared envelope
# ---------------------------------------------------------------


def test_the_probe_is_inside_every_driver_declared_envelope(check):
    """Per driver, discovered from the registry so nothing opts out.

    The envelope is the driver's own `LIMITS`. A probe outside it is a
    request the instrument cannot carry out - the compliance would be
    refused or clamped, and every check downstream would then be
    measuring the clamp rather than the instrument.

    Both edges are checked. A probe of zero would satisfy every upper
    bound and measure nothing at all, which is the shape of a bound
    checked on one side only.
    """
    for cls in KNOWN_DRIVERS:
        limits = cls.LIMITS
        probe = probe_levels_for(any_driver(cls))

        for value, ceiling, what in (
                (probe.current, limits.max_current, "source current"),
                (probe.compliance_i, limits.max_current,
                 "current compliance"),
                (probe.voltage, limits.max_voltage, "source voltage"),
                (probe.compliance_v, limits.max_voltage,
                 "voltage compliance")):
            check(f"{cls.__name__}: the {what} probe is inside the "
                  f"declared maximum", value <= ceiling,
                  f"{value:g} against a {ceiling:g} ceiling")
            check(f"{cls.__name__}: the {what} probe is not zero",
                  value > 0, f"{value!r}")

        widest_i = max(limits.current_ranges)
        widest_v = max(limits.voltage_ranges)
        check(f"{cls.__name__}: no current probe is above the widest "
              f"declared range",
              probe.current <= widest_i and probe.compliance_i <= widest_i,
              f"{probe.current:g} / {probe.compliance_i:g} against "
              f"{widest_i:g}")
        check(f"{cls.__name__}: no voltage probe is above the widest "
              f"declared range",
              probe.voltage <= widest_v and probe.compliance_v <= widest_v,
              f"{probe.voltage:g} / {probe.compliance_v:g} against "
              f"{widest_v:g}")

        check(f"{cls.__name__}: the probe says where it came from",
              probe.notes, "no provenance recorded for the levels")


def test_a_narrow_envelope_pulls_the_probe_down(check):
    """The control leg for the test above.

    Every registered driver's envelope happens to contain the nominal
    probe, so that test would pass against a function that returned the
    nominal unchanged and ignored `LIMITS` entirely. This one gives a
    driver an envelope the nominal does not fit, and requires the probe
    to move.
    """
    from core.limits import SMULimits
    from drivers.dummy_smu import DummySMU

    class Tiny(DummySMU):
        LIMITS = SMULimits(
            max_voltage=0.05, max_current=1e-7,
            voltage_ranges=[0.01, 0.05],
            current_ranges=[1e-8, 1e-7],
        )

    probe = probe_levels_for(any_driver(Tiny))
    check("the voltage probe was pulled inside the envelope",
          probe.voltage <= 0.05 and probe.compliance_v <= 0.05,
          f"{probe.voltage:g} / {probe.compliance_v:g}")
    check("the current compliance was pulled inside the envelope",
          probe.compliance_i <= 1e-7, f"{probe.compliance_i:g}")
    check("and the report says it was clamped rather than chosen",
          any("clamped" in note for note in probe.notes),
          f"{probe.notes}")


def test_the_u2722a_probe_clears_its_own_sub_count_floor(check):
    """The instrument this whole change exists for.

    Asserted against a floor derived from the driver's own declarations
    rather than against a number typed here: 73.2 uA is ten counts of
    R120mA today, and a constant in this file would go on passing if the
    driver's count model changed underneath it.

    The range that matters is the widest, because that is where the
    checkup's all-AUTO current axis lands on an instrument with no
    autorange - which is the whole mechanism.
    """
    cls = KeysightU2722A
    widest = max(ceiling for ceiling, _ in cls.CURRENT_RANGE_TOKENS)
    floor = widest / cls.COUNTS_PER_RANGE * cls.MIN_LEVEL_COUNTS

    check("the nominal probe would have been below the floor on the "
          "range the plan lands on", PROBE_CURRENT < floor,
          f"nominal {PROBE_CURRENT:g} A against a {floor:g} A floor - if "
          f"this is false the test is no longer exercising the case it "
          f"was written for")

    transport = U2722ATransport()
    c = Checkup(KeysightU2722A(transport), open_circuit=False)
    c.run()

    check("the probe that ran clears it", c.probe.current >= floor,
          f"probed at {c.probe.current:g} A against a {floor:g} A floor")
    check("and it was raised rather than left at the nominal",
          c.probe.current > PROBE_CURRENT, f"{c.probe.current:g} A")
    check("nothing failed", c.counts()["fail"] == 0,
          f"{[(r.name, r.detail) for r in c.results if r.severity == 'fail']}")


def test_a_driver_with_no_floor_keeps_the_nominal_probe(check):
    """The other half: instrument-aware does not mean instrument-moved.

    Seven of the eight drivers declare no floor, and their probe must
    come out at the nominal. Without this, a change that raised every
    probe to some model-derived value would pass the U2722A test above
    and silently re-range the whole fleet - which is exactly the kind of
    change that makes two commissioning reports incomparable.
    """
    from drivers.dummy_smu import DummySMU

    driver = any_driver(DummySMU)
    check("this driver declares no floor",
          driver.source_level_floor("current") is None)
    probe = probe_levels_for(driver)
    check("so the source current probe is the nominal",
          probe.current == PROBE_CURRENT, f"{probe.current:g}")
    check("and the source voltage probe is the nominal",
          probe.voltage == PROBE_VOLTAGE, f"{probe.voltage:g}")
    check("and the compliances are the nominal",
          probe.compliance_i == PROBE_COMPLIANCE_I
          and probe.compliance_v == PROBE_COMPLIANCE_V,
          f"{probe.compliance_i:g} / {probe.compliance_v:g}")


# ---------------------------------------------------------------
# B. every readback state, told apart
# ---------------------------------------------------------------


def _states_seen(driver, expected=1e-4):
    return driver.verify_compliance("voltage", expected).state


def test_all_five_readback_states_are_distinguishable(check):
    """One driver, five configurations, five different answers.

    The states have to be reachable and they have to be *different*. A
    contract that collapsed two of them would still pass a test that
    only asserted each answer is a member of the vocabulary, which is
    why this asserts the set has five elements rather than checking them
    one at a time.
    """
    from drivers.dummy_smu import DummySMU

    class Silent(DummySMU):
        def read_current_limit(self):
            return None

    class Untrusted(DummySMU):
        COMPLIANCE_READBACK_TRUSTED = False

        def read_current_limit(self):
            return 1e-4

    class Trusted(Untrusted):
        COMPLIANCE_READBACK_TRUSTED = True

    class Raises(DummySMU):
        def read_current_limit(self):
            raise ValueError("the instrument answered something else")

    seen = {
        readback_states.UNSUPPORTED: _states_seen(any_driver(DummySMU)),
        readback_states.UNREADABLE: _states_seen(any_driver(Silent)),
        readback_states.UNVERIFIED: _states_seen(any_driver(Untrusted)),
        readback_states.CONFIRMED: _states_seen(any_driver(Trusted)),
        readback_states.MISMATCHED: _states_seen(any_driver(Trusted), 1e-2),
    }
    for wanted, got in seen.items():
        check(f"a {wanted} readback reports {wanted}", got == wanted,
              f"reported {got!r}")
    check("all five are distinct", len(set(seen.values())) == 5,
          f"{sorted(set(seen.values()))}")

    check("a reader that raises is unreadable, not a crash",
          _states_seen(any_driver(Raises)) == readback_states.UNREADABLE)

    passes = [s for s in readback_states.STATES
              if readback_states.SEVERITY[s] == "pass"]
    check("exactly one state renders as a pass",
          passes == [readback_states.CONFIRMED], f"{passes}")
    check("a mismatch is a failure, not a warning",
          readback_states.SEVERITY[readback_states.MISMATCHED] == "fail")


def test_disagreement_is_never_downgraded_by_doubt(check):
    """The ordering rule, and the one most easily written backwards.

    An unverified readback that disagrees is a MISMATCH. Either the
    instrument is holding a value nobody chose, or the query is
    answering dishonestly; both need a human before anything is sourced,
    and there is no third reading under which everything is fine.

    The previous contract checked the trust flag *before* comparing, so
    an untrusted driver reporting 12 mA against a requested 100 uA - the
    exact 120-fold widening the U2722A bench session watched happen -
    came out as a skip.
    """
    from drivers.dummy_smu import DummySMU

    class Untrusted(DummySMU):
        COMPLIANCE_READBACK_TRUSTED = False

        def read_current_limit(self):
            return 1.2e-2          # what the bench saw, from a 100 uA ask

    answer = any_driver(Untrusted).verify_compliance("voltage", 1e-4)
    check("an unverified readback that disagrees is a mismatch",
          answer.state == readback_states.MISMATCHED,
          f"{answer.state}: {answer.detail}")
    check("it is a failure", answer.severity == "fail", answer.severity)
    check("it is flagged as a safety event", answer.is_safety_event)
    check("and it names the doubt as well as the numbers",
          "never been verified" in answer.detail
          and "0.012" in answer.detail,
          answer.detail)


def test_a_mismatch_is_surfaced_loudly_in_a_checkup(check):
    """A mismatch has to reach the report, not just the contract.

    Injected on the compliance, which is the subject whose disagreement
    can hurt a sample: the fake accepts the limit and then reports a
    different one, which is what a range change did on the U2722A.
    """
    class LiesAboutItsCompliance(GWInstekGSM20H10):
        def read_current_limit(self):
            return 1e-9            # the collapse fault 23 describes

    c = Checkup(LiesAboutItsCompliance(GSMTransport()), open_circuit=False)
    c.run()
    failures = [r for r in c.results if r.severity == "fail"]
    named = [r for r in failures if "compliance" in r.name]
    check("the mismatch is a failure in the report", named,
          f"failures were {[r.name for r in failures]}")
    if named:
        check("and it points at the fault note",
              "23-autorange-resets-compliance" in (named[0].detail or ""),
              named[0].detail)

    # Control: the same fake without the lie must not produce it.
    clean = Checkup(GWInstekGSM20H10(GSMTransport()), open_circuit=False)
    clean.run()
    check("and an honest instrument does not",
          not [r for r in clean.results
               if r.severity == "fail" and "compliance" in r.name],
          f"{rows(clean.results, 'compliance')}")


def test_a_silently_narrowed_range_is_caught(check):
    """The GSM-20H10's `+824`, reproduced.

    Asking for a 100 uA measurement range with a 10 uA compliance in
    force is refused, and the instrument stays on 10.5 uA - a range the
    operator did not choose, with no exception. Nothing in the suite
    noticed, because `apply_ranges()` reported what it sent.
    """
    class RefusesTheRange(GSMTransport):
        """Takes the range command, queues +824, and does not move.

        Starts on the 10 uA range, which is where the bench found it:
        `SENS:CURR:DC:RANG?` read `1.050000E-05` after `1E-4` had been
        asked for.
        """

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.measure_current_range = 1.05e-5

        def _write(self, text):
            if text.upper().startswith("SENS:CURR:DC:RANG") and \
                    ":AUTO" not in text.upper():
                self.sent.append(text)
                self.errors.append((824, "Cannot set range"))
                return
            super()._write(text)

    c = Checkup(GWInstekGSM20H10(RefusesTheRange()), open_circuit=False)
    c.run()
    named = [r for r in c.results if r.name.startswith("range readback")
             and r.severity == "fail"]
    check("the refused range is a failure", named,
          f"{rows(c.results, 'range readback')}")
    if named:
        check("and it says a safety-relevant state disagrees",
              "SAFETY" in (named[0].detail or ""), named[0].detail)

    # Control: the same driver on a fake that accepts the range.
    clean = Checkup(GWInstekGSM20H10(GSMTransport()), open_circuit=False)
    clean.run()
    check("and an instrument that took the range does not fail",
          not [r for r in clean.results
               if r.name.startswith("range readback")
               and r.severity == "fail"],
          f"{rows(clean.results, 'range readback')}")


def test_an_unqueryable_range_is_unsupported_not_confirmed(check):
    """Four of the eight drivers cannot be asked. That is a skip.

    And it must be a skip rather than a silence: an axis missing from a
    report reads as an axis that was checked. Every axis gets a row.
    """
    from drivers.keithley_2401 import Keithley2401

    driver = any_driver(Keithley2401)
    for axis in BaseSMU.RANGE_AXES:
        answer = driver.verify_range(axis, 1e-4 if "current" in axis else 0.2)
        check(f"{axis} is unsupported on this model",
              answer.state == readback_states.UNSUPPORTED, answer.state)
        check(f"{axis} renders as a skip, not a pass",
              answer.severity == "skip", answer.severity)
        check(f"{axis} says what is unknown",
              "no confirmed query" in answer.detail, answer.detail)


def test_a_wider_range_than_asked_for_is_a_mismatch(check):
    """Resolution given away without anyone choosing to.

    The headroom exists because an instrument reports a range by its
    full scale, and the Keithley and GW Instek families put full scale
    5% above the nominal decade. It has to allow that and nothing more:
    a range a decade wider is not a rounding, it is a different range,
    and the reading it produces is coarser than the one the run was
    designed around.
    """
    from drivers.dummy_smu import DummySMU

    class ReportsFullScale(DummySMU):
        RANGE_READBACK_TRUSTED = True
        reported = 1.05e-4

        def read_measure_current_range(self):
            return self.reported

    driver = any_driver(ReportsFullScale)
    answer = driver.verify_range("measure_current", 1e-4)
    check("the 5% full-scale convention is not a mismatch",
          answer.state == readback_states.CONFIRMED,
          f"{answer.state}: {answer.detail}")

    driver.reported = 1.05e-3
    answer = driver.verify_range("measure_current", 1e-4)
    check("a range a decade wider is",
          answer.state == readback_states.MISMATCHED,
          f"{answer.state}: {answer.detail}")
    check("and the detail explains what a wider range costs",
          "resolution" in answer.detail, answer.detail)

    driver.reported = 1.05e-5
    answer = driver.verify_range("measure_current", 1e-4)
    check("and so is a range a decade narrower",
          answer.state == readback_states.MISMATCHED,
          f"{answer.state}: {answer.detail}")
    check("which is named as the clamping case",
          "clamps a source level" in answer.detail, answer.detail)


# ---------------------------------------------------------------
# C. the power-limit ceiling on the 2635B
# ---------------------------------------------------------------


def test_the_power_limit_is_read_back_on_the_2635b(check):
    """`limitp` was a ceiling nothing watched. One query answers it."""
    transport = Keithley2635BTransport()
    driver = Keithley2635B(transport)
    driver.reset()

    check("the driver holds it at disabled",
          Keithley2635B.POWER_LIMIT_SETTING == 0.0,
          f"{Keithley2635B.POWER_LIMIT_SETTING!r}")
    check("and it can be asked", driver.read_power_limit() == 0.0,
          f"{driver.read_power_limit()!r}")

    answer = driver.verify_power_limit()
    check("an agreement is unverified rather than confirmed",
          answer.state == readback_states.UNVERIFIED,
          f"{answer.state}: {answer.detail}")
    check("which is a warning, not a pass", answer.severity == "warn",
          answer.severity)


def test_a_recalled_power_limit_is_caught(check):
    """The case the entry was written for.

    `limitp` resets to disabled, which is why nothing looked - but
    `Recall setup` can carry a nonzero one into a session, where it
    overrides whichever of the three limits is lower and is invisible to
    the compliance readback, because `limitv` reports the programmed
    value rather than the effective one.

    Modelled as a ceiling the driver's own write does not clear, which
    is the state that matters whichever way the instrument got into it:
    the software believes it is disabled and it is not. A fake that let
    the write land would be asserting that the driver can write, which
    it demonstrably can, rather than that anything checks.
    """
    class HoldsARecalledCeiling(Keithley2635BTransport):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.recalled = "2.0e-2"

        def _write(self, text):
            super()._write(text)
            if "source.limitp" in text:
                self.attrs["smua.source.limitp"] = self.recalled

    transport = HoldsARecalledCeiling()
    driver = Keithley2635B(transport)
    driver.reset()

    answer = driver.verify_power_limit()
    check("a nonzero power limit is a mismatch",
          answer.state == readback_states.MISMATCHED,
          f"{answer.state}: {answer.detail}")
    check("even though the readback itself is unverified",
          answer.severity == "fail" and answer.is_safety_event,
          answer.severity)

    c = Checkup(driver, open_circuit=False)
    c.run()
    named = [r for r in c.results
             if "power limit" in r.name and r.severity == "fail"]
    check("and the checkup reports it loudly", named,
          f"{rows(c.results, 'power limit')}")
    if named:
        check("with the safety marker", "SAFETY" in (named[0].detail or ""),
              named[0].detail)


def test_a_model_with_no_power_limit_says_so(check):
    """Not every model has one, and that is a skip rather than a gap."""
    from drivers.keithley_2401 import Keithley2401

    answer = any_driver(Keithley2401).verify_power_limit()
    check("no power-limit setting is unsupported",
          answer.state == readback_states.UNSUPPORTED, answer.state)
    check("and renders as a skip", answer.severity == "skip",
          answer.severity)


# ---------------------------------------------------------------
# D. sub-count source levels
# ---------------------------------------------------------------


def test_the_u2722a_refuses_a_sub_count_level(check):
    """Measured behaviour, and the driver refuses before energising.

    On R120mA one count is 7.32 uA. Commanding `-1 uA` and `+1 uA`
    produced the *same output* at the bench on 2026-08-25, because the
    sign of what comes out is not the sign that was asked for.
    """
    transport = U2722ATransport()
    driver = KeysightU2722A(transport)
    driver.reset()
    driver.set_source_function("current")
    driver.set_voltage_limit(1.0)
    driver._apply_current_range("R120mA")

    floor = driver.source_level_floor("current")
    check("the floor is ten counts of the active range",
          floor is not None
          and math.isclose(floor, 0.12 / 16384 * 10, rel_tol=1e-9),
          f"{floor!r}")

    with pytest.raises(RangeError):
        driver.set_current_level(floor / 10.0)

    # Control legs. A level at the floor is accepted, and zero always is
    # - a guard that refused everything would pass the assertion above.
    before = len(transport.sent)
    driver.set_current_level(floor)
    check("a level at the floor is accepted",
          len(transport.sent) > before)
    driver.set_current_level(0.0)
    check("and zero is always allowed - it is exactly representable",
          True)


def test_the_checkup_probes_the_refusal_where_a_floor_is_declared(check):
    """A guard that has stopped guarding passes every other check.

    The level written is a tenth of the driver's own declared floor, so
    a working guard must decline it. Asked with the output off, and
    asked in the direction where the interesting answer is the correct
    one - which is the fault this project keeps relearning.
    """
    c = Checkup(KeysightU2722A(U2722ATransport()), open_circuit=False)
    c.run()
    named = [r for r in c.results if "is refused" in r.name]
    check("both axes are reported", len(named) == 2,
          f"{[r.name for r in named]}")
    passed = [r for r in named if r.severity == "pass"]
    check("and the guard fired on both", len(passed) == 2,
          f"{[(r.name, r.severity, r.detail) for r in named]}")


def test_a_guard_that_stopped_guarding_is_a_failure(check):
    """The control leg for the probe above.

    Without this the probe could be passing because nothing reached it.
    """
    class GuardRemoved(KeysightU2722A):
        def _refuse_unresolvable_level(self, level, quantity, unit, token,
                                       table):
            return          # the mutation this probe exists to catch

    c = Checkup(GuardRemoved(U2722ATransport()), open_circuit=False)
    c.run()
    named = [r for r in c.results
             if "is refused" in r.name and r.severity == "fail"]
    check("removing the guard turns the probe red", named,
          f"{rows(c.results, 'is refused')}")
    if named:
        check("and it says what the guard is for",
              "sign is not commanded" in (named[0].detail or ""),
              named[0].detail)


def test_an_unmeasured_sub_count_axis_warns_rather_than_passes(check):
    """Absence of evidence is not a pass, and this is where it shows.

    Six of the eight drivers have never had their converter's bottom
    count measured. A checkup on those instruments has to say so on its
    own line - a skip would read as a model difference, and there is no
    model difference here, only an unasked question.
    """
    from core.transports.null_transport import NullTransport
    from drivers.dummy_smu import DummySMU

    class Unmeasured(DummySMU):
        SUB_COUNT_LEVELS = {"current": BaseSMU.SUB_COUNT_UNMEASURED,
                            "voltage": BaseSMU.SUB_COUNT_UNMEASURED}

    transport = NullTransport()
    transport.connect("demo")
    c = Checkup(Unmeasured(transport), open_circuit=False)
    c.run()
    named = [r for r in c.results if r.name.startswith("sub-count")]
    check("both axes are reported", len(named) == 2,
          f"{[r.name for r in named]}")
    check("as warnings", all(r.severity == "warn" for r in named),
          f"{[(r.name, r.severity) for r in named]}")
    check("saying the state is unmeasured rather than fine",
          all("UNMEASURED" in (r.detail or "") for r in named),
          f"{[r.detail for r in named]}")
    check("and saying what would close it",
          all("bench measurement" in (r.detail or "") for r in named))

    # Control: an axis with no source range must NOT warn, or the
    # warning becomes noise everybody reads past.
    plain = Checkup(DummySMU(transport), open_circuit=False)
    plain.run()
    check("a not-applicable axis is a skip instead",
          all(r.severity == "skip" for r in plain.results
              if r.name.startswith("sub-count")),
          f"{rows(plain.results, 'sub-count')}")


def test_the_minismu_current_axis_is_not_asked_the_wrong_question(check):
    """There is no source current range on that instrument at all.

    `CH1:IRANGE` is a *measurement* range - established 2026-08-27 from
    the commands the vendor library sends - so a source current is never
    judged against it and the sub-count question does not arise in the
    same form. Asking it anyway would be a warning nobody can ever
    close.
    """
    from drivers.undalogic_minismu import UndalogicMiniSMU

    check("the current axis is recorded as not applicable",
          UndalogicMiniSMU.sub_count_state("current")
          == BaseSMU.SUB_COUNT_NOT_APPLICABLE,
          UndalogicMiniSMU.sub_count_state("current"))
    check("and the voltage axis, which does have a source range, is not",
          UndalogicMiniSMU.sub_count_state("voltage")
          == BaseSMU.SUB_COUNT_UNMEASURED,
          UndalogicMiniSMU.sub_count_state("voltage"))
