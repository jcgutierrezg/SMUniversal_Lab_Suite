"""Multicomp Pro MP710772 - what its own bench sitting established.

The dialect is the 72-13200's and its traps are tested in
`test_72_13200.py` against the shared code. What is tested here is what
the 2026-11-17 probe found to be this model's own, and what a driver
written from the community driver would have got wrong:

  * it is reached by `*IDN?`, which carries no brand, and must resolve to
    this class and never to the 72-13200's;
  * its readings are zero-padded;
  * `:MODE` is ignored - the mode goes by `:FUNC`, the spelling the
    probe confirmed, and is read back;
  * every write is followed by the probe's 150 ms, after an unpaced
    first checkup lost two;
  * its headroom floor is unmeasured, and a bound is not presented as a
    number.

The fake answers the way the probe recorded, and ignores `:MODE` the way
the instrument did: a fake that obeyed it would let a driver sending it
pass.
"""
import pytest
from test_72_13200 import LoadTransport

from smuniversal_lab_suite.core import provenance
from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.core.ranges import RangePlan
from smuniversal_lab_suite.drivers.korad_load import KoradLoad
from smuniversal_lab_suite.drivers.multicomp_72_13200 import (
    MulticompPro7213200,
)
from smuniversal_lab_suite.drivers.multicomp_mp710772 import (
    MulticompProMP710772,
)
from smuniversal_lab_suite.drivers.registry import (
    KNOWN_LOADS,
    driver_for_idn,
)

#: Read off the unit on 2026-11-17. No brand, unlike the 72-13200's.
IDN = "MP710772 V1.14 SN:0000023205"


class MP710772Transport(LoadTransport):
    """The 72-13200's fake, answering as the MP710772 did at the bench:
    its identity, padded readings, ceilings to five digits."""

    def __init__(self, current_ceiling=40.0, voltage_ceiling=150.0,
                 **kwargs):
        super().__init__(current_ceiling=current_ceiling,
                         voltage_ceiling=voltage_ceiling, **kwargs)

    def _read(self, timeout_s=3.0):
        last = self.sent[-1].upper()
        if "IDN" in last:
            return IDN
        if "MEAS" in last:
            value = {"VOLT": self.volts, "CURR": self.amps,
                     "POW": self.watts}[next(
                         k for k in ("VOLT", "CURR", "POW") if k in last)]
            unit = {"VOLT": "V", "CURR": "A", "POW": "W"}[next(
                k for k in ("VOLT", "CURR", "POW") if k in last)]
            return f"{value:06.3f}{unit}"
        return super()._read(timeout_s)


def build(**kwargs):
    transport = MP710772Transport(**kwargs)
    load = MulticompProMP710772(transport)
    # The pause is asserted on its own below; here it would only add
    # 0.15 s to every write the fake takes.
    transport.write_delay_s = 0.0
    return load, transport


# ---------------------------------------------------------------
# Identity
# ---------------------------------------------------------------


def test_its_idn_resolves_to_it_and_never_to_the_72_13200(check):
    check("the MP710772's reply", driver_for_idn(IDN) is MulticompProMP710772,
          f"{driver_for_idn(IDN)}")
    check("and the 72-13200's still resolves to the 72-13200",
          driver_for_idn("Multicomp Pro 72-13200 V3.30 SN:00028215")
          is MulticompPro7213200)
    check("registered as a load", MulticompProMP710772 in KNOWN_LOADS)


def test_both_models_speak_the_shared_dialect(check):
    for cls in (MulticompPro7213200, MulticompProMP710772):
        check(f"{cls.__name__} is a KoradLoad", issubclass(cls, KoradLoad))
    check("the dialect itself is not registered", KoradLoad not in KNOWN_LOADS)


def test_an_edit_to_the_dialect_stales_both_drivers(check):
    """`korad_load.py` is neither a fleet base nor either driver's file.
    It must still be in both fingerprints, or a change to the mode
    command would leave both notes reading commissioned."""
    for path in ("drivers/multicomp_72_13200.py",
                 "drivers/multicomp_mp710772.py"):
        paths = provenance.code_paths_for(path, fleet="load")
        check(f"{path} is fingerprinted with korad_load.py",
              "drivers/korad_load.py" in paths, f"{paths}")
    check("and an SMU is not",
          "drivers/korad_load.py" not in provenance.code_paths_for(
              "drivers/keithley_2450.py", fleet="smu"))


# ---------------------------------------------------------------
# Readings
# ---------------------------------------------------------------


@pytest.mark.parametrize("reply,expected", [
    ("00.199A", 0.199),
    ("05.034V", 5.034),
    ("00.999W", 0.999),
    ("40.000A", 40.0),
    ("150.00V", 150.0),
    ("7500.0OHM", 7500.0),
])
def test_padded_replies_parse(reply, expected):
    assert MulticompProMP710772._number(reply) == expected


def test_a_padded_sink_reads_negative(check):
    load, _ = build(volts=5.034, amps=0.199)
    volts, amps = load.measure()
    check("volts", volts == 5.034, f"{volts!r}")
    check("a sink is negative in this suite", amps == -0.199, f"{amps!r}")


# ---------------------------------------------------------------
# The mode, by `:FUNC` - and never `:MODE`
# ---------------------------------------------------------------


def test_the_mode_goes_by_function_and_is_read_back(check):
    load, transport = build()
    load.set_source_function("voltage")
    check("CV sent", ":FUNC CV" in transport.sent, f"{transport.sent}")
    check("and read back", ":FUNC?" in transport.sent)
    check("never the long form this unit was not probed with",
          not any("FUNCTION" in s.upper() for s in transport.sent),
          f"{transport.sent}")
    check("and it took", transport.function == "CV")
    check("never the community driver's :MODE",
          not any(s.upper().startswith(":MODE") for s in transport.sent))


def test_the_72_13200_keeps_the_long_form_it_was_commissioned_on(check):
    """The header is a per-model declaration, not a base-class change."""
    from test_72_13200 import build as build_72_13200
    load, transport = build_72_13200()
    load.set_source_function("voltage")
    check("the 72-13200 sends :FUNCtion", ":FUNCtion CV" in transport.sent,
          f"{transport.sent}")


def test_every_write_is_followed_by_the_probes_pause(check, monkeypatch):
    """0.15 s after each write: the timing every probe write landed with.
    The first checkup sent the same writes unpaced and lost two."""
    from smuniversal_lab_suite.core.transports import base
    slept = []
    monkeypatch.setattr(base.time, "sleep", lambda s: slept.append(s))
    transport = MP710772Transport()
    load = MulticompProMP710772(transport)
    check("declared", MulticompProMP710772.WRITE_DELAY_S == 0.15,
          f"{MulticompProMP710772.WRITE_DELAY_S}")
    check("and put on the link it was given", transport.write_delay_s == 0.15)
    load.set_source_function("voltage")
    check("the mode write was paced", slept == [0.15], f"{slept}")
    check("the 72-13200 is still unpaced",
          MulticompPro7213200.WRITE_DELAY_S == 0)


def test_a_mode_that_did_not_take_is_refused(check):
    load, transport = build()
    transport._write = lambda text: transport.sent.append(text)
    with pytest.raises(RuntimeError, match="asked for CV"):
        load.set_source_function("voltage")


def test_nothing_it_sends_is_a_probe_only_or_dangerous_command(check):
    """Never `:MODE`, `:SYST:DEVINFO?` (seven lines, which shift every
    reply after it), SHORT or LIST, whatever a run does."""
    load, transport = build(volts=0.6, amps=2.0)
    load.reset()
    load.set_source_function("current")
    load.apply_ranges(RangePlan.for_sourcing(
        "current", source_range=3.0, measure_range=18.0))
    load.set_current_level(-1.0)
    load.output_on()
    load.measure()
    load.set_source_function("voltage")
    load.set_voltage_level(0.5)
    load.output_off()
    sent = " ".join(transport.sent).upper()
    for forbidden in (":MODE", "DEVINFO", "SHORT", ":LIST", "*RST"):
        check(f"no {forbidden}", forbidden not in sent, sent)


# ---------------------------------------------------------------
# The envelope, and what is not yet known
# ---------------------------------------------------------------


def test_the_envelope_is_this_models(check):
    limits = MulticompProMP710772.LIMITS
    check("150 V, 40 A, 500 W", (limits.max_voltage, limits.max_current,
                                 limits.max_power) == (150.0, 40.0, 500.0))
    check("two ranges per quantity", limits.voltage_ranges == [18.0, 150.0]
          and limits.current_ranges == [3.0, 40.0])
    check("one quadrant", limits.voltage_polarity == "positive"
          and limits.current_polarity == "negative")


def test_a_sweep_over_the_72_13200s_reach_is_accepted(check):
    load, _ = build()
    load.validate_source_point(current=-35.0, voltage=150.0,
                               sourcing="current")
    check("35 A on the 150 V range", True)


def test_the_cv_floor_is_shared_and_names_the_unmeasured_headroom(check):
    load, transport = build()
    with pytest.raises(LimitError) as raised:
        load.validate_source_point(voltage=0.05, current=-3.0,
                                   sourcing="voltage")
    check("refused below 0.1 V", "0.1 V" in str(raised.value))
    check("and says the headroom floor is unmeasured",
          "has not been measured" in str(raised.value), str(raised.value))
    with pytest.raises(ValueError):
        load.set_voltage_level(0.05)


def test_the_headroom_floor_is_unmeasured_not_a_bound(check):
    check("declared unmeasured", not MulticompProMP710772.declares_headroom())
    load, _ = build()
    check("no number", load.minimum_operating_voltage(10.0) is None)
    load.guard_operating_point(0.1, 30.0)
    check("so nothing is refused on headroom grounds", True)


def test_the_point_delay_covers_the_measured_settling(check):
    load, _ = build()
    check("0.5 s, above the slowest step measured (454 ms)",
          load.minimum_point_delay("current") == 0.5
          and load.minimum_point_delay("voltage") == 0.5)


def test_ranging_snaps_to_its_own_ranges(check):
    load, transport = build()
    load.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=10.0))
    check("18 V for a 0.8 V sweep", transport.voltage_ceiling == 18.0,
          f"{transport.voltage_ceiling}")
    check("40 A for a 10 A expectation", transport.current_ceiling == 40.0,
          f"{transport.current_ceiling}")
