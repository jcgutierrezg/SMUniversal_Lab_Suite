"""
GW Instek GSM-20H10 Source Measure Unit - third SCPI dialect in the suite.

Ported from `IV_Meas_20H10.py`. The instrument was never named in that
script; it was identified from the commented-out resource string
`USB0::8580::125::gew852313::0::INSTR` - 8580 is 0x2184, GW Instek's USB
vendor ID, and `gew...` is their serial prefix.

Why this needs its own file
---------------------------
It is SCPI, like the 2450 and the 2401 next door, and it is *nearly*
the 2400 dialect - but "nearly" is the problem. Compare compliance:

    2450    :SOUR:VOLT:ILIM 1e-3
    2401    :SENS:CURR:PROT 1e-3
    GSM     :SENS:CURR:DC:PROT:LEV 1e-3

Three spellings of one idea. Send the wrong one and the instrument logs
an error, ignores the command, and carries on at its previous
compliance - no exception, no warning, just a sample cooked at the last
setting somebody happened to leave it on. That silent-ignore behaviour
is the entire reason drivers exist as separate files rather than one
class with `if model ==` branches.

Envelope
--------
+/-210 V, +/-1.05 A, 22 W, four-quadrant. Same corner shape as the 2450:
21 V at 1.05 A *or* 210 V at 105 mA, never both maxima at once.

Sweeps
------
Unlike the 2401 - whose hardware sweep the original script abandoned -
this one is implemented, because the GSM has a genuine sequence engine
(linear staircase, log staircase, custom, SRC-MEM; up to 2500 points).
The original script never touched it and stepped the source from Python
instead, which is why `sweep_kind` matters here: two runs off the same
instrument can now have been taken two different ways.

**The staircase command spellings are an inference and are verified at
runtime rather than trusted.** They are the standard 2400-family
sequence commands, which is what the GSM's documented command
compatibility implies, but nobody has confirmed them against this
instrument on a bench. So `_probe_sweep_support()` sends one distinctive
sweep command at connect and then reads the error queue: if the
instrument complains, the driver quietly reports itself as
`sweep_kind() == "software"` and inherits the point-by-point fallback
from BaseSMU. The failure mode this defends against is precisely the
silent-ignore described above - the difference is that here the driver
*asks* whether it was understood instead of assuming.

If the probe turns out to be wrong in either direction, the fix is in
this file and nothing in experiments/ changes.
"""
from smuniversal_lab_suite.core.limits import SMULimits
from smuniversal_lab_suite.core.ranges import AUTO, NOT_SOURCED
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

from .base_smu import BaseSMU

# Reading buffer capacity, from the command list. The staircase
# stores one reading per sweep point, so this is also the largest
# hardware sweep the instrument can run in one go.
MAX_BUFFER_POINTS = 2500

class GWInstekGSM20H10(BaseSMU):
    # This instrument reports "no reading" as a very large number
    # rather than as an error: +9.91e37 when a function was neither
    # sourced nor measured, +9.9e37 for an over-range reading. It was
    # the first driver here to handle that, and NAN_THRESHOLD has since
    # been promoted to BaseSMU because four other drivers turned out to
    # need it too. Inherited now; the reasoning is in base_smu.py.
    # The *IDN? reply was never captured - the original commented its
    # `*IDN?` query out. "GSM-20H10" is the model as printed; the
    # hyphenless and bare forms are fallbacks for reply strings that
    # punctuate differently. The registry prefers the longest match, so
    # the specific spelling wins wherever the full string is present.
    MODEL_IDS = ["GSM-20H10", "GSM20H10", "20H10"]
    DISPLAY_NAME = "GW Instek GSM-20H10"

    # Provisional: downgraded to "software" by the connect-time probe if
    # the instrument doesn't recognise the staircase commands. See
    # sweep_kind() below - it is an instance method on this driver, not
    # the class-level constant the other drivers use, because the answer
    # is only known once there is something on the other end of the wire.
    SWEEP_KIND = "hardware"

    LIMITS = SMULimits(
        max_voltage=210.0,
        max_current=1.05,
        # Four source ranges and seven current ranges, per the manual's
        # range tables. Note there is no 20 mV range - the family starts
        # at 200 mV, unlike the 2450.
        voltage_ranges=[0.2, 2.0, 20.0, 200.0],
        current_ranges=[1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0],
        # 22 W four-quadrant: 21 V at 1.05 A, or 210 V at 105 mA
        power_envelope=[(21.0, 1.05), (210.0, 0.105)],
    )

    # Speed settings run Fast (0.01) to High (10) PLC, with anything in
    # between allowed via the manual "Other" option.
    NPLC_RANGE = (0.01, 10.0)

    # Overvoltage protection. The original pinned this at MIN with
    # `SOUR:VOLT:PROT DEF  # Higher voltage` commented out beside it, so
    # both tokens are known to be accepted. MIN stays first in the list
    # and so remains the default the panel offers - the original's
    # behaviour is preserved for anyone who doesn't touch the control.
    #
    # Overvoltage protection, now pinned down by the manual:
    #
    #   <n> = -210 to 210   any level in range (magnitude; sign ignored)
    #   NONE                disable OVP entirely
    #   MINimum             20 V      <- not "the smallest possible"
    #   DEFault / MAXimum   210 V
    #
    # Two corrections to what was here before. NONE *is* valid after all
    # - it was removed last round on the reasoning that a <n> parameter
    # wouldn't take a name, which the manual disproves. And MINimum is
    # specifically 20 V, not a floor.
    #
    # The MIN/DEF/MAX tokens are dropped from the menu in favour of the
    # numbers they stand for. They were the source of the confusion in
    # the first place, and "20 V" tells an operator what the instrument
    # will do where "MIN" does not. `IV_Meas_20H10.py` sent MIN, so 20 V
    # is first in the list and remains the default; its commented-out
    # DEF is the 210 V entry.
    #
    # The instrument accepts any level in range, not a ladder, so these
    # are conveniences rather than the permitted set.
    OVP_CHOICES = ["20", "40", "60", "80", "100", "120", "160", "200",
                   "210", "OFF"]

    # THIS INSTRUMENT DROPS COMMANDS THAT ARRIVE IN A BURST.
    #
    # Measured 2026-09-16 on V1.16 over vendor VISA, with the twenty-five
    # writes an IV sweep sends before its first query, then that query:
    #
    #   unpaced   7 of 10 never answered - not in 30 s, so not late but
    #             absent - and the 3 that did returned three DIFFERENT
    #             error queues from identical commands
    #   5 ms      10 of 10 answered, all with the same queue
    #
    # Identical input producing three outcomes is the evidence: commands
    # were being lost at random depths in the burst. When the lost one
    # was a setting, the run was configured by whatever survived; when
    # it was the query, no reply was ever generated, the read timed out,
    # the transport latched and the run was discarded.
    #
    # It is also why this went unseen for so long. `IV_Meas_20H10.py`
    # alternated a level write with a `MEAS?` and never built a burst;
    # the SCPI console, checking the error queue after every write,
    # paces itself the same way, which is why replaying a failing
    # session over it in August measured 9.9 ms and was recorded as not
    # reproducible. The suite is the only caller that sends twenty
    # commands without reading anything back.
    #
    # 5 ms is the tested value, not a measured threshold. It costs
    # 125 ms per configuration block.
    WRITE_DELAY_S = 0.005

    def __init__(self, transport):
        super().__init__(transport)
        # None until probed; then "hardware" or "software".
        self._sweep_mode = None
        self._sweep_points = 0
        self._sweep_note = ""
        self._feed_token = None
        self._buffer_stride = None
        # The fixed measurement range each axis was last asked for, or
        # None. Re-sent when that axis's compliance arrives - see
        # `_resend_measure_range()`.
        self._measure_ranges = {"current": None, "voltage": None}
        # What the armed staircase will cost, for the budget of the
        # query that waits for it - see _sweep_wait_budget(). NPLC 1 is
        # the *RST default.
        self._sweep_delay = 0.0
        self._nplc = 1.0

    # ---- identity and housekeeping ----
    def reset(self):
        """Reset, clear the error queue, and re-enable the beeper.

        `SYST:CLE` empties the error queue specifically - distinct from
        `*CLS`, which clears the status registers. Both are sent because
        the sweep probe below reads the error queue and needs to start
        from a known-empty one.

        `OUTP:ENAB 0` disables the interlock line, matching the original
        and the 2401 driver next door. Without it an instrument with
        nothing wired to the interlock refuses to turn its output on.
        """
        self.transport.write("*CLS")
        self.transport.write("*RST")
        self.transport.write("SYST:CLE")
        self.transport.write("SYST:BEEP:STAT 1")
        self.transport.write("OUTP:ENAB 0")
        # Output-off mode is NOT set here. It is a per-run choice
        # driven from the panel via set_output_off_mode(), because the
        # manual warns against HIMPedance "for tests that turn the
        # output on and off frequently" and iv_sweep's periodic mode
        # does exactly that. *RST leaves this at NORMal, which is the
        # default the panel also offers.
        # NPLC is only worth setting if the instrument knows the mains
        # frequency - integrating over "one cycle" cancels hum only when
        # the cycle length is right. Auto-detect rather than hardcoding
        # 50 Hz, so this survives the rig being taken anywhere else.
        self.transport.write("SYST:LFR:AUTO 1")
        self.transport.write("SOUR:CLE:AUTO 0")
        self.transport.write("ROUT:TERM FRON")
        # Disarm buffer storage. The command list is explicit that
        # `TRACe:FEED cannot be changed while buffer storage is active`,
        # and a sweep setup has to change it. *RST is supposed to leave
        # storage off, but this instrument was rejecting `TRAC:FEED`
        # anyway - so it is turned off by name rather than by
        # assumption, once, where it costs nothing.
        self.transport.write("TRAC:FEED:CONT NEV")
        # Fix what a reading contains, rather than inheriting whatever
        # the front panel was left showing. Two fields, voltage first -
        # which is the order the original's MEAS? parsing assumed but
        # never actually set.
        self.transport.write("FORM:ELEM VOLT,CURR")
        self._sweep_mode = None
        self._nplc = 1.0
        # *RST discarded the ranges; re-sending a remembered one after
        # it would configure a setting nobody asked for since (fault 6).
        self._measure_ranges = {"current": None, "voltage": None}

    def read_error(self):
        """Pop one entry off the instrument's error queue.

        Returns (code, message). Code 0 means the queue was empty, i.e.
        everything sent so far was understood. A transport hiccup is
        reported as code 0 as well: failing to *read* the error queue is
        not evidence that a command failed, and treating it as such
        would disable the hardware sweep over a dropped reply.
        """
        try:
            reply = self.transport.query("SYST:ERR?", timeout_s=3.0)
        except TransportDesynchronised:
            raise
        except Exception:
            return (0, "")
        if not reply:
            return (0, "")
        head, _, tail = reply.partition(",")
        try:
            return (int(float(head.strip())), tail.strip().strip('"'))
        except ValueError:
            return (0, reply.strip())

    def _drain_errors(self):
        """Empty the error queue, returning everything found.

        `:SYST:ERR:ALL?` returns the whole queue in one reply, which the
        original bounded polling loop was a workaround for not knowing
        about. One round trip instead of up to ten, and no risk of an
        instrument that errors on every query spinning here.

        Reply shape is repeated `code,"message"` pairs, so the split is
        on commas and the codes are whatever parses as a number.
        """
        try:
            reply = self.transport.query("SYST:ERR:ALL?", timeout_s=3.0)
        except TransportDesynchronised:
            raise
        except Exception:
            return []
        if not reply:
            return []

        found = []
        parts = [p.strip() for p in str(reply).split(",")]
        i = 0
        while i < len(parts):
            try:
                code = int(float(parts[i]))
            except (ValueError, IndexError):
                i += 1
                continue
            message = parts[i + 1].strip('"') if i + 1 < len(parts) else ""
            if code != 0:
                found.append((code, message))
            i += 2
        return found

    # ---- source configuration ----
    def set_source_function(self, mode):
        # Both sense functions stay on, with concurrent measurement
        # enabled, regardless of which quantity is being sourced.
        #
        # This matters more than it looks. With CONCurrent off, only one
        # function is actually measured and the other element of the
        # reply is filled in from the *source setting* rather than from
        # a measurement. Sourcing 1 V into a 4-wire rig, the voltage
        # field would read back exactly 1.000000 V - the number that was
        # asked for, not the number across the sample - so lead and
        # contact drops would vanish from the data and 4-wire sensing
        # would silently become a very convincing 2-wire measurement.
        #
        # The original never set this, so whatever the front panel was
        # last left in decided it.
        self.transport.write("SENS:FUNC:CONC ON")
        self.transport.write('SENS:FUNC:ON "VOLT","CURR"')

        if mode == "current":
            self.transport.write("SOUR:FUNC CURR")
        elif mode == "voltage":
            self.transport.write("SOUR:FUNC VOLT")
        else:
            raise ValueError(f"Unknown source mode: {mode!r}")
        # Hold the level between points instead of dropping to zero and
        # settling again, as the original did for both directions.
        self.transport.write("SOUR:CLE:AUTO 0")
        # A range remembered under the other function must not follow a
        # limit into this one. Setting the measurement range of the
        # quantity being sourced is `+823` here, and a plan for the new
        # function will say which ranges it wants.
        self._measure_ranges = {"current": None, "voltage": None}

    #: Counts across one source range, measured 2026-09-01.
    #:
    #: `tools/bench_envelope.py` pinned the source current range to
    #: 1e-4 A and halved down. The sign stopped being followed below
    #: **3.052e-09 A**, and
    #:
    #:     1e-4 A / 32768 = 3.0518e-09 A
    #:
    #: so the measured floor is one count of the range the sweep was on.
    #:
    #: This instrument is also the reason the *procedure* that produced
    #: the number can be believed. On 2026-08-28 an earlier version of
    #: the sweep reported "sign follows" for twenty-one halvings down to
    #: 95 pA on readings that never left +140 uA and +20 uA - a fixed
    #: offset sitting inside a window that shrank with the level. The
    #: bound that fixed it, and that the 09-01 figures were taken under,
    #: is in `sign_is_commanded()`: the two legs must land on opposite
    #: sides of zero and separate by about 2L, not merely by more than
    #: L.
    #:
    #: Current only. The bench procedure sources current and only
    #: current, so the voltage axis stays `unmeasured`.
    SOURCE_COUNTS_PER_RANGE = {"current": 32768, "voltage": None}

    SUB_COUNT_LEVELS = {"current": BaseSMU.SUB_COUNT_REFUSED,
                        "voltage": BaseSMU.SUB_COUNT_UNMEASURED}

    def set_current_level(self, amps):
        self.guard_source_level("current", amps, "A")
        self.transport.write(f"SOUR:CURR {amps:.6e}")

    def set_voltage_level(self, volts):
        # The original rounded each level to 4 decimals before sending
        # (`round(Vo + i*step, 4)`). Not reproduced: on the 200 mV range
        # that quantises the sweep to 0.1 mV steps, which is 100x coarser
        # than the instrument's 1 uV programming resolution. Same
        # decision, and same reasoning, as the 2401 driver.
        self.transport.write(f"SOUR:VOLT {volts:.6e}")

    def set_current_limit(self, amps):
        """Current compliance while sourcing voltage.

        This is the setting the original's dropdown drove - labelled
        "current range" in that GUI, but it is a compliance level.
        """
        self.transport.write(f"SENS:CURR:DC:PROT:LEV {amps:.6e}")
        self._resend_measure_range("current")

    def set_voltage_limit(self, volts):
        """Voltage compliance while sourcing current - the mirror of
        the above, and the one the original never used because it only
        ever swept voltage."""
        self.transport.write(f"SENS:VOLT:DC:PROT:LEV {volts:.6e}")
        self._resend_measure_range("voltage")

    def _resend_measure_range(self, quantity):
        """Send the remembered measurement range again, now its limit is in.

        ON THIS INSTRUMENT NEITHER ORDER IS SAFE ON ITS OWN.

        A limit sent before its range is clamped to the range in force -
        fault 15, and the reason every experiment ranges first. But a
        range sent before its limit is refused if it is wider than the
        compliance already there: `+824 Cannot exceed compliance range`,
        and the instrument **stays on the narrower range**. After `*RST`
        the current compliance is 105 uA, so an IV sweep asking for a
        100 mA measurement range had it refused on every first run after
        a connect, and measured current on 105 uA - overranging into a
        sentinel above that. Seen on 2026-08-20 at 10 uA, and named
        against `SENS:CURR:DC:RANG 1.000000e-01` on 2026-09-16, three
        runs out of three. It went unnoticed because the error-queue
        read that would have reported it was the query this instrument
        kept dropping.

        So the range goes first, as fault 15 requires, and again once
        the limit that has to hold it has arrived. Whatever order a
        caller uses, the second send meets the compliance the caller
        chose. If that compliance is narrower than the range, the
        second send is refused too and the narrower range stands -
        which is right: the compliance is the protection, and a range
        wider than it would only report readings the limit will never
        let happen.

        The first refusal stays in the error queue as `+824`. It is a
        true record of what the instrument did, and the range that
        matters is the one in force afterwards, which the checkup reads
        back.

        Only a fixed range is remembered. AUTO needs nothing re-sent,
        and a source axis is never touched here: `SOUR:CURR:RANG:AUTO`
        is the command that collapses this instrument's compliance
        (fault 23).

        The voltage axis is the mirror and is unmeasured. It is done
        anyway because the 2026-09-11 readback session asked for a 200 V
        measure-voltage range with the reset compliance of 21 V in
        force, saw it not taken, and did not read the queue - which is
        this refusal, if the rule is symmetric. The round's checkup
        answers that.
        """
        remembered = self._measure_ranges.get(quantity)
        if remembered is None:
            return
        axis = "CURR" if quantity == "current" else "VOLT"
        self.transport.write(f"SENS:{axis}:DC:RANG {remembered:.6e}")

    #: Verified at the bench, 2026-08-20. `SENS:CURR:DC:PROT:LEV?`
    #: returned `+1.050000e-04` after `*RST` - matching the manual's
    #: factory-defaults table - and `+1.000000e-09` immediately after
    #: `SOUR:CURR:RANG:AUTO ON`, matching the collapse that was then
    #: reproduced repeatedly in both source functions.
    #:
    #: Trusted despite `OUTP?` on this same instrument returning 0 with
    #: the output on and 10 V flowing. The two are different queries and
    #: the compliance one was checked directly against values known from
    #: two independent sources; the output one was believed for five
    #: rounds and never checked, which is the whole reason this flag
    #: exists.
    COMPLIANCE_READBACK_TRUSTED = True

    def _read_compliance(self, query):
        """One float from a compliance query, or `None`.

        Local rather than shared: the U2722A has a `_read_number` of its
        own that applies `drop_sentinel`, which is right for a
        *measurement* and wrong here. A compliance is a setting - if it
        ever came back as the no-reading sentinel that would be a fault
        to report, not a value to discard.
        """
        try:
            reply = self.transport.query(query, timeout_s=3.0)
            return float(str(reply).strip().split(",")[0])
        except TransportDesynchronised:
            raise
        except Exception:
            return None

    def read_current_limit(self):
        return self._read_compliance("SENS:CURR:DC:PROT:LEV?")

    def read_voltage_limit(self):
        return self._read_compliance("SENS:VOLT:DC:PROT:LEV?")

    # ---- ranging ----
    # ---- ranging: per-axis (wave 6d) ----
    def _render_not_sourced(self, value):
        """Send nothing on a source axis that is carrying nothing.

        `SOUR:CURR:RANG:AUTO ON` while sourcing voltage silently resets
        the current compliance from 105 uA to **1 nA**, and
        `SOUR:VOLT:RANG:AUTO ON` while sourcing current takes the
        voltage compliance from 21 V to 200 uV. Measured 2026-08-20,
        repeatable, in both source functions, with a clean error queue
        across the command that does it - see fault 23.

        The `+824` and `+826` errors that led to this were consequences
        landing on later, innocent commands: with the compliance at
        1 nA, narrowing a measurement range to 100 uA genuinely does
        exceed it. That is why `+826 Attempt to exceed power limit`
        appeared on a microwatt and never made sense.

        Runs were surviving it only because fault 15's ordering puts
        the experiment's own compliance *after* the ranging block, which
        restored it by accident rather than by design.

        Returning `None` means the hook makes no call at all. The
        instrument keeps whatever source range it had, which is correct:
        no level of that quantity will be sourced.
        """
        return None if value is NOT_SOURCED else value

    def _apply_source_current_range(self, amps):
        """Source ranging confirmed present; autorange ON at reset."""
        if amps is None:
            return          # not sourced - see _render_not_sourced
        if amps is AUTO:
            self.transport.write("SOUR:CURR:RANG:AUTO ON")
        else:
            self.transport.write("SOUR:CURR:RANG:AUTO OFF")
            self.transport.write(f"SOUR:CURR:RANG {amps:.6e}")

    def _apply_source_voltage_range(self, volts):
        if volts is None:
            return          # not sourced - see _render_not_sourced
        if volts is AUTO:
            self.transport.write("SOUR:VOLT:RANG:AUTO ON")
        else:
            self.transport.write("SOUR:VOLT:RANG:AUTO OFF")
            self.transport.write(f"SOUR:VOLT:RANG {volts:.6e}")

    def _apply_measure_current_range(self, amps):
        if amps is AUTO:
            self._measure_ranges["current"] = None
            self.transport.write("SENS:CURR:DC:RANG:AUTO ON")
        else:
            # Remembered before it is sent: it may be refused against
            # the compliance in force. See _resend_measure_range().
            self._measure_ranges["current"] = amps
            self.transport.write("SENS:CURR:DC:RANG:AUTO OFF")
            self.transport.write(f"SENS:CURR:DC:RANG {amps:.6e}")

    def _apply_measure_voltage_range(self, volts):
        if volts is AUTO:
            self._measure_ranges["voltage"] = None
            self.transport.write("SENS:VOLT:DC:RANG:AUTO ON")
        else:
            self._measure_ranges["voltage"] = volts
            self.transport.write("SENS:VOLT:DC:RANG:AUTO OFF")
            self.transport.write(f"SENS:VOLT:DC:RANG {volts:.6e}")

    #: The measurement-range readback, whose spelling came off this
    #: instrument rather than out of a manual: on 2026-08-20 asking for
    #: `SENS:CURR:DC:RANG 1.000000e-04` with the compliance at 10 uA
    #: gave `+824` and left `SENS:CURR:DC:RANG?` reading
    #: `1.050000E-05` - a range the operator did not choose, with no
    #: exception raised. That observation is the reason this exists and
    #: is also why it is **not** trusted: it shows the query answers and
    #: answers meaningfully, and it does not show the answer being
    #: checked against a range known independently.
    #:
    #: 2026-09-11 closed half of it. Measure current passed every leg
    #: of `tools/bench_readback.py`: it named a range set from the
    #: front panel and followed two bus changes. Measure voltage named
    #: the front-panel range but stayed on it when the bus asked for
    #: 200 V; the error queue was not read, so why is not known. The
    #: flag covers both axes, so it stays False.
    #:
    #: The two *source* range queries are deliberately absent. Nothing
    #: has ever asked this instrument for one, `SOUR:CURR:RANG:AUTO` is
    #: the command that silently resets its compliance (fault 23), and
    #: an unanswered query latches the transport - so a guess costs a
    #: run rather than a line in a report.
    RANGE_READBACK_TRUSTED = False

    def read_measure_current_range(self):
        return self._read_setting("SENS:CURR:DC:RANG?")

    def read_measure_voltage_range(self):
        return self._read_setting("SENS:VOLT:DC:RANG?")

    def _read_setting(self, query):
        """One float from a settings query, or `None`.

        Same shape and same reasoning as `_read_compliance` above, and
        deliberately not that method: a range and a compliance are
        different subsystems whose queries were confirmed at different
        times, and sharing a reader would let one's verification be read
        as the other's.
        """
        try:
            reply = self.transport.query(query, timeout_s=3.0)
            return float(str(reply).strip().split(",")[0])
        except TransportDesynchronised:
            raise
        except Exception:
            return None

    # ---- sensing ----
    def set_remote_sense(self, on=True):
        self.transport.write(f"SYST:RSEN {1 if on else 0}")

    def set_terminals(self, which="front"):
        """Front or rear terminals. Not part of BaseSMU - plenty of SMUs
        have no such switch. Note the output drops when this changes."""
        self.transport.write(
            f"ROUT:TERM {'FRON' if which == 'front' else 'REAR'}")

    # ---- protection ----
    def set_voltage_protection(self, choice):
        """Set the OVP ceiling.

        Distinct from compliance, and worth keeping straight: compliance
        limits the quantity you are *not* sourcing, whereas OVP is a
        hard ceiling on the source itself. The case it exists for is a
        4-wire sense lead falling off mid-run - the instrument sees 0 V
        at the sample, assumes it is undershooting, and winds the output
        up to compensate. OVP is what stops that at a chosen level
        instead of at the instrument's 210 V maximum.
        """
        token = str(choice).strip().upper()
        if token in ("OFF", "NONE", "DISABLE", ""):
            token = "NONE"
        self.transport.write(f"SOUR:VOLT:PROT {token}")

    #: Which protection trip reports compliance, per sourced quantity.
    #: The limit is always on the quantity you are NOT setting, and this
    #: instrument's manual says so in as many words: ":CURRent:
    #: PROTection:TRIPped? is used to check the compliance state of the
    #: V-Source, and the :VOLTage:PROTection:TRIPped? Command is used to
    #: check the compliance state of the I-Source."
    #:
    #: Same table, word for word, in the Keithley 2401 manual, so this
    #: is the SCPI convention rather than a GW Instek quirk - which is
    #: why the B2901A carries the same map under its own spellings.
    _TRIP_QUERY = {"VOLT": "SENS:CURR:DC:PROT:TRIP?",
                   "CURR": "SENS:VOLT:DC:PROT:TRIP?"}

    def compliance_tripped(self):
        """Ask the protection trip belonging to the quantity NOT sourced.

        This used to query both axes and OR them, on the argument that
        it cost one extra query and removed a way to get the answer
        wrong when the mode and the tripped function disagreed. Against
        the documented meaning of these queries it *added* one: on a
        voltage source, `SENS:VOLT:DC:PROT:TRIP?` reports the I-Source,
        which is not running. If that flag holds a value from the last
        time it was, the OR returns True for a clamp that is not
        happening - and the checkup's clamping check would then pass on
        a stale flag while the mechanism the experiments rely on was
        broken. A check that passes for free is worse than no check.

        (Whether these flags latch is still unmeasured; the manual's
        entry has no *Affected by* column. Selecting the axis makes the
        question moot for this answer, because the inactive flag is
        never read. It is still worth a probe: source current into an
        open circuit until it rides the voltage limit, then switch to
        sourcing voltage with nothing clamping and read both. The
        interesting answer is the second one.)

        The sourced function is read from the instrument rather than
        remembered, for the same reason the B2901A reads it: a local
        copy is one `reset()` or one front-panel change away from being
        wrong, and being wrong here means a confident False, which is
        worse than no answer.

        `MEMory` is a third source mode on this model - a saved sequence
        of setups, recalled in turn - and in it neither trip query
        describes what the instrument is doing. That returns None, which
        the report renders as "cannot say" rather than as a reassurance.
        """
        try:
            mode = self.transport.query("SOUR:FUNC?", timeout_s=3.0)
        except TransportDesynchronised:
            raise
        except Exception:
            return None
        # Long or short form, quoted or bare: `VOLTage`, `VOLT`, `"VOLT"`
        # are all the same answer.
        key = str(mode).strip().strip('"').upper()[:4]
        query = self._TRIP_QUERY.get(key)
        if query is None:
            return None                    # MEMory, or a reply we cannot read
        try:
            reply = self.transport.query(query, timeout_s=3.0)
            return bool(int(float(str(reply).strip().split(",")[0])))
        except TransportDesynchronised:
            raise
        except Exception:
            return None

    # ---- timing ----
    def set_source_delay(self, seconds):
        """Source delay in SECONDS, 0 to 999.9999 on this model.

        (An earlier comment here said 9999.999 - off by a factor of ten.
        The manual's figure is 999.9999, with a *RST default of 1 ms.)

        Auto delay is turned off first: left on, the instrument picks
        its own settle time from the selected range and ignores the
        value being set here, so a delay typed into the panel would do
        nothing.
        """
        self.transport.write("SOUR:DEL:AUTO 0")
        value = min(max(float(seconds), 0.0), 999.9999)
        self.transport.write(f"SOUR:DEL {value:.5f}")

    def set_nplc(self, nplc):
        """Integration time, on both sense functions.

        Note the `:DC:` infix - this family spells the sense subsystem
        `SENS:CURR:DC:...` where the 2450 and 2401 use `SENS:CURR:...`.
        The original sent `SENS:CURR:DC:NPLC 1` and it worked, which
        pins the spelling for the current side; the voltage side is the
        matching form.
        """
        value = self.clamp_nplc(nplc)
        self.transport.write(f"SENS:CURR:DC:NPLC {value:.4f}")
        self.transport.write(f"SENS:VOLT:DC:NPLC {value:.4f}")
        self._nplc = float(value)

    # ---- output ----
    def output_on(self):
        self.transport.write("OUTP 1")

    def output_off(self):
        self.transport.write("OUTP 0")

    HIGH_Z_OFF = True

    def set_output_off_mode(self, high_z=False):
        """HIMPedance opens the output relay; NORMal sources 0 V.

        ZERO and GUARd also exist on this model and are not exposed -
        ZERO is for generating 0 V/level waveforms with auto-clear, and
        GUARd is for 6-wire guarded ohms. Neither is what any experiment
        here is doing, and offering four options where two are wanted
        makes the common choice harder to see.
        """
        self.transport.write(
            f"OUTP:SMOD {'HIMP' if high_z else 'NORM'}")

    def beep(self, hertz=500, seconds=2):
        """Sound the front-panel beeper.

        The original beeped at the end of every sweep - genuinely useful
        when a long run is going and you are across the room. Exposed
        here rather than fired automatically, so the experiment decides.
        """
        self.transport.write(f"SYST:BEEP:IMM {int(hertz)},{int(seconds)}")

    # ---- measurement ----
    def measure(self, timeout_s=3.0):
        """One reading as (volts, amps).

        `READ?`, not `MEAS?` - and this is a change from the original.
        # DEVIATION 11

        `MEAS?` on this family means "configure, then read": it resets
        the ranging and compliance that were just set, on every single
        point of the sweep. `IV_Meas_20H10.py` set
        `SENS:CURR:DC:PROT:LEV` once before its loop and then called
        `MEAS?` at each point, so the compliance it carefully chose was
        being undone before the very first reading.

        Exactly the same fault was found in the 2401 original and fixed
        the same way - see docs/faults/01-meas-per-point.md. `READ?`
        triggers a reading against the configuration already in place,
        which is what a sweep wants.

        Pairs with `FORM:ELEM VOLT,CURR` in reset(), which fixes the
        reply to two fields in that order.
        """
        reply = self.transport.query("READ?", timeout_s=timeout_s)
        return self._parse_reading(reply)

    @classmethod
    def _clean(cls, value):
        """Map the instrument's NAN/overflow sentinels to None."""
        if value is None:
            return None
        return None if abs(value) >= cls.NAN_THRESHOLD else value

    @classmethod
    def _parse_reading(cls, reply):
        """Pull the leading numbers out of a reading reply as
        (voltage, current), with sentinels mapped to None."""
        if not reply:
            return (None, None)
        sep = "," if "," in reply else None
        parts = reply.split(sep) if sep else reply.split()
        nums = []
        for p in parts:
            try:
                nums.append(float(p))
            except ValueError:
                stripped = "".join(
                    ch for ch in p if (ch.isdigit() or ch in ".-+eE"))
                try:
                    nums.append(float(stripped))
                except ValueError:
                    pass
        if len(nums) >= 2:
            return (cls._clean(nums[0]), cls._clean(nums[1]))
        if len(nums) == 1:
            return (cls._clean(nums[0]), None)
        return (None, None)

    # ---- sweeps ----
    def sweep_kind(self):
        """'hardware' or 'software', probed rather than declared.

        Deliberately an *instance* method here where every other driver
        uses the class-level SWEEP_KIND constant, because on this model
        the honest answer isn't known until an instrument has been asked.
        Calling GWInstekGSM20H10.sweep_kind() on the class will not work;
        nothing does, and the alternative - claiming "hardware" and
        finding out mid-run - is worse.
        """
        if self._sweep_mode is None:
            self._probe_sweep_support()
        return self._sweep_mode

    def sweep_note(self):
        """Human-readable outcome of the probe, for the console."""
        if self._sweep_mode is None:
            self._probe_sweep_support()
        return self._sweep_note

    def _probe_sweep_support(self):
        """Ask the instrument whether it understands the staircase
        commands, and remember the answer.

        Two commands, both harmless on their own - a spacing mode and a
        point count, neither of which sources anything. The error queue
        is drained first so anything found afterwards is attributable to
        the probe rather than to whatever was sent before it.
        """
        try:
            self._drain_errors()
            self.transport.write("SOUR:SWE:SPAC LIN")
            self.transport.write("SOUR:SWE:POIN 2")
            complaints = self._drain_errors()
        except Exception as exc:
            self._sweep_mode = "software"
            self._sweep_note = (
                f"sweep probe failed ({exc}); using the point-by-point "
                f"software sweep")
            return

        if complaints:
            code, message = complaints[0]
            self._sweep_mode = "software"
            self._sweep_note = (
                f"instrument rejected the staircase commands "
                f"({code}: {message}); using the point-by-point software "
                f"sweep instead")
        else:
            self._sweep_mode = "hardware"
            self._sweep_note = ("instrument staircase sweep accepted "
                                "(runs off the SMU's own timebase)")

    def start_linear_sweep(self, mode, start, stop, points, delay_s):
        """Begin a linear staircase sweep and return immediately.

        Falls through to BaseSMU's software sweep when the probe said
        the instrument won't take these commands, so the caller gets a
        working sweep either way and never branches on the answer.
        """
        if self.sweep_kind() != "hardware":
            return super().start_linear_sweep(mode, start, stop, points,
                                              delay_s)

        if mode == "voltage":
            source = "VOLT"
        elif mode == "current":
            source = "CURR"
        else:
            raise ValueError(f"Unknown sweep mode: {mode!r}")

        points = int(points)
        if points < 2:
            raise ValueError("A sweep needs at least 2 points.")
        if points > MAX_BUFFER_POINTS:
            # The buffer tops out at 2500 readings and the staircase
            # stores one per point. Caught here with a message naming
            # the limit, rather than at `TRAC:POIN` where the
            # instrument's own complaint would be a bare error code
            # attached to a command the operator never typed.
            raise ValueError(
                f"The {self.DISPLAY_NAME} buffer holds at most "
                f"{MAX_BUFFER_POINTS} readings; {points} points were "
                f"requested. Use fewer points, or split the sweep.")
        self._sweep_points = points
        self._sweep_delay = max(float(delay_s), 0.0)
        self._last_sweep_mode = mode

        # Resolved BEFORE the error queue is cleared for the staircase.
        # It probes by writing and checking the queue, so running it
        # mid-setup would swallow a complaint about an earlier command -
        # and the setup check at the end would then see a clean queue
        # and fire a half-configured sweep. That is precisely the
        # failure the check exists to catch.
        feed = self._buffer_feed_command()

        self._drain_errors()

        # Staircase definition. Start/stop/points rather than a step
        # size: a step that doesn't divide the span exactly leaves the
        # last point somewhere unintended, and the experiment already
        # thinks in points.
        setup = [
            f"SOUR:{source}:STAR {float(start):.6e}",
            f"SOUR:{source}:STOP {float(stop):.6e}",
            "SOUR:SWE:SPAC LIN",
            f"SOUR:SWE:POIN {points}",
            "SOUR:SWE:DIR UP",
        ]
        for command in setup:
            self.transport.write(command)
        # UP means "start level to stop level", NOT "ascending".
        # Confirmed against the command list, which is unambiguous:
        # "Normally, a sweep is run from the start level to the stop
        # level... With DOWn selected, the sweep will begin at the stop
        # level and end at the start level. Selecting UP restores sweep
        # operation to the normal start to stop direction."
        #
        # So a descending sweep is expressed as start > stop with
        # DIRection left at UP; DOWn would reverse it back again and run
        # the sweep the wrong way round, silently returning the data
        # backwards. The panel allows start > stop, so this is
        # load-bearing.
        # BEST picks one fixed range covering the whole sweep. AUTO
        # would range-change mid-sweep, and each change carries its own
        # settling time - which is exactly the timing consistency the
        # hardware sweep is being used for in the first place.
        setup += ["SOUR:SWE:RANG BEST", f"SOUR:{source}:MODE SWE"]
        self.transport.write("SOUR:SWE:RANG BEST")
        self.transport.write(f"SOUR:{source}:MODE SWE")

        setup.append(f"SOUR:DEL {max(float(delay_s), 0.0):.5f}")
        self.transport.write(f"SOUR:DEL {max(float(delay_s), 0.0):.5f}")
        # Total readings is arm count MULTIPLIED BY trigger count, not
        # the trigger count alone. *RST leaves arm count at 1, but this
        # driver never assumes the instrument was reset by us - a stale
        # arm count of 2 would run the whole sweep twice and overfill
        # the buffer, with no error to say so.
        for command in ("ARM:COUN 1", f"TRIG:COUN {points}",
                        # Storage OFF before anything about the buffer
                        # is changed. The command list: "TRACe:FEED
                        # cannot be changed while buffer storage is
                        # active." Every sweep arms storage with
                        # `CONT NEXT` at the end of this block, so from
                        # the second sweep onward it is still armed when
                        # the next one starts - and the feed command is
                        # refused, taking the whole staircase setup down
                        # with it.
                        "TRAC:FEED:CONT NEV",
                        "TRAC:CLE", f"TRAC:POIN {points}", feed,
                        # Elements BEFORE storage is armed. On this
                        # instrument, sent after `CONT NEXT` it is
                        # accepted, queues no error, and has no effect -
                        # the buffer still came back with a resistance
                        # column. Same shape as the TRACe:FEED rule the
                        # manual states outright.
                        "FORM:ELEM VOLT,CURR", "TRAC:FEED:CONT NEXT"):
            # Buffer: storage off, cleared, sized, fed, then armed.
            # Sizing before feeding matters too - the instrument won't
            # resize a buffer that already holds readings.
            setup.append(command)
            self.transport.write(command)

        complaints = self._drain_errors()
        if complaints:
            # Configuration was refused after the probe passed. Rather
            # than fire a sweep that has been half-configured, drop to
            # the software path for this run and every run after it.
            code, message = complaints[0]
            culprit = self._find_rejected_command(setup)
            self._sweep_mode = "software"
            self._sweep_note = (
                f"staircase setup rejected ({code}: {message})"
                + (f" on `{culprit}`" if culprit else "")
                + "; switched to the point-by-point software sweep")

            # THE SOURCE MUST COME OUT OF SWEEP MODE FIRST.
            #
            # This was the bug the bench found. `SOUR:<x>:MODE SWE` had
            # already been sent by the time the setup was refused, and
            # falling straight through to the software sweep left it
            # there. The software sweep steps by sending
            # `SOUR:VOLT <level>` - which, in SWE mode, the instrument
            # reads as a sweep *endpoint* rather than a level to hold.
            #
            # So the source never moved. The run completed, returned
            # the right number of points, reported no error, and every
            # point sat at 0 V. A flat line from a working instrument,
            # with the fallback that was supposed to rescue the run
            # being the thing that broke it.
            self._restore_fixed_source(source)
            return super().start_linear_sweep(mode, start, stop, points,
                                              delay_s)

        # ARM IT AND ASK NOTHING. The instrument is busy from here.
        #
        # The first version of this checked the error queue immediately
        # after `INIT`, to catch a staircase that was armed and then
        # refused. It is the right question at the worst possible
        # moment: `INIT` starts the sweep, this instrument does not
        # service `SYST:ERR:ALL?` while it is sweeping, and the query
        # therefore waits for the whole sweep to finish. Any sweep
        # longer than the 3 s query timeout then times out - which
        # latches the transport, discards the run and demands a
        # reconnect.
        #
        # It turned an intermittent fault into a reproducible one, on
        # the bench, in front of the person who reported the original
        # problem. A diagnostic that costs every run is worse than the
        # fault it diagnoses.
        #
        # The question is still worth asking - just not here. It moves
        # to `read_sweep()`, which runs after the poll loop has given
        # up, where the instrument is idle again and a query is safe.
        self.transport.write("INIT")

    # Feed-source tokens, in the order they are tried.
    #
    # The command list documents the parameter as `SENSe1` and gives
    # `:TRACe:FEED SENSe1` as its example. By SCPI convention the
    # capitals are the short form, so `SENS1` should be equivalent - but
    # the error this instrument returned was **-140, Character data
    # error**, which is specifically a complaint about the *parameter*,
    # not about the instrument's state. A settings conflict would
    # normally be -221.
    #
    # So both readings stay in play and both are covered:
    #
    #   SENS1   documented short form, tried first
    #   SENSe1  the long form exactly as the manual prints it, in case
    #           this implementation matches literally rather than
    #           honouring the abbreviation
    #   SENS    un-numbered, in case the suffix is the problem
    #
    # Separately, the manual also states that "TRACe:FEED cannot be
    # changed while buffer storage is active", and the setup was arming
    # storage with `CONT NEXT` and never turning it off - so a rejected
    # setup left the buffer armed and waiting forever, and every later
    # run then failed on a command that had nothing to do with the
    # original fault. That is fixed independently (see reset() and the
    # setup block); this probe covers the parameter question.
    BUFFER_FEED_TOKENS = ("SENS1", "SENSe1", "SENS")

    def _buffer_feed_command(self):
        """`TRAC:FEED <token>`, using whichever token this box accepts.

        Probed once and cached. Storage is disarmed first, because that
        is the documented precondition for changing the feed at all -
        without it the probe would reject a perfectly good token and
        cache the wrong answer for the session.

        If neither token is accepted the last one is returned anyway:
        the setup check downstream will see the error, name it, and fall
        back cleanly. Better that than raising here and losing the sweep
        entirely.
        """
        if self._feed_token is not None:
            return f"TRAC:FEED {self._feed_token}"

        for token in self.BUFFER_FEED_TOKENS:
            self._drain_errors()
            try:
                self.transport.write("TRAC:FEED:CONT NEV")
                self.transport.write(f"TRAC:FEED {token}")
            except Exception:
                continue
            if not self._drain_errors():
                self._feed_token = token
                return f"TRAC:FEED {token}"

        self._feed_token = self.BUFFER_FEED_TOKENS[-1]
        return f"TRAC:FEED {self._feed_token}"

    def _restore_fixed_source(self, source):
        """Undo the staircase configuration.

        Three things, all of which bite silently if left:
        `MODE SWE` makes later level-setting a no-op; a trigger count
        above 1 makes the next `READ?` take that many readings; and an
        arm count above 1 multiplies it again.
        """
        for command in (f"SOUR:{source}:MODE FIX", "TRIG:COUN 1",
                        "ARM:COUN 1"):
            try:
                self.transport.write(command)
            except Exception:
                pass
        self._drain_errors()

    def _find_rejected_command(self, setup):
        """Replay the setup one command at a time to name the offender.

        Only ever runs on the failure path, so the extra round trips
        cost nothing in normal use. Worth it because "-140: Character
        data error" names a *kind* of mistake and not the command that
        made it, and the staircase block is fifteen commands long -
        several of which carry character parameters this instrument may
        simply not accept (`SPAC LIN`, `DIR UP`, `RANG BEST`,
        `MODE SWE`, `FEED SENS1`).
        """
        self._drain_errors()
        for command in setup:
            try:
                self.transport.write(command)
            except Exception:
                return command
            if self._drain_errors():
                return command
        return None

    def sweep_points_ready(self):
        """How many readings the armed staircase has taken.

        TWO THINGS THIS INSTRUMENT DOES, measured 2026-09-16
        (`tools/probes/20h10_stale_buffer.txt`):

        **The query waits for the sweep.** `TRAC:POIN:ACT?` sent while a
        staircase runs is not answered until it finishes - 1034 ms for
        ten points at 100 ms, 324 ms for three. So a poll never sees a
        sweep part-way, and a fixed 5 s budget would fail every sweep
        longer than that: the reply arriving after the read had given
        up, the transport latched and the run discarded. The budget is
        now the sweep's own duration - see `_sweep_wait_budget()`. The
        cost is that Stop is not felt until the sweep ends.

        **The count is the buffer's high-water mark, not this sweep's.**
        After a 10-point sweep, a 3-point one reports 10. `TRAC:CLE`
        zeroes it only until the next reading lands. Capped at the
        points armed, so the caller's "all points in" test means this
        sweep's points - see `read_sweep()` for the data half.
        """
        if self.sweep_kind() != "hardware":
            return super().sweep_points_ready()
        try:
            reply = self.transport.query("TRAC:POIN:ACT?",
                                         timeout_s=self._sweep_wait_budget())
            count = int(float(reply.strip().split(",")[0]))
        except (ValueError, IndexError, AttributeError):
            return 0
        if self._sweep_points:
            return min(count, self._sweep_points)
        return count

    def _sweep_wait_budget(self):
        """Seconds to allow a query that waits for the armed staircase.

        An upper bound, not an estimate: the reply comes as soon as the
        sweep ends, so a generous budget costs nothing on a working
        instrument and only delays declaring a dead one.

        Per point: the source delay, plus a reading. Both sense functions
        are measured concurrently, and the bench table (2026-09-01) has
        a reading at 10.3 ms at NPLC 0.01, 269 ms at 2.5 and 1.06 s at
        10 - under 50 ms + 110 ms per PLC at every row. Doubled, plus
        5 s for the query itself, and never below the 5 s it used to be.
        """
        points = max(int(self._sweep_points or 0), 1)
        per_point = self._sweep_delay + 0.05 + 0.11 * max(self._nplc, 0.0)
        return max(5.0, 2.0 * points * per_point + 5.0)

    # The order the 2400 family returns elements in, regardless of the
    # order they were requested. Used when the instrument's own account
    # of its element list cannot be believed - see _buffer_layout().
    CANONICAL_ELEMENTS = ("VOLT", "CURR", "RES", "TIME", "STAT")

    def _buffer_layout(self, count, values):
        """How many numbers per reading, and where V and I sit.

        **Counted from the data, not asked for and not read back.**

        Both of the obvious approaches fail on this instrument. Sending
        `FORM:ELEM VOLT,CURR` does not restrict the reply: it is
        accepted, queues no error, and the buffer still comes back with
        a resistance column. And querying `FORM:ELEM?` does not reveal
        that - it answers `VOLT,CURR`, matching what was asked rather
        than what it sends. The instrument's account of itself is wrong
        in both directions, so neither can be trusted.

        What cannot lie is arithmetic: the buffer reports how many
        readings it holds, and the reply contains a certain quantity of
        numbers. Their ratio is the stride. Which column is which then
        comes from the canonical element order the family documents,
        truncated to that stride.

        Falls back to a plain V,I pair when the count is unknown or the
        division is not exact, which is what every other instrument here
        does.
        """
        if not count or not values or len(values) % count:
            return (2, 0, 1)

        stride = len(values) // count
        if stride < 2:
            return (2, 0, 1)

        names = list(self.CANONICAL_ELEMENTS[:stride])
        if "VOLT" not in names or "CURR" not in names:
            return (2, 0, 1)
        return (stride, names.index("VOLT"), names.index("CURR"))

    def read_sweep(self, points):
        """Collect a finished sweep as (source_values, measured_values).

        The buffer is unpacked using the element list the instrument
        *reports*, not the one that was asked for - see
        `_buffer_layout()`. The pairs are then assigned to
        source/measure by mode rather than by position.

        Found on the bench: this instrument returned three numbers per
        reading (voltage, current, resistance) after being told
        `FORM:ELEM VOLT,CURR`, and the fixed stride of two turned 5
        readings into 15 numbers read as 7 pairs. Four of those
        contained the resistance NAN and were dropped, leaving 3 -
        which were readings 1, 3 and 5, genuine V/I pairs, and
        therefore looked entirely plausible. Only the point-count check
        caught it.

        Reading the element list back does not help: `FORM:ELEM?`
        answers `VOLT,CURR` while the buffer sends three columns. The
        stride is therefore counted, not asked for.
        """
        if self.sweep_kind() != "hardware":
            return super().read_sweep(points)

        # How many readings the instrument says it took. Asked before
        # the data is fetched, because it is the denominator that turns
        # a flat list of numbers into a stride.
        try:
            actual = int(float(str(self.transport.query(
                "TRAC:POIN:ACT?",
                timeout_s=self._sweep_wait_budget())).strip().split(",")[0]))
        except TransportDesynchronised:
            raise
        except Exception:
            actual = int(points)

        if actual <= 0:
            # An empty buffer means the staircase never ran, and THIS is
            # where to ask why: the poll loop has already given up, so
            # the instrument is idle and a query is safe. Asking
            # immediately after `INIT` is the same question at the one
            # moment this instrument cannot answer it - see there.
            #
            # A refused `INIT` is written, queued, and otherwise silent.
            # Without this the caller reports "sweep timed out with
            # 0/N points; no data returned" - three descriptions of the
            # symptom, while the instrument's own answer sits unread.
            for code, message in self._drain_errors():
                self._sweep_mode = "software"
                self._sweep_note = (
                    f"the staircase was armed but produced nothing, and "
                    f"the instrument reports {code}: {message}; switching "
                    f"to the point-by-point software sweep for the rest of "
                    f"this session")

                # AND TAKE THE SOURCE OUT OF SWEEP MODE, which the
                # first draft of this forgot.
                #
                # `SOUR:<x>:MODE SWE` is still in force here - the arm
                # set it and the sweep never ran. The software sweep
                # steps by sending `SOUR:VOLT <level>`, which in SWE
                # mode is read as a sweep *endpoint* rather than a level
                # to hold. So the source would never move: the next run
                # would complete, return the right number of points,
                # report no error, and sit at 0 V throughout.
                #
                # That is not a hypothetical. It is the bug a bench
                # session found on the other fallback path in this file,
                # written up twelve lines above `INIT`, and leaving it
                # out here would have reintroduced it one branch over.
                self._restore_fixed_source(
                    "VOLT" if self._sweep_source_mode() == "voltage"
                    else "CURR")
                break

        reply = self.transport.query("TRAC:DATA?", timeout_s=30.0)
        values = []
        for chunk in str(reply).replace("\n", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                values.append(float(chunk))
            except ValueError:
                pass

        stride, v_index, i_index = self._buffer_layout(actual, values)
        if stride != 2:
            self._sweep_note = (
                f"the buffer returns {stride} values per reading, not 2 - "
                f"`FORM:ELEM VOLT,CURR` is accepted and ignored on this "
                f"model, and `FORM:ELEM?` reports the requested list "
                f"rather than the one it sends. Stride counted from "
                f"{len(values)} values over {actual} readings")

        volts = values[v_index::stride]
        amps = values[i_index::stride]
        # Ragged tail: an interrupted transfer can leave one orphan
        # number. Trim to matched pairs rather than pad, on the same
        # principle as the software sweep - fewer real points beats
        # inventing one.
        n = min(len(volts), len(amps))
        volts, amps = volts[:n], amps[:n]

        # THIS SWEEP'S READINGS ARE THE FIRST ONES, AND ONLY THOSE.
        #
        # Measured 2026-09-16: `TRAC:CLE`, `TRAC:POIN <n>` and *RST all
        # leave an earlier, longer sweep's readings in the buffer, and
        # `TRAC:DATA?` returns them after the new ones. A 5-point sweep
        # following a 10-point one came back with ten readings - five
        # fresh, then readings 6-10 of the old sweep, identical to seven
        # digits across three runs and a reset - and nothing in the
        # reply marks where one ends. Recorded as they stood, those are
        # points the sample was never taken to.
        #
        # The stride above still comes from the whole reply: the buffer
        # sends every reading it holds, so values over readings is still
        # the count of numbers per reading.
        #
        # The gap left open: a staircase that stopped part-way would be
        # topped up here with old readings. This model's sweep does not
        # abort on compliance unless told to (`SOUR:SWE:CAB`, never set
        # here), so a sweep that runs finishes.
        expected = int(self._sweep_points or points or 0)
        if expected and n > expected:
            self._sweep_note = (
                f"the buffer held {n} readings for a {expected}-point "
                f"sweep; the {n - expected} after the first {expected} "
                f"are left over from an earlier, longer sweep (this "
                f"model keeps them through TRAC:CLE and *RST) and were "
                f"discarded")
            volts, amps = volts[:expected], amps[:expected]
            n = expected

        # Drop NAN/overflow pairs. One of these left in a sweep is
        # worse than a missing point: at 1e37 it dominates the
        # least-squares sum completely, so the fitted line runs to that
        # single point and the real data becomes noise around zero.
        # Dropped in pairs so the two columns stay aligned.
        kept_v, kept_i, dropped = [], [], 0
        for v, i in zip(volts, amps):
            if self._clean(v) is None or self._clean(i) is None:
                dropped += 1
                continue
            kept_v.append(v)
            kept_i.append(i)
        if dropped:
            self._sweep_note = (
                f"{dropped} of {n} sweep points came back as "
                f"NAN/over-range and were dropped")
        volts, amps = kept_v, kept_i

        # Put the source back in fixed mode. Left in SWE, the next
        # `SOUR:VOLT <level>` is read as a sweep endpoint rather than a
        # level to hold - which would break the bias-hold path between
        # periodic sweeps, and do it silently.
        source = "VOLT" if self._sweep_source_mode() == "voltage" else "CURR"
        try:
            self.transport.write(f"SOUR:{source}:MODE FIX")
            # And put the trigger count back. This one was found on the
            # bench: `TRIG:COUN <points>` above is what makes the
            # staircase fire N times, and leaving it there means the
            # next plain `READ?` triggers N readings instead of one. It
            # is silent at low NPLC - just slow - and at NPLC 10 the
            # reply takes five times the aperture and blows through
            # measure()'s timeout as a USB error that looks like a
            # cable fault. Every bias-hold reading between periodic
            # sweeps went through this path.
            self.transport.write("TRIG:COUN 1")
            self.transport.write("ARM:COUN 1")
        except Exception:
            pass

        if self._sweep_source_mode() == "voltage":
            return volts, amps
        return amps, volts

    def _sweep_source_mode(self):
        """Which quantity the last started sweep sourced."""
        return getattr(self, "_last_sweep_mode", "voltage")

    def abort_sweep(self):
        """Stop a running sweep and drop the output.

        `:TRIG:CLE`, not `:ABOR`. Settled on the bench 2026-08-14:
        `:ABOR` is rejected with `-113: Undefined header`, against a
        control that proved the error queue was reporting. The manual's
        `:MEASure?` description mentions an abort being performed
        internally, but there is no bus command for it on this model.
        `:TRIGger:CLEar` is documented outright, clears the pending
        trigger, and is what stops a sweep here.

        Note `:SOUR:SWE:CABort` is *not* the abort action despite the
        name - it is a setting that configures what a sweep does when
        it hits compliance.
        """
        if self.sweep_kind() != "hardware":
            return super().abort_sweep()
        try:
            self.transport.write("TRIG:CLE")
            self.transport.write("OUTP 0")
        except Exception:
            return False
        return True
