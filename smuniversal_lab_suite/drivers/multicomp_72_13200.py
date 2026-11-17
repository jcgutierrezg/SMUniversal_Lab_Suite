"""
Multicomp Pro 72-13200 DC electronic load - the first non-SMU driver.

150 W, 0-120 V, 0-30 A, four regulation modes (CV, CC, CR, CW), SCPI
over a USB virtual COM port. A Korad KEL102 under another name: the
command set, and everything peculiar about it, is in `korad_load.py`,
shared with the MP710772. This file holds what is this model's own - its
identity, its envelope, and the numbers measured on it.

Written from *Communication Commands with Computer V2.10* and the
72-13200 user manual; neither PDF is committed (see `manuals/README.md`),
and the command table is transcribed in
`docs/reference/manuals/72-13200-commands.md`.

Bought for one measurement this lab could not otherwise take: the
illuminated IV curve of a large silicon solar cell, whose short-circuit
current is around 10 A. The B2901A is the widest-range SMU here and
stops at 3 A, so the current was clamped from the first point.

What this instrument is not
---------------------------
It sinks. It cannot source, and that is not a missing feature - it is
what a load is. Three consequences run through everything below, and
each of them is a way to record a wrong number rather than an error:

  * **One quadrant.** Terminal voltage positive, current inward. A
    solar sweep from -0.2 V to 0.8 V asks this instrument for the first
    quarter of a span it physically cannot enter. `LIMITS` declares the
    polarity so the request is refused at the gate rather than absorbed.
  * **Above Voc it is equally helpless.** Past the open-circuit voltage
    the cell must be *driven*, so the usable window is 0 V to Voc and
    nothing either side. On a silicon cell that is about 0 to 0.65 V.
  * **It cannot reach V = 0.** The pass element needs volts across it to
    regulate, so short-circuit current - the one point every solar
    measurement wants - is below the floor. **Measured 2026-09-15 at
    two currents: it is a saturation resistance of 43.1 mOhm**, so the
    floor is 0.431 V at 10 A and 0.216 V at 5 A. For a silicon cell
    with Voc around 0.65 V that leaves a usable window of roughly
    0.43 V to Voc - which contains the knee and the maximum power
    point, and does not contain Isc.

Numbers that are not from this model's own document
----------------------------------------------------
The command PDF is written for a product family: its examples answer
`>150V` and `>300W` where this unit is 120 V and 150 W. **No envelope
figure here comes from it** - `LIMITS` is transcribed from the
72-13200's own specification table.
"""
from smuniversal_lab_suite.core.limits import (
    NEGATIVE,
    POSITIVE,
    SMULimits,
)

from .base_load import BaseLoad
from .korad_load import KoradLoad


class MulticompPro7213200(KoradLoad):
    MODEL_IDS = ["72-13200"]
    DISPLAY_NAME = "Multicomp Pro 72-13200"

    #: Transcribed from the 72-13200 specification table, not from the
    #: family command PDF.
    #:
    #: The two ranges per quantity are the ceilings the specification
    #: documents and states an accuracy against. They matter more here
    #: than a range usually does: the accuracy spec carries a full-scale
    #: term, so the ceiling sets the noise floor directly. Current:
    #: 1.35 mA on the 3 A ceiling, 13.5 mA on the 30 A one. Voltage:
    #: 4.5 mV on 18 V against 30 mV on 120 V, which for a cell sitting
    #: below 0.7 V is the difference between resolving Voc and not.
    #:
    #: A cell whose short-circuit current is a few milliamps cannot be
    #: measured on this instrument at all, on either ceiling. Use an SMU.
    #:
    #: The instrument also accepts ceilings between these - 5 A and 15 A
    #: both land exactly - but `apply_ranges()` snaps to the two
    #: documented ones on purpose. See there.
    LIMITS = SMULimits(
        max_voltage=120.0,
        max_current=30.0,
        voltage_ranges=[18.0, 120.0],
        current_ranges=[3.0, 30.0],
        # A continuous 150 W hyperbola, not a set of corners. The OPP
        # trip sits just above it at 165 W, so a sweep that crosses this
        # does not clamp - it ends.
        max_power=150.0,
        # The quadrant, in this suite's convention. See BaseLoad.
        voltage_polarity=POSITIVE,
        current_polarity=NEGATIVE,
    )

    #: 4-wire is the user manual's "remote compensation function",
    #: entered with SHIFT+CW; the display shows `Comm` while it is on.
    FIXED_SENSE = "as set at the front panel (SHIFT+CW remote compensation)"

    #: The load's saturation resistance, in ohms - and therefore its
    #: headroom floor, which is `R x I`.
    #:
    #: **MEASURED at two currents a factor of two apart, 2026-09-15**,
    #: and that is what makes it a resistance rather than a number:
    #:
    #:     9.998 A   floor 0.4310 V   43.11 mOhm
    #:     5.023 A   floor 0.2164 V   43.08 mOhm
    #:
    #: The two agree to 0.03 mOhm. Predicting the 5 A floor from the
    #: 10 A one gave 0.2165 V against 0.2164 V measured, so there is no
    #: measurable fixed term: the pass element is simply a resistance
    #: once it saturates.
    #:
    #: Both floors were sharp - 0.0 mV of spread across every setpoint
    #: below them, four points at 10 A and five at 5 A.
    #:
    #: **Held as a resistance for the same reason the B2901A's
    #: sub-count floor is held as counts.** An absolute figure would be
    #: right at one current and wrong at every other, and this
    #: instrument is used across a 6:1 range of them. That driver's
    #: lesson was learned from two measurements on two ranges; this is
    #: the same experiment on the other side of the fleet.
    SATURATION_RESISTANCE_OHM = 0.04310

    #: How long the CV loop takes to settle a step down at 10 A, in
    #: seconds. Measured in the same session: a 1.0 -> 0.5 V step was
    #: still at 0.624 V after 220 ms and had reached its final value by
    #: 430 ms.
    #:
    #: This is the floor under an IV sweep's per-point delay, and it is
    #: long: a 100-point CV sweep cannot run faster than about a minute
    #: without recording the loop rather than the cell. It is a property
    #: of the instrument and the operating point, not of the bus - the
    #: queries themselves take 4-6 ms.
    #:
    #: **It is enforced, in both modes** (`minimum_point_delay()`), and
    #: there is a second reason beside the loop. Polled every 100 ms on
    #: 2026-10-07, `:MEASure:VOLTage?` gave the same value twice before
    #: moving: the reading itself is refreshed only about every 0.2 s.
    #: A CC sweep at 0.1 s a point recorded -1.7 mA at 0.564 V for a
    #: point that asked for 50 mA - a reading from between two levels.
    SETTLING_S = 0.45

    HEADROOM_STATE = BaseLoad.HEADROOM_MEASURED

    def minimum_operating_voltage(self, amps):
        """Lowest terminal voltage this model holds at `amps`, in volts.

        `R x I`, with R measured at two currents - see
        `SATURATION_RESISTANCE_OHM`. Below this the pass element has
        nothing to regulate with: the setpoint stops being followed, no
        error is raised, and the readings keep their usual shape.

        **This is not the only floor**, and the other one wins at low
        current. `MIN_CV_SETPOINT_V` is 0.1 V and is absolute - the
        instrument will not accept a smaller CV setpoint at any current
        - so the effective floor is the larger of the two, and they
        cross at 2.32 A. Below that the commanding floor decides;
        above it, the headroom does.

        They are kept separate rather than collapsed into one number
        because they are different mechanisms with different remedies:
        one is a limit on what can be *asked for*, the other on what can
        be *held*, and an operator looking at a truncated curve needs to
        know which stopped them.
        """
        return self.SATURATION_RESISTANCE_OHM * abs(float(amps))
