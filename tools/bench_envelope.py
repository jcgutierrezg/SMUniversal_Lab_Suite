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

**Sub-count.** Pin the widest current range, then halve the commanded
level down and at each step command `+X` then `-X`. Below one converter
count there is no signal, only offset residue, and its polarity is not
under anyone's control - established on the U2722A, where `-1 uA` and
`+1 uA` produced the same output and the residue walked the output to
the range rail during a commissioning run.

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
import math
import statistics
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from core.transports.null_transport import NullTransport      # noqa: E402
from core.transports.serial_transport import SerialTransport  # noqa: E402
from core.transports.visa_transport import (                  # noqa: E402
    VisaTransport, VisaPyTransport)
from core.transports.minismu_transport import MiniSMUTransport  # noqa: E402
from drivers.registry import driver_for_idn                   # noqa: E402

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
    """n readings, returning (currents, seconds_per_reading).

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
    return currents, elapsed / n


def envelope(driver, log):
    """Phase 1. Rate against noise, one row per NPLC rung."""
    rows = []
    driver.set_source_function("current")
    driver.set_voltage_limit(COMPLIANCE_V)
    driver.set_current_level(BIAS_A)
    driver.output_on()
    try:
        for nplc in nplc_rungs(driver):
            driver.set_nplc(nplc)
            currents, per_reading = burst(driver)
            blanks = sum(1 for c in currents if not isinstance(c, (int, float)))
            row = {
                "nplc": nplc,
                "seconds_per_reading": per_reading,
                "rate_hz": (1.0 / per_reading) if per_reading > 0 else None,
                "rsd": rsd(currents),
                "blanks": blanks,
            }
            rows.append(row)
            shown = "--" if row["rsd"] is None else f"{row['rsd'] * 100:.3f}%"
            log(f"  NPLC {nplc:>9.4g}  "
                f"{per_reading * 1000:8.2f} ms  "
                f"{row['rate_hz'] or 0:7.1f} Hz  "
                f"RSD {shown}"
                f"{'  BLANKS' if blanks else ''}")
    finally:
        driver.safe_output_off()
    return rows


def sign_is_commanded(driver, level, log):
    """B3/B5. Command +level and -level alternately; do the readings differ?

    Returns (commanded, positive_mean, negative_mean). `commanded` is
    True when the two groups are separated by more than their own
    scatter - if they overlap, the polarity was not under anyone's
    control at this level.
    """
    positives, negatives = [], []
    for i in range(SIGN_READINGS):
        for sign, bucket in ((+1, positives), (-1, negatives)):
            driver.set_current_level(sign * level)
            reading = driver.measure()[1]
            if isinstance(reading, (int, float)):
                bucket.append(reading)
    if len(positives) < 2 or len(negatives) < 2:
        return None, None, None
    pos, neg = statistics.fmean(positives), statistics.fmean(negatives)
    scatter = max(statistics.stdev(positives), statistics.stdev(negatives))
    separation = pos - neg

    # Two conditions, and the second is the one that matters.
    #
    # Bigger than the scatter says the groups are distinguishable. On
    # its own that is not enough: with a quiet instrument the scatter
    # approaches zero and *any* difference clears it, so a fixed offset
    # that happens to differ by a nanoamp would read as a working sign.
    # An offline fake did exactly that and this check believed it.
    #
    # Bigger than the level says the difference is the one that was
    # asked for. Commanding +L and -L should separate the readings by
    # 2L; requiring at least L allows for a compliance-limited or
    # half-honoured output while still refusing residue, which does not
    # scale with L at all.
    commanded = separation > 3 * scatter and separation > abs(level)
    return commanded, pos, neg


def sub_count(driver, log):
    """Phase 2. Halve down from full scale until the sign stops following."""
    driver.set_source_function("current")
    driver.set_voltage_limit(COMPLIANCE_V)
    # Widest range the driver will give us. Asking for a large level
    # rather than naming a range, because only one driver in the fleet
    # declares a range ladder at all.
    driver._apply_source_current_range(1.0)
    driver.set_current_level(0.0)
    driver.output_on()
    rows = []
    try:
        # B6. The control leg, at a level the instrument must honour.
        # If this ever reads as uncommanded, the probe is measuring
        # nothing and every row below it is meaningless.
        control, pos, neg = sign_is_commanded(driver, BIAS_A, log)
        log(f"  control at {BIAS_A:.3e} A: sign "
            f"{'follows' if control else 'DOES NOT FOLLOW'} "
            f"(+{pos:.4e} / {neg:.4e})" if pos is not None
            else "  control produced no readings")
        rows.append({"level": BIAS_A, "control": True,
                     "sign_commanded": control,
                     "positive": pos, "negative": neg})
        if not control:
            log("  ABORTING: the control leg failed, so nothing below it "
                "would mean anything.")
            return rows

        level = BIAS_A
        while level > BIAS_A * MIN_FRACTION:
            level /= 2.0
            commanded, pos, neg = sign_is_commanded(driver, level, log)
            rows.append({"level": level, "control": False,
                         "sign_commanded": commanded,
                         "positive": pos, "negative": neg})
            log(f"  {level:.3e} A: sign "
                f"{'follows' if commanded else 'does not follow'}"
                + (f" (+{pos:.4e} / {neg:.4e})" if pos is not None else ""))
            if commanded is False:
                log(f"\n  The commanded sign stops being followed below "
                    f"{level * 2:.3e} A on this range.")
                break
    finally:
        driver.set_current_level(0.0)
        driver.safe_output_off()
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="demo")
    parser.add_argument("--transport", default="visa", choices=TRANSPORTS)
    parser.add_argument("--load", type=float, required=True,
                        help="measured load resistance in ohms, e.g. 9958")
    args = parser.parse_args(argv)

    transport = TRANSPORTS[args.transport]()
    transport.connect(args.address)
    idn = transport.query("*IDN?")
    driver = driver_for_idn(idn)(transport)
    driver.identify()
    driver.reset()

    def log(text):
        print(text, flush=True)

    log(f"{idn}\nload {args.load} ohm, bias {BIAS_A:.3e} A, "
        f"compliance {COMPLIANCE_V} V\n")
    try:
        log("Envelope:")
        rows = envelope(driver, log)
        log("\nSub-count:")
        floor = sub_count(driver, log)
    finally:
        driver.safe_output_off()
        transport.close()

    log("\n--- paste everything above this line ---")
    return {"idn": idn, "load_ohm": args.load,
            "envelope": rows, "sub_count": floor}


if __name__ == "__main__":
    main()
