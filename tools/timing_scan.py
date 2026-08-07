"""
Measure how a reading's cost varies with integration time.

    uv run tools/timing_scan.py --address COM5 --transport minismu
    uv run tools/timing_scan.py --address GPIB0::25::INSTR --points 6

Times readings across the instrument's whole declared NPLC range and
fits `time = overhead + apertures x integration`. Prints the table, the
fit, and the residuals.

Why this exists
---------------
`smu_checkup --nplc <slow>` gives two timing points, and two points fit
a two-parameter model exactly - it passes through both by construction,
so it can neither be wrong nor be checked. It answers "what rate would
explain these two readings" and nothing more.

That is enough to catch an error of the size the miniSMU had, where the
declared aperture was out by two orders of magnitude. It is not enough
to trust the resulting number, and it says nothing about whether the
model itself holds.

This scans four or more points. With more points than parameters the
residuals become meaningful: if they are small and unstructured the
linear model holds and the fitted rate means something. If they curve,
the model is wrong and the number derived from it should not be relied
on however well two points happened to agree.

*** Nothing connected to the output. It sources nothing; it only reads.
    But an unconnected instrument is the one whose readings are
    predictable. ***
"""
import sys, os, math, time, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.driver_registry import identify, UnknownInstrumentError
from core.transports.visa_transport import VisaTransport, VisaPyTransport
from core.transports.serial_transport import SerialTransport
from core.transports.minismu_transport import MiniSMUTransport
from core.transports.null_transport import NullTransport

TRANSPORTS = {
    "visa": VisaTransport,
    "visapy": VisaPyTransport,
    "serial": SerialTransport,
    "minismu": MiniSMUTransport,
    "demo": NullTransport,
}

LINE_FREQUENCY_HZ = 50.0


def curvature(residuals):
    """How much the residuals bow, as a fraction of their spread.

    A straight line forced through a curve leaves the endpoints on one
    side and the middle on the other. Counting sign changes misses this
    completely - the pattern +,-,-,+ has two of them, the same as noise.
    Comparing the ends against the middle is what shows it up.

    Returns roughly 0 for scatter and at least 1 for a clean bow, capped
    at 1. Normalised by the largest single residual rather than by twice
    it: the scan's points are spaced logarithmically, so one end
    dominates the spread and a genuine bow would otherwise score around
    0.3 and be missed.
    """
    if len(residuals) < 4:
        return 0.0
    ends = (residuals[0] + residuals[-1]) / 2.0
    middle = sum(residuals[1:-1]) / len(residuals[1:-1])
    spread = max(abs(r) for r in residuals)
    if spread == 0:
        return 0.0
    return min(1.0, abs(ends - middle) / spread)


def fit_line(xs, ys):
    """Least squares y = a + b*x. Returns (a, b, residuals)."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denominator = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y)
                for x, y in zip(xs, ys)) / denominator
    intercept = mean_y - slope * mean_x
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    return intercept, slope, residuals


def scan_points(driver, count):
    """NPLC values spread logarithmically across the declared range.

    Logarithmic because the ladder is powers of two and the interesting
    behaviour is at both ends: linear spacing would put almost every
    point at the slow end, where overhead is invisible and the fit
    learns nothing about it.
    """
    low, high = type(driver).NPLC_RANGE
    if high <= low:
        return [low]
    step = (math.log(high) - math.log(low)) / (count - 1)
    wanted = [math.exp(math.log(low) + step * i) for i in range(count)]

    # Collapse duplicates: a coarse ladder maps several requests to the
    # same achievable value, and repeating it adds no information.
    seen = []
    for value in wanted:
        achieved = type(driver).clamp_nplc(value)
        if not any(abs(achieved - x) < 1e-12 for x in seen):
            seen.append(achieved)
    return seen


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--transport", default="visa", choices=TRANSPORTS)
    parser.add_argument("--points", type=int, default=6,
                        help="how many integration times to try (min 3)")
    parser.add_argument("--repeats", type=int, default=5,
                        help="readings averaged at each point")
    args = parser.parse_args()

    if args.points < 3:
        parser.error("--points must be at least 3; with two the fit is "
                     "exact by construction and proves nothing.")

    transport = TRANSPORTS[args.transport]()
    print(f"Connecting to {args.address} over {args.transport}...")
    transport.connect(args.address)

    try:
        driver, idn = identify(transport)
    except UnknownInstrumentError as exc:
        print(f"Not recognised: {exc}")
        return 1
    print(f"Detected: {type(driver).DISPLAY_NAME}")
    print(f"Identity: {idn}\n")

    if not type(driver).supports_nplc():
        print("This model has no integration-time control, so there is "
              "nothing to scan.")
        return 1

    driver.reset()
    driver.set_source_function("voltage")
    driver.set_voltage_level(0.0)
    driver.output_on()          # after the function change, not before

    values = scan_points(driver, args.points)
    print(f"{'NPLC':>12} {'aperture':>12} {'reading':>12} {'per aperture':>14}")
    print("-" * 54)

    apertures = []
    timings = []
    try:
        for nplc in values:
            driver.set_nplc(nplc)
            achieved = type(driver).clamp_nplc(nplc)
            aperture = achieved / LINE_FREQUENCY_HZ

            driver.measure()            # discard: first is often slower
            started = time.perf_counter()
            for _ in range(args.repeats):
                driver.measure(timeout_s=max(10.0, aperture * 4 + 5))
            elapsed = (time.perf_counter() - started) / args.repeats

            apertures.append(aperture)
            timings.append(elapsed)
            print(f"{achieved:12.5g} {aperture * 1000:10.2f} ms "
                  f"{elapsed * 1000:10.2f} ms "
                  f"{elapsed / aperture:13.2f}")
    finally:
        driver.output_off()
        transport.close()

    if len(apertures) < 3:
        print("\nToo few distinct integration times on this model to fit.")
        return 0

    scale = max(timings)
    if scale < 1e-3:
        # Nothing to characterise. The simulated driver answers
        # instantly, and a real instrument this fast would mean the
        # integration is not happening at all - either way, fitting a
        # line through microseconds of jitter would produce a confident
        # and meaningless number.
        print(f"\nEvery reading returned in under a millisecond "
              f"({scale * 1000:.3f} ms at the slowest).\nThere is no "
              f"integration time here to measure - this is either the\n"
              f"simulated instrument or one that is ignoring its NPLC "
              f"setting.")
        return 0

    overhead, slope, residuals = fit_line(apertures, timings)
    spread = max(abs(r) for r in residuals)

    print("\nFit:  reading = overhead + apertures x integration")
    print(f"  apertures per reading : {slope:.3f}")
    print(f"  fixed overhead        : {overhead * 1000:.2f} ms")
    print(f"  largest residual      : {spread * 1000:.2f} ms "
          f"({spread / scale * 100:.1f}% of the slowest reading)")
    print(f"  degrees of freedom    : {len(apertures) - 2}")

    print("\n  residuals (ms):", ", ".join(f"{r * 1000:+.2f}"
                                           for r in residuals))

    print()
    if spread / scale > 0.10:
        print("  The residuals are large. The linear model does not hold "
              "here,\n  so the apertures figure above is not meaningful.")
    elif curvature(residuals) > 0.5:
        # Not "do the signs alternate". A curve fitted with a straight
        # line puts the ends on one side and the middle on the other -
        # +,-,-,+ - which is TWO sign changes, so counting them finds
        # nothing. What identifies it is the ends and the middle
        # disagreeing.
        print("  The ends and the middle of the fit sit on opposite sides "
              "of the\n  line, which is what a curve looks like when a "
              "straight line is\n  forced through it. Treat the fit as "
              "approximate.")
    else:
        print("  Residuals are small and unstructured: the linear model "
              "holds,\n  and the apertures figure can be trusted.")

    if slope <= 0:
        print("\n  The fitted slope is not positive, so reading time is "
              "not\n  increasing with integration time at all. Either the "
              "NPLC\n  setting is being ignored, or the timings are "
              "dominated by\n  something other than the measurement.")
    elif abs(slope - round(slope)) < 0.2 and round(slope) >= 1:
        print(f"\n  {round(slope)} integration(s) per reading, as expected "
              f"for this driver.")
    elif slope < 0.5:
        print(f"\n  Under one integration per reading is impossible: the "
              f"driver's\n  declared aperture is about {1 / slope:.0f}x too "
              f"long, and the NPLC it\n  records is overstated by the same "
              f"factor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
