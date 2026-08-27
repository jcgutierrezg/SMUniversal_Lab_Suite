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
import sys, os

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


def test_the_widest_range_is_pinned_before_any_level():
    smu = FakeSMU()
    be.sub_count(smu, lambda _: None)
    assert smu.ranges and smu.ranges[0] == 1.0


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
