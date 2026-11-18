"""The Keithley 2400 driver, and the 2400-series dialect it shares.

The 2400 is the 2401 with a 200 V range. The two share
`drivers/keithley_2400_series.py`, so the dialect itself - the
2400-series spellings, the range re-send, the trip query - is already
tested in `test_2401_driver.py`. What is tested here is what the split
has to get right:

* a 2400 and a 2401 are told apart by `*IDN?`, in both directions;
* both send the same bytes for the same call, because there is one
  dialect;
* an edit to the dialect stales both drivers' checkups;
* the 2400's envelope has the 200 V corner and the 2401's does not;
* **none of the 2401's bench claims leak into the 2400.** Its readback
  trust and its sub-count floor were measured on one 2401, and a model
  that inherited them would report another unit's measurements as its
  own.
"""
from test_2401_driver import Fake2401

from smuniversal_lab_suite.core import provenance
from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.drivers.base_smu import BaseSMU
from smuniversal_lab_suite.drivers.keithley_2400 import Keithley2400
from smuniversal_lab_suite.drivers.keithley_2400_series import (
    Keithley2400Series,
)
from smuniversal_lab_suite.drivers.keithley_2401 import Keithley2401
from smuniversal_lab_suite.drivers.registry import KNOWN_SMUS, driver_for_idn


class Fake2400(Fake2401):
    """The 2401's fake answering as a 2400. The dialect is one, so the
    fake is one; only the identity differs."""

    IDN = "KEITHLEY INSTRUMENTS INC.,MODEL 2400,1234567,C30"


# ---------------------------------------------------------------
# Identity
# ---------------------------------------------------------------


def test_a_2400_and_a_2401_are_told_apart(check):
    check("a 2400 resolves to the 2400 driver",
          driver_for_idn(Fake2400.IDN) is Keithley2400)
    check("a 2401 still resolves to the 2401 driver",
          driver_for_idn(Fake2401.IDN) is Keithley2401)

    # The serials that would fool a loose match. The 2401's bare "2401"
    # fallback is four characters; "MODEL 2400" is ten, and the registry
    # prefers the longer match.
    tricky_2400 = "KEITHLEY INSTRUMENTS INC.,MODEL 2400,1240199,C30"
    check("a 2400 whose serial contains 2401 is still a 2400",
          driver_for_idn(tricky_2400) is Keithley2400,
          str(driver_for_idn(tricky_2400)))
    tricky_2401 = "KEITHLEY INSTRUMENTS INC.,MODEL 2401,1240012,A01"
    check("a 2401 whose serial contains 2400 is still a 2401",
          driver_for_idn(tricky_2401) is Keithley2401,
          str(driver_for_idn(tricky_2401)))
    check("the 2400 declares no bare '2400' that a serial could match",
          Keithley2400.MODEL_IDS == ["MODEL 2400"])


def test_the_dialect_is_shared_and_not_registered(check):
    for cls in (Keithley2400, Keithley2401):
        check(f"{cls.__name__} is a Keithley2400Series",
              issubclass(cls, Keithley2400Series))
    check("the dialect itself is not registered",
          Keithley2400Series not in KNOWN_SMUS)
    check("and no reply can resolve to it",
          Keithley2400Series.MODEL_IDS == [])
    check("the 2400 is registered", Keithley2400 in KNOWN_SMUS)


def test_both_models_send_the_same_bytes(check):
    """One dialect: the same call is the same command on either model.

    A model file that grew its own spelling of something would be a
    second dialect hiding in a subclass, and this is what finds it.
    """
    def drive(cls, transport):
        smu = cls(transport)
        smu.reset()
        smu.set_source_function("voltage")
        smu._apply_source_voltage_range(20.0)
        smu._apply_measure_current_range(1e-3)
        smu.set_current_limit(1e-3)
        smu.set_nplc(1.0)
        smu.set_output_off_mode(True)
        smu.output_on()
        smu.set_voltage_level(0.5)
        smu.measure()
        smu.output_off()
        return [s for s in transport.sent if "IDN" not in s]

    sent_2400 = drive(Keithley2400, Fake2400())
    sent_2401 = drive(Keithley2401, Fake2401())
    check("identical command streams", sent_2400 == sent_2401,
          f"{sent_2400} vs {sent_2401}")


def test_an_edit_to_the_dialect_stales_both_drivers(check):
    """`keithley_2400_series.py` is neither a fleet base nor either
    driver's file. It must be in both fingerprints, or a change to the
    compliance command would leave both notes reading commissioned."""
    for path in ("drivers/keithley_2400.py", "drivers/keithley_2401.py"):
        paths = provenance.code_paths_for(path, fleet="smu")
        check(f"{path} is fingerprinted with the series file",
              "drivers/keithley_2400_series.py" in paths, f"{paths}")
    check("the 2400 is not fingerprinted with the 2401's file",
          "drivers/keithley_2401.py" not in provenance.code_paths_for(
              "drivers/keithley_2400.py", fleet="smu"))
    check("and an unrelated SMU is not fingerprinted with the series",
          "drivers/keithley_2400_series.py" not in provenance.code_paths_for(
              "drivers/keithley_2450.py", fleet="smu"))


# ---------------------------------------------------------------
# The 200 V range and its corner
# ---------------------------------------------------------------


def test_the_200_v_range_is_declared_and_sent(check):
    check("200 V is a voltage range on the 2400",
          200.0 in Keithley2400.LIMITS.voltage_ranges)
    check("but not on the 2401",
          200.0 not in Keithley2401.LIMITS.voltage_ranges)
    check("the 2400 reaches 210 V", Keithley2400.LIMITS.max_voltage == 210.0)

    t = Fake2400()
    smu = Keithley2400(t)
    smu._apply_source_voltage_range(200.0)
    check("the range goes out in the shared spelling",
          ":SOUR:VOLT:RANG 2.000000e+02" in t.sent, f"{t.sent}")
    check("and reads back", smu.read_source_voltage_range() == 200.0)


def test_the_envelope_refuses_both_maxima_at_once(check):
    limits = Keithley2400.LIMITS
    for volts, amps in ((20.0, 1.0), (21.0, 1.05), (200.0, 0.1),
                        (210.0, 0.105)):
        try:
            limits.validate_source_point(current=amps, voltage=volts)
            check(f"{volts} V at {amps} A is allowed", True)
        except LimitError as exc:
            check(f"{volts} V at {amps} A is allowed", False, str(exc))

    # The corner itself: high voltage with high current.
    for volts, amps in ((100.0, 1.0), (22.0, 0.2)):
        try:
            limits.validate_source_point(current=amps, voltage=volts)
            check(f"{volts} V at {amps} A is refused", False, "accepted")
        except LimitError as exc:
            check(f"{volts} V at {amps} A is refused",
                  "power envelope" in str(exc), str(exc))


def test_above_50_v_is_a_hazard(check):
    check("the 2400 asks before a run above 50 V",
          Keithley2400.hazardous_above_v() == 50.0)
    check("the 2401, which cannot reach it, does not",
          Keithley2401.hazardous_above_v() is None)


# ---------------------------------------------------------------
# No borrowed bench claims
# ---------------------------------------------------------------


def test_no_readback_trust_is_borrowed_from_the_2401(check):
    """The 2401's readbacks are trusted on a bench session with that
    unit. The 2400's queries are the same headers, so they answer - and
    that makes them `unverified`, a warn, until a session on a 2400."""
    check("the 2401 is trusted (its own bench session)",
          Keithley2401.COMPLIANCE_READBACK_TRUSTED is True
          and Keithley2401.RANGE_READBACK_TRUSTED is True)
    check("the 2400 is not",
          Keithley2400.COMPLIANCE_READBACK_TRUSTED is False
          and Keithley2400.RANGE_READBACK_TRUSTED is False)
    check("and the dialect carries no trust of its own",
          "COMPLIANCE_READBACK_TRUSTED" not in vars(Keithley2400Series)
          and "RANGE_READBACK_TRUSTED" not in vars(Keithley2400Series))

    smu = Keithley2400(Fake2400())
    smu.set_current_limit(1e-3)
    answer = smu.verify_compliance("voltage", 1e-3)
    check("an agreeing compliance readback is unverified",
          answer.state == "unverified", f"{answer.state}: {answer.detail}")

    smu._apply_measure_current_range(1e-3)
    answer = smu.verify_range("measure_current", 1e-3)
    check("an agreeing range readback is unverified",
          answer.state == "unverified", f"{answer.state}: {answer.detail}")


def test_no_sub_count_floor_is_borrowed_from_the_2401(check):
    check("the 2401's current floor is its own measurement",
          Keithley2401.SOURCE_COUNTS_PER_RANGE["current"] == 32768)
    check("the 2400 declares no counts on either axis",
          Keithley2400.SOURCE_COUNTS_PER_RANGE
          == {"current": None, "voltage": None})
    for quantity in ("current", "voltage"):
        check(f"the 2400's {quantity} axis is unmeasured",
              Keithley2400.sub_count_state(quantity)
              == BaseSMU.SUB_COUNT_UNMEASURED)
        check(f"so no {quantity} floor is offered",
              Keithley2400(Fake2400()).source_level_floor(quantity) is None)

    # And nothing is refused on that basis, however small.
    t = Fake2400()
    Keithley2400(t).set_current_level(1e-12)
    check("a picoamp level is written, unguarded",
          any(":SOUR:CURR:LEV" in s for s in t.sent),
          "a floor here would be a claim nobody has measured on a 2400")
