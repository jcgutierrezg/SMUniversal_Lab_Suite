"""
Multicomp Pro MP710772 DC electronic load - the second load in the fleet.

500 W, 0-150 V, 0-40 A, CC/CV/CR/CW, over a USB virtual COM port (also
RS232 and LAN, unused here). Another Korad design under the Multicomp
Pro name, and it speaks the 72-13200's dialect: everything about the
command set is in `korad_load.py`, and this file holds only what is this
model's own.

**Written from a bench probe, not a manual.** No command reference
exists for it. Its documents (`manuals/MP710772/`) cover the front
panel, the LAN settings and the USB driver, and nothing else. The one
community driver for the family sets the mode with `:MODE`, which this
unit ignores. So `tools/bench_mp710772.py` asked it first, on
2026-11-17 at firmware V1.14
(`checkups/20261117/bench_MP710772_20261117_124656.md`), and every
spelling this driver sends was confirmed there by a readback that moved
and came back.

What the probe found that differs from the 72-13200
---------------------------------------------------
  * `*IDN?` is `MP710772 V1.14 SN:0000023205` - no brand in front.
  * The USB bridge reports `0416:5011`, the 72-13200's ids. A port is
    therefore not enough to say which of the two is on it; `*IDN?` is.
  * Readings are zero-padded, `00.199A`, to three decimals with the
    40 A and 150 V ceilings. The parser takes them as they are.
  * A query takes about 10 ms, twice the 72-13200's.
  * The headroom floor is lower, and not yet found. At 2 A and 4 A the
    terminal voltage followed the setpoint all the way down to the
    0.1 V commanding floor, so the saturation resistance is **at most**
    0.1 V / 4.027 A = 25 mOhm. That is a bound, and this file declares
    the floor unmeasured rather than turning a bound into a number.
"""
from smuniversal_lab_suite.core.limits import (
    NEGATIVE,
    POSITIVE,
    SMULimits,
)

from .base_load import BaseLoad
from .korad_load import KoradLoad


class MulticompProMP710772(KoradLoad):
    MODEL_IDS = ["MP710772"]
    DISPLAY_NAME = "Multicomp Pro MP710772"

    #: Transcribed from the MP710772 column of the user manual's
    #: specification table (rev. 11/22).
    #:
    #: Two ranges per quantity, each with its own accuracy: current
    #: +-(0.05% of set + 0.045% of full scale) on 3 A and 40 A, so a
    #: 1.35 mA floor on 3 A and 18 mA on 40 A; voltage
    #: +-(0.05% + 0.025% FS) on 18 V and 150 V, so 4.5 mV against
    #: 37.5 mV. For a solar cell sitting below 0.7 V the voltage ceiling
    #: is the difference between resolving Voc and not, and
    #: `apply_ranges()` picks it from the sweep span for that reason.
    LIMITS = SMULimits(
        max_voltage=150.0,
        max_current=40.0,
        voltage_ranges=[18.0, 150.0],
        current_ranges=[3.0, 40.0],
        # The CW-mode maximum. The OPP trip is at 520 W, so a sweep that
        # crosses this does not clamp - it ends.
        max_power=500.0,
        # The quadrant, in this suite's convention. See BaseLoad.
        voltage_polarity=POSITIVE,
        current_polarity=NEGATIVE,
    )

    #: `:FUNC`, the spelling the probe confirmed: `:FUNC CV/CC` moved the
    #: mode there and back. **The long `:FUNCtion` the 72-13200 takes is
    #: ignored here**, in silence. The first checkup (2026-11-17) sent
    #: `:FUNCtion CV` and read CC back. Sent by hand in the SCPI console
    #: the same day, `:FUNCtion CV` left `:FUNC?` unmoved. Long headers
    #: work for `:CURRent` and `:INPut`, so the long form can't be
    #: assumed per header on this firmware.
    FUNCTION_HEADER = ":FUNC"

    #: Seconds the link is held after every write. **The probe's own
    #: timing, not a measured threshold.** Every write in the probe was
    #: followed by 150 ms before the next command, and every one landed.
    #: The first checkup sent them unpaced and two did not: the mode
    #: read back CC after `:FUNCtion CV`, and `:CURRent 0.2A` sent right
    #: after `:INPut ON` sank nothing - 0 A at 5.04 V with the input on.
    #: The 72-13200 takes the same traffic unpaced; this unit has not
    #: been shown to.
    #:
    #: The ignored long header explains the mode. It does not explain
    #: the 0 A, so the pause stays until something does. The paced
    #: re-run (2026-11-17 14:23) sank -0.1999 A for 0.2 A asked, and its
    #: burst check answered 10 of 10 unpaced. That check grades whether
    #: queries are answered, not whether setpoints land, so it doesn't
    #: settle this either way.
    #:
    #: It costs 0.15 s per sweep point, on top of the 0.5 s settle. A
    #: checkup with a shorter value that still passes is what lowers it.
    WRITE_DELAY_S = 0.15

    #: 4-wire is "Remote Comp" in the front panel's Config page (user
    #: manual 9.4). Nothing over the bus sets or reports it.
    FIXED_SENSE = "as set at the front panel (Config > Remote Comp)"

    #: Seconds between a new setpoint and a reading that describes it.
    #:
    #: **Measured 2026-11-17**, from a 10 ms poll after each step, as the
    #: time the reading came within 2% of the step and stayed there:
    #:
    #:     CC 0.2 -> 1 A          454 ms
    #:     CC 1 -> 0.2 A          341 ms
    #:     CV 3 -> 2 V at 2 A     354 ms
    #:     CV 3 -> 2 V at 4 A     323 ms
    #:
    #: Rounded up from the slowest. Those times include however long the
    #: reading takes to refresh, which was not measured - at 1 mA
    #: resolution it never changed in 3 s of polling, so there was
    #: nothing to time. The 72-13200 refreshes about every 0.2 s.
    #:
    #: Enforced as the shortest per-point delay, in both modes
    #: (`minimum_point_delay()`). A sweep stepped faster records the
    #: loop on its way to each level, in a file that looks like any
    #: other.
    SETTLING_S = 0.5

    #: Not measured - see the module docstring. The bench sitting bounds
    #: it at 25 mOhm or less, and below 4 A the 0.1 V commanding floor
    #: (`MIN_CV_SETPOINT_V`) is reached first, which is the floor that
    #: decides a sweep there. Above 4 A nothing is known yet, so nothing
    #: refuses a setpoint on headroom grounds.
    HEADROOM_STATE = BaseLoad.HEADROOM_UNMEASURED

    def minimum_operating_voltage(self, amps):
        """`None`: this model's headroom floor has not been measured.

        Not "there is no floor" - every load has one. The 2026-11-17
        sitting followed the setpoint down to 0.1 V at 4.027 A, which
        puts the saturation resistance at 25 mOhm or less, and a bound
        is not a measurement: returned as a number it would refuse
        setpoints the instrument can hold. A sitting at 10 A or more,
        where the floor rises above 0.1 V, closes this.
        """
        return None
