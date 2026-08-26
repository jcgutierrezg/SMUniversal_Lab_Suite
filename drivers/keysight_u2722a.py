"""
Keysight U2722A USB Modular Source Measure Unit - fourth SCPI dialect.

Ported from `IV_Meas_2722A.py` (and its two earlier revisions, which are
the same program with GUI additions - nothing instrument-facing differs
between them).

Why this needs its own file
---------------------------
It is SCPI, but it is not the 2400 family and it is not the GSM. Three
things make it genuinely its own dialect, and each one is a silent
failure if you send a neighbour's spelling instead:

  1. **Every command carries a channel list.** `SOUR:VOLT 5, (@1)`. This
     is a three-channel instrument and the channel is not optional.
  2. **Ranges are named tokens, not numbers.** `R1uA`, `R10mA`, `R2V`,
     `R20V` - there is no `SOUR:CURR:RANG 1e-3` and no AUTO.
  3. **There is no source-function command.** No `SOUR:FUNC`. You select
     the mode implicitly by which quantity you drive, following the
     ordered sequence in the User's Guide.

Command order is load-bearing
-----------------------------
This is the one that will bite. The Programmer's Reference states that
the maximum value of `[SOURce:]CURRent:LIMit` **depends on the current
range currently set**, and the factory defaults are:

    CURRent:RANGe   R1uA
    CURRent:LIMit   0.0000001     (100 nA)
    VOLTage:RANGe   R2V
    VOLTage:LIMit   0.2

So after `*RST`, asking for a 10 mA compliance while the range is still
R1uA gets the limit clamped to something near 1 uA. Nothing raises. You
then source 1 V into your sample with a ~100 nA compliance and record a
flat line that reads exactly like an open circuit.

`IVSweepExperiment._one_sweep` calls `set_current_limit()` *before*
`set_current_range()`, which is the wrong order for this instrument and
the right order for the other four. Rather than change the experiment
for one model, this driver remembers the requested limit and re-sends it
after any range change. Same result, no experiment change, one-way
dependency intact.

Source range for the swept quantity
-----------------------------------
The experiment sets the range of the quantity it *measures* (the
compliance side) and leaves the sourced quantity's range to the
instrument, because every other SMU in the suite auto-ranges its source.
This one does not: after `*RST` it sits on R2V, so a sweep to 5 V would
clip at 2 V and still return a tidy, entirely wrong curve.

`start_linear_sweep()` therefore picks a source range covering both ends
of the sweep before it starts - the same job the GSM does with
`SOUR:SWE:RANG BEST`. The level setters do the same check for the
bias-hold path, which does not go through a sweep.

Sensing is a wiring decision
----------------------------
There is no remote-sense command anywhere in the Programmer's Reference
index. The User's Guide describes local versus remote sensing purely as
how you strap the SENSE± terminals. This rig is permanently wired
4-wire, so the driver declares that and refuses a request for 2-wire
rather than accepting one it cannot honour - a silent no-op would write
"2-wire" into a CSV describing a 4-wire measurement.

No hardware sweep
-----------------
The immediate SOURce subsystem has no staircase. The memory-list
sequencer, which genuinely is a hardware sweep engine, is a **U2723A**
feature - same command set otherwise, so if the lab ever buys a 23A the
upgrade path is `SOUR:MEM:*` in this file and nothing above it. Until
then this driver inherits the point-by-point software sweep from
BaseSMU, which is what the original script did by hand anyway.

Measured on the bench (2026-08-05)
----------------------------------
14-bit converters, confirmed from the returned values themselves: every
reading is an exact multiple of range/16384, so 6.1035 nA on the 100 uA
current range and 122.07 uV on the 2 V voltage range. Worth knowing
because it sets the floor on what a low-level measurement can resolve
regardless of NPLC - averaging longer does not add bits.

Output capacitance is around 1 uF. Sourcing 1 uA into an open circuit
reached 41 mV in 50 ms, which is a slew of about 1 V/s. So a small
current into a high-impedance sample does not settle quickly: allow
over a second per point at 1 uA if the compliance is volts away, and
more on the smaller ranges.

Timing you cannot control
-------------------------
Two floors the panel's delay field sits on top of and cannot remove:

  * **Auto delay.** There is no immediate-mode `SOUR:DEL`; the only
    delay commands are memory-list ones. The instrument applies its own
    settle of 0.5 ms to 20 ms depending on range and mode (User's Guide
    Table 2-2), always, and it cannot be switched off from here.
  * **Two queries per point.** There is no combined voltage+current
    read, so `measure()` costs `MEAS:VOLT?` plus `MEAS:CURR?`, each
    taking NPLC/line-frequency seconds plus bus latency.

    Measured on the bench 2026-08-05 rather than assumed: 75 ms per
    reading at NPLC 1 and 1056 ms at NPLC 25, which is a slope of
    **2.04 apertures per reading** with 34 ms of fixed overhead. Both
    integrations are paid in full. So a 200-point sweep costs about
    3.5 minutes at NPLC 25, and NPLC is worth twice what it looks like
    on this instrument.

`sweep_note()` reports both at connect, so nobody has to discover it by
watching a sweep crawl.
"""
from core.limits import SMULimits
from core.ranges import AUTO, NOT_SOURCED, RangeError
from .base_smu import BaseSMU
from core.transports.base import TransportDesynchronised

# The instrument has three independent channels; the rig uses channel 1
# and the original script hardcoded it. Kept as a constructor argument
# with this default so that using another channel is a one-line change
# at the call site rather than a hunt through string literals.
DEFAULT_CHANNEL = 1

# Mains frequency, for NPLC. Unlike the GSM this model has no
# auto-detect - SYSTem:LFRequency takes F50HZ or F60HZ and nothing else -
# so it has to be declared. Named rather than inlined because this is
# the one line that is wrong if the rig ever leaves the UK.
LINE_FREQUENCY_HZ = 50.0
LINE_FREQUENCY = "F50HZ" if LINE_FREQUENCY_HZ == 50.0 else "F60HZ"


class _SourcedAxis:
    """Sentinel: this axis's limit belongs to the quantity being sourced.

    Distinct from `None`, which means "nobody has said anything about
    this axis, leave it alone", and from a float, which is a compliance
    the operator asked for.

    It resolves to **the narrowest limit the active range can hold that
    still admits every level commanded so far** - that is, the range's
    own floor until a level exceeds it, and then just enough to clear
    the largest one. Full scale would also never cap a level, and was
    the first draft, but it is the *weakest* value in the window: on
    R120mA it means 120 mA where the floor means 12 mA. Since the point
    of this axis is that it must not throttle the operator's level,
    and nothing more, the tightest value that achieves it is the right
    one.
    """

    __slots__ = ()

    def __repr__(self):
        return "SOURCED_AXIS"


SOURCED_AXIS = _SourcedAxis()

#: How much room above the largest level commanded the sourced axis's
#: own limit is given.
#:
#: Doubling, not a percent. A tight margin is tempting - the whole point
#: of resolving the sentinel to the narrowest workable value is to keep
#: a real fallback - but headroom granted just above each level is
#: headroom rewritten at every level, and this sits in the inner loop of
#: a software sweep at two round trips a time. Granting it in doubling
#: steps is the same trick a growing array uses: the write happens on a
#: logarithmic number of points instead of all of them, and the fallback
#: is still twice the level rather than the range's full scale.
SOURCED_AXIS_HEADROOM = 2.0


class KeysightU2722A(BaseSMU):
    # The U2723A is deliberately NOT listed: same dialect, different
    # current ranges, and it would resolve to these limits.
    # Confirmed on the bench 2026-08-05:
    #     AGILENT TECHNOLOGIES,U2722A,MY62030002,R1.10-1.12-1.06
    # Note the vendor field says AGILENT, not Keysight - this predates
    # the rename. Matching on the model field alone was the right call.
    MODEL_IDS = ["U2722A"]
    DISPLAY_NAME = "Keysight U2722A"

    # No staircase in the immediate subsystem - see the module docstring.
    SWEEP_KIND = "software"

    # Three channels of 20 V and 120 mA each. Flat maxima: unlike the
    # 2450 and the GSM there is no corner where one maximum costs you
    # the other, so no power_envelope is declared.
    LIMITS = SMULimits(
        max_voltage=20.0,
        max_current=0.12,
        voltage_ranges=[2.0, 20.0],
        current_ranges=[1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 0.12],
    )

    # Range tokens, exactly as the Programmer's Reference lists them,
    # smallest first. The instrument accepts nothing else - there is no
    # numeric form and no AUTO.
    CURRENT_RANGE_TOKENS = [
        (1e-6, "R1uA"),
        (1e-5, "R10uA"),
        (1e-4, "R100uA"),
        (1e-3, "R1mA"),
        (1e-2, "R10mA"),
        (0.12, "R120mA"),
    ]
    VOLTAGE_RANGE_TOKENS = [
        (2.0, "R2V"),
        (20.0, "R20V"),
    ]

    #: A limit is only settable between a tenth of the active range and
    #: its full scale. Measured on the bench 2026-08-24, not read out of
    #: the Programmer's Reference, which says only that the maximum
    #: "depends on the range".
    #:
    #: Directly measured at four points: R100uA refused 9.9 uA and
    #: accepted 10.0 uA; R20V refused 0.5 V and accepted 2.0 V; and
    #: `*RST` leaves 100 nA on R1uA and 200 mV on R2V, both of which the
    #: instrument evidently considers legal. The four intermediate
    #: current ranges are interpolation across a uniform decade family,
    #: not four more measurements - see the note.
    LIMIT_FLOOR_FRACTION = 0.1

    #: Fractional agreement required between a limit written and the
    #: limit read back. Same default as `verify_compliance`.
    LIMIT_READBACK_TOLERANCE = 0.01

    #: The smallest source level that means anything, in counts. Below
    #: this the driver refuses rather than commanding a level the
    #: converter cannot express.
    #:
    #: One count is the floor where a request means *something* at all,
    #: and there the quantisation error is 100%. Ten caps it at 10%,
    #: which is the number this project chose - it is a decision, not a
    #: measurement, and it is one constant to change.
    #:
    #: It bounds quantisation error and **nothing more**. It is not a
    #: guarantee that the sign comes out right: probe G saw current
    #: readings excursing to twelve counts on R120mA, and separating
    #: source residue from measurement noise there needs a known load,
    #: which has not been done. See the note.
    MIN_LEVEL_COUNTS = 10

    #: Counts across a range. 14-bit, so every reading is an exact
    #: multiple of range/16384 whatever the NPLC - averaging longer does
    #: not add bits. Used to report the resolution the chosen compliance
    #: buys, because on this instrument those are the same decision.
    COUNTS_PER_RANGE = 16384

    # Integer 0 to 255 power line cycles. The floor is declared as 1
    # rather than 0 on purpose: this is an integer setting, so a
    # requested 0.01 or 0.1 rounds to 0 - no integration at all, from a
    # control the operator just used to ask for *quieter* readings.
    # Declaring 1 makes refresh_nplc() drop those two presets from the
    # menu instead of offering a value that would backfire.
    NPLC_RANGE = (1, 255)

    # No overvoltage protection command, and OUTPut[:STATe] is the only
    # output command - no high-Z output-off mode.
    OVP_CHOICES = []
    HIGH_Z_OFF = False

    # Sensing is set by how the SENSE terminals are strapped, not by any
    # command. This rig is permanently wired 4-wire.
    REMOTE_SENSE_CONTROL = False
    FIXED_SENSE = "4-wire (hardwired)"

    def __init__(self, transport, channel=DEFAULT_CHANNEL):
        super().__init__(transport)
        self.channel = int(channel)

        # Compliance is re-sent after any range change, so it has to be
        # remembered. None means "never set" - in which case there is
        # nothing to restore and the instrument keeps its default.
        self._current_limit = None
        self._voltage_limit = None
        self._forget_sourced_axis_state()

        # Active range tokens, tracked so a level setter can tell
        # whether it needs to range up. None means unknown; *RST leaves
        # R1uA and R2V but this driver does not assume it was the one
        # that reset the instrument.
        self._current_range_token = None
        self._voltage_range_token = None

        self._source_mode = "voltage"
        # Integration window per reading, in seconds. Tracked locally
        # rather than queried per point: SENS:CURR:APER? is derived
        # arithmetically from NPLC and the line frequency, so asking the
        # instrument for it on every reading would add a third round
        # trip to a measurement that already costs two.
        self._aperture_s = None

    # ---- channel list -------------------------------------------------
    #
    # Two spellings, and the difference is not cosmetic. The
    # Programmer's Reference is explicit that a query needs a space
    # between the '?' and the channel list, or the instrument answers
    # error -103, "Invalid separator".

    def _ch(self):
        """Channel-list suffix for a command: `..., (@1)`."""
        return f", (@{self.channel})"

    def _chq(self):
        """Channel-list suffix for a query: `...? (@1)`, space required."""
        return f" (@{self.channel})"

    def _write(self, text):
        self.transport.write(f"{text}{self._ch()}")

    def _query(self, text, timeout_s=10.0):
        return self.transport.query(f"{text}{self._chq()}", timeout_s=timeout_s)

    # ---- identity and housekeeping ------------------------------------
    def reset(self):
        """Reset, clear status, and pin the line frequency.

        Ranges and limits are deliberately NOT set here. They are a
        per-run decision made by the experiment, and setting them at
        connect would only mean setting them twice. What matters is that
        the cached values are forgotten, so the next range change cannot
        restore a limit belonging to a previous run.
        """
        self.transport.write("*CLS")
        self.transport.write("*RST")
        # No SYSTem:LFRequency auto-detect on this model, unlike the GSM.
        # NPLC only cancels mains hum if the instrument knows the period.
        self._write(f"SYST:LFREQ {LINE_FREQUENCY}")

        self._current_limit = None
        self._voltage_limit = None
        self._forget_sourced_axis_state()
        # *RST leaves R1uA / R2V per the factory-defaults table.
        self._current_range_token = "R1uA"
        self._voltage_range_token = "R2V"
        # *RST also leaves NPLC at 0.
        self._aperture_s = 0.0
        self._drain_errors()

    def read_error(self):
        """Pop one entry off the error queue as (code, message).

        Code 0 means the queue was empty. A transport failure is also
        reported as 0: failing to *read* the queue is not evidence that
        a command failed, and treating it as such would abort runs over
        a dropped reply.

        Note there is no `SYST:ERR:ALL?` on this model - the GSM has one
        and this one does not - so the queue is drained by polling, with
        a hard bound so an instrument erroring on every query cannot
        spin here. It holds 20 entries.
        """
        try:
            reply = self.transport.query("SYST:ERR?", timeout_s=3.0)
        except TransportDesynchronised:
            raise
        except Exception:
            return (0, "")
        if not reply:
            return (0, "")
        head, _, tail = str(reply).partition(",")
        try:
            return (int(float(head.strip())), tail.strip().strip('"'))
        except ValueError:
            return (0, str(reply).strip())

    def _drain_errors(self, limit=21):
        """Empty the error queue, returning every non-zero entry."""
        found = []
        for _ in range(limit):
            code, message = self.read_error()
            if code == 0:
                break
            found.append((code, message))
        return found

    # ---- source configuration -----------------------------------------
    def set_source_function(self, mode):
        """Record which quantity is being sourced, and open its limit.

        **No mode command is sent**, because there is no `SOUR:FUNC` on
        this instrument - the mode is selected implicitly by which
        quantity you drive, which is why the User's Guide gives two
        separate ordered sequences instead of one with a mode switch.
        One thing *is* sent: see below.

        The error queue is drained here because this is the first call
        of every configure sequence, so anything found later in the run
        is attributable to that run rather than to whatever came before.
        """
        if mode not in ("voltage", "current"):
            raise ValueError(f"Unknown source mode: {mode!r}")
        self._source_mode = mode

        # The limit on the quantity being *sourced* is opened to the
        # active range's full scale, and follows the range from here.
        #
        # It has to be one or the other and it cannot be left where the
        # last run put it. `SOUR:CURR:LIM` is the current compliance
        # while sourcing voltage; while sourcing current it applies to
        # the quantity the operator is commanding, and a value carried
        # over from a voltage-sourcing run - 100 uA, say - is at best
        # meaningless and at worst a cap on the sweep itself, delivering
        # a fraction of the requested current and drawing a smooth,
        # entirely wrong curve.
        #
        # Full scale is the safe write under *either* reading of what
        # this setting does, which is why this needed no further bench
        # work: if it caps the level, full scale caps nothing the range
        # can produce; if it is a compliance, full scale is the widest
        # that range allows. Protection during the run comes from the
        # limit on the quantity NOT being sourced, which is the one the
        # experiment sets.
        # DEVIATION 53
        if mode == "current":
            self._current_limit = SOURCED_AXIS
            self._restore_current_limit()
        else:
            self._voltage_limit = SOURCED_AXIS
            self._restore_voltage_limit()

        self._drain_errors()

    def _refuse_unresolvable_level(self, level, quantity, unit, token,
                                   table):
        """Refuse a source level the converter cannot express.

        Below one count there is no signal, only offset. The bench
        established this on 2026-08-25 in a way that leaves nothing to
        interpret: on R120mA, where one count is 7.32 uA, commanding
        `-1 uA` and `+1 uA` produced **the same output** - the sign was
        simply ignored, because 1 uA is a seventh of a count. What comes
        out in that regime is residue, and its polarity is not under
        anyone's control: it sat positive through every probe that day
        and negative during the commissioning run, where it walked the
        output to the -2 V range rail against a 1 V compliance that was
        working correctly the whole time.

        So an operator asking for a 1 uA bias can get an output at the
        opposite polarity from the one their sample is wired for, with
        no error anywhere. That is why this refuses instead of warning.

        A zero level is always allowed: "off" is exactly representable
        and is what `stop` and every settle-to-zero path writes.

        The range came from the plan, and the level may well be
        expressible on a narrower one - the message says which. Choosing
        it here instead would be the general `RangePlan` fix applied to
        one driver, which is a different wave.
        """
        magnitude = abs(float(level))
        if magnitude == 0.0:
            return
        ceiling = self._ceiling_of(token, table)
        if ceiling is None:
            return
        count = ceiling / self.COUNTS_PER_RANGE
        floor = count * self.MIN_LEVEL_COUNTS
        if magnitude >= floor:
            return

        narrower = next(
            (name for _, name in table
             if magnitude >= (self._ceiling_of(name, table)
                              / self.COUNTS_PER_RANGE
                              * self.MIN_LEVEL_COUNTS)),
            None)
        remedy = (f"{narrower} would carry it"
                  if narrower else
                  "no range on this instrument can carry it")
        raise RangeError(
            f"{self.DISPLAY_NAME}: a {quantity} level of "
            f"{magnitude:.6g} {unit} is below what {token} can express. "
            f"One count on that range is {count:.6g} {unit} and this "
            f"driver requires at least {self.MIN_LEVEL_COUNTS} "
            f"({floor:.6g} {unit}), because below a count the output is "
            f"offset residue whose sign is not commanded - the "
            f"instrument ignores the one you asked for. {remedy}. "
            f"Refusing before the output is energised.")

    def set_current_level(self, amps):
        # DEVIATION 54
        self._ensure_current_range(amps)
        self._refuse_unresolvable_level(
            amps, "current", "A", self._current_range_token,
            self.CURRENT_RANGE_TOKENS)
        self._raise_current_headroom(amps)
        self._write(f"SOUR:CURR {amps:.6e}")

    def set_voltage_level(self, volts):
        # No rounding before sending, for the same reason as the 2401
        # and GSM drivers: the original's `round(V, 4)` quantises to
        # 100 uV, which is invisible at 1 V and destroys a sweep on the
        # 2 V range.
        # DEVIATION 54
        self._ensure_voltage_range(volts)
        self._refuse_unresolvable_level(
            volts, "voltage", "V", self._voltage_range_token,
            self.VOLTAGE_RANGE_TOKENS)
        self._raise_voltage_headroom(volts)
        self._write(f"SOUR:VOLT {volts:.6e}")

    def set_current_limit(self, amps):
        """Current compliance while sourcing voltage.

        On this instrument the compliance very nearly determines the
        range, so the range is chosen *from the limit* rather than
        widened to fit it: each range accepts a limit only between a
        tenth of its full scale and full scale, and the ranges are
        decades, so 5 uA is settable on R10uA and nowhere else.

        The order is therefore range, then limit, then read the limit
        back. All three matter:

        * **Range first**, because a limit sent while a range that
          cannot hold it is active is *refused* - `-222, "Data out of
          range"` - and the previous value stays in force. The refusal
          is loud in the error queue but the instrument keeps running,
          so without the readback the run continues against a
          compliance nobody chose.
        * **The range chosen from the limit**, because the widest range
          that merely *fits* the value is often one whose floor is
          above it. R120mA fits 100 uA in the sense that 100 uA is less
          than 120 mA, and refuses it in the sense that matters.
        * **Read it back**, because a range change can silently move a
          limit in either direction - the bench saw 100 uA become 12 mA
          with a clean error queue, a 120x widening of the protection
          around somebody's sample.

        Raises `RangeError` when the requested compliance is not
        settable on any range, rather than accepting a value the
        instrument would quietly replace.
        """
        # DEVIATION 52
        amps = float(amps)
        token = self._range_for_limit(amps, self.CURRENT_RANGE_TOKENS,
                                      "current", "A")
        self._current_limit = amps
        self._apply_current_range(token, force=True)
        self._announce_resolution("current", amps, "A", token,
                                  self.CURRENT_RANGE_TOKENS)

    def set_voltage_limit(self, volts):
        """Voltage compliance while sourcing current.

        The User's Guide calls this the "input protection voltage". It
        is compliance, not overvoltage protection - this model has no
        OVP control.

        Same three-step rule as `set_current_limit()`, and the same
        window: R2V accepts 0.2 V to 2 V, R20V accepts 2 V to 20 V.
        """
        volts = float(volts)
        token = self._range_for_limit(volts, self.VOLTAGE_RANGE_TOKENS,
                                      "voltage", "V")
        self._voltage_limit = volts
        self._apply_voltage_range(token, force=True)
        self._announce_resolution("voltage", volts, "V", token,
                                  self.VOLTAGE_RANGE_TOKENS)

    # ---- ranging ------------------------------------------------------
    @classmethod
    def _token_for(cls, value, table):
        """Smallest range token that still fits `value`, or the largest
        available if nothing does."""
        magnitude = abs(float(value))
        for ceiling, token in table:
            if magnitude <= ceiling:
                return token
        return table[-1][1]

    # ---- ranging: the limit window ------------------------------------
    @classmethod
    def _ceiling_of(cls, token, table):
        """Full scale of a named range, in amps or volts."""
        for ceiling, name in table:
            if name == token:
                return ceiling
        return None

    @classmethod
    def _window_of(cls, token, table):
        """`(floor, ceiling)` of settable limits on a named range."""
        ceiling = cls._ceiling_of(token, table)
        if ceiling is None:
            return None
        return (ceiling * cls.LIMIT_FLOOR_FRACTION, ceiling)

    @classmethod
    def _limit_fits(cls, value, token, table):
        """Would this range accept this limit?

        A tolerance is applied at both ends because the boundary values
        are the useful ones - a 10 uA limit on R100uA is exactly the
        floor - and floating-point arithmetic on `1e-4 * 0.1` does not
        reliably land on `1e-5`.
        """
        window = cls._window_of(token, table)
        if window is None:
            return False
        floor, ceiling = window
        slack = 1.0 + cls.LIMIT_READBACK_TOLERANCE
        return floor / slack <= abs(float(value)) <= ceiling * slack

    @classmethod
    def _range_for_limit(cls, value, table, quantity, unit):
        """The narrowest range whose window admits `value`.

        Raises `RangeError` when no range does. Three ways that
        happens, and the middle one is the surprising one:

        * below the smallest range's floor - 100 nA, or 200 mV;
        * **between 10 mA and 12 mA**, because the current ranges are
          decades until the last one, so R10mA's ceiling and R120mA's
          floor leave a genuine gap with nothing in it;
        * above the instrument.

        Refusing here is the whole point of the wave. The alternative -
        letting the instrument take the value and clamp it - is a run
        that proceeds with protection nobody chose, which on a delicate
        sample is the difference between a failed run and a dead
        sample.
        """
        magnitude = abs(float(value))
        for _, token in table:
            if cls._limit_fits(magnitude, token, table):
                return token

        options = ", ".join(
            f"{name} takes {lo:.6g} to {hi:.6g} {unit}"
            for name, (lo, hi) in
            ((name, cls._window_of(name, table)) for _, name in table))
        raise RangeError(
            f"{cls.DISPLAY_NAME}: a {quantity} compliance of "
            f"{magnitude:.6g} {unit} is not settable on any range of "
            f"this instrument. Each range accepts a limit only between "
            f"a tenth of its full scale and full scale: {options}. "
            f"Choose a compliance inside one of those, or use a "
            f"different instrument for this measurement.")

    # ---- ranging: per-axis (wave 6d) ----
    #: One range knob per quantity, serving both source and measure.
    #: `apply_ranges()` reconciles a plan by taking the wider of the two
    #: and saying so.
    INDEPENDENT_SOURCE_RANGE = False
    HAS_MEASURE_RANGE = False

    #: Verified on the bench 2026-08-24, in exactly the case that was
    #: left open: a limit the instrument had *refused*. Three writes of
    #: an out-of-window value were rejected with `-222` and the readback
    #: reported the surviving value each time, not the rejected one;
    #: an accepted write read back as written. The readback tells the
    #: truth, including the truth that a write did not take.
    COMPLIANCE_READBACK_TRUSTED = True

    def read_current_limit(self):
        return self._read_number("SOUR:CURR:LIM?", timeout_s=3.0)

    def read_voltage_limit(self):
        return self._read_number("SOUR:VOLT:LIM?", timeout_s=3.0)

    # No `_render_not_sourced` override here, and that is deliberate.
    #
    # The obvious fix for this instrument's 2026-08-18 failures was to
    # override it - the marker arrives, the driver leaves the range
    # alone, done. Written that way it passed its tests and a mutation
    # round then showed it was **unreachable**: removing the override
    # changed nothing.
    #
    # `INDEPENDENT_SOURCE_RANGE` is False here, so `apply_ranges` sends
    # both source axes through `RangePlan.widest()` first, and that is
    # where an unsourced axis loses its claim on the shared knob. The
    # marker is resolved before any hook sees it. What actually fixed
    # this instrument was the reconciliation, not the driver.
    #
    # Left as a comment rather than as unreachable code, because a hook
    # that looks load-bearing and never runs is worse than no hook: the
    # next person to touch the ranging path would trust it.

    def _apply_source_current_range(self, amps):
        """No autorange on this instrument, so AUTO takes the widest.

        The first version refused AUTO outright. That was wrong for the
        same reason decision W6d-2 settled on "take the wider value":
        the widest range never clamps a level and never overranges a
        reading, so it is the one realisation of "let the instrument
        choose" that cannot produce a wrong number. It costs resolution,
        which is a worse measurement rather than a false one.

        Refusing also broke callers that are model-agnostic by design -
        the checkup asks every instrument for an all-AUTO plan, and an
        instrument that cannot autorange should answer it as best it
        can rather than abort the run.

        Silently doing nothing would still be wrong: that leaves the
        range wherever it was, most likely the 1 uA it resets to, and
        clamps every level above it. Hence the console note.
        """
        if amps is None:
            return      # not sourced - see _render_not_sourced
        if amps is AUTO:
            # No special case for "a compliance is already set", though
            # the first draft of this wave had one, on the reasoning
            # that a compliance is a bound on the measured quantity and
            # so the narrowest range holding it is the right answer for
            # AUTO. The reasoning is sound and the code was
            # unreachable: `_apply_current_range` already refuses to
            # move to a range that would strand the limit, so the
            # widest-range request is declined and the range stays
            # exactly where the compliance put it. A mutation round
            # proved it - disabling the special case changed no
            # observable behaviour. Same treatment as the
            # `_render_not_sourced` override that is also absent here.
            ceiling, token = max(self.CURRENT_RANGE_TOKENS)
            print(f"{self.DISPLAY_NAME}: no autorange on this model; "
                  f"using the widest current range ({token}) for AUTO. "
                  f"Nothing will clamp, but resolution is the widest "
                  f"range's.")
            self._apply_current_range(token)
            return
        self._apply_current_range(self._token_for(amps,
                                                  self.CURRENT_RANGE_TOKENS))

    def _apply_source_voltage_range(self, volts):
        """As above: AUTO takes the widest range this model has."""
        if volts is None:
            return      # not sourced - see _render_not_sourced
        if volts is AUTO:
            # See _apply_source_current_range: the stranding guard in
            # _apply_voltage_range already keeps a compliance's range.
            ceiling, token = max(self.VOLTAGE_RANGE_TOKENS)
            print(f"{self.DISPLAY_NAME}: no autorange on this model; "
                  f"using the widest voltage range ({token}) for AUTO.")
            self._apply_voltage_range(token)
            return
        self._apply_voltage_range(self._token_for(volts,
                                                  self.VOLTAGE_RANGE_TOKENS))


    def _apply_current_range(self, token, force=False):
        """Send a current range token, then re-establish the limit.

        A range change on this instrument does not leave the compliance
        alone. The bench watched 100 uA become 12 mA on a move from
        R100uA to R120mA, with `SYST:ERR?` reporting no error - the
        protection around the sample widened by a factor of 120 and
        nothing said so. So every range change is followed by writing
        the limit again and reading it back.

        **A range change that would strand the compliance is refused.**
        Where the requested range's window excludes the cached limit,
        the range does not move and the console says why. Resolution
        loses to protection: a narrower range than the plan asked for
        is a worse measurement, and a compliance the operator did not
        choose is a wrong one. `force=True` is how the limit setters
        say "this range *is* the one the limit needs".
        """
        if isinstance(self._current_limit, float) and not force and \
                not self._limit_fits(self._current_limit, token,
                                     self.CURRENT_RANGE_TOKENS):
            floor, ceiling = self._window_of(token,
                                             self.CURRENT_RANGE_TOKENS)
            print(f"{self.DISPLAY_NAME}: keeping the current range at "
                  f"{self._current_range_token} rather than moving to "
                  f"{token}, which accepts a compliance only between "
                  f"{floor:.6g} and {ceiling:.6g} A and would strand "
                  f"the {self._current_limit:.6g} A one that was asked "
                  f"for. Readings lose resolution; nothing is clamped.")
            return
        if token != self._current_range_token:
            self._write(f"SOUR:CURR:RANG {token}")
            self._current_range_token = token
        self._restore_current_limit()

    def _apply_voltage_range(self, token, force=False):
        """Send a voltage range token, then re-establish the limit."""
        if isinstance(self._voltage_limit, float) and not force and \
                not self._limit_fits(self._voltage_limit, token,
                                     self.VOLTAGE_RANGE_TOKENS):
            floor, ceiling = self._window_of(token,
                                             self.VOLTAGE_RANGE_TOKENS)
            print(f"{self.DISPLAY_NAME}: keeping the voltage range at "
                  f"{self._voltage_range_token} rather than moving to "
                  f"{token}, which accepts a compliance only between "
                  f"{floor:.6g} and {ceiling:.6g} V and would strand "
                  f"the {self._voltage_limit:.6g} V one that was asked "
                  f"for. Readings lose resolution; nothing is clamped.")
            return
        if token != self._voltage_range_token:
            self._write(f"SOUR:VOLT:RANG {token}")
            self._voltage_range_token = token
        self._restore_voltage_limit()

    def _announce_resolution(self, quantity, limit, unit, token, table):
        """Say what resolution the chosen compliance just bought.

        On every other instrument here the compliance and the
        measurement range are separate decisions. On this one the
        compliance *is* the range - deviation 52 - so a field the
        operator thinks of as protection is also a resolution control,
        and a decade of it can turn on the difference between typing
        90 uA and 9 uA. Nothing on the panel says so, so the log does.
        """
        ceiling = self._ceiling_of(token, table)
        if ceiling is None:
            return
        print(f"{self.DISPLAY_NAME}: a {limit:.6g} {unit} {quantity} "
              f"compliance selects {token}, so readings are multiples of "
              f"{ceiling / self.COUNTS_PER_RANGE:.4g} {unit}. A tighter "
              f"compliance would buy a finer range; a looser one costs "
              f"resolution.")

    # ---- the sourced axis's own limit ---------------------------------
    def _forget_sourced_axis_state(self):
        """Drop what is known about levels commanded on either axis.

        Called from `reset()` and from every source-function change: the
        largest level of the *previous* run is not headroom the next one
        is entitled to.
        """
        self._current_level_seen = 0.0
        self._voltage_level_seen = 0.0
        self._current_limit_written = None
        self._voltage_limit_written = None

    def _sourced_axis_target(self, level_seen, token, table):
        """The narrowest limit `token` can hold that admits `level_seen`.

        The range floor when nothing has been commanded yet, and just
        enough to clear the largest level once something has. Never
        above full scale, because the range was chosen to fit the level
        in the first place - but clamped anyway, since a caller that
        got that wrong should not send an out-of-window value and earn
        a `-222`.

        `None` when the active range is not known, which is the state
        before `reset()` has run: a driver that has not been reset has
        no idea what range the instrument is on, and inventing a limit
        for a range it has not selected would be a write to the
        instrument on nothing but a guess. The caller writes nothing and
        waits - the first range change re-establishes the limit anyway.
        """
        window = self._window_of(token, table)
        if window is None:
            return None
        floor, ceiling = window
        # The headroom factor also covers the case a bare `max()` would
        # get wrong: a limit set to exactly the level is a limit the
        # level sits on, and an instrument rounding it down by one count
        # would clip the endpoint of a sweep - a curve with a flat top
        # and no error anywhere.
        return min(ceiling,
                   max(floor, abs(level_seen) * SOURCED_AXIS_HEADROOM))

    def _headroom_is_enough(self, level, written):
        """Would the limit already on the instrument admit this level?"""
        if written is None:
            return False
        return abs(level) <= written * (1.0 + self.LIMIT_READBACK_TOLERANCE)

    def _raise_current_headroom(self, amps):
        """Make room for a commanded level, **before** it is commanded.

        Order matters and it is not obvious. If `SOUR:CURR:LIM` caps the
        sourced current - which is the open question on this instrument,
        and one the bench could not close with the output off - then a
        level written while the limit is below it comes out capped, and
        the readback of `SOUR:CURR?` would still report the value asked
        for. So the headroom goes up first and the level second.

        Only writes when the level would not already fit. `set_current
        _level()` is the per-point call in a software sweep, and a write
        plus a readback is two round trips at about 13 ms; doing that
        per point would cost more than the measurement. The largest
        level seen only ever grows, and the range only ever widens, so
        in practice this fires a handful of times across a sweep.
        """
        if abs(amps) > self._current_level_seen:
            self._current_level_seen = abs(amps)
        if self._current_limit is not SOURCED_AXIS:
            return
        if self._headroom_is_enough(amps, self._current_limit_written):
            return
        self._restore_current_limit()

    def _raise_voltage_headroom(self, volts):
        """As `_raise_current_headroom()`, for the voltage axis."""
        if abs(volts) > self._voltage_level_seen:
            self._voltage_level_seen = abs(volts)
        if self._voltage_limit is not SOURCED_AXIS:
            return
        if self._headroom_is_enough(volts, self._voltage_limit_written):
            return
        self._restore_voltage_limit()

    # ---- ranging: re-establishing a limit after the range moved -------
    def _restore_current_limit(self):
        """Write the cached current limit again and check it landed."""
        target = self._current_limit
        if target is None:
            return
        if target is SOURCED_AXIS:
            target = self._sourced_axis_target(
                self._current_level_seen, self._current_range_token,
                self.CURRENT_RANGE_TOKENS)
            if target is None:
                return
        self._write(f"SOUR:CURR:LIM {target:.6e}")
        self._current_limit_written = abs(target)
        self._confirm_limit("current", target, self.read_current_limit,
                            self._current_range_token,
                            self.CURRENT_RANGE_TOKENS, "A")

    def _restore_voltage_limit(self):
        """Write the cached voltage limit again and check it landed."""
        target = self._voltage_limit
        if target is None:
            return
        if target is SOURCED_AXIS:
            target = self._sourced_axis_target(
                self._voltage_level_seen, self._voltage_range_token,
                self.VOLTAGE_RANGE_TOKENS)
            if target is None:
                return
        self._write(f"SOUR:VOLT:LIM {target:.6e}")
        self._voltage_limit_written = abs(target)
        self._confirm_limit("voltage", target, self.read_voltage_limit,
                            self._voltage_range_token,
                            self.VOLTAGE_RANGE_TOKENS, "V")

    def _confirm_limit(self, quantity, expected, reader, token, table,
                       unit):
        """Read a limit back and refuse to continue if it is not there.

        This is what makes the rest of the wave trustworthy. A limit
        outside the active range's window is *refused* - `-222, "Data
        out of range"` - and the previous value stays in force, so
        without a readback the run continues against whatever the
        instrument happened to be holding. The refusal does appear in
        the error queue, but only `start_linear_sweep()` reads that,
        and only at the start of a sweep.

        Only one condition is checked, deliberately. The obvious second
        one - "is the value the instrument reports inside the window
        this range can enforce?" - is the lesson of bench snippet G,
        where a 5 mA limit survived a move to the 1 mA range and read
        back quite happily as 5 mA. But it cannot fire from any path
        this driver takes: the range is chosen from the limit and a
        range change that would strand it is refused, so `expected` is
        always inside `token`'s window, and a reported value close
        enough to pass the tolerance is inside it too. A check that
        cannot fail is worse than no check, for the same reason the
        `_render_not_sourced` override was left out of this file.

        What actually protects against G is the guard in
        `_apply_current_range()`, and the range is never taken on the
        instrument's word - only ever on the driver's own, which is the
        one that chose it. If a `SOUR:CURR:RANG?` query is ever
        confirmed against hardware, reading the range back here would
        make the window check real; until then it would be decoration.

        A `None` readback is a transport problem rather than a wrong
        compliance, and is left to the layers that handle those.
        """
        actual = reader()
        if actual is None:
            return
        reference = abs(expected) or 1.0
        if abs(abs(actual) - abs(expected)) / reference <= \
                self.LIMIT_READBACK_TOLERANCE:
            return
        raise RangeError(
            f"{self.DISPLAY_NAME}: asked for a {quantity} compliance of "
            f"{expected:.6g} {unit} on {token} and the instrument "
            f"reports {actual:.6g} {unit} - the value was not taken. "
            f"Refusing to run rather than measure against a compliance "
            f"nobody chose.")

    def _ensure_current_range(self, amps):
        """Range up if a level would not fit the active range.

        Only ever upward, and only when it does not fit: ranging down
        mid-sweep would change the measurement resolution partway
        through, which is exactly the inconsistency the sweep-wide range
        choice in start_linear_sweep() exists to avoid.
        """
        needed = self._token_for(amps, self.CURRENT_RANGE_TOKENS)
        if self._rank(needed, self.CURRENT_RANGE_TOKENS) > \
                self._rank(self._current_range_token, self.CURRENT_RANGE_TOKENS):
            self._apply_current_range(needed)

    def _ensure_voltage_range(self, volts):
        needed = self._token_for(volts, self.VOLTAGE_RANGE_TOKENS)
        if self._rank(needed, self.VOLTAGE_RANGE_TOKENS) > \
                self._rank(self._voltage_range_token, self.VOLTAGE_RANGE_TOKENS):
            self._apply_voltage_range(needed)

    @staticmethod
    def _rank(token, table):
        """Position of a token in its table; -1 when unknown."""
        for index, (_, name) in enumerate(table):
            if name == token:
                return index
        return -1

    # ---- sensing ------------------------------------------------------
    def set_remote_sense(self, on=True):
        """Accept 4-wire; refuse 2-wire.

        There is no command for this. The SENSE terminals are strapped
        one way or the other and this rig is wired 4-wire permanently,
        so a request for 2-wire cannot be honoured. Raising rather than
        ignoring it: a silent no-op would put "2-wire" in a CSV
        describing a 4-wire measurement, and that is a wrong number
        rather than a missing feature.

        The panel greys the checkbox out and forces it ticked, so this
        is a backstop rather than something an operator can trip.
        """
        if not on:
            raise NotImplementedError(
                f"{self.DISPLAY_NAME} sensing is set by wiring, not by "
                f"command, and this unit is wired 4-wire. It cannot be "
                f"switched to 2-wire from software.")

    # ---- timing -------------------------------------------------------
    def set_source_delay(self, seconds):
        """No-op. This instrument has no immediate-mode source delay.

        `[SOURce:]MEMory:SOURce:DELay` exists but is a memory-list
        entry, which is U2723A territory. The panel's delay field still
        works: the software sweep in BaseSMU does its settling host-side
        and never calls this method.

        What cannot be removed is the instrument's own auto delay -
        0.5 ms to 20 ms depending on range and mode - which is always
        applied and has no off switch here. sweep_note() says so at
        connect.
        """

    @classmethod
    def clamp_nplc(cls, nplc):
        """Clamp to the model's window AND round to an integer.

        `SENSe:CURRent[:DC]:NPLCycles` takes an NR1 - a whole number of
        cycles from 0 to 255. Sending 2.5 is not a finer setting, it is
        a rounding the instrument does for you without saying which way.
        """
        low, high = cls.NPLC_RANGE
        return int(round(min(max(float(nplc), low), high)))

    def set_nplc(self, nplc):
        """Integration time, in whole power line cycles, on both
        functions.

        Note the spelling: `SENS:CURR:NPLC`, with no `:DC:` infix. The
        GSM next door needs `SENS:CURR:DC:NPLC` and the 2450 uses yet
        another form. Send the wrong one and it is logged and ignored.
        """
        value = self.clamp_nplc(nplc)
        self._write(f"SENS:CURR:NPLC {value}")
        self._write(f"SENS:VOLT:NPLC {value}")
        self._aperture_s = value / LINE_FREQUENCY_HZ

    def aperture(self, quantity="current"):
        """The actual integration window, in seconds, as the instrument
        computes it (NPLC / line frequency).

        Worth having because the number that matters for how long a
        sweep takes is this one, not the NPLC that produced it: 200 NPLC
        at 50 Hz is a 4 s aperture per reading, and two of those per
        sweep point.
        """
        head = "SENS:CURR:APER?" if quantity == "current" \
            else "SENS:VOLT:APER?"
        try:
            return float(str(self._query(head)).strip().split(",")[0])
        except (ValueError, IndexError, AttributeError, ConnectionError):
            return None

    # ---- output -------------------------------------------------------
    def output_on(self):
        self._write("OUTP ON")

    def output_off(self):
        self._write("OUTP OFF")

    # ---- measurement --------------------------------------------------
    def measure(self, timeout_s=3.0):
        """One reading as (volts, amps).

        Two queries, not one. There is no combined read and no
        `FORM:ELEM` on this model, so voltage and current are separate
        round trips - which is why a point costs twice the aperture plus
        twice the ~15 ms latency.

        `MEAS:VOLT?` / `MEAS:CURR?` are safe to use per point here.
        This is NOT the 2400-family `MEAS?`, which is a `CONFigure`
        followed by a `READ?` and resets ranging and compliance on every
        point - the fault found in both the 2401 and the 20H10
        originals. On this instrument `MEASure` simply takes a reading
        against the configuration in place, governed by the NPLC and
        line-frequency settings.

        The timeout floor exists because a long aperture legitimately
        takes seconds: the User's Guide recommends more than 5.115 s for
        the worst case of NPLC 255 at 50 Hz.
        """
        timeout_s = max(float(timeout_s), self._read_timeout())
        volts = self._read_number("MEAS:VOLT?", timeout_s)
        amps = self._read_number("MEAS:CURR?", timeout_s)
        return (volts, amps)

    def _read_timeout(self):
        """A timeout that covers the configured aperture plus latency.

        Derived from the NPLC this driver last set, not queried. The
        worst case is 255 PLC at 50 Hz, a 5.1 s aperture, for which the
        User's Guide recommends allowing more than 5.115 s.
        """
        if self._aperture_s is None:
            return 6.0
        return max(6.0, self._aperture_s * 2.0 + 1.0)

    def _read_number(self, head, timeout_s):
        try:
            reply = self._query(head, timeout_s=timeout_s)
        except Exception:
            return None
        try:
            value = float(str(reply).strip().split(",")[0])
        except (ValueError, IndexError, AttributeError):
            return None
        # Two separate queries here, so there is no column to shift -
        # but a no-reading sentinel is still not a measurement. See
        # BaseSMU.drop_sentinel.
        return self.drop_sentinel(value)

    # ---- sweeps -------------------------------------------------------
    def start_linear_sweep(self, mode, start, stop, points, delay_s):
        """Pick a source range covering the whole sweep, verify the
        configure sequence was accepted, then run BaseSMU's software
        sweep.

        Two jobs the base class cannot do for itself.

        **The range.** The experiment sets the range of the quantity it
        measures and leaves the sourced one alone, because every other
        SMU here auto-ranges its source. This one cannot: left at the
        *RST default of R2V, a sweep to 5 V clips at 2 V and returns a
        perfectly tidy wrong curve. One range covering both ends is
        chosen up front rather than switched mid-sweep, so resolution
        does not change partway through a dataset.

        **The check.** Mode selection on this instrument is an ordered
        sequence rather than an explicit command, so it is inferred
        rather than documented as a single call. The error queue is
        drained in set_source_function() at the start of the configure
        and read here at the end of it: anything in it was caused by
        this run's setup. Raising rather than logging, because the
        thing most likely to be in there is a clamped compliance, and
        that produces data that looks fine and is not.
        """
        span = max(abs(float(start)), abs(float(stop)))
        if mode == "voltage":
            self._apply_voltage_range(
                self._token_for(span, self.VOLTAGE_RANGE_TOKENS))
        elif mode == "current":
            self._apply_current_range(
                self._token_for(span, self.CURRENT_RANGE_TOKENS))
        else:
            raise ValueError(f"Unknown sweep mode: {mode!r}")

        complaints = self._drain_errors()
        if complaints:
            detail = "; ".join(f"{code}: {message}"
                               for code, message in complaints)
            raise RuntimeError(
                f"{self.DISPLAY_NAME} rejected part of the sweep setup "
                f"({detail}). Nothing was sourced. The usual cause is a "
                f"compliance value outside the selected range.")

        return super().start_linear_sweep(mode, start, stop, points, delay_s)

    def sweep_note(self):
        """What the console should say about this instrument at connect.

        Reuses the hook the GSM uses to report its sweep probe. Here
        there is nothing to probe - the answer is always the software
        sweep - but there are two timing floors the panel cannot show
        and somebody would otherwise discover by watching a sweep crawl.
        """
        parts = [
            "no staircase sweep in the immediate command set (the memory"
            " list sequencer is U2723A only), so every sweep is stepped"
            " point by point from the PC",
            "the instrument's own auto delay of 0.5-20 ms per point"
            " depending on range is always applied and cannot be"
            " disabled",
        ]
        aperture = self._aperture_s
        if aperture:
            parts.append(
                f"each point costs two readings of {aperture:.4g} s "
                f"(no combined voltage+current read on this model)")
        return "; ".join(parts)
