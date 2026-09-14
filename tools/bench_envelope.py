"""
One bench pass per instrument: how fast can it poll, and where does the
commanded sign stop being commanded.

    uv run python tools/bench_envelope.py --address GPIB0::9::INSTR --load 9958
    uv run python tools/bench_envelope.py --transport demo --load 9958

Run `tools/smu_checkup.py` first on the same fixture. This tool does not
repeat it; the checkup writes its own report and owns commissioning.

Two phases, one connection, deliberately in this order.

**Envelope.** At each rung of the driver's declared NPLC ladder, hold a
fixed bias and take a burst of readings. Records the achieved sample
rate and the relative standard deviation. The question it answers is
the one a per-reading figure cannot: *after the first read, how fast can
I poll while keeping the noise I can live with?*

Relative standard deviation, not peak-to-peak. `tools/timing_scan.py`
uses peak-to-peak and is right to - its question is "is this instrument
integrating at all?", where a thirtyfold change is unmissable however it
is measured. For comparing instruments peak-to-peak is set by the single
worst sample and grows with the burst length, so an instrument scanned
harder looks noisier.

**Sub-count.** Pin the range that carries the bias, then halve the
commanded level down and at each step command `+X` then `-X`, on the
current axis and then the voltage axis. Below the output's zero offset
the polarity is not under anyone's control - established on the U2722A,
where `-1 uA` and `+1 uA` produced the same output and the residue
walked the output to the range rail during a commissioning run. It runs
at `SUB_COUNT_NPLC`, set explicitly rather than left at the envelope's
last - and longest - rung.

**The reading noise is the detection limit, and it is not the same
thing as the source floor.** Below the noise the sign is undetectable
whatever the source is doing, so a crossing found there is a statement
about the measurement, not about the converter. Compare the crossing
against the envelope phase's RSD at the same NPLC before reading it as
a source floor: if they coincide, the answer is "quieter integration
needed", not "here is the count".

The floor is *measured*, not predicted. No driver here declares its
converter bits, so where one count falls is exactly what is unknown.
Halving from full scale brackets the crossing, and the crossing is the
number a deviation-54 equivalent would need.

Nothing is predicted from the load resistance. The load is measured with
one of these instruments, so using it to judge them is circular. The
sign flip needs no calibration: either the reading follows the commanded
polarity or it does not.

SAFETY
------
This energises whatever is in the fixture. The bias is bounded by the
compliance, not by the commanded level, so the worst case on any range
is the compliance into the load - 2 V into 10 k is 200 uA and 0.4 mW.
The output goes off between phases, on any exception, and on Ctrl-C.
Nothing runs without an explicit `--load`.
"""
import argparse
import dataclasses
import math
import statistics
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from smuniversal_lab_suite.core.ranges import (  # noqa: E402
    RangeError,
    RangePlan,
)
from smuniversal_lab_suite.core.transports.base import (
    TransportDesynchronised,  # noqa: E402
)
from smuniversal_lab_suite.core.transports.minismu_transport import (
    MiniSMUTransport,  # noqa: E402
)
from smuniversal_lab_suite.core.transports.null_transport import (
    NullTransport,  # noqa: E402
)
from smuniversal_lab_suite.core.transports.serial_transport import (
    SerialTransport,  # noqa: E402
)
from smuniversal_lab_suite.core.transports.visa_transport import (  # noqa: E402
    VisaPyTransport,
    VisaTransport,
)
from smuniversal_lab_suite.drivers.registry import driver_for_idn  # noqa: E402

TRANSPORTS = {
    "visa": VisaTransport,
    "visapy": VisaPyTransport,
    "serial": SerialTransport,
    "minismu": MiniSMUTransport,
    "demo": NullTransport,
}

#: Signed off as B1. Fixed rather than scaled per instrument: a bias at
#: each instrument's mid-range would be fairer to the wide-range ones
#: and would make the numbers incomparable, which is the whole point of
#: the table this feeds.
BIAS_A = 100e-6

#: Bounds every phase. Into 10 k this caps the current at 200 uA
#: whatever range is pinned or whatever level is commanded.
COMPLIANCE_V = 2.0

#: B2. Enough that a standard deviation means something, few enough that
#: a 25 PLC rung does not take a minute.
BURST = 20

#: B5. Alternating, not ten of each: on an instrument where charge
#: survives between readings, ten consecutive positives would drift into
#: a different state than ten consecutive negatives, and the comparison
#: would measure the drift rather than the sign.
SIGN_READINGS = 10

#: B4. Stop before the levels stop meaning anything even in principle.
MIN_FRACTION = 1e-6

#: The voltage-axis bias, chosen to put the standard fixture in the same
#: place the current axis does: 100 uA through 9958 ohm is 0.9958 V, and
#: 1 V across 9958 ohm draws 100.4 uA.
BIAS_V = 1.0

#: How much room the compliance leaves above what the bias will actually
#: reach.
#:
#: Derived from the measured load rather than fixed, and the first
#: version was fixed - 200 uA, which is right for 9958 ohm and wrong for
#: anything else. On the demo transport, whose simulated load is 1 k, a
#: 1 V bias against a 200 uA ceiling clamped at 0.2 V and the control leg
#: correctly refused to report a floor from it.
#:
#: That is the failure this factor exists to prevent, and it is the same
#: one the current axis hit when it pinned the widest range: a control
#: leg that is itself limited tests the condition it exists to rule out.
#: Twice the reached value is enough room to be sure the limit is not in
#: play, and near enough to the 2 V the current axis used on the standard
#: fixture (1.99 V) that floors stay comparable with the 2026-09-01 data.
COMPLIANCE_HEADROOM = 2.0

#: The fixture this bench uses, and the one the 2026-09-01 floors were
#: measured on.
#:
#: `main()` requires `--load`, so this is only reached by a caller that
#: asks for a sub-count run without naming a fixture - the tests do, and
#: a floor derived against a load that is not the one on the bench would
#: be wrong in a way nothing downstream could detect. Named rather than
#: defaulted silently so that a wrong number here is visible.
STANDARD_LOAD_OHM = 9958.0

#: The integration time the sub-count phase runs at, set explicitly.
#:
#: Until 2026-09-11 it was not set at all: the phase inherited whatever
#: the envelope's last rung left behind, which is the TOP of the ladder.
#: Every 2026-09-01 floor was therefore measured at 10-255 PLC by
#: accident. On the U2722A that is 10.4 s a reading, and the voltage
#: axis - which, unlike the current axis, is not refused five halvings
#: in - would have taken most of an hour on one instrument.
#:
#: One PLC because the 2026-09-01 envelope shows every instrument
#: already at or below one count of noise there (quantised, or RSD
#: under 0.001% at 100 uA), so the longer integration was buying
#: nothing the sign test could see. The current axis re-run at this
#: setting is the check on that claim: its floors should land where
#: the 2026-09-01 ones did. One PLC is also the one setting every
#: ladder in the fleet contains, and it rejects mains hum.
SUB_COUNT_NPLC = 1.0

#: How far the control readings may sit from the command.
#:
#: The sign test's window - separation between half and three times
#: what was asked for - is wide on purpose, because below a count an
#: honest output is partly honoured. At the control level there is no
#: such excuse: 100 uA and 1 V are thousands of counts on every range
#: here, so the reading should be the command. On 2026-09-11 the U2722A
#: read 71% of it at every level and the window passed all of them.
CONTROL_ACCURACY = 0.05

#: Readings thrown away after each step, to start with, and the most
#: the calibration will try.
#:
#: The sign test steps the output from -L to +L before every reading, so
#: a reading taken before the output has finished moving catches it on
#: the way. The envelope cannot show this: it holds one level and never
#: steps. At 1 PLC the U2722A had not arrived, and every row of its
#: 2026-09-11 current walk read about 71% of the command.
#:
#: One discard also covers the first reading after `output_on()`, which
#: on the GSM-20H10's voltage axis was taken before the source was up -
#: nine readings of 1.0 V and one of 0, a control mean of 0.89996.
SETTLE_READINGS = 1
MAX_SETTLE_READINGS = 16

#: How much the reading may still move between the last discard and the
#: kept reading, as a fraction of the control level, before the output
#: counts as still settling.
SETTLE_TOLERANCE = 0.01


class Axis:
    """Which quantity is being sourced, and how to say so to a driver.

    The sub-count question is the same on both axes and the answer is
    not: a converter has a bottom count per range whichever quantity it
    is producing, and the count differs. Rather than a second copy of
    `sign_is_commanded` with `current` replaced by `voltage` throughout -
    where the two would drift and only one would carry the bounds that
    were argued for on the bench - the axis is a parameter.

    `reading_index` is which half of `measure()` to believe. Sourcing
    current, the interesting reading is the current; sourcing voltage it
    is the voltage. Reading the other one measures the load.
    """

    def __init__(self, name, unit, bias, compliance_unit,
                 set_level, set_compliance, reading_index):
        self.name = name
        self.unit = unit
        self.bias = bias
        self.compliance_unit = compliance_unit
        self._set_level = set_level
        self._set_compliance = set_compliance
        self.reading_index = reading_index

    def compliance_for(self, load_ohm):
        """The limit on the OTHER quantity, with room to spare.

        Sourcing current, the other quantity is a voltage and the bias
        will reach `bias * load`; sourcing voltage it is a current and
        the bias will draw `bias / load`. Either way the ceiling is a
        multiple of what the bias actually reaches, so the control leg
        cannot be limited by it on any fixture.
        """
        reached = (self.bias * load_ohm if self.name == "current"
                   else self.bias / load_ohm)
        return COMPLIANCE_HEADROOM * reached

    def prepare(self, driver, load_ohm, log=None):
        """Every range this axis depends on, set here and not inherited.

        Through `RangePlan.for_sourcing`, the plan every experiment and
        the checkup use, so each driver resolves it the way it was
        commissioned to - including the ones with one knob per quantity,
        and the 2400 family, which rejects a measurement range on the
        quantity it is sourcing.

        The first version pinned only the source range and left the
        other quantity's range to whatever came before, and both ways
        that went wrong were seen on 2026-09-11:

        * the 2635B autoranged its current measurement into the pA
          decades on the voltage axis, where every range has a long
          settle, and one reading outlasted the 3 s timeout;
        * the miniSMU was left on its 1 uA range by the current axis,
          so the voltage axis's 1 V control came out at 10 mV - one
          microamp into the load.

        The other quantity is ranged to carry the compliance, which is
        the most it can reach.

        On a one-knob instrument the plan is adjusted: `for_sourcing`
        leaves the sourced quantity's measurement at AUTO, and on a
        shared knob AUTO wins the reconciliation - so the U2722A would
        have walked its current on R120mA and its voltage on R20V, not
        on the ranges that carry the bias. Stating the bias there makes
        the widest of the two the bias.

        The limit is set on both sides of the ranges, because the fleet
        disagrees about the order. The U2722A needs the range first
        (fault 15: a range applied after a limit can clamp it). The
        GSM-20H10 needs the limit first: a measurement range above the
        compliance in force gives `+824` and is left at the
        compliance's range, and after reset that compliance is 105 uA.
        Limit, ranges, limit satisfies both.
        """
        compliance = self.compliance_for(load_ohm)
        plan = RangePlan.for_sourcing(self.name, source_range=self.bias,
                                      measure_range=compliance)
        if not getattr(driver, "INDEPENDENT_SOURCE_RANGE", True):
            plan = dataclasses.replace(
                plan, **{f"measure_{self.name}": self.bias})
        set_limit = getattr(driver, self._set_compliance)
        driver.set_source_function(self.name)
        set_limit(compliance)
        driver.apply_ranges(plan, log=log)
        set_limit(compliance)
        # `apply_ranges` records the source range, and a driver with a
        # declared floor then refuses at ten counts of it - which is
        # exactly where this pass needs to look below. Forgetting it
        # puts the guard back on the narrowest-range bound, where it
        # was when this pass called the range hooks directly and where
        # the 2026-09-01 walks were taken. A driver that knows its range
        # some other way still refuses, and that is reported as the
        # floor.
        driver._record_source_range(self.name, None)
        getattr(driver, self._set_level)(0.0)

    def command(self, driver, level):
        getattr(driver, self._set_level)(level)

    def read(self, driver):
        return driver.measure()[self.reading_index]


CURRENT = Axis("current", "A", BIAS_A, "V",
               "set_current_level", "set_voltage_limit", reading_index=1)

VOLTAGE = Axis("voltage", "V", BIAS_V, "A",
               "set_voltage_level", "set_current_limit", reading_index=0)

AXES = {"current": CURRENT, "voltage": VOLTAGE}


def rsd(values):
    """Relative standard deviation, as a fraction. None if undefined."""
    numbers = [v for v in values if isinstance(v, (int, float))]
    if len(numbers) < 2:
        return None
    mean = statistics.fmean(numbers)
    if mean == 0:
        return None
    return statistics.stdev(numbers) / abs(mean)


def nplc_rungs(driver, count=6):
    """The declared ladder, logarithmically spaced, duplicates collapsed.

    Logarithmic because the interesting behaviour is at both ends and
    the ladders here span five orders of magnitude on one instrument and
    a factor of 255 on another.
    """
    span = type(driver).NPLC_RANGE
    if not span:
        return []
    low, high = span
    if high <= low:
        return [low]
    step = (math.log(high) - math.log(low)) / (count - 1)
    seen = []
    for i in range(count):
        achieved = type(driver).clamp_nplc(math.exp(math.log(low) + step * i))
        if not any(abs(achieved - x) < 1e-12 for x in seen):
            seen.append(achieved)
    return seen


def burst(driver, n=BURST):
    """n readings, returning (currents, voltages, seconds_per_reading).

    The first reading is taken and discarded. Every instrument in this
    fleet pays a large one-off after `output_on()` - between 1.3x and
    14x the steady figure - and averaging it in is what this tool exists
    to stop doing.
    """
    driver.measure()
    started = time.perf_counter()
    readings = [driver.measure() for _ in range(n)]
    elapsed = time.perf_counter() - started
    currents = [r[1] for r in readings]
    voltages = [r[0] for r in readings]
    return currents, voltages, elapsed / n


def envelope(driver, log):
    """Phase 1. Rate against noise, one row per NPLC rung."""
    rows = []
    driver.set_source_function("current")
    driver.set_voltage_limit(COMPLIANCE_V)
    # Pin the same range the sub-count phase uses, so the two phases
    # describe the same instrument configuration and the noise figures
    # are comparable between instruments.
    #
    # Without this the level went onto whatever range reset() left
    # active. On 2026-08-28 the B2901A then read a mean of 4.3e-7 A
    # against a commanded 1e-4 - 250x low, at every rung. The run before
    # it reported RSD 0.000% for the same instrument and looked like the
    # best on the bench, because there was no mean column to contradict
    # it.
    driver._apply_source_current_range(BIAS_A)
    driver.set_current_level(BIAS_A)
    driver.output_on()
    try:
        for nplc in nplc_rungs(driver):
            driver.set_nplc(nplc)
            currents, voltages, per_reading = burst(driver)
            numbers = [c for c in currents if isinstance(c, (int, float))]
            blanks = len(currents) - len(numbers)
            distinct = len(set(numbers))
            mean = statistics.fmean(numbers) if numbers else None
            volts = [v for v in voltages if isinstance(v, (int, float))]
            # The voltage is what tells a clamped output from one that
            # is not sourcing at all. On 2026-09-11 the GSM-20H10 read
            # 2.5 nA at every rung against a commanded 100 uA, which is
            # its own zero offset - and with only the current recorded,
            # "open circuit at the compliance" (about 2 V) and "nothing
            # coming out" (about 0 V) were the same row.
            mean_v = statistics.fmean(volts) if volts else None
            row = {
                "nplc": nplc,
                "seconds_per_reading": per_reading,
                "rate_hz": (1.0 / per_reading) if per_reading > 0 else None,
                "rsd": rsd(currents),
                "blanks": blanks,
                "distinct_values": distinct,
                "mean": mean,
                "mean_v": mean_v,
                # An RSD of zero is not silence. It means every reading
                # landed on the same converter code, so the noise is
                # below one count and this rung says nothing about how
                # quiet the instrument is - only that it has run out of
                # resolution. On the first bench run every instrument
                # reported 0.000% at its upper rungs and the curve went
                # flat, which reads as a perfect result and is not one.
                "quantised": distinct <= 1,
                # The bias is 100 uA into ~10 k against a 2 V
                # compliance. A mean far from the commanded level means
                # the output is clamped, and a clamped output has almost
                # no scatter - so it reads as the QUIETEST rung on the
                # curve. Several drivers here cannot report compliance,
                # and then this is the only thing that would say so.
                "mean_off_command": (mean is not None
                                     and abs(mean - BIAS_A) > 0.2 * BIAS_A),
            }
            rows.append(row)
            if row["quantised"]:
                shown = "quantised (all readings equal)"
            elif row["rsd"] is None:
                shown = "--"
            else:
                shown = f"{row['rsd'] * 100:.3f}%"
            log(f"  NPLC {nplc:>9.4g}  "
                f"{per_reading * 1000:8.2f} ms  "
                f"{row['rate_hz'] or 0:7.1f} Hz  "
                f"RSD {shown}"
                + (f"  V {mean_v:+.4e}" if mean_v is not None else "")
                + f"{'  BLANKS' if blanks else ''}"
                + (f"  [mean {mean:.4e} A, commanded {BIAS_A:.3e} - CLAMPED?]"
                   if row["mean_off_command"] else ""))
    finally:
        driver.safe_output_off()
    return rows


def sign_is_commanded(driver, level, log, axis=None,
                      settle=SETTLE_READINGS):
    """B3/B5. Command +level and -level alternately; do the readings differ?

    Returns (commanded, positive_mean, negative_mean). `commanded` is
    True when the two groups are separated by more than their own
    scatter - if they overlap, the polarity was not under anyone's
    control at this level.
    """
    result = sign_test(driver, level, axis, settle)
    return result["commanded"], result["positive"], result["negative"]


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def sign_test(driver, level, axis=None, settle=SETTLE_READINGS):
    """The sign test, with what it saw along the way.

    A dict: `commanded` and the two means as `sign_is_commanded`
    returns them, plus `scatter` and `settle_shift` - how far the kept
    reading moved from the last one thrown away, the larger of the two
    signs. A shift that is not small means the output was still on its
    way when it was read, and then so is the verdict.
    """
    axis = axis or CURRENT
    positives, negatives = [], []
    last_discards = {+1: [], -1: []}
    for i in range(SIGN_READINGS):
        for sign, bucket in ((+1, positives), (-1, negatives)):
            try:
                axis.command(driver, sign * level)
            except RangeError:
                # The driver refused before energising anything, which
                # is the best possible answer to this question - it is
                # the floor, stated by the driver rather than inferred
                # from readings. Only the U2722A does this today
                # (deviation 54), and the first version of this tool
                # crashed on the one instrument that gets it right.
                return {"commanded": "refused", "positive": None,
                        "negative": None, "scatter": None,
                        "settle_shift": None}
            discard = None
            for _ in range(settle):
                discard = axis.read(driver)
            reading = axis.read(driver)
            if _is_number(reading):
                bucket.append(reading)
                if _is_number(discard):
                    last_discards[sign].append(discard)
    if len(positives) < 2 or len(negatives) < 2:
        return {"commanded": None, "positive": None, "negative": None,
                "scatter": None, "settle_shift": None}
    pos, neg = statistics.fmean(positives), statistics.fmean(negatives)
    scatter = max(statistics.stdev(positives), statistics.stdev(negatives))
    shifts = [abs(statistics.fmean(kept) - statistics.fmean(last_discards[s]))
              for s, kept in ((+1, positives), (-1, negatives))
              if last_discards[s]]
    settle_shift = max(shifts) if shifts else None
    separation = pos - neg

    # The separation must be ABOUT the one that was asked for - bounded
    # from both sides.
    #
    # The first version required only `separation > abs(level)`, on the
    # reasoning that residue does not scale with the level. That is
    # backwards: the threshold shrinks with the level, so a FIXED offset
    # clears it more easily the smaller the request gets. On the bench
    # it reported "sign follows" for twenty-one consecutive halvings
    # down to 95 pA, on readings that never moved off +140 uA and
    # +20 uA - both positive, nothing following anything.
    #
    # Commanding +L then -L should separate the readings by 2L. Half of
    # that allows for a compliance-limited or partly honoured output;
    # three times it allows for gain error and noise. An offset that
    # does not track the command satisfies neither once L is small.
    expected = 2 * abs(level)

    # The legs must land on opposite sides of zero. Decisive, and it
    # needs no threshold: if commanding a negative level reads positive,
    # the polarity was not under anyone's control, whatever the
    # separation happens to be.
    #
    # The GSM-20H10 on 2026-08-28 showed why the separation bound is not
    # enough on its own. Below about 1.5 nA both legs read positive and
    # the readings stopped changing, but a fixed ~0.85 nA offset kept
    # sitting inside the window as the window shrank with the level, so
    # four more rows were reported as following and the floor came out
    # nearly ten times too low.
    opposite_signs = pos > 0 > neg

    commanded = (opposite_signs
                 and separation > 3 * scatter
                 and 0.5 * expected < separation < 3 * expected)
    return {"commanded": commanded, "positive": pos, "negative": neg,
            "scatter": scatter, "settle_shift": settle_shift}


def control_is_accurate(positive, negative, level):
    """Both control legs within CONTROL_ACCURACY of the command."""
    if positive is None or negative is None:
        return False
    tolerance = CONTROL_ACCURACY * abs(level)
    return (abs(positive - abs(level)) <= tolerance
            and abs(negative + abs(level)) <= tolerance)


def did_not_move(previous, positive, negative, level):
    """True when a halving left both legs where they were.

    Halving from 2L to L moves each leg's command by L. If neither leg
    moved by even half of that, the output did not respond to the
    change: what this level produced is what the level above produced,
    so a pass here belongs to the level above, not to this one. This
    row fails whatever its sign test said. The row above stands - its
    own output did change from the one above it.

    The 2401 is why. Its current walk read +6.42e-9 / -6.04e-10 A at
    6.104e-9 A and +6.43e-9 / -6.47e-10 A at 3.052e-9 A on 2026-09-11,
    and the same pair of rows repeated on 2026-09-01; both times the
    sign test passed the second and reported it as the floor.

    Both legs, not either: at a small level one leg can sit still on
    an offset while the other follows, and that is still a response.
    """
    if not (_is_number(previous.get("positive"))
            and _is_number(previous.get("negative"))):
        return False
    half_step = abs(level) / 2
    return (abs(positive - previous["positive"]) < half_step
            and abs(negative - previous["negative"]) < half_step)


def _settle(driver, axis, log):
    """How many readings the output needs after a step.

    Found at the control level, where a shortfall is unmistakable, and
    then used for every level below. For an output that settles like a
    linear system the fraction still to go after a given wait is the
    same whatever the step, so the count found here holds for the whole
    walk - and below the control the noise would swamp the shift anyway.

    Returns (result, settle): the sign test at the control with the
    count it settled at, or with `None` if it never did.
    """
    settle = SETTLE_READINGS
    while True:
        result = sign_test(driver, axis.bias, axis, settle)
        shift = result["settle_shift"]
        if (result["commanded"] == "refused" or shift is None
                or shift <= SETTLE_TOLERANCE * axis.bias):
            return result, settle
        if settle >= MAX_SETTLE_READINGS:
            log(f"  the output was still moving {settle} readings after "
                f"each step, by {shift:.3e} {axis.unit} - it never settled.")
            return result, None
        log(f"  still moving {settle} reading(s) after each step, by "
            f"{shift:.3e} {axis.unit}; waiting {settle * 2}.")
        settle *= 2


def _row(level, axis, nplc, settle, result, control=False):
    pos, neg = result["positive"], result["negative"]
    return {"level": level, "control": control, "axis": axis.name,
            "nplc": nplc, "settle": settle,
            "sign_commanded": result["commanded"],
            "positive": pos, "negative": neg,
            "scatter": result["scatter"],
            # The midpoint of the two legs is the output's zero offset
            # on this range, and on 2026-09-11 it turned out to be what
            # the crossing measures: the legs straddle zero exactly while
            # the level is larger than the offset. Recorded on every row
            # because it is steady across levels, so the rows well above
            # the crossing measure it best.
            "offset": ((pos + neg) / 2
                       if _is_number(pos) and _is_number(neg) else None)}


def _describe(row, unit):
    if row["positive"] is None or row["negative"] is None:
        return ""
    return (f" ({row['positive']:+.4e} / {row['negative']:+.4e})"
            f"  offset {row['offset']:+.2e} {unit}")


def _last_followed(rows):
    followed = [r["level"] for r in rows if r.get("sign_commanded") is True]
    return followed[-1] if followed else None


def sub_count(driver, log, axis=None, load_ohm=None, nplc=None):
    """Phase 2. Halve down from full scale until the sign stops following."""
    axis = axis or CURRENT
    load_ohm = (STANDARD_LOAD_OHM if load_ohm is None
                else load_ohm)
    # Set, never inherited - see SUB_COUNT_NPLC. None from clamp_nplc
    # means the model has no integration setting, and then there is
    # nothing to inherit either.
    nplc = type(driver).clamp_nplc(
        SUB_COUNT_NPLC if nplc is None else nplc)
    if nplc is not None:
        driver.set_nplc(nplc)
        log(f"  integration {nplc:g} PLC")
    # Pin the range that suits the BIAS, not the widest available.
    #
    # The first version asked for 1.0 A, on the reasoning that a wide
    # range puts one count high and makes the floor easy to reach. It
    # made the control leg impossible instead: 100 uA on a 1 A range is
    # itself sub-count, so the control was testing the condition it
    # exists to rule out, and it failed on four instruments. It also
    # raised ValueError on the miniSMU, whose ladder stops at 180 mA.
    #
    # The compliance settles it independently. 2 V into ~10 k caps the
    # current at 200 uA, so no level on a wide range could be honoured
    # even if the converter would allow it. The narrowest range that
    # carries the bias is the only one where the control means
    # anything, and the floor found on it is a real floor for that
    # range.
    axis.prepare(driver, load_ohm, log)
    driver.output_on()
    rows = []
    level = axis.bias
    try:
        # B6. The control leg, at a level the instrument must honour.
        # If this ever reads as uncommanded, the probe is measuring
        # nothing and every row below it is meaningless.
        result, settle = _settle(driver, axis, log)
        if result["commanded"] == "refused":
            log("  the driver refuses the bias itself - nothing to probe.")
            return rows
        control = _row(axis.bias, axis, nplc, settle, result, control=True)
        accurate = control_is_accurate(control["positive"],
                                       control["negative"], axis.bias)
        rows.append(control)
        if control["positive"] is None:
            log("  control produced no readings")
        else:
            log(f"  control at {axis.bias:.3e} {axis.unit}: sign "
                f"{'follows' if result['commanded'] else 'DOES NOT FOLLOW'}"
                f"{_describe(control, axis.unit)}")
            if result["commanded"] and not accurate:
                log(f"  but more than {CONTROL_ACCURACY:.0%} from the "
                    f"command, which no count or offset explains at this "
                    f"level: the output is limited, or still moving when "
                    f"it is read.")
        if settle is not None and settle > SETTLE_READINGS:
            log(f"  {settle} readings discarded after every step from "
                f"here on.")
        if not (result["commanded"] and accurate and settle is not None):
            control["sign_commanded"] = False
            log("  ABORTING: the control leg failed, so nothing below it "
                "would mean anything.")
            return rows

        while level > axis.bias * MIN_FRACTION:
            level /= 2.0
            result = sign_test(driver, level, axis, settle)
            row = _row(level, axis, nplc, settle, result)
            previous = rows[-1]
            rows.append(row)
            if result["commanded"] == "refused":
                log(f"  {level:.3e} {axis.unit}: REFUSED by the driver "
                    f"before the "
                    f"output was energised - it will not source a level "
                    f"it cannot express, so the floor is declared rather "
                    f"than measured.")
                break
            log(f"  {level:.3e} {axis.unit}: sign "
                f"{'follows' if result['commanded'] else 'does not follow'}"
                f"{_describe(row, axis.unit)}")
            if (row["positive"] is not None
                    and did_not_move(previous, row["positive"],
                                     row["negative"], level)):
                row["sign_commanded"] = False
                row["frozen"] = True
                log(f"  the same output as at {previous['level']:.3e} "
                    f"{axis.unit}: halving the command changed nothing, "
                    f"so this level is not being followed whatever the "
                    f"signs say.")
            if row["sign_commanded"] is False:
                last = _last_followed(rows)
                if last is not None:
                    log(f"\n  The commanded sign stops being followed "
                        f"below {last:.3e} {axis.unit} on this range.")
                break
        else:
            log(f"\n  Still following at {level:.3e} {axis.unit}, where "
                f"the walk ends - no crossing on this range.")
    except TransportDesynchronised as exc:
        # Recorded, not swallowed: the link cannot be read again, so the
        # walk cannot continue, but everything above this level was
        # measured on a working link and is worth keeping. `main()`
        # sees the latched transport and stops there.
        log(f"  STOPPED at {level:.3e} {axis.unit}: the instrument "
            f"stopped answering. {exc}")
        log("  The rows above are valid; nothing at or below this level "
            "was measured.")
        rows.append({"level": level, "control": False, "axis": axis.name,
                     "nplc": nplc, "sign_commanded": None,
                     "positive": None, "negative": None,
                     "stopped": str(exc)})
    finally:
        # Both are writes, which a desynchronised link still carries -
        # see Transport.write. Commanded, not confirmed.
        axis.command(driver, 0.0)
        driver.safe_output_off()
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="demo")
    parser.add_argument("--transport", default="visa", choices=TRANSPORTS)
    parser.add_argument("--load", type=float, required=True,
                        help="measured load resistance in ohms, e.g. 9958")
    parser.add_argument("--axis", default="both",
                        choices=("current", "voltage", "both"),
                        help="which source axis to probe for its "
                             "floor. The default does both, in "
                             "that order, on one connection")
    args = parser.parse_args(argv)

    transport = TRANSPORTS[args.transport]()
    transport.connect(args.address)
    idn = transport.query("*IDN?")
    driver = driver_for_idn(idn)(transport)
    driver.identify()
    driver.reset()

    def log(text):
        print(text, flush=True)

    chosen = ["current", "voltage"] if args.axis == "both" else [args.axis]
    log(f"{idn}")
    log(f"load {args.load} ohm")
    floors = {}
    rows = []
    stopped = None
    try:
        log("")
        log("Envelope:")
        rows = envelope(driver, log)
        for name in chosen:
            axis = AXES[name]
            if transport.is_desynchronised:
                # The walk before this one lost the link. Every reply
                # from here would answer an earlier question, so the
                # axis is not attempted - and said so, so the paste
                # shows what is missing rather than ending early.
                log("")
                log(f"Sub-count ({axis.name}): not run - the link is out "
                    f"of step. Reconnect and re-run with --axis "
                    f"{axis.name}.")
                continue
            # Restated per axis rather than only in the header: the
            # two do not share a bias, and a reader comparing floors
            # across instruments has to know which fixture produced
            # which number.
            log("")
            log(f"Sub-count ({axis.name}, bias {axis.bias:.3e} "
                f"{axis.unit}, compliance "
                f"{axis.compliance_for(args.load):.3e} "
                f"{axis.compliance_unit}):")
            floors[name] = sub_count(driver, log, axis,
                                     args.load)
    except TransportDesynchronised as exc:
        # Outside a walk - the envelope, or a walk's setup. Reported and
        # the run ends; the paste marker still prints, because what was
        # measured before this is worth pasting.
        log("")
        log(f"STOPPED: the instrument stopped answering. {exc}")
    finally:
        driver.safe_output_off()
        transport.close()

    if transport.is_desynchronised:
        stopped = transport.desync_reason
    log("")
    log("--- paste everything above this line ---")
    return {"idn": idn, "load_ohm": args.load, "envelope": rows,
            "sub_count": floors.get("current", []), "floors": floors,
            "stopped": stopped}


if __name__ == "__main__":
    sys.exit(1 if main().get("stopped") else 0)
