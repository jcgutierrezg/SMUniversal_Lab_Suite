"""Multicomp Pro 72-13200 - command spellings and the two traps.

Modelled on `test_gsm20h10.py`: the assertions are about the exact
strings on the wire, and about the *absence* of the other dialects'
spellings. That matters more here than anywhere else in the suite,
because this instrument **has no error queue**. On every other driver a
wrong header is logged and a bench session can read it back; here it is
ignored in silence, so a test asserting only that a number came back
would pass against a driver that sent nothing the instrument understood.

The two traps this file exists for:

  * replies carry their units, and a raw `'0.789A'` handed to
    `drop_sentinel()` becomes `None` - a reading that existed, silently
    discarded;
  * a sinking current is positive on the instrument and negative in this
    suite, and getting that wrong yields a complete, plausible,
    inverted IV curve.
"""
import pytest

from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.core.ranges import RangePlan
from smuniversal_lab_suite.core.transports.base import (
    Transport,
    TransportDesynchronised,
)
from smuniversal_lab_suite.drivers.multicomp_72_13200 import (
    MulticompPro7213200,
)

#: The real reply, read off the unit 2026-09-15. Note what it is NOT:
#: comma-delimited. Every other instrument in this suite answers *IDN?
#: with the four comma-separated fields the standard asks for; this one
#: returns a sentence. `driver_for_idn()` matches by substring, so it
#: resolves anyway - but anything that ever splits an identity on commas
#: will find one field here.
IDN = "Multicomp Pro 72-13200 V3.30 SN:00028215"


class LoadTransport(Transport):
    """A 72-13200 that answers the way the command table says it does.

    Every reply carries its unit, because that is the whole point: a
    fake returning bare floats would let a driver that never strips a
    suffix pass.
    """

    def __init__(self, volts=2.5, amps=4.0, watts=10.0,
                 current_ceiling=3.0, voltage_ceiling=18.0):
        super().__init__()
        self.connected = True
        self.sent = []
        self.volts = volts
        self.amps = amps          # SINKING, the instrument's own sign
        self.watts = watts
        self.current_ceiling = current_ceiling
        self.voltage_ceiling = voltage_ceiling
        self.input_on = False
        self.function = "CC"
        self.setpoints = {}

    def connect(self, address, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)
        upper = text.upper()
        if upper.startswith(":INP"):
            self.input_on = "ON" in upper
        elif upper.startswith(":FUNC"):
            # Only CV and CC take. Anything else is ignored in silence -
            # measured on the instrument 2026-09-15, and the reason the
            # manual's documented `VOLT`/`CURR` arguments spent a whole
            # driver revision doing nothing. A fake that accepted them
            # would let that bug back in.
            arg = upper.split()[-1]
            if arg in ("CV", "CC"):
                self.function = arg
        elif "UPP" in upper:
            # Settable over the bus, which the manual denies, and with
            # the same mandatory unit suffix as the setpoints.
            value = upper.split()[-1]
            for unit, axis in (("A", "current_ceiling"),
                               ("V", "voltage_ceiling")):
                if value.endswith(unit):
                    try:
                        setattr(self, axis, float(value[:-1]))
                    except ValueError:
                        pass
        elif upper.startswith(":VOLT"):
            self.setpoints["voltage"] = text
        elif upper.startswith(":CURR"):
            self.setpoints["current"] = text

    def _read(self, timeout_s=3.0):
        last = self.sent[-1].upper()
        if "IDN" in last:
            return IDN
        if "MEAS:VOLT" in last or "MEASURE:VOLT" in last:
            return f"{self.volts:.4f}V"
        if "MEAS:CURR" in last or "MEASURE:CURR" in last:
            return f"{self.amps:.4f}A"
        if "MEAS:POW" in last or "MEASURE:POW" in last:
            return f"{self.watts:.4f}W"
        if "CURR" in last and "UPP" in last:
            return f"{self.current_ceiling:g}A"
        if "VOLT" in last and "UPP" in last:
            return f"{self.voltage_ceiling:g}V"
        if "FUNC" in last:
            return self.function
        return ""


def build(**kwargs):
    transport = LoadTransport(**kwargs)
    return MulticompPro7213200(transport), transport


# ---------------------------------------------------------------
# Trap 1: replies carry units
# ---------------------------------------------------------------


def test_a_reading_survives_its_unit_suffix(check):
    """`'2.5000V'` is a reading, not a parse failure.

    The failure this guards is not an exception - it is
    `drop_sentinel()` catching the ValueError and returning None, so
    the reading disappears with nothing raised and nothing logged.
    """
    load, _ = build(volts=2.5, amps=4.0)
    volts, amps = load.measure()
    check("the voltage parsed", volts == 2.5, f"got {volts!r}")
    check("the current parsed", amps == -4.0, f"got {amps!r}")


@pytest.mark.parametrize("reply,expected", [
    ("0.789A", 0.789),
    ("1.4999V", 1.4999),
    ("1.1968W", 1.1968),
    ("20OHM", 20.0),
    ("  30A  ", 30.0),
    ("5.00AH", 5.0),
    ("", None),
    ("nonsense", None),
    (None, None),
])
def test_the_unit_stripper(reply, expected):
    assert MulticompPro7213200._number(reply) == expected


def test_a_sentinel_is_still_dropped_after_its_unit_comes_off(check):
    """Parse first, then check for the sentinel - in that order.

    The order is the whole point. Checked here rather than assumed
    because reversing it is invisible: both orders return None for a
    sentinel, and only one of them returns a number for a real reading.
    """
    load, transport = build()
    transport.volts = 9.91e37
    volts, amps = load.measure()
    check("the sentinel became None", volts is None, f"got {volts!r}")
    check("the real reading in the other column survived", amps == -4.0,
          f"got {amps!r} - a dropped column shifts the row")


# ---------------------------------------------------------------
# Trap 2: the sign
# ---------------------------------------------------------------


def test_the_suite_sees_a_sink_as_negative(check):
    load, transport = build(amps=9.8)
    _, amps = load.measure()
    check("negative in this suite's convention", amps == -9.8, f"got {amps!r}")
    check("the instrument itself still said positive", transport.amps == 9.8)


def test_setting_a_sink_current_sends_a_positive_magnitude(check):
    load, transport = build()
    load.set_current_level(-9.8)
    check("the command is the documented spelling",
          transport.setpoints.get("current") == ":CURRent 9.8A",
          f"sent {transport.setpoints!r}")


def test_asking_it_to_source_is_refused(check):
    load, transport = build()
    with pytest.raises(LimitError):
        load.set_current_level(+9.8)
    check("and nothing reached the wire",
          not transport.setpoints, f"sent {transport.setpoints!r}")


# ---------------------------------------------------------------
# Command spellings, and the absence of the others
# ---------------------------------------------------------------


def test_the_regulation_mode_spellings(check):
    """`CV`/`CC`, not the `VOLT`/`CURR` the manual documents.

    Measured 2026-09-15 on firmware V3.30: `:FUNCtion VOLT` sent to an
    instrument in CC leaves it in CC and says nothing. The manual's
    parameter list and its worked example are both wrong, and there is
    no error queue for the instrument to disagree with them.
    """
    load, transport = build()
    load.set_source_function("voltage")
    check("CV", ":FUNCtion CV" in transport.sent, f"{transport.sent}")
    load.set_source_function("current")
    check("CC", ":FUNCtion CC" in transport.sent, f"{transport.sent}")
    check("the manual's spellings are never sent",
          not any(s.upper().endswith(("VOLT", "CURR"))
                  and "FUNC" in s.upper() for s in transport.sent),
          f"{transport.sent}")


def test_a_mode_that_does_not_take_is_caught_by_the_readback(check):
    """The only protection available on an instrument with no queue.

    This is the bug that shipped and was found on the bench: the driver
    sent a mode the instrument ignored, and every "voltage sweep" would
    have run as a constant-current sink returning a full set of
    plausible readings.
    """
    load, transport = build()
    transport.function = "CC"

    original = transport._write

    def deaf(text):
        # A transport that accepts the write and never changes mode -
        # exactly what the real instrument does with a bad argument.
        transport.sent.append(text)

    transport._write = deaf
    with pytest.raises(RuntimeError) as caught:
        load.set_source_function("voltage")
    check("it says the mode did not change",
          "did not change" in str(caught.value), str(caught.value))
    check("and says why nothing complained",
          "no error queue" in str(caught.value), str(caught.value))
    transport._write = original


def test_the_cv_setpoint_floor(check):
    """0.1 V, measured. Below it the instrument clamps and says nothing.

    Including zero: asking for 0 V leaves `:VOLTage?` reading 0.1000 V.
    So a sweep stepping toward zero would record several distinct
    requested levels at one physical point, flattening the curve
    exactly where a solar IV curve is most interesting.
    """
    load, transport = build()
    load.set_voltage_level(0.6)
    check("above the floor is sent",
          transport.setpoints.get("voltage") == ":VOLTage 0.6V",
          f"{transport.setpoints!r}")

    for refused in (0.05, 0.01, 0.0):
        transport.setpoints.clear()
        with pytest.raises(ValueError) as caught:
            load.set_voltage_level(refused)
        check(f"{refused} V is refused, not clamped",
              not transport.setpoints, f"{transport.setpoints!r}")
        check(f"{refused} V message points at output_off()",
              "output_off()" in str(caught.value), str(caught.value))


def test_the_cc_axis_has_no_such_floor(check):
    """Measured: 0.001 A and 0 A both land exactly, and
    `:CURRent:LOWer?` reports 0. The floor is a CV-only property and
    must not be applied to both axes out of symmetry."""
    load, transport = build()
    for wanted, expected in ((-1.0, ":CURRent 1A"),
                             (-0.01, ":CURRent 0.01A"),
                             (0.0, ":CURRent 0A")):
        load.set_current_level(wanted)
        check(f"{wanted} A lands", transport.setpoints["current"] == expected,
              f"{transport.setpoints!r}")


def test_short_mode_is_unreachable(check):
    """`:FUNC SHORT` shorts whatever is attached. It is not a mode this
    driver can be asked for, by accident or otherwise."""
    load, transport = build()
    for asked in ("short", "SHORT", "resistance", "power"):
        with pytest.raises(ValueError):
            load.set_source_function(asked)
    check("nothing was sent", not transport.sent, f"{transport.sent}")


def test_the_input_is_switched_not_the_output(check):
    load, transport = build()
    load.output_on()
    check("input on", ":INPut ON" in transport.sent, f"{transport.sent}")
    load.output_off()
    check("input off", ":INPut OFF" in transport.sent, f"{transport.sent}")


def test_no_other_dialect_is_spoken(check):
    """The SMU spellings must be absent, and silence is why.

    On any other instrument here a stray `:SOUR:VOLT` would be logged
    and found. This one ignores it, so the only place it can be caught
    is a test.
    """
    load, transport = build()
    load.reset()
    load.set_source_function("voltage")
    load.set_voltage_level(0.6)
    load.output_on()
    load.measure()
    load.output_off()

    banned = (":SOUR", ":SENS", "OUTP", "smu.", "print(", ":SYST:ERR",
              "*RST", "*CLS", ":FUNC SHORT", ":LIST")
    traffic = " | ".join(transport.sent)
    for spelling in banned:
        check(f"{spelling!r} never sent", spelling not in traffic, traffic)


def test_a_negative_cv_setpoint_is_refused_at_the_wire(check):
    """The gate in LIMITS catches a sweep's endpoints; this catches the
    per-point levels a software sweep computes for itself."""
    load, transport = build()
    with pytest.raises(ValueError):
        load.set_voltage_level(-0.2)
    check("nothing sent", not transport.setpoints, f"{transport.setpoints!r}")


# ---------------------------------------------------------------
# The reset that is not one, and the error queue that is not there
# ---------------------------------------------------------------


def test_reset_does_not_pretend_to_reset(check):
    """No `*RST` exists on this model, so none is sent.

    What it does instead is disable the input and record what it found,
    which is the only honest answer to inherited state when nothing can
    clear it.
    """
    load, transport = build()
    load.reset()
    check("no *RST", "*RST" not in transport.sent, f"{transport.sent}")
    check("the input was disabled", ":INPut OFF" in transport.sent,
          f"{transport.sent}")
    check("and the inherited state was written down",
          load.state_at_connect.get("ceilings", {}).get("current") == 3.0,
          f"{load.state_at_connect!r}")


def test_read_error_says_it_cannot_be_asked(check):
    """Code 0, because a failure to ask is not evidence of a fault -
    but the message must not read as a clean bill of health."""
    load, _ = build()
    code, message = load.read_error()
    check("code 0", code == 0, f"got {code!r}")
    check("the message says why", "no error queue" in message.lower(),
          message)


# ---------------------------------------------------------------
# Ranging, which this instrument can only be asked about
# ---------------------------------------------------------------


def test_apply_ranges_sets_the_ceilings_over_the_bus(check):
    """The manual marks both `UPPer` entries query-only. Measured
    2026-09-15: they are writable, and the write takes effect."""
    load, transport = build(current_ceiling=30.0, voltage_ceiling=120.0)
    logged = []
    plan = RangePlan.for_sourcing("voltage", source_range=0.8,
                                  measure_range=2.0)
    described = load.apply_ranges(plan, log=logged.append)

    check("a ceiling was written",
          any("UPP" in cmd.upper() for cmd in transport.sent),
          f"{transport.sent}")
    check("the unit suffix is on it",
          any(cmd.upper().endswith(("A", "V"))
              for cmd in transport.sent if "UPP" in cmd.upper()),
          f"a bare number is accepted and ignored: {transport.sent}")
    check("2 A snapped up to the 3 A documented ceiling",
          transport.current_ceiling == 3.0, f"{transport.current_ceiling}")
    check("and the description reports what was read back, not sent",
          "3A" in described.replace(" ", ""), described)
    check("the console explains why the ceiling matters",
          logged and "measurement floor" in logged[0], f"{logged!r}")


def test_apply_ranges_snaps_to_a_documented_ceiling(check):
    """Intermediate ceilings are accepted by the instrument but not
    used. The specification states accuracy per range, and what an
    in-between ceiling does to the full-scale term is unmeasured - so
    the driver stays where the accuracy figures apply."""
    for wanted, expected in ((0.5, 3.0), (2.9, 3.0), (3.0, 3.0),
                             (3.1, 30.0), (25.0, 30.0)):
        load, transport = build(current_ceiling=1.0)
        load.apply_ranges(RangePlan.for_sourcing(
            "voltage", source_range=0.8, measure_range=wanted))
        check(f"{wanted} A -> {expected} A ceiling",
              transport.current_ceiling == expected,
              f"got {transport.current_ceiling}")


def test_a_ceiling_mismatch_is_reported_not_raised(check):
    """A ceiling that did not take is recorded in the run rather than
    ending it: wider costs resolution, narrower clamps a level, and
    either way the file should say what the instrument reported."""
    # Start the fake somewhere the plan would NOT choose, so "unchanged"
    # can only mean the write did nothing. Built at 18 V it already sat
    # where a 0.8 V span lands, and the test could not have failed.
    load, transport = build(current_ceiling=30.0, voltage_ceiling=120.0)
    original = transport._write
    transport._write = lambda text: transport.sent.append(text)  # deaf
    described = load.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=2.0))
    check("the mismatch is named", "MISMATCH" in described, described)
    check("and it names both axes", described.count("MISMATCH") == 2,
          described)
    transport._write = original


def test_a_ceiling_that_cannot_be_read_is_none_not_a_guess(check):
    """An unparseable reply leaves the axis unknown, not invented.

    The realistic shape of this: the instrument answers something the
    unit stripper cannot turn into a number. A gap in the record is the
    honest result - a ceiling this driver guessed would be worse than
    one it admits it does not know, because the ceiling is what sets the
    measurement floor.
    """
    load, transport = build()
    transport._read = lambda timeout_s=3.0: "----"
    ceilings = load.read_ceilings()
    check("current unknown", ceilings["current"] is None, f"{ceilings!r}")
    check("voltage unknown", ceilings["voltage"] is None, f"{ceilings!r}")


def test_a_desynchronised_link_is_never_absorbed_into_a_none(check):
    """A latched transport must not read as 'this model cannot say'.

    The two look identical in a `None` and mean opposite things: one is
    a model difference, the other is a link whose replies now answer the
    previous command. On this instrument it matters more than on any
    other - there is no error queue to cross-check against, so a desync
    is the only signal that the stream has gone out of step.

    `tests/test_desync_not_swallowed.py` scans for the broad handler
    statically; this checks the behaviour it is scanning for.
    """
    load, transport = build()

    def explode(timeout_s=3.0):
        raise RuntimeError("no reply")

    transport._read = explode
    with pytest.raises(TransportDesynchronised):
        load.read_ceilings()


# ---------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------


def test_what_this_model_declares(check):
    M = MulticompPro7213200
    check("no compliance", not M.supports_compliance())
    check("no NPLC", not M.supports_nplc())
    check("no OVP", not M.supports_ovp())
    check("no high-Z off", not M.supports_high_z_off())
    check("no remote-sense control", not M.supports_remote_sense_control())
    check("the wiring is recorded instead", M.fixed_sense())
    check("software sweep", M.sweep_kind() == "software")
    check("and no error queue at all", not M.supports_error_queue())
    check("headroom measured 2026-09-15",
          M.HEADROOM_STATE == M.HEADROOM_MEASURED)
    check("and therefore declares a floor", M.declares_headroom())


def test_the_envelope_is_this_model_not_the_family(check):
    """The command PDF answers `>150V` and `>300W` in its examples,
    which belong to other units in the family. Nothing here may come
    from it."""
    limits = MulticompPro7213200.LIMITS
    check("120 V, not 150", limits.max_voltage == 120.0)
    check("30 A", limits.max_current == 30.0)
    check("150 W, not 300", limits.max_power == 150.0)


def test_the_quadrant_is_declared(check):
    limits = MulticompPro7213200.LIMITS
    limits.validate_source_point(voltage=0.8, current=-10.0)
    with pytest.raises(LimitError):
        limits.validate_source_point(voltage=-0.2)
    with pytest.raises(LimitError):
        limits.validate_source_point(current=+10.0)


def test_remote_sense_is_refused_rather_than_ignored(check):
    load, transport = build()
    with pytest.raises(NotImplementedError):
        load.set_remote_sense(True)
    check("nothing sent", not transport.sent, f"{transport.sent}")


# ---------------------------------------------------------------
# The headroom floor, measured 2026-09-15 at 10 A
# ---------------------------------------------------------------


def test_the_headroom_floor_is_declared_and_refuses(check):
    """0.431 V at 10 A, and the guard fires below it.

    Sharp in the measurement and sharp here: it held a 0.430 V setpoint
    exactly and sat at 0.4310 V for every setpoint below, across four
    points with no spread at all.
    """
    load, _ = build()
    check("the state says measured",
          load.HEADROOM_STATE == load.HEADROOM_MEASURED)
    check("and the class declares a floor",
          MulticompPro7213200.declares_headroom())
    check("the figure at 10 A is the measured one",
          abs(load.minimum_operating_voltage(10.0) - 0.4310) < 5e-4,
          f"got {load.minimum_operating_voltage(10.0)}")

    load.guard_operating_point(volts=0.5, amps=10.0)
    with pytest.raises(LimitError) as caught:
        load.guard_operating_point(volts=0.35, amps=10.0)
    check("the message says the failure is silent",
          "no error is raised" in str(caught.value), str(caught.value))


def test_the_floor_is_a_resistance_not_a_number(check):
    """Measured at two currents, and they agree to 0.03 mOhm.

        9.998 A   floor 0.4310 V   43.11 mOhm
        5.023 A   floor 0.2164 V   43.08 mOhm

    Predicting the 5 A floor from the 10 A one gave 0.2165 V against
    0.2164 V measured, so there is no measurable fixed term. Held as a
    resistance for the same reason the B2901A's sub-count floor is held
    as counts: an absolute figure is right at one current and wrong at
    every other, and this instrument is used across a 6:1 range.
    """
    load, _ = build()
    for amps, expected in ((10.0, 0.4310), (5.0, 0.2155), (1.0, 0.0431)):
        got = load.minimum_operating_voltage(amps)
        check(f"{amps} A -> {expected} V", abs(got - expected) < 5e-4,
              f"got {got}")
    check("and the sign of the request does not matter",
          load.minimum_operating_voltage(-10.0)
          == load.minimum_operating_voltage(10.0))


def test_the_two_floors_are_kept_separate(check):
    """The commanding floor and the headroom floor are different
    mechanisms, and they cross at 2.32 A.

    Collapsing them into one number would leave an operator with a
    truncated curve and no way to tell which limit stopped them - one
    is a limit on what can be asked for, the other on what can be held.
    """
    load, _ = build()
    check("below the crossover the headroom floor is the smaller",
          load.minimum_operating_voltage(1.0) < load.MIN_CV_SETPOINT_V)
    check("above it the headroom floor is the larger",
          load.minimum_operating_voltage(5.0) > load.MIN_CV_SETPOINT_V)
    check("the crossover is where it was computed to be",
          abs(load.MIN_CV_SETPOINT_V / load.SATURATION_RESISTANCE_OHM
              - 2.32) < 0.01)

    # Both are enforced, by different guards, at their own layer.
    with pytest.raises(ValueError):
        load.set_voltage_level(0.05)          # commanding floor
    with pytest.raises(LimitError):
        load.guard_operating_point(volts=0.3, amps=10.0)   # headroom


def test_the_settling_time_is_declared(check):
    """430 ms for a step down at 10 A, and it is the floor under any
    sweep's per-point delay. Declared because the first attempt to
    measure the headroom dwelt 350 ms and produced three phantom
    floors that were the CV loop still slewing."""
    check("declared", MulticompPro7213200.SETTLING_S >= 0.4,
          f"{MulticompPro7213200.SETTLING_S}")


def test_the_voltage_ceiling_follows_the_sweep_span(check):
    """The span the operator typed picks the ceiling, not AUTO.

    `for_sourcing()` marks the measurement range of the sourced
    quantity AUTO because on an SMU that value is read back through the
    source. A load measures its terminals with its own converter, whose
    range is the ceiling - so letting AUTO win would pick 120 V full
    scale for a 0.8 V sweep and give away 30 mV of accuracy where 18 V
    gives 4.5 mV.

    Resolved inside this driver. `for_sourcing()` and `widest()` are
    untouched.
    """
    load, transport = build(voltage_ceiling=120.0)
    load.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=10.0))
    check("0.8 V span -> the 18 V ceiling",
          transport.voltage_ceiling == 18.0,
          f"got {transport.voltage_ceiling}")

    load, transport = build(voltage_ceiling=18.0)
    load.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=40.0, measure_range=1.0))
    check("a 40 V span still gets 120 V",
          transport.voltage_ceiling == 120.0,
          f"got {transport.voltage_ceiling}")


def test_output_on_refuses_a_source_above_the_ceiling(check):
    """The guard that pays for narrowing the ceiling.

    With the input off the terminals are loaded only by 150 kOhm, so
    the driver can see what it is about to connect to. Past output-on
    the reading would simply overrange.
    """
    load, transport = build(voltage_ceiling=18.0)
    transport.volts = 48.0
    with pytest.raises(LimitError) as caught:
        load.output_on()
    check("it names both numbers",
          "48" in str(caught.value) and "18" in str(caught.value),
          str(caught.value))
    check("and the input was never enabled",
          not transport.input_on, "the input came on anyway")

    transport.volts = 5.0
    load.output_on()
    check("a source inside the ceiling is fine", transport.input_on)
