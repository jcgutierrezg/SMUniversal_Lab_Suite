"""
Keithley 2400 SourceMeter - the 200 V member of the 2400 series.

The dialect is in `keithley_2400_series.py`, shared with the 2401: one
manual (2400S-900-01) and one SCPI command reference cover both. What
is in this file is what is the 2400's own - its identity and its
envelope - and, deliberately, **no bench claims yet**. The 2401's
readback trust and sub-count floor were earned on that unit and stay
in its file; this model is `unverified` and `unmeasured` until a
session on a 2400 says otherwise (see the note in the series file).

What the extra range changes
----------------------------
The 2400 adds a 200 V source and measure range (±210 V / ±211 V) to the
2401's three, and with it the same corner the 2450 has: 21 V at 1.05 A,
or 210 V at 105 mA, never both - 22 W. The manual's Figure 6-3 draws the
two boxes. `power_envelope` declares them, so a run asking for 1 A of
compliance above 21 V is refused before anything is sent.

The current ranges are the 2401's, 1 uA to 1 A.

Not here
--------
The over-voltage protection, `:SOUR:VOLT:PROT`, which `*RST` leaves at
NONE (the full 210 V). It would be a hardware backstop on the 200 V
range, but it is new behaviour the 2401 does not have, so it was left
for a change of its own (decided 2026-11-18).

A 2400-LV is a 21 V instrument. Should one ever reply with a string
containing `MODEL 2400`, it would be matched here and given limits it
does not have; the instrument would still refuse the levels it cannot
reach, with an error the checkup reports.
"""
from smuniversal_lab_suite.core.limits import SMULimits

from .base_smu import BaseSMU
from .keithley_2400_series import Keithley2400Series


class Keithley2400(Keithley2400Series):
    # Only the long form. A bare "2400" would match any reply whose
    # serial number or firmware date happens to contain it - and the
    # registry's longest-match rule means "MODEL 2401" still wins for a
    # 2401 whose serial does.
    MODEL_IDS = ["MODEL 2400"]
    DISPLAY_NAME = "Keithley 2400"

    LIMITS = SMULimits(
        max_voltage=210.0,
        max_current=1.05,
        voltage_ranges=[0.2, 2.0, 20.0, 200.0],
        current_ranges=[1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0],
        # 21 V at 1.05 A, or 210 V at 105 mA - not both maxima at once.
        # The same corner as the 2450's.
        power_envelope=[(21.0, 1.05), (210.0, 0.105)],
    )

    #: It reaches 210 V, so a run above 50 V asks first, as on every
    #: other SMU here that can.
    HAZARDOUS_ABOVE_V = 50.0

    # ---- bench claims: none yet ----
    #
    # Stated rather than left to the BaseSMU defaults, so that nobody
    # reading the 2401's file next door takes their absence here for an
    # oversight. Each is promoted by a bench session on a 2400, never by
    # analogy with the 2401.

    #: `tools/bench_envelope.py` has not been run on a 2400.
    SOURCE_COUNTS_PER_RANGE = {"current": None, "voltage": None}

    SUB_COUNT_LEVELS = {"current": BaseSMU.SUB_COUNT_UNMEASURED,
                        "voltage": BaseSMU.SUB_COUNT_UNMEASURED}

    #: The queries are the 2401's, so they answer; whether they report
    #: the state rather than the last write is a bench question
    #: (`tools/bench_readback.py`), not yet asked of a 2400.
    COMPLIANCE_READBACK_TRUSTED = False
    RANGE_READBACK_TRUSTED = False
