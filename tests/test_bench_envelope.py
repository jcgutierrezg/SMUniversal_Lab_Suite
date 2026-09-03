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
        self.off_calls = 0
        self._tick = 0

    @classmethod
    def clamp_nplc(cls, nplc):
        low, high = cls.NPLC_RANGE
        return max(low, min(high, nplc))

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

    def measure(self):
        self._tick += 1
        jitter = 3e-6 * (self._tick % 3 - 1)
        current = (1.442e-4 if self.level >= 0 else 2.0e-5) + jitter
        return (current * 9958.0, current)


def test_a_fixed_offset_is_not_a_commanded_sign():
    """The bench case that produced twenty-one false rows."""
    smu = Offset()
    rows = be.sub_count(smu, lambda _: None)

    # Not caught at the control, and that is honest rather than a bug:
    # +144 uA against +20 uA separates by 124 uA, which is a plausible
    # response to a commanded +/-100 uA. A fixed offset and a real
    # signal are genuinely indistinguishable at one level. What
    # separates them is what happens as the level shrinks - the
    # expected separation shrinks with it and the offset does not.
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
    from core.ranges import RangeError

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
