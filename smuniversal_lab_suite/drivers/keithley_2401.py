"""
Keithley 2401 SourceMeter - the 20 V member of the 2400 series.

The dialect - every command this driver sends, and why - is in
`keithley_2400_series.py`, shared with the Keithley 2400. It lived here
until 2026-11-18 and was lifted out unchanged; the bench history in the
docstrings there is this instrument's. What stays in this file is what
is the 2401's own: its identity, its envelope, and the numbers measured
on this lab's unit (serial 4084766).
"""
from smuniversal_lab_suite.core.limits import SMULimits

from .base_smu import BaseSMU
from .keithley_2400_series import Keithley2400Series


class Keithley2401(Keithley2400Series):
    # "MODEL 2401" is what the instrument actually reports. Bare "2401"
    # is a fallback for reply strings that omit the MODEL keyword; the
    # registry prefers the longer match when both are present.
    MODEL_IDS = ["MODEL 2401", "2401"]
    DISPLAY_NAME = "Keithley 2401"

    LIMITS = SMULimits(
        max_voltage=21.0,
        max_current=1.05,
        voltage_ranges=[0.2, 2.0, 20.0],
        current_ranges=[1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0],
        # The 2401 is the 20 V member of the 2400 family - it does not
        # have the 200 V range its 2400/2410 siblings do. Declaring the
        # flat maxima is enough: unlike the 2400 and 2450 there is no
        # high-voltage corner to trade against current, so a single
        # rectangle describes the whole operating region.
        power_envelope=[],
    )

    #: Counts across one source range, measured 2026-09-01.
    #:
    #: `tools/bench_envelope.py` pinned the source current range to
    #: 1e-4 A, then halved the commanded level while watching whether
    #: the two legs of a +/- pair still landed on opposite sides of
    #: zero. The sign stopped following below **3.052e-09 A**, and
    #:
    #:     1e-4 A / 32768 = 3.0518e-09 A
    #:
    #: 32768 is what is declared. It is a refusal threshold, not a
    #: measured converter width: the walk halves from full scale, so
    #: every level it tries is the range over a power of two and any
    #: crossing matches one. And the 3.052e-09 A row that set it
    #: produced the same output as the 6.104e-09 A row above it, on
    #: 2026-09-01 and again on 2026-09-11 - the output last changed at
    #: 6.104e-09 A. Ten counts is 3.05e-08 A, five times that, which is
    #: the margin the floor actually rests on.
    #:
    #: **Current only.** The bench procedure sources current and only
    #: current (`sub_count()` calls `set_source_function("current")`),
    #: so nothing here has measured the voltage converter. Carrying this
    #: number across to the voltage axis would be an inference dressed
    #: as a measurement, which is the thing `SUB_COUNT_LEVELS` exists to
    #: stop - so the voltage axis stays `unmeasured`.
    SOURCE_COUNTS_PER_RANGE = {"current": 32768, "voltage": None}

    SUB_COUNT_LEVELS = {"current": BaseSMU.SUB_COUNT_REFUSED,
                        "voltage": BaseSMU.SUB_COUNT_UNMEASURED}

    #: The compliance readback, which this driver did not have. Until
    #: 2026-09-04 the checkup reported "Keithley 2401 does not report
    #: its compliance - a collapse here would be invisible", and that
    #: was a statement about the driver rather than about the
    #: instrument: `:SENS:CURR:PROT` is written by `set_current_limit()`.
    #:
    #: Trusted since 2026-09-11. `tools/bench_readback.py` followed two
    #: writes of each limit and then wrote ten times the model's
    #: maximum: the instrument refused it (`-222`) and the query kept
    #: reporting the value that survived - the state, not the last
    #: write. Both limits, one unit (serial 4084766).
    COMPLIANCE_READBACK_TRUSTED = True

    #: The four range queries, `:SOUR:*:RANG?` and `:SENS:*:RANG?`.
    #:
    #: Trusted since 2026-09-11, on all four axes. For each,
    #: `tools/bench_readback.py` read the range first, a different one
    #: was set from the front panel and the query named it, and the
    #: query then followed two bus range changes. One unit.
    RANGE_READBACK_TRUSTED = True
