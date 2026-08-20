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
        """Record which quantity is being sourced.

        **Sends nothing.** There is no `SOUR:FUNC` on this instrument -
        the mode is selected implicitly by which quantity you drive,
        which is why the User's Guide gives two separate ordered
        sequences instead of one with a mode switch.

        The error queue is drained here because this is the first call
        of every configure sequence, so anything found later in the run
        is attributable to that run rather than to whatever came before.
        """
        if mode not in ("voltage", "current"):
            raise ValueError(f"Unknown source mode: {mode!r}")
        self._source_mode = mode
        self._drain_errors()

    def set_current_level(self, amps):
        self._ensure_current_range(amps)
        self._write(f"SOUR:CURR {amps:.6e}")

    def set_voltage_level(self, volts):
        # No rounding before sending, for the same reason as the 2401
        # and GSM drivers: the original's `round(V, 4)` quantises to
        # 100 uV, which is invisible at 1 V and destroys a sweep on the
        # 2 V range.
        self._ensure_voltage_range(volts)
        self._write(f"SOUR:VOLT {volts:.6e}")

    def set_current_limit(self, amps):
        """Current compliance while sourcing voltage.

        The range is widened first if the requested limit will not fit
        it, and the value is cached so that any *later* range change
        re-sends it. Both halves are needed and the first was missing
        until the bench found it.

        The original design only re-sent the limit after a range
        change, which leaves the end state correct but logs an error on
        the way there: after `*RST` the range is R1uA, the experiment
        asks for a 100 uA compliance before it touches the range, and
        the instrument answers -222, "Data out of range". That entry
        then sits in the queue until `start_linear_sweep()` reads it and
        refuses to run the sweep at all - so every sweep on this
        instrument would have aborted with a message about a rejected
        setup, having been configured perfectly correctly.

        Widening first means the limit is accepted the first time and
        the queue stays clean, which is what the sweep guard is there
        to notice.
        """
        amps = float(amps)
        self._ensure_current_range(amps)
        self._current_limit = amps
        self._write(f"SOUR:CURR:LIM {amps:.6e}")

    def set_voltage_limit(self, volts):
        """Voltage compliance while sourcing current.

        The User's Guide calls this the "input protection voltage". It
        is compliance, not overvoltage protection - this model has no
        OVP control.

        Ranges up first, for the same reason as set_current_limit():
        `*RST` leaves the voltage range at R2V with a 0.2 V limit, so
        anything above 2 V would be refused before the range moved.
        """
        volts = float(volts)
        self._ensure_voltage_range(volts)
        self._voltage_limit = volts
        self._write(f"SOUR:VOLT:LIM {volts:.6e}")

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

    # ---- ranging: per-axis (wave 6d) ----
    #: One range knob per quantity, serving both source and measure.
    #: `apply_ranges()` reconciles a plan by taking the wider of the two
    #: and saying so.
    INDEPENDENT_SOURCE_RANGE = False
    HAS_MEASURE_RANGE = False

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
            ceiling, token = max(self.VOLTAGE_RANGE_TOKENS)
            print(f"{self.DISPLAY_NAME}: no autorange on this model; "
                  f"using the widest voltage range ({token}) for AUTO.")
            self._apply_voltage_range(token)
            return
        self._apply_voltage_range(self._token_for(volts,
                                                  self.VOLTAGE_RANGE_TOKENS))


    def _apply_current_range(self, token):
        """Send a current range token and restore the compliance.

        The restore is the whole point: `CURRent:LIMit`'s accepted
        maximum depends on the active range, so a limit set on a small
        range and then followed by a range change is left clamped where
        it was. Re-sending is cheap and makes the order the experiment
        happens to use irrelevant.
        """
        if token == self._current_range_token:
            return
        self._write(f"SOUR:CURR:RANG {token}")
        self._current_range_token = token
        if self._current_limit is not None:
            self._write(f"SOUR:CURR:LIM {self._current_limit:.6e}")

    def _apply_voltage_range(self, token):
        """Send a voltage range token and restore the voltage limit."""
        if token == self._voltage_range_token:
            return
        self._write(f"SOUR:VOLT:RANG {token}")
        self._voltage_range_token = token
        if self._voltage_limit is not None:
            self._write(f"SOUR:VOLT:LIM {self._voltage_limit:.6e}")

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
