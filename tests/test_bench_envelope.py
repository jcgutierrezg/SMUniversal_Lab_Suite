"""
The bench pass must be able to see what it claims to look for.

Offline, against fakes that behave in known ways. The point is not that
the tool runs - it is that a fake with a working sign and a fake with an
uncommanded one produce *different* verdicts, and that the control leg
fails loudly when the probe is measuring nothing.

That is the fault this repository hits most: a probe asked where the
answer is already known. See
`docs/faults/19-non-discriminating-probe.md`.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import bench_envelope as be


class FakeSMU:
    """A source whose sign follows down to `floor`, and not below.

    Below the floor it returns offset residue: a fixed magnitude whose
    polarity does not depend on what was commanded. That is the
    U2722A's measured behaviour, and the thing the pass exists to
    detect on the rest of the fleet.
    """

    NPLC_RANGE = (0.01, 10.0)

    def __init__(self, floor=1e-6, residue=3e-7, noise=1e-9,
                 quietens=True):
        self.floor = floor
        self.residue = residue
        self.noise = noise
        self.quietens = quietens
        self.level = 0.0
        self.nplc = 1.0
        self.output = False
        self.ranges = []
        self.plans = []
        self.recorded = {}
        self.off_calls = 0
        self._tick = 0

    @classmethod
    def clamp_nplc(cls, nplc):
        low, high = cls.NPLC_RANGE
        return max(low, min(high, nplc))

    def apply_ranges(self, plan, log=None):
        self.plans.append(plan)
        self._apply_source_current_range(plan.source_current)

    def _record_source_range(self, quantity, value):
        self.recorded[quantity] = value

    def set_source_function(self, mode): self.mode = mode
    def set_voltage_limit(self, volts): self.limit = volts
    def set_current_level(self, amps): self.level = amps
    def set_nplc(self, nplc): self.nplc = nplc
    def output_on(self): self.output = True
    def output_off(self): self.output = False

    def safe_output_off(self):
        self.off_calls += 1
        self.output = False

    def _apply_source_current_range(self, amps):
        self.ranges.append(amps)

    def measure(self):
        self._tick += 1
        # Deterministic dither, so the tests are not timing- or
        # RNG-dependent, with a period of three rather than two.
        #
        # The first version alternated every reading, which is exactly
        # the period the +/- loop alternates on - so every positive got
        # +noise and every negative -noise, the within-group scatter was
        # zero, and residue readings separated by 2*noise looked like a
        # perfectly commanded sign. The fake manufactured the signal the
        # test was looking for. A period the caller does not share is
        # what stops that.
        scale = self.noise / (self.nplc ** 0.5) if self.quietens else self.noise
        dither = scale * (self._tick % 3 - 1)
        if abs(self.level) >= self.floor:
            current = self.level + dither
        else:
            current = self.residue + dither    # sign ignored
        return (current * 10_000.0, current)


def test_the_envelope_reports_a_rate_and_a_noise_per_rung():
    smu = FakeSMU()
    rows = be.envelope(smu, lambda _: None)
    assert rows, "no rungs scanned"
    assert all(r["rate_hz"] and r["rate_hz"] > 0 for r in rows)
    assert all(r["rsd"] is not None for r in rows)


def test_a_longer_integration_reads_quieter():
    """The discriminating half.

    A tool that reported the same noise at every NPLC would look
    identical to one measuring nothing, so this asserts the fake's
    quietening actually comes through the metric.
    """
    smu = FakeSMU(quietens=True)
    rows = be.envelope(smu, lambda _: None)
    assert rows[-1]["rsd"] < rows[0]["rsd"], (
        f"{rows[0]['rsd']} -> {rows[-1]['rsd']}")


def test_an_instrument_that_does_not_integrate_is_visible():
    """The opposite case must look different, or the check is decorative."""
    smu = FakeSMU(quietens=False)
    rows = be.envelope(smu, lambda _: None)
    assert rows[-1]["rsd"] == pytest.approx(rows[0]["rsd"], rel=0.5)


def test_the_output_goes_off_after_the_envelope():
    smu = FakeSMU()
    be.envelope(smu, lambda _: None)
    assert smu.output is False
    assert smu.off_calls >= 1


def test_the_output_goes_off_even_when_a_reading_raises():
    """The safety-relevant one. An exception mid-scan must not leave a
    biased sample energised."""
    smu = FakeSMU()

    def explode():
        raise RuntimeError("instrument fell over")

    smu.measure = explode
    with pytest.raises(RuntimeError):
        be.envelope(smu, lambda _: None)
    assert smu.output is False
    assert smu.off_calls >= 1


# ---------------------------------------------------------------
# sub-count
# ---------------------------------------------------------------
def test_the_floor_is_found_between_the_bracketing_levels():
    smu = FakeSMU(floor=6.25e-6)
    rows = be.sub_count(smu, lambda _: None)
    failed = [r for r in rows if r["sign_commanded"] is False]
    assert failed, "the sign never stopped following, so nothing was found"
    crossing = failed[0]["level"]
    assert crossing < smu.floor <= crossing * 2, (
        f"crossing {crossing:.3e} does not bracket the fake's "
        f"{smu.floor:.3e} floor")


def test_a_well_behaved_instrument_reports_no_early_crossing():
    """Must not invent a floor on an instrument that has none.

    "None at all" is unphysical: below the reading noise the sign
    becomes undetectable whatever the source does, so the tool reports
    a crossing there and is right to. What it must not do is report one
    while the commanded level is still comfortably above the noise.
    """
    smu = FakeSMU(floor=0.0, noise=1e-12)
    rows = be.sub_count(smu, lambda _: None)
    failed = [r for r in rows if r["sign_commanded"] is False]
    if failed:
        assert failed[0]["level"] < be.BIAS_A / 1000, (
            f"reported a floor at {failed[0]['level']:.3e} A on an "
            f"instrument with none, well above the {smu.noise:.3e} A "
            f"noise that is the real detection limit")


def test_the_control_leg_stops_the_run_when_it_fails():
    """B6. If the probe cannot see the sign at a level the instrument
    must honour, it is measuring nothing and everything below is
    meaningless - so it must stop rather than report."""
    smu = FakeSMU(floor=1.0)          # nothing at all follows
    logged = []
    rows = be.sub_count(smu, logged.append)
    assert len(rows) == 1 and rows[0]["control"] is True
    assert rows[0]["sign_commanded"] is False
    assert any("ABORTING" in line for line in logged)


def test_the_bias_range_is_pinned_not_the_widest():
    """Pinning the widest range made the control leg impossible.

    100 uA on a 1 A range is itself sub-count, so the control tested the
    condition it exists to rule out and failed on four instruments; it
    also raised ValueError on the miniSMU, whose ladder stops at 180 mA.
    """
    smu = FakeSMU()
    be.sub_count(smu, lambda _: None)
    assert smu.ranges and smu.ranges[0] == be.BIAS_A


def test_a_range_beyond_the_instrument_is_never_requested():
    """The miniSMU raised ValueError on a 1 A request. Any driver may."""
    class Narrow(FakeSMU):
        MAX_RANGE = 0.18

        def _apply_source_current_range(self, amps):
            if amps > self.MAX_RANGE:
                raise ValueError(f"{amps} exceeds {self.MAX_RANGE}")
            self.ranges.append(amps)

    be.sub_count(Narrow(), lambda _: None)      # must not raise


# ---------------------------------------------------------------
# the verdict, against readings recorded on the bench
# ---------------------------------------------------------------
class Offset:
    """Readings that do not move whatever is commanded.

    The GSM-20H10's actual behaviour on 2026-08-28: ~+140 uA on the
    positive leg and ~+20 uA on the negative one, unchanged across
    twenty-one halvings down to 95 pA, both positive. The first version
    of the verdict called every one of those "sign follows", because it
    only required the separation to exceed the commanded level - a
    threshold that shrinks as the request does, so a fixed offset clears
    it more easily the smaller the level gets.
    """

    NPLC_RANGE = (0.01, 10.0)

    def __init__(self):
        self.level = 0.0
        self.output = False
        self.ranges = []
        self.off_calls = 0
        self._tick = 0

    @classmethod
    def clamp_nplc(cls, nplc): return nplc
    def set_source_function(self, mode): pass
    def set_voltage_limit(self, volts): pass
    def set_current_level(self, amps): self.level = amps
    def set_nplc(self, nplc): pass
    def output_on(self): self.output = True
    def output_off(self): self.output = False
    def safe_output_off(self): self.off_calls += 1; self.output = False
    def _apply_source_current_range(self, amps): self.ranges.append(amps)
    def _record_source_range(self, quantity, value): pass

    def apply_ranges(self, plan, log=None):
        self._apply_source_current_range(plan.source_current)

    def measure(self):
        self._tick += 1
        jitter = 3e-6 * (self._tick % 3 - 1)
        current = (1.442e-4 if self.level >= 0 else 2.0e-5) + jitter
        return (current * 9958.0, current)


def test_a_fixed_offset_is_not_a_commanded_sign():
    """The bench case that produced twenty-one false rows."""
    smu = Offset()
    rows = be.sub_count(smu, lambda _: None)

    # Caught at the control now, twice over: both legs read positive,
    # and neither is anywhere near +/-100 uA, which at the control
    # level no count or offset excuses. The version this test was
    # written against had only the separation window, which +124 uA
    # satisfies - a fixed offset and a real signal cannot be told apart
    # at one level by separation alone - and it refused only as the
    # levels shrank. Either way it must stop early.
    refused = [i for i, r in enumerate(rows) if r["sign_commanded"] is False]
    assert refused, "the offset was never refused at any level"
    assert len(rows) <= 6, (
        f"{len(rows)} levels reported before refusing; the first version "
        f"of this check ran twenty-one halvings down to 95 pA on exactly "
        f"these readings")


def test_the_b2901a_reading_pattern_is_accepted():
    """The other half: a real result must still pass.

    Its 2026-08-28 readings tracked the command and quantised at about
    6.3 uA, with the sign failing one step below. A verdict tightened
    until nothing passes would be no better than one that accepts
    everything.
    """
    for level, pos, neg in [(1.00e-4, 6.93e-5, -6.90e-5),
                            (5.00e-5, 3.41e-5, -3.43e-5),
                            (1.25e-5, 6.30e-6, -6.90e-6)]:
        separation = pos - neg
        expected = 2 * abs(level)
        assert 0.5 * expected < separation < 3 * expected, (
            f"{level:.2e} A would now be rejected: separation "
            f"{separation:.3e} against expected {expected:.3e}")

    # And the row where it genuinely stopped following.
    separation = -5.0e-7 - -1.0e-7
    assert not (0.5 * (2 * 3.125e-6) < separation < 3 * (2 * 3.125e-6))


def test_quantised_rungs_are_named_rather_than_reported_as_silent():
    """An RSD of zero is the converter running out, not a quiet reading.

    Every instrument reported 0.000% at its upper rungs on the first
    bench run, which flattens the curve and reads as a perfect result.
    """
    class Coarse(FakeSMU):
        def measure(self):
            return (1.0, 1.0e-4)        # every reading identical

    rows = be.envelope(Coarse(), lambda _: None)
    assert all(r["quantised"] for r in rows)
    assert all(r["distinct_values"] == 1 for r in rows)


def test_a_clamped_output_is_flagged_not_praised():
    """A compliance-limited output has almost no scatter, so it reads as
    the quietest rung on the curve. Several drivers here cannot report
    compliance, and then this is the only thing that would say so."""
    class Clamped(FakeSMU):
        def measure(self):
            self._tick += 1
            return (2.0, 2.0e-5 + 1e-9 * (self._tick % 3 - 1))

    rows = be.envelope(Clamped(), lambda _: None)
    assert all(r["mean_off_command"] for r in rows)

    ok = be.envelope(FakeSMU(), lambda _: None)
    assert not any(r["mean_off_command"] for r in ok), (
        "a healthy instrument must not be flagged, or the flag is noise")


def test_the_sub_count_sets_its_own_integration_time():
    """It inherited the envelope's last rung, which is the longest.

    Every 2026-09-01 floor was measured at the top of its ladder by
    accident, and on the U2722A that is 10.4 s a reading. The envelope
    runs first in `main()`, so this runs it first too - a sub-count
    tested on a fresh fake would pass whether or not it sets anything.
    """
    smu = FakeSMU()
    be.envelope(smu, lambda _: None)
    assert smu.nplc == FakeSMU.NPLC_RANGE[1], (
        "precondition: the envelope should leave the longest rung set, "
        "or this test cannot tell setting from inheriting")

    seen = []
    measure = smu.measure

    def spy():
        seen.append(smu.nplc)
        return measure()

    smu.measure = spy
    rows = be.sub_count(smu, lambda _: None)
    assert seen and set(seen) == {be.SUB_COUNT_NPLC}, set(seen)
    assert rows and all(r["nplc"] == be.SUB_COUNT_NPLC for r in rows)


def test_the_level_is_returned_to_zero_and_the_output_off():
    smu = FakeSMU()
    be.sub_count(smu, lambda _: None)
    assert smu.level == 0.0
    assert smu.output is False


def test_rsd_is_none_rather_than_zero_when_undefined():
    assert be.rsd([]) is None
    assert be.rsd([1.0]) is None
    assert be.rsd([0.0, 0.0]) is None
    assert be.rsd([None, "x"]) is None


# ---------------------------------------------------------------
# both legs on the same side of zero is not a commanded sign
# ---------------------------------------------------------------
class SameSideOffset(Offset):
    """The GSM-20H10 below about 1.5 nA on 2026-08-28.

    Both legs positive, readings frozen at roughly +1.28 nA and
    +0.40 nA whatever is commanded. The separation bound alone passed
    four of those rows, because a fixed ~0.85 nA offset kept sitting
    inside a window that shrank with the level - so the reported floor
    came out nearly ten times too low.
    """

    def measure(self):
        self._tick += 1
        jitter = 2e-11 * (self._tick % 3 - 1)
        current = (1.28e-9 if self.level >= 0 else 4.0e-10) + jitter
        return (current * 9958.0, current)


def test_both_legs_on_the_same_side_of_zero_is_refused():
    smu = SameSideOffset()
    commanded, pos, neg = be.sign_is_commanded(smu, 7.629e-10, lambda _: None)
    assert pos > 0 and neg > 0, "the fake should put both legs positive"
    assert commanded is False, (
        "commanding a negative level and reading positive is not a "
        "commanded sign, whatever the separation happens to be")


def test_opposite_signs_alone_are_not_enough():
    """The new check adds to the bounds rather than replacing them.

    A reading that straddles zero but by the wrong amount is still not
    following the command - otherwise a fixed +/-1 A output would pass
    at every level.
    """
    class Overshoot(Offset):
        def measure(self):
            self._tick += 1
            return (1.0, 1e-3 if self.level >= 0 else -1e-3)

    commanded, pos, neg = be.sign_is_commanded(Overshoot(), 1e-7,
                                               lambda _: None)
    assert pos > 0 > neg
    assert commanded is False, "a fixed +/-1 mA output passed at 100 nA"


def test_the_envelope_pins_the_same_range_as_the_sub_count_phase():
    """Otherwise the level lands on whatever reset() left active.

    The B2901A then read a mean of 4.3e-7 A against a commanded 1e-4 at
    every rung, and the run before - which had no mean column - reported
    RSD 0.000% and looked like the best instrument on the bench.
    """
    smu = FakeSMU()
    be.envelope(smu, lambda _: None)
    assert smu.ranges and smu.ranges[0] == be.BIAS_A


def test_a_driver_that_refuses_the_level_is_the_answer_not_a_crash():
    """The U2722A refuses a sub-count level before energising anything.

    That is the best available answer to this question - the floor
    declared by the driver rather than inferred from readings - and the
    first version of this tool crashed on the one instrument that gets
    it right.
    """
    from smuniversal_lab_suite.core.ranges import RangeError

    class Refuses(FakeSMU):
        def set_current_level(self, amps):
            if 0 < abs(amps) < 6.1e-8:
                raise RangeError("below what R100uA can express")
            self.level = amps

    # floor=0 so the walk reaches the refusal rather than stopping at
    # the fake's own sub-count behaviour first.
    rows = be.sub_count(Refuses(floor=0.0, noise=1e-13), lambda _: None)
    refused = [r for r in rows if r["sign_commanded"] == "refused"]
    assert refused, "the refusal was not recorded as the floor"
    assert refused[-1] is rows[-1], "it must stop at the refusal"
    assert rows[0]["control"] is True and rows[0]["sign_commanded"] is True


# ---------------------------------------------------------------
# 2026-09-11: settling, control accuracy, frozen rows, ranges, a dead
# link, and the voltage the envelope was not recording
# ---------------------------------------------------------------
class Slow(FakeSMU):
    """An output that covers 85.5% of the remaining distance per reading.

    The U2722A's shape at 1 PLC on 2026-09-11: stepping from -L to +L,
    the first reading lands at 71% of the command. Every row of its
    current walk read about that, and the separation window passed
    them all.
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.out = 0.0

    def measure(self):
        self._tick += 1
        self.out += (self.level - self.out) * 0.855
        return (self.out * 10_000.0, self.out)


def test_a_slow_output_is_waited_for_not_believed():
    smu = Slow()
    rows = be.sub_count(smu, lambda _: None)
    control = rows[0]
    assert control["settle"] > be.SETTLE_READINGS, (
        f"settled at {control['settle']} discard(s); the fake needs more")
    assert control["sign_commanded"] is True
    assert abs(control["positive"] - be.BIAS_A) <= 0.01 * be.BIAS_A, control
    assert len(rows) > 1, "the walk should proceed once the output settles"


def test_without_the_wait_the_same_output_reads_short():
    """The discriminating half: the calibration is doing the work.

    Read straight after each step, the fake reads 71% of the command -
    which the sign test still calls following, and only the control
    accuracy check refuses.
    """
    commanded, pos, neg = be.sign_is_commanded(Slow(), be.BIAS_A,
                                               lambda _: None, settle=0)
    assert commanded is True, "the window alone lets this through"
    assert pos < 0.8 * be.BIAS_A, pos
    assert not be.control_is_accurate(pos, neg, be.BIAS_A)


def test_a_steady_shortfall_at_the_control_stops_the_run():
    """Settled, but only 71% of the command - a limited output."""
    class Short(FakeSMU):
        def measure(self):
            self._tick += 1
            current = 0.71 * self.level + 1e-10 * (self._tick % 3 - 1)
            return (current * 10_000.0, current)

    logged = []
    rows = be.sub_count(Short(), logged.append)
    assert len(rows) == 1 and rows[0]["sign_commanded"] is False, rows
    assert any("ABORTING" in line for line in logged), logged


class Replay2401(FakeSMU):
    """The 2401's 2026-09-11 current walk, from 1.221e-8 A down.

    6.104e-9 and 3.052e-9 A produced the same output, and the sign test
    passed both. The same pair repeated on 2026-09-01.
    """

    TABLE = {6.104e-9: (6.4237e-9, -6.0437e-10),
             3.052e-9: (6.4258e-9, -6.4707e-10),
             1.526e-9: (4.5621e-9, 4.5759e-9)}

    def measure(self):
        self._tick += 1
        dither = 1e-13 * (self._tick % 3 - 1)
        magnitude = abs(self.level)
        for level, (pos, neg) in self.TABLE.items():
            if magnitude and abs(magnitude - level) / level < 0.01:
                current = (pos if self.level > 0 else neg) + dither
                return (current * 10_000.0, current)
        current = self.level + dither
        return (current * 10_000.0, current)


def test_a_level_that_changed_nothing_is_not_the_floor():
    logged = []
    rows = be.sub_count(Replay2401(), logged.append)
    by_level = {round(r["level"], 12): r for r in rows}
    frozen = by_level[round(3.0517578125e-09, 12)]
    assert frozen["sign_commanded"] is False and frozen.get("frozen"), frozen
    above = by_level[round(6.103515625e-09, 12)]
    assert above["sign_commanded"] is True, (
        "the level above did change its output, so its pass stands")
    assert any("below 6.104e-09 A" in line for line in logged), logged


def test_a_leg_sitting_on_its_offset_is_still_a_response():
    """Both legs must stay put. One moving is the output following."""
    previous = {"positive": 2.6041e-4, "negative": -7.2335e-5}
    # The 2401's voltage walk: 1.221e-4 V, then 6.104e-5 V.
    assert not be.did_not_move(previous, 2.2627e-4, -3.6513e-6, 6.104e-5)
    # And its next row, which was the same output as this one.
    previous = {"positive": 2.2627e-4, "negative": -3.6513e-6}
    assert be.did_not_move(previous, 2.2606e-4, -3.2827e-6, 3.052e-5)


class BothAxes(FakeSMU):
    """Sources either quantity into 10 k, and records what it was told."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls = []
        self.mode = "current"

    def set_source_function(self, mode):
        self.mode = mode
        self.calls.append(("function", mode))

    def set_voltage_level(self, volts): self.level = volts
    def set_current_limit(self, amps): self.calls.append(("limit", amps))
    def set_voltage_limit(self, volts): self.calls.append(("limit", volts))

    def apply_ranges(self, plan, log=None):
        self.plans.append(plan)
        self.calls.append(("ranges", plan))

    def measure(self):
        self._tick += 1
        if self.mode == "voltage":
            return (self.level, self.level / 9958.0)
        return (self.level * 9958.0, self.level)


def test_each_axis_ranges_the_quantity_it_does_not_read():
    """Nothing is inherited from the axis before.

    The 2635B autoranged its current into the pA decades on the voltage
    axis and a reading timed out; the miniSMU was left on its 1 uA range
    by the current axis and its 1 V control came out at 10 mV.
    """
    from smuniversal_lab_suite.core.ranges import NOT_SOURCED

    smu = BothAxes()
    be.sub_count(smu, lambda _: None, be.CURRENT, 9958.0)
    be.sub_count(smu, lambda _: None, be.VOLTAGE, 9958.0)
    current_plan, voltage_plan = smu.plans
    assert current_plan.measure_voltage == be.CURRENT.compliance_for(9958.0)
    assert current_plan.source_voltage is NOT_SOURCED
    assert voltage_plan.measure_current == be.VOLTAGE.compliance_for(9958.0)
    assert voltage_plan.source_current is NOT_SOURCED
    assert voltage_plan.source_voltage == be.BIAS_V


def test_the_limit_is_set_on_both_sides_of_the_ranges():
    """The U2722A needs the range first; the GSM-20H10 the limit first."""
    smu = BothAxes()
    be.sub_count(smu, lambda _: None, be.VOLTAGE, 9958.0)
    order = [kind for kind, _ in smu.calls if kind in ("ranges", "limit")]
    assert order[:3] == ["limit", "ranges", "limit"], order


def test_a_shared_knob_is_pinned_to_the_bias_not_left_at_auto():
    """On one knob per quantity, AUTO beats any fixed value.

    `for_sourcing` leaves the sourced quantity's measurement at AUTO,
    which on the U2722A would have put the current walk on R120mA.
    """
    smu = BothAxes()
    smu.INDEPENDENT_SOURCE_RANGE = False
    be.sub_count(smu, lambda _: None, be.CURRENT, 9958.0)
    be.sub_count(smu, lambda _: None, be.VOLTAGE, 9958.0)
    current_plan, voltage_plan = smu.plans
    assert current_plan.measure_current == be.BIAS_A, current_plan
    assert voltage_plan.measure_voltage == be.BIAS_V, voltage_plan


def test_a_dead_link_stops_the_walk_and_keeps_what_was_measured():
    from smuniversal_lab_suite.core.transports.base import (
        TransportDesynchronised,
    )

    class Dies(FakeSMU):
        def measure(self):
            if 0 < abs(self.level) < 1e-5:
                raise TransportDesynchronised("no reply")
            return super().measure()

    smu = Dies(floor=0.0, noise=1e-12)
    logged = []
    rows = be.sub_count(smu, logged.append)
    assert rows[-1].get("stopped"), rows[-1]
    assert any(r.get("sign_commanded") is True for r in rows[:-1])
    assert any("STOPPED" in line for line in logged)
    assert smu.output is False and smu.level == 0.0


def test_the_envelope_records_the_voltage():
    """Without it, open circuit and nothing-sourcing are the same row."""
    rows = be.envelope(FakeSMU(), lambda _: None)
    assert all(r["mean_v"] == pytest.approx(1.0, rel=0.01) for r in rows)
